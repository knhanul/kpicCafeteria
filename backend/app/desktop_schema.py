from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine


DESKTOP_SCHEMA_VERSION = 1


def ensure_desktop_schema_version(engine: Engine) -> int:
    if engine.dialect.name != "sqlite":
        return 0
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL, "
            "checksum VARCHAR(64) NOT NULL)"
        ))
        current = connection.execute(text("SELECT MAX(version) FROM schema_migrations")).scalar() or 0
        if current > DESKTOP_SCHEMA_VERSION:
            raise RuntimeError("이 데이터는 현재 PC 버전보다 새로운 스키마를 사용합니다.")
        if current < 1:
            connection.execute(
                text("INSERT INTO schema_migrations(version, applied_at, checksum) VALUES (:version, :applied_at, :checksum)"),
                {
                    "version": 1,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                    "checksum": "desktop-schema-v1",
                },
            )
    return DESKTOP_SCHEMA_VERSION
