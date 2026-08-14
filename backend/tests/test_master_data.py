"""Tests for master data management: HWPX templates and meal service defaults."""
from __future__ import annotations

import io
import zipfile
from datetime import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import DocumentTemplate, MealTypeSetting, User
from app.routers.master_data import (
    MealServiceDefaultsBody,
    MealServiceDefaultItem,
    activate_template,
    delete_template,
    get_meal_service_defaults,
    list_templates,
    update_meal_service_defaults,
    upload_template,
)
from app.hwpx_service import HwpxTemplateError, validate_hwpx


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def make_user(db: Session) -> User:
    user = User(username="admin", password_hash="x", display_name="관리자", active=True)
    db.add(user)
    db.flush()
    return user


def seed_meal_types(db: Session):
    db.add(MealTypeSetting(code="LUNCH", name="중식", default_planned_count=400, default_service_time=time(11, 40), sort_order=1, active=True))
    db.add(MealTypeSetting(code="DINNER", name="석식", default_planned_count=100, default_service_time=time(17, 30), sort_order=2, active=True))
    db.flush()


# ---------------------------------------------------------------------------
# Meal service defaults tests
# ---------------------------------------------------------------------------

class TestMealServiceDefaults:
    def test_get_defaults(self):
        db = make_db()
        seed_meal_types(db)
        user = make_user(db)
        result = get_meal_service_defaults(db, user)
        assert len(result) == 2
        assert result[0]["meal_type"] == "LUNCH"
        assert result[0]["default_planned_count"] == 400
        assert result[0]["default_service_time"] == "11:40"
        assert result[1]["meal_type"] == "DINNER"
        assert result[1]["default_planned_count"] == 100

    def test_update_defaults(self):
        db = make_db()
        seed_meal_types(db)
        user = make_user(db)
        body = MealServiceDefaultsBody(items=[
            MealServiceDefaultItem(meal_type="LUNCH", default_planned_count=350, default_service_time="12:00", is_active=True),
            MealServiceDefaultItem(meal_type="DINNER", default_planned_count=80, default_service_time="18:00", is_active=True),
        ])
        result = update_meal_service_defaults(body, db, user)
        assert result[0]["default_planned_count"] == 350
        assert result[0]["default_service_time"] == "12:00"
        assert result[1]["default_planned_count"] == 80
        assert result[1]["default_service_time"] == "18:00"

    def test_update_defaults_non_negative_count(self):
        with pytest.raises(Exception):
            MealServiceDefaultItem(meal_type="LUNCH", default_planned_count=-1, default_service_time="12:00")

    def test_update_defaults_invalid_time(self):
        with pytest.raises(Exception):
            MealServiceDefaultItem(meal_type="LUNCH", default_planned_count=100, default_service_time="25:99")

    def test_update_defaults_unknown_meal_type(self):
        db = make_db()
        seed_meal_types(db)
        user = make_user(db)
        body = MealServiceDefaultsBody(items=[
            MealServiceDefaultItem(meal_type="BREAKFAST", default_planned_count=50, default_service_time="08:00"),
        ])
        with pytest.raises(HTTPException) as exc_info:
            update_meal_service_defaults(body, db, user)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# HWPX validation tests
# ---------------------------------------------------------------------------

