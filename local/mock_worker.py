import json
import mimetypes
import secrets
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, request, send_file

STATE_ROOT = Path(__file__).with_name("state")
ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
DEFAULT_USER = "admin"
DEFAULT_PASS = "localpass"


def sanitize_device(value):
    if not value:
        return None
    value = str(value).strip()
    if not value or len(value) > 64:
        return None
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in value):
        return None
    return value


def sanitize_filename(value):
    if not value:
        return None
    name = Path(str(value)).name
    if not name:
        return None
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if any(ch not in allowed for ch in name):
        return None
    return name


def device_dir(device):
    path = STATE_ROOT / device
    path.mkdir(parents=True, exist_ok=True)
    (path / "images").mkdir(parents=True, exist_ok=True)
    return path


def read_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def get_settings(device):
    settings_path = device_dir(device) / "settings.json"
    defaults = {"website_url": "https://example.com", "slide_seconds": 5, "rev": 0}
    data = read_json(settings_path, defaults)
    return {
        "website_url": str(data.get("website_url", defaults["website_url"])),
        "slide_seconds": max(1, int(data.get("slide_seconds", defaults["slide_seconds"]))),
        "rev": int(data.get("rev", defaults["rev"])),
    }


def set_settings(device, settings):
    settings_path = device_dir(device) / "settings.json"
    write_json(settings_path, settings)


def get_images(device):
    images_path = device_dir(device) / "images.json"
    data = read_json(images_path, [])
    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = sanitize_filename(item.get("name"))
        ctype = item.get("contentType")
        if name and isinstance(ctype, str):
            cleaned.append({"name": name, "contentType": ctype})
    return cleaned


def set_images(device, images):
    images_path = device_dir(device) / "images.json"
    write_json(images_path, images)


def get_last_scan(device):
    path = device_dir(device) / "scan.json"
    data = read_json(path, {"lastScanMs": None})
    return data.get("lastScanMs")


def set_last_scan(device, value):
    path = device_dir(device) / "scan.json"
    write_json(path, {"lastScanMs": value})


def get_sessions():
    return read_json(STATE_ROOT / "sessions.json", {})


def set_sessions(payload):
    write_json(STATE_ROOT / "sessions.json", payload)


def response_with_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp


def unauthorized():
    return response_with_cors(make_response(jsonify({"error": "unauthorized"}), 401))


def is_authed(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:].strip()
    if not token:
        return False
    sessions = get_sessions()
    return bool(sessions.get(token))


app = Flask(__name__)


@app.after_request
def add_cors(resp):
    return response_with_cors(resp)


@app.route("/", methods=["GET"])
def root_ok():
    return Response("ok", content_type="text/plain")


@app.route("/scan", methods=["GET"])
def scan():
    device = sanitize_device(request.args.get("device"))
    if not device:
        return jsonify({"error": "missing_device"}), 400
    now_ms = int(__import__("time").time() * 1000)
    set_last_scan(device, now_ms)
    return Response("ok", content_type="text/plain")


@app.route("/poll", methods=["GET"])
def poll():
    device = sanitize_device(request.args.get("device"))
    if not device:
        return jsonify({"error": "missing_device"}), 400
    return jsonify({"device": device, "lastScanMs": get_last_scan(device)})


@app.route("/cms/login", methods=["POST"])
def cms_login():
    payload = request.get_json(silent=True) or {}
    username = payload.get("username", "")
    password = payload.get("password", "")

    if username != DEFAULT_USER or password != DEFAULT_PASS:
        return jsonify({"error": "invalid_credentials"}), 401

    token = secrets.token_urlsafe(24)
    sessions = get_sessions()
    sessions[token] = {"username": username}
    set_sessions(sessions)
    return jsonify({"token": token, "expiresInSeconds": 43200})


@app.route("/cms/state", methods=["GET"])
def cms_state():
    if not is_authed(request):
        return unauthorized()

    device = sanitize_device(request.args.get("device"))
    if not device:
        return jsonify({"error": "missing_device"}), 400

    settings = get_settings(device)
    images = get_images(device)
    return jsonify(
        {
            "device": device,
            "website_url": settings["website_url"],
            "slide_seconds": settings["slide_seconds"],
            "rev": settings["rev"],
            "images": images,
        }
    )


