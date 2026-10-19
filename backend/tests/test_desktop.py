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
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker
from types import SimpleNamespace

from app.db import Base, create_database_engine
from app.desktop_runtime import configure_desktop_environment, desktop_data_root
from app.desktop_schema import DESKTOP_SCHEMA_VERSION, ensure_desktop_schema_version
from app.deps import current_user
from app.models import BackupRecord, Menu, User
from app.routers.admin import _create_sqlite_backup, _perform_backup, _run_restore, create_backup
from app.routers.documents import _require_pdf_enabled
from app.storage_resolver import document_template_file, import_job_file, resolve_stored_file


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


def test_resolve_stored_file_rebases_foreign_paths(tmp_path):
    template_root = tmp_path / "templates"
    target = template_root / "meal_plan" / "stored.hwpx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"hwpx")

    # Docker 서버에서 기록된 절대 경로가 이 PC에서도 파일명으로 다시 찾아진다.
    resolved = resolve_stored_file("/app/storage/templates/meal_plan/stored.hwpx", template_root)
    assert resolved == target
    # Windows 형식 경로도 동일하게 처리한다.
    resolved_win = resolve_stored_file(r"C:\other\storage\meal_plan\stored.hwpx", template_root)
    assert resolved_win == target
    # 파일이 없으면 기본 재배치 후보를 돌려준다.
    missing = resolve_stored_file("/app/storage/templates/meal_plan/missing.hwpx", template_root, subdir="meal_plan")
    assert missing == template_root / "meal_plan" / "missing.hwpx"


def test_document_template_file_uses_document_type_subdir(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    target = storage_root / "templates" / "cooking_instruction" / "v2.hwpx"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"hwpx")
    monkeypatch.setattr("app.storage_resolver.settings.storage_root", storage_root)

    row = SimpleNamespace(
        document_type="COOKING_INSTRUCTION",
        stored_filename="v2.hwpx",
        storage_path="/app/storage/templates/cooking_instruction/v2.hwpx",
    )
    assert document_template_file(row) == target


def test_import_job_file_rebases_to_import_dir(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    import_root = storage_root / "imports"
    import_root.mkdir(parents=True)
    target = import_root / "token.xlsx"
    target.write_bytes(b"xlsx")
    monkeypatch.setattr("app.storage_resolver.settings.storage_root", storage_root)

    assert import_job_file("/app/storage/imports/token.xlsx") == target


def test_sqlite_restore_reverts_data_and_creates_safety_backup(tmp_path, monkeypatch):
    source = tmp_path / "application.db"
    engine = create_database_engine(f"sqlite:///{source.as_posix()}")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    exports = tmp_path / "exports"
    (exports / "backup" / "auto").mkdir(parents=True)
    (exports / "backup" / "manual").mkdir(parents=True)
    monkeypatch.setattr("app.routers.admin.settings.database_url", f"sqlite:///{source.as_posix()}")
    monkeypatch.setattr("app.routers.admin.settings.data_export_root", exports)
    monkeypatch.setattr("app.routers.admin.engine", engine)
    monkeypatch.setattr("app.routers.admin.SessionLocal", TestingSession)

    with TestingSession() as db:
        user = User(username="restore-user", password_hash="unused", display_name="복원", role="admin")
        db.add(user)
        db.add(Menu(name="된장찌개", canonical_name="된장찌개"))
        db.commit()
        manual = _perform_backup(db, user, "manual")
        backup_path = exports / "backup" / "manual" / manual.stored_filename
        assert backup_path.is_file()

        db.add(Menu(name="김치찌개", canonical_name="김치찌개"))
        db.commit()

        result = _run_restore(backup_path, db, user, manual.filename)
        assert result["safety_backup"].endswith(".db")

        safety_path = exports / "backup" / "auto" / result["safety_backup"]
        assert safety_path.is_file()

    with TestingSession() as db:
        names = {menu.name for menu in db.scalars(select(Menu)).all()}
        assert names == {"된장찌개"}
        safety = db.scalar(select(BackupRecord).where(BackupRecord.filename == result["safety_backup"]))
        # 백업 기록 테이블도 백업 시점으로 되돌아간다.
        assert safety is None

    # 안전 백업을 복원하면 되돌리기 전 데이터가 다시 돌아온다.
    with TestingSession() as db:
        user = db.scalar(select(User).where(User.username == "restore-user"))
        _run_restore(safety_path, db, user, result["safety_backup"])
    with TestingSession() as db:
        names = {menu.name for menu in db.scalars(select(Menu)).all()}
        assert names == {"된장찌개", "김치찌개"}
