import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
TARGET = BASE / "config.json"
LOCAL = BASE / "config.local.json"
ONLINE = BASE / "config.online.json"
BACKUP = BASE / "config.last.json"


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"local", "online"}:
        print("Usage: python3 switch_config.py [local|online]")
        raise SystemExit(1)

    mode = sys.argv[1]
    source = LOCAL if mode == "local" else ONLINE
    if not source.exists():
        print(f"Missing template: {source}")
        raise SystemExit(1)

    if TARGET.exists():
        shutil.copy2(TARGET, BACKUP)

    shutil.copy2(source, TARGET)
    print(f"Switched kiosk/config.json -> {source.name}")
    if BACKUP.exists():
        print(f"Backup saved to {BACKUP.name}")


if __name__ == "__main__":
    main()
