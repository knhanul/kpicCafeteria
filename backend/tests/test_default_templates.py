from __future__ import annotations

import hashlib
import io
import re
from zipfile import ZipFile
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.default_templates import DEFAULT_TEMPLATE_SPECS, default_template_source_dir, ensure_default_templates
from app.document_hwpx import HwpxRenderRequest
from app.hwpx_engine import render_document
from app.models import DocumentTemplate


SOURCE_DIR = Path(__file__).resolve().parents[2] / "docs" / "template"


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def test_default_template_source_directory_is_resolved():
    assert default_template_source_dir() == SOURCE_DIR


def test_default_templates_are_seeded_active_and_repeatable(tmp_path):
    db = make_db()
    storage_dir = tmp_path / "storage" / "templates"

    assert ensure_default_templates(db, storage_dir, SOURCE_DIR) == 3
    rows = db.scalars(select(DocumentTemplate).order_by(DocumentTemplate.document_type)).all()
    assert len(rows) == len(DEFAULT_TEMPLATE_SPECS)
    assert {row.document_type for row in rows} == {spec[0] for spec in DEFAULT_TEMPLATE_SPECS}
    assert all(row.active and row.is_valid for row in rows)

    for row in rows:
        stored = Path(row.storage_path)
        source = SOURCE_DIR / row.original_filename
        assert stored.is_file()
        assert hashlib.sha256(stored.read_bytes()).hexdigest() == hashlib.sha256(source.read_bytes()).hexdigest()
        payload = {
            "MEAL_PLAN": {"weeks": []},
            "COOKING_INSTRUCTION": {"days": [], "period_label": ""},
            "PRESERVATION_RECORD": {"records": [], "period_label": ""},
        }[row.document_type]
        rendered = render_document(stored, HwpxRenderRequest(row.document_type, payload))
        with ZipFile(io.BytesIO(rendered)) as archive:
            section_xml = b"".join(
                archive.read(name)
                for name in archive.namelist()
                if re.fullmatch(r"Contents/section\d+\.xml", name)
            )
        assert b"{{" not in section_xml

    assert ensure_default_templates(db, storage_dir, SOURCE_DIR) == 0
    assert db.scalar(select(DocumentTemplate.id).order_by(DocumentTemplate.id.desc()).limit(1)) == 3
    db.close()


def test_seeding_does_not_replace_or_activate_over_existing_user_template(tmp_path):
    db = make_db()
    custom = DocumentTemplate(
        document_type="MEAL_PLAN",
        name="사용자 식단표",
        original_filename="custom.hwpx",
        stored_filename="custom.hwpx",
        storage_path=str(tmp_path / "custom.hwpx"),
        checksum_sha256="user-template-checksum",
        active=True,
        version=1,
        is_valid=True,
        created_by="user",
    )
    db.add(custom)
    db.commit()

    assert ensure_default_templates(db, tmp_path / "templates", SOURCE_DIR) == 3
    db.refresh(custom)
    meal_plan_rows = db.scalars(
        select(DocumentTemplate).where(DocumentTemplate.document_type == "MEAL_PLAN")
    ).all()
    assert custom.active is True
    assert len(meal_plan_rows) == 2
    assert sum(row.active for row in meal_plan_rows) == 1
    assert next(row for row in meal_plan_rows if row.id != custom.id).active is False
    db.close()
