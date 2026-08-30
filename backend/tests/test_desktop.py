from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import Base, create_database_engine
from app.desktop_runtime import configure_desktop_environment, desktop_data_root
from app.desktop_schema import DESKTOP_SCHEMA_VERSION, ensure_desktop_schema_version
from app.deps import current_user
from app.models import User
from app.routers.admin import _create_sqlite_backup, create_backup
from app.routers.documents import _require_pdf_enabled


def test_desktop_environment_uses_local_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert desktop_data_root() == tmp_path / "KPICCafeteria"

    root = configure_desktop_environment()
    first_secret = os.environ["APP_SECRET"]
    configure_desktop_environment(root)

    assert root == (tmp_path / "KPICCafeteria").resolve()
    assert os.environ["DESKTOP_MODE"] == "true"
    assert os.environ["DESKTOP_HWP_ONLY"] == "true"
    assert os.environ["DATABASE_URL"].endswith("/data/cafeteria.db")
    assert Path(os.environ["STORAGE_ROOT"]).is_dir()
    assert Path(os.environ["DATA_EXPORT_ROOT"]).is_dir()
    assert os.environ["APP_SECRET"] == first_secret


def test_sqlite_engine_enforces_desktop_pragmas(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'desktop.db').as_posix()}")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"


def test_utc_datetime_round_trip_on_sqlite(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'time.db').as_posix()}")
    Base.metadata.create_all(engine)
    original = datetime(2026, 8, 30, 18, 20, tzinfo=timezone(timedelta(hours=9)))
    with Session(engine) as db:
        user = User(username="time-user", password_hash="unused", display_name="시간", created_at=original)
        db.add(user)
        db.commit()
        user_id = user.id
    with Session(engine) as db:
        restored = db.get(User, user_id).created_at
        assert restored.tzinfo == timezone.utc
        assert restored == original.astimezone(timezone.utc)


def test_desktop_schema_version_is_idempotent(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'schema.db').as_posix()}")
    Base.metadata.create_all(engine)
    assert ensure_desktop_schema_version(engine) == DESKTOP_SCHEMA_VERSION
    assert ensure_desktop_schema_version(engine) == DESKTOP_SCHEMA_VERSION
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar() == 1


def test_sqlite_backup_is_valid_and_preserves_data(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "backup.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(name) VALUES ('급식')")
        connection.commit()

    _create_sqlite_backup(f"sqlite:///{source.as_posix()}", target)

    with sqlite3.connect(target) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT name FROM sample").fetchone()[0] == "급식"


def test_desktop_backup_endpoint_uses_sqlite_online_backup(tmp_path, monkeypatch):
    source = tmp_path / "application.db"
    engine = create_database_engine(f"sqlite:///{source.as_posix()}")
    Base.metadata.create_all(engine)
    backup_root = tmp_path / "exports"
    (backup_root / "backup" / "manual").mkdir(parents=True)
    monkeypatch.setattr("app.routers.admin.settings.database_url", f"sqlite:///{source.as_posix()}")
    monkeypatch.setattr("app.routers.admin.settings.data_export_root", backup_root)
    with Session(engine) as db:
        user = User(username="backup-user", password_hash="unused", display_name="백업", role="admin")
        db.add(user)
        db.commit()
        result = create_backup(db, user)
        backup_file = backup_root / "backup" / "manual" / result["filename"]
        assert result["filename"].endswith(".db")
        assert backup_file.is_file()
        with sqlite3.connect(backup_file) as verification:
            assert verification.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_desktop_current_user_uses_local_actor(tmp_path, monkeypatch):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(username="local-test", password_hash="unused", display_name="로컬", role="admin"))
        db.commit()
        monkeypatch.setattr("app.deps.settings.desktop_mode", True)
        monkeypatch.setattr("app.deps.settings.desktop_username", "local-test")
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        assert current_user(request, db).username == "local-test"


def test_desktop_hwp_only_mode_rejects_pdf(monkeypatch):
    monkeypatch.setattr("app.routers.documents.settings.desktop_hwp_only", True)
    with pytest.raises(HTTPException) as exc:
        _require_pdf_enabled()
    assert exc.value.status_code == 404


def test_desktop_app_boots_without_login_or_user_routes(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    script = """
import json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    root = client.get('/')
    login = client.get('/login', follow_redirects=False)
    codes = client.get('/api/master/codes')
    print(json.dumps({
        'root': root.status_code,
        'login': login.status_code,
        'codes': codes.status_code,
        'auth_route': any(route.path.startswith('/api/auth') for route in app.routes),
        'users_route': any(route.path.startswith('/api/users') for route in app.routes),
    }))
"""
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(backend),
        "DESKTOP_MODE": "true",
        "DESKTOP_HWP_ONLY": "true",
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        "STORAGE_ROOT": str(tmp_path / "storage"),
        "DATA_EXPORT_ROOT": str(tmp_path / "exports"),
        "APP_SECRET": "desktop-test-secret",
    })
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"root": 200, "login": 302, "codes": 200, "auth_route": False, "users_route": False}