def make_minimal_hwpx(placeholders: list[str] | None = None) -> bytes:
    """Create a minimal valid HWPX file in memory."""
    placeholders = placeholders or []
    meal_plan_aliases = {
        "D1_DATE": "W1_D1_DATE",
        "D1_LUNCH": "W1_D1_LUNCH_MENU",
        "D1_DINNER": "W1_D1_DINNER_MENU",
        "D2_DATE": "W1_D2_DATE",
        "D2_LUNCH": "W1_D2_LUNCH_MENU",
        "D2_DINNER": "W1_D2_DINNER_MENU",
        "D3_DATE": "W1_D3_DATE",
        "D3_LUNCH": "W1_D3_LUNCH_MENU",
        "D3_DINNER": "W1_D3_DINNER_MENU",
        "D4_DATE": "W1_D4_DATE",
        "D4_LUNCH": "W1_D4_LUNCH_MENU",
        "D4_DINNER": "W1_D4_DINNER_MENU",
        "D5_DATE": "W1_D5_DATE",
        "D5_LUNCH": "W1_D5_LUNCH_MENU",
        "D5_DINNER": "W1_D5_DINNER_MENU",
        "D6_DATE": "W2_D1_DATE",
        "D6_LUNCH": "W2_D1_LUNCH_MENU",
        "D6_DINNER": "W2_D1_DINNER_MENU",
        "D7_DATE": "W2_D2_DATE",
        "D7_LUNCH": "W2_D2_LUNCH_MENU",
        "D7_DINNER": "W2_D2_DINNER_MENU",
        "D8_DATE": "W2_D3_DATE",
        "D8_LUNCH": "W2_D3_LUNCH_MENU",
        "D8_DINNER": "W2_D3_DINNER_MENU",
        "D9_DATE": "W2_D4_DATE",
        "D9_LUNCH": "W2_D4_LUNCH_MENU",
        "D9_DINNER": "W2_D4_DINNER_MENU",
        "D10_DATE": "W2_D5_DATE",
        "D10_LUNCH": "W2_D5_LUNCH_MENU",
        "D10_DINNER": "W2_D5_DINNER_MENU",
    }
    placeholders = [meal_plan_aliases.get(item, item) for item in placeholders]
    placeholder_text = " ".join(f"{{{{{p}}}}}" for p in placeholders)
    section_xml = f'<?xml version="1.0" encoding="UTF-8"?><section xmlns="http://www.hancom.co.kr/hwpml/2011/section"><p><run><t>{placeholder_text}</t></run></p></section>'
    content_hpf = '<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.hancom.co.kr/hwpml/2011/package"><manifest><item id="section1" href="section1.xml"/></manifest><spine><itemref idref="section1"/></spine></package>'
    header_xml = '<?xml version="1.0" encoding="UTF-8"?><header xmlns="http://www.hancom.co.kr/hwpml/2011/header"/>'
    version_xml = '<?xml version="1.0" encoding="UTF-8"?><version/>'
    container_xml = '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles><rootfile full-path="Contents/content.hpf"/></rootfiles></container>'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/vnd.hancom.hwpx")
        zf.writestr("version.xml", version_xml)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("Contents/content.hpf", content_hpf)
        zf.writestr("Contents/header.xml", header_xml)
        zf.writestr("Contents/section1.xml", section_xml)
    return buf.getvalue()


MEAL_PLAN_PLACEHOLDERS = [
    "W1_D1_DATE", "W1_D1_LUNCH_MENU", "W1_D1_DINNER_MENU",
    "W1_D2_DATE", "W1_D2_LUNCH_MENU", "W1_D2_DINNER_MENU",
    "W1_D3_DATE", "W1_D3_LUNCH_MENU", "W1_D3_DINNER_MENU",
    "W1_D4_DATE", "W1_D4_LUNCH_MENU", "W1_D4_DINNER_MENU",
    "W1_D5_DATE", "W1_D5_LUNCH_MENU", "W1_D5_DINNER_MENU",
    "W2_D1_DATE", "W2_D1_LUNCH_MENU", "W2_D1_DINNER_MENU",
    "W2_D2_DATE", "W2_D2_LUNCH_MENU", "W2_D2_DINNER_MENU",
    "W2_D3_DATE", "W2_D3_LUNCH_MENU", "W2_D3_DINNER_MENU",
    "W2_D4_DATE", "W2_D4_LUNCH_MENU", "W2_D4_DINNER_MENU",
    "W2_D5_DATE", "W2_D5_LUNCH_MENU", "W2_D5_DINNER_MENU",
    "PERIOD_TITLE", "ORIGIN_INFO", "NOTICE", "W1_LUNCH_TIME_INFO", "W2_LUNCH_TIME_INFO", "DINNER_TIME_INFO",
]