@app.route("/cms/settings", methods=["POST"])
def cms_settings():
    if not is_authed(request):
        return unauthorized()

    device = sanitize_device(request.args.get("device"))
    if not device:
        return jsonify({"error": "missing_device"}), 400

    payload = request.get_json(silent=True) or {}
    website_url = str(payload.get("website_url", "")).strip()
    slide_seconds = payload.get("slide_seconds", 5)

    if not website_url:
        return jsonify({"error": "missing_website_url"}), 400

    try:
        slide_seconds = max(1, int(slide_seconds))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_slide_seconds"}), 400

    settings = get_settings(device)
    settings["website_url"] = website_url
    settings["slide_seconds"] = slide_seconds
    settings["rev"] = settings["rev"] + 1
    set_settings(device, settings)

    return jsonify({"ok": True, "rev": settings["rev"]})


@app.route("/cms/upload", methods=["POST"])
def cms_upload():
    if not is_authed(request):
        return unauthorized()

    device = sanitize_device(request.args.get("device"))
    if not device:
        return jsonify({"error": "missing_device"}), 400

    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "no_files"}), 400

    images = {item["name"]: item for item in get_images(device)}
    img_dir = device_dir(device) / "images"

    uploaded = 0
    for file in files:
        safe_name = sanitize_filename(file.filename)
        if not safe_name:
            continue
        target = img_dir / safe_name
        file.save(target)
        content_type = file.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        images[safe_name] = {"name": safe_name, "contentType": content_type}
        uploaded += 1

    if uploaded == 0:
        return jsonify({"error": "no_valid_files"}), 400

    next_images = sorted(images.values(), key=lambda x: x["name"])
    set_images(device, next_images)
    settings = get_settings(device)
    settings["rev"] = settings["rev"] + 1
    set_settings(device, settings)

    return jsonify({"ok": True, "uploaded": uploaded, "rev": settings["rev"]})


@app.route("/cms/delete", methods=["POST"])
def cms_delete():
    if not is_authed(request):
        return unauthorized()

    device = sanitize_device(request.args.get("device"))
    if not device:
        return jsonify({"error": "missing_device"}), 400

    payload = request.get_json(silent=True) or {}
    filename = sanitize_filename(payload.get("filename"))
    if not filename:
        return jsonify({"error": "invalid_filename"}), 400

    images = [img for img in get_images(device) if img["name"] != filename]
    if len(images) == len(get_images(device)):
        return jsonify({"error": "not_found"}), 404

    set_images(device, images)
    target = device_dir(device) / "images" / filename
    if target.exists():
        target.unlink()

    settings = get_settings(device)
    settings["rev"] = settings["rev"] + 1
    set_settings(device, settings)
    return jsonify({"ok": True, "rev": settings["rev"]})


@app.route("/cms/public", methods=["GET"])
def cms_public():
    device = sanitize_device(request.args.get("device"))
    if not device:
        return jsonify({"error": "missing_device"}), 400

    settings = get_settings(device)
    images = get_images(device)
    base = request.host_url.rstrip("/")

    payload_images = [
        {
            "name": item["name"],
            "contentType": item["contentType"],
            "url": f"{base}/cms/image?device={device}&name={item['name']}",
        }
        for item in images
    ]

    return jsonify(
        {
            "device": device,
            "website_url": settings["website_url"],
            "slide_seconds": settings["slide_seconds"],
            "rev": settings["rev"],
            "images": payload_images,
        }
    )


@app.route("/cms/image", methods=["GET"])
def cms_image():
    device = sanitize_device(request.args.get("device"))
    name = sanitize_filename(request.args.get("name"))
    if not device:
        return jsonify({"error": "missing_device"}), 400
    if not name:
        return jsonify({"error": "invalid_filename"}), 400

    target = device_dir(device) / "images" / name
    if not target.exists() or not target.is_file():
        return jsonify({"error": "not_found"}), 404

    mimetype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return send_file(target, mimetype=mimetype)


@app.route("/<path:_>", methods=["GET", "POST", "OPTIONS"])
def not_found(_):
    return Response("not found", status=404, content_type="text/plain")


if __name__ == "__main__":
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=8787, debug=False)
