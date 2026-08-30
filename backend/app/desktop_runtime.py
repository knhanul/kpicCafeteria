from __future__ import annotations

import os
import secrets
import socket
from pathlib import Path


APP_DATA_FOLDER = "KPICCafeteria"


def desktop_data_root(environ: dict[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    base = values.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_DATA_FOLDER
    return Path.home() / "AppData" / "Local" / APP_DATA_FOLDER


def configure_desktop_environment(root: Path | None = None) -> Path:
    data_root = (root or desktop_data_root()).resolve()
    data_dir = data_root / "data"
    storage_dir = data_root / "storage"
    export_dir = data_root / "exports"
    for path in (data_dir, storage_dir, export_dir, data_root / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    secret_path = data_root / ".desktop-secret"
    if secret_path.exists():
        app_secret = secret_path.read_text(encoding="utf-8").strip()
    else:
        app_secret = secrets.token_urlsafe(48)
        secret_path.write_text(app_secret, encoding="utf-8")

    db_path = (data_dir / "cafeteria.db").as_posix()
    os.environ["DESKTOP_MODE"] = "true"
    os.environ["DESKTOP_HWP_ONLY"] = "true"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["STORAGE_ROOT"] = str(storage_dir)
    os.environ["DATA_EXPORT_ROOT"] = str(export_dir)
    os.environ["APP_SECRET"] = app_secret
    os.environ["PUBLIC_BASE_URL"] = "http://127.0.0.1"
    return data_root


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