class TestHwpxValidation:
    def test_valid_hwpx(self, tmp_path):
        data = make_minimal_hwpx(MEAL_PLAN_PLACEHOLDERS)
        path = tmp_path / "test.hwpx"
        path.write_bytes(data)
        result = validate_hwpx(path, "MEAL_PLAN")
        assert result["sections"] == 1
        assert "W1_D1_DATE" in result["placeholders"]

    def test_missing_required_file(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/vnd.hancom.hwpx")
            zf.writestr("Contents/section1.xml", '<?xml version="1.0"?><section/>')
        path = tmp_path / "bad.hwpx"
        path.write_bytes(buf.getvalue())
        with pytest.raises(HwpxTemplateError):
            validate_hwpx(path)

    def test_too_small_file(self, tmp_path):
        path = tmp_path / "tiny.hwpx"
        path.write_bytes(b"tiny")
        with pytest.raises(HwpxTemplateError, match="너무 작습니다"):
            validate_hwpx(path)

    def test_zip_slip_protection(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/vnd.hancom.hwpx")
            zf.writestr("version.xml", '<?xml version="1.0"?><version/>')
            zf.writestr("META-INF/container.xml", '<?xml version="1.0"?><container/>')
            zf.writestr("Contents/content.hpf", '<?xml version="1.0"?><package><manifest><item id="s1" href="section1.xml"/></manifest><spine><itemref idref="s1"/></spine></package>')
            zf.writestr("Contents/header.xml", '<?xml version="1.0"?><header/>')
            zf.writestr("Contents/section1.xml", '<?xml version="1.0"?><section/>')
            zf.writestr("../evil.txt", "malicious")
        path = tmp_path / "slip.hwpx"
        path.write_bytes(buf.getvalue())
        with pytest.raises(HwpxTemplateError, match="안전하지 않은 경로"):
            validate_hwpx(path)

    def test_missing_placeholders(self, tmp_path):
        data = make_minimal_hwpx(["D1_DATE"])
        path = tmp_path / "test.hwpx"
        path.write_bytes(data)
        with pytest.raises(HwpxTemplateError, match="플레이스홀더"):
            validate_hwpx(path, "MEAL_PLAN")

    def test_spine_references_missing_manifest_id(self, tmp_path):
        content_hpf = '<?xml version="1.0"?><package xmlns="http://www.hancom.co.kr/hwpml/2011/package"><manifest><item id="section1" href="section1.xml"/></manifest><spine><itemref idref="nonexistent"/></spine></package>'
        section_xml = '<?xml version="1.0"?><section xmlns="http://www.hancom.co.kr/hwpml/2011/section"><p><run><t>' + 'x' * 1200 + '</t></run></p></section>'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/vnd.hancom.hwpx")
            zf.writestr("version.xml", '<?xml version="1.0"?><version/>')
            zf.writestr("META-INF/container.xml", '<?xml version="1.0"?><container/>')
            zf.writestr("Contents/content.hpf", content_hpf)
            zf.writestr("Contents/header.xml", '<?xml version="1.0"?><header/>')
            zf.writestr("Contents/section1.xml", section_xml)
        path = tmp_path / "bad_spine.hwpx"
        path.write_bytes(buf.getvalue())
        with pytest.raises(HwpxTemplateError, match="spine이 manifest"):
            validate_hwpx(path)


# ---------------------------------------------------------------------------
# Template management API tests
# ---------------------------------------------------------------------------

class TestTemplateManagement:
    def _make_upload_file(self, data: bytes, filename: str = "test.hwpx"):
        from fastapi import UploadFile
        return UploadFile(filename=filename, file=io.BytesIO(data), size=len(data))

    def test_upload_and_list_template(self, tmp_path):
        db = make_db()
        user = make_user(db)
        data = make_minimal_hwpx(MEAL_PLAN_PLACEHOLDERS)
        with patch("app.routers.master_data.settings") as mock_settings:
            mock_settings.template_dir = tmp_path / "templates"
            file = self._make_upload_file(data)
            result = upload_template(
                document_type="MEAL_PLAN", name="테스트 식단표", description="테스트용",
                activate=True, file=file, db=db, user=user,
            )
        assert result["is_valid"] is True
        assert result["active"] is True
        assert result["version"] == 1
        assert result["file_size"] > 0
        assert len(result["checksum_sha256"]) == 64
        assert "W1_D1_DATE" in result["placeholder_summary"]["placeholders"]

        templates = list_templates(db, user)
        assert len(templates) == 1

    def test_activate_deactivates_previous(self, tmp_path):
        db = make_db()
        user = make_user(db)
        data = make_minimal_hwpx(MEAL_PLAN_PLACEHOLDERS)
        with patch("app.routers.master_data.settings") as mock_settings:
            mock_settings.template_dir = tmp_path / "templates"
            file1 = self._make_upload_file(data, "v1.hwpx")
            first = upload_template(document_type="MEAL_PLAN", name="v1", description="", activate=True, file=file1, db=db, user=user)
            file2 = self._make_upload_file(data, "v2.hwpx")
            second = upload_template(document_type="MEAL_PLAN", name="v2", description="", activate=True, file=file2, db=db, user=user)

        assert first["active"] is True
        assert second["active"] is True
        # After activating second, first should be deactivated
        db.refresh(db.get(DocumentTemplate, first["id"]))
        first_row = db.get(DocumentTemplate, first["id"])
        assert first_row.active is False
        second_row = db.get(DocumentTemplate, second["id"])
        assert second_row.active is True

    def test_delete_active_template_blocked(self, tmp_path):
        db = make_db()
        user = make_user(db)
        data = make_minimal_hwpx(MEAL_PLAN_PLACEHOLDERS)
        with patch("app.routers.master_data.settings") as mock_settings:
            mock_settings.template_dir = tmp_path / "templates"
            file = self._make_upload_file(data)
            result = upload_template(document_type="MEAL_PLAN", name="test", description="", activate=True, file=file, db=db, user=user)

        with pytest.raises(HTTPException) as exc_info:
            delete_template(result["id"], db, user)
        assert exc_info.value.status_code == 400
        assert "활성" in exc_info.value.detail

    def test_delete_inactive_template(self, tmp_path):
        db = make_db()
        user = make_user(db)
        data = make_minimal_hwpx(MEAL_PLAN_PLACEHOLDERS)
        with patch("app.routers.master_data.settings") as mock_settings:
            mock_settings.template_dir = tmp_path / "templates"
            file = self._make_upload_file(data)
            result = upload_template(document_type="MEAL_PLAN", name="test", description="", activate=False, file=file, db=db, user=user)

        delete_template(result["id"], db, user)
        assert db.get(DocumentTemplate, result["id"]) is None

    def test_activate_validates_first(self, tmp_path):
        db = make_db()
        user = make_user(db)
        data = make_minimal_hwpx(MEAL_PLAN_PLACEHOLDERS)
        with patch("app.routers.master_data.settings") as mock_settings:
            mock_settings.template_dir = tmp_path / "templates"
            file = self._make_upload_file(data)
            result = upload_template(document_type="MEAL_PLAN", name="test", description="", activate=False, file=file, db=db, user=user)

            # Now corrupt the file
            template = db.get(DocumentTemplate, result["id"])
            Path(template.storage_path).write_bytes(b"corrupted")

            with pytest.raises(HTTPException) as exc_info:
                activate_template(result["id"], db, user)
            assert exc_info.value.status_code == 400
