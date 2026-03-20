import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnM"
    "j8sAAAAASUVORK5CYII="
)


def request_json(method, url, *, payload=None, headers=None):
    body = None
    req_headers = {"accept": "application/json"}
    if headers:
        req_headers.update(headers)

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers["content-type"] = "application/json"

    request = urllib.request.Request(url, data=body, method=method, headers=req_headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw)


def request_text(method, url, *, headers=None):
    request = urllib.request.Request(url, method=method, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def upload_multipart(url, fields, files, *, headers=None):
    boundary = f"----qrkiosk{uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    for file_field, filename, content_type, content in files:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    req_headers = {"content-type": f"multipart/form-data; boundary={boundary}"}
    if headers:
        req_headers.update(headers)

    request = urllib.request.Request(
        url, data=bytes(body), method="POST", headers=req_headers
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw)


def wait_for_server(base_url, timeout_seconds=10):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status, body = request_text("GET", f"{base_url}/")
            if status == 200 and body.strip() == "ok":
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise RuntimeError(f"Server did not become ready at {base_url}")


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def main():
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787").rstrip("/")
    device = f"DEMO{uuid4().hex[:8].upper()}"

    wait_for_server(base_url)

    _, login = request_json(
        "POST",
        f"{base_url}/cms/login",
        payload={"username": "admin", "password": "localpass"},
    )
    token = login.get("token")
    if not token:
        raise AssertionError("Login did not return a token")

    auth_headers = {"authorization": f"Bearer {token}"}

    _, initial_state = request_json(
        "GET", f"{base_url}/cms/state?device={urllib.parse.quote(device)}", headers=auth_headers
    )
    assert_equal(initial_state["device"], device, "State device mismatch")
    assert_equal(initial_state["website_url"], "https://example.com", "Default URL mismatch")
    assert_equal(initial_state["slide_seconds"], 5, "Default slide seconds mismatch")
    assert_equal(initial_state["rev"], 0, "Default revision mismatch")
    assert_equal(initial_state["images"], [], "Initial images should be empty")

    _, save_result = request_json(
        "POST",
        f"{base_url}/cms/settings?device={urllib.parse.quote(device)}",
        payload={"website_url": "https://openai.com", "slide_seconds": 7},
        headers=auth_headers,
    )
    assert_equal(save_result["ok"], True, "Settings save should succeed")
    assert_equal(save_result["rev"], 1, "Settings save should increment revision")

    _, upload_result = upload_multipart(
        f"{base_url}/cms/upload?device={urllib.parse.quote(device)}",
        {},
        [("images", "slide1.png", "image/png", PNG_1X1)],
        headers=auth_headers,
    )
    assert_equal(upload_result["ok"], True, "Upload should succeed")
    assert_equal(upload_result["uploaded"], 1, "Exactly one image should upload")
    assert_equal(upload_result["rev"], 2, "Upload should increment revision")

    _, public_state = request_json(
        "GET", f"{base_url}/cms/public?device={urllib.parse.quote(device)}"
    )
    assert_equal(public_state["website_url"], "https://openai.com", "Public URL mismatch")
    assert_equal(public_state["slide_seconds"], 7, "Public slide seconds mismatch")
    assert_equal(public_state["rev"], 2, "Public revision mismatch")
    images = public_state["images"]
    assert_equal(len(images), 1, "Expected one public image")
    image_url = images[0]["url"]

    with urllib.request.urlopen(image_url, timeout=10) as image_response:
        image_bytes = image_response.read()
        assert_equal(image_response.status, 200, "Image fetch should succeed")
        assert_equal(image_response.headers.get_content_type(), "image/png", "Image content type mismatch")
        assert_equal(len(image_bytes), len(PNG_1X1), "Image size mismatch")

    _, scan_body = request_text(
        "GET", f"{base_url}/scan?device={urllib.parse.quote(device)}"
    )
    assert_equal(scan_body.strip(), "ok", "Scan endpoint should return ok")

    _, poll_state = request_json(
        "GET", f"{base_url}/poll?device={urllib.parse.quote(device)}"
    )
    if not isinstance(poll_state.get("lastScanMs"), int):
        raise AssertionError("Poll endpoint did not return a scan timestamp")

    _, delete_result = request_json(
        "POST",
        f"{base_url}/cms/delete?device={urllib.parse.quote(device)}",
        payload={"filename": "slide1.png"},
        headers=auth_headers,
    )
    assert_equal(delete_result["ok"], True, "Delete should succeed")
    assert_equal(delete_result["rev"], 3, "Delete should increment revision")

    _, final_public_state = request_json(
        "GET", f"{base_url}/cms/public?device={urllib.parse.quote(device)}"
    )
    assert_equal(final_public_state["images"], [], "Final image list should be empty")
    assert_equal(final_public_state["rev"], 3, "Final revision mismatch")

    print(f"Smoke test passed for device {device}")


if __name__ == "__main__":
    main()
