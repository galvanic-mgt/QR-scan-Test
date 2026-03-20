import json
import threading
import webbrowser
from pathlib import Path
from tkinter import Tk, Label

import requests
from PIL import Image, ImageTk

CONFIG_PATH = Path(__file__).with_name("config.json")


class RuntimeSettings:
    def __init__(self, config):
        self._lock = threading.Lock()
        self._config = config
        self._settings_path = resolve_path(
            config.get("cms_settings_file", "cms_settings.json")
        )
        self._data = {
            "website_url": config["website_url"],
            "slide_seconds": float(config.get("slide_seconds", 5)),
        }
        self.refresh_from_file()

    def refresh_from_file(self):
        settings = {
            "website_url": self._config["website_url"],
            "slide_seconds": float(self._config.get("slide_seconds", 5)),
        }

        if self._settings_path.exists():
            try:
                with self._settings_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                settings["website_url"] = loaded.get(
                    "website_url", settings["website_url"]
                )
                settings["slide_seconds"] = float(
                    loaded.get("slide_seconds", settings["slide_seconds"])
                )
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                pass

        with self._lock:
            self._data = settings

    def save(self, website_url, slide_seconds):
        payload = {
            "website_url": website_url,
            "slide_seconds": max(1, int(slide_seconds)),
        }
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        with self._settings_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        self.refresh_from_file()

    def get(self, key):
        with self._lock:
            return self._data[key]


def resolve_path(path_value):
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (CONFIG_PATH.parent / path).resolve()


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_images(photos_dir):
    exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
    photos = resolve_path(photos_dir)
    if not photos.exists():
        return []
    paths = [p for p in photos.iterdir() if p.suffix.lower() in exts and p.is_file()]
    return sorted(paths)


def safe_filename(name):
    cleaned = Path(name).name
    if not cleaned:
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if any(ch not in allowed for ch in cleaned):
        return None
    if "." not in cleaned:
        return None
    return cleaned


class Slideshow:
    def __init__(self, root, config, runtime_settings):
        self.root = root
        self.config = config
        self.runtime_settings = runtime_settings
        self.paths = []
        self.index = 0
        self.label = Label(root, bg="black")
        self.label.pack(fill="both", expand=True)

        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        if config.get("fullscreen", True):
            self.root.attributes("-fullscreen", True)
        self.root.configure(bg="black")

        self.show_next()

    def show_next(self):
        self.runtime_settings.refresh_from_file()
        self.paths = iter_images(self.config["photos_dir"])
        slide_ms = int(max(1, self.runtime_settings.get("slide_seconds")) * 1000)

        if not self.paths:
            self.label.config(text="No images found", fg="white", bg="black", image="")
            self.label.image = None
            self.root.after(slide_ms, self.show_next)
            return

        if self.index >= len(self.paths):
            self.index = 0

        path = self.paths[self.index]
        self.index = (self.index + 1) % len(self.paths)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        try:
            with Image.open(path) as image:
                image.thumbnail((screen_w, screen_h))
                tk_image = ImageTk.PhotoImage(image)
        except OSError:
            self.root.after(slide_ms, self.show_next)
            return

        self.label.config(image=tk_image, text="", bg="black")
        self.label.image = tk_image

        self.root.after(slide_ms, self.show_next)


def poll_loop(config, runtime_settings, stop_event):
    poll_url = config["poll_url"].rstrip("/")
    device_id = config["device_id"]
    poll_seconds = config.get("poll_seconds", 2)

    last_seen = None

    try:
        resp = requests.get(f"{poll_url}?device={device_id}", timeout=5)
        if resp.ok:
            last_seen = resp.json().get("lastScanMs")
    except requests.RequestException:
        last_seen = None

    while not stop_event.is_set():
        runtime_settings.refresh_from_file()

        try:
            resp = requests.get(f"{poll_url}?device={device_id}", timeout=5)
            if resp.ok:
                last_scan = resp.json().get("lastScanMs")
                if last_scan and last_scan != last_seen:
                    last_seen = last_scan
                    webbrowser.open(runtime_settings.get("website_url"))
        except requests.RequestException:
            pass

        stop_event.wait(poll_seconds)


def load_sync_state(path):
    if not path.exists():
        return {"rev": None, "files": []}
    try:
        with path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        rev = loaded.get("rev")
        files = loaded.get("files")
        if not isinstance(files, list):
            files = []
        safe_files = [name for name in files if safe_filename(name)]
        return {"rev": rev, "files": safe_files}
    except (json.JSONDecodeError, OSError, TypeError):
        return {"rev": None, "files": []}


def save_sync_state(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def sync_cms_loop(config, runtime_settings, stop_event):
    cms_public_url = (config.get("cms_public_url") or "").strip()
    if not cms_public_url:
        return

    device_id = config["device_id"]
    photos_dir = resolve_path(config["photos_dir"])
    photos_dir.mkdir(parents=True, exist_ok=True)

    sync_seconds = max(2, int(config.get("cms_sync_seconds", 15)))
    state_path = resolve_path(config.get("cms_sync_state_file", "cms_sync_state.json"))
    sync_state = load_sync_state(state_path)

    while not stop_event.is_set():
        try:
            resp = requests.get(f"{cms_public_url}?device={device_id}", timeout=10)
            if resp.ok:
                payload = resp.json()
                website_url = payload.get("website_url")
                slide_seconds = payload.get("slide_seconds")
                rev = payload.get("rev")
                images = payload.get("images", [])

                if isinstance(website_url, str) and website_url.strip():
                    try:
                        seconds_value = int(slide_seconds)
                    except (ValueError, TypeError):
                        seconds_value = int(config.get("slide_seconds", 5))
                    runtime_settings.save(website_url.strip(), max(1, seconds_value))

                if rev != sync_state.get("rev"):
                    downloaded = []
                    failed = False

                    for item in images:
                        name = safe_filename(item.get("name")) if isinstance(item, dict) else None
                        image_url = item.get("url") if isinstance(item, dict) else None
                        if not name or not isinstance(image_url, str):
                            failed = True
                            break

                        img_resp = requests.get(image_url, timeout=20)
                        if not img_resp.ok:
                            failed = True
                            break

                        image_path = photos_dir / name
                        with image_path.open("wb") as f:
                            f.write(img_resp.content)
                        downloaded.append(name)

                    if not failed:
                        previous_files = set(sync_state.get("files", []))
                        current_files = set(downloaded)
                        for stale_name in previous_files - current_files:
                            stale_path = photos_dir / stale_name
                            if stale_path.exists() and stale_path.is_file():
                                stale_path.unlink()

                        sync_state = {"rev": rev, "files": sorted(downloaded)}
                        save_sync_state(state_path, sync_state)
        except (requests.RequestException, OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

        stop_event.wait(sync_seconds)


def main():
    config = load_config()
    runtime_settings = RuntimeSettings(config)
    stop_event = threading.Event()

    poll_thread = threading.Thread(
        target=poll_loop, args=(config, runtime_settings, stop_event), daemon=True
    )
    poll_thread.start()

    sync_thread = threading.Thread(
        target=sync_cms_loop, args=(config, runtime_settings, stop_event), daemon=True
    )
    sync_thread.start()

    root = Tk()
    root.title("QR Kiosk")
    Slideshow(root, config, runtime_settings)
    root.protocol("WM_DELETE_WINDOW", root.destroy)

    try:
        root.mainloop()
    finally:
        stop_event.set()
        poll_thread.join(timeout=2)
        sync_thread.join(timeout=2)


if __name__ == "__main__":
    main()
