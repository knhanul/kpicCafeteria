from __future__ import annotations

from datetime import date, datetime, time, timezone
from urllib.parse import quote

import pytest

import app.routers.documents as documents_router
from app.document_hwpx import generate_pdf_bytes
from app.document_service import create_preview
from app.models import MealService
from app.routers.documents import download_pdf
from pydantic import ValidationError
from tests.test_document_hwpx import add_service, make_db, make_user, seed_template


def _seed_meal_plan(db, tmp_path):
    template = seed_template(db, tmp_path, "MEAL_PLAN")
    add_service(
        db,
        service_date=date(2026, 8, 17),
        meal_type="LUNCH",
        planned_count=321,
        service_time=time(11, 40),
        concept_title="여름 보양식",
        menus=[{"name": "현미밥"}, {"name": "육개장"}, {"name": "제육볶음"}],
    )
    add_service(
        db,
        service_date=date(2026, 8, 17),
        meal_type="DINNER",
        planned_count=87,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "비빔밥"}],
    )
    return template


def _seed_cooking_instruction(db, tmp_path):
    template = seed_template(db, tmp_path, "COOKING_INSTRUCTION")
    add_service(
        db,
        service_date=date(2026, 8, 17),
        meal_type="LUNCH",
        planned_count=357,
        service_time=time(11, 40),
        concept_title=None,
        menus=[
            {
                "name": "제육볶음",
                "ingredients": [
                    {"name": "돼지고기", "quantity": 18.0, "unit": "kg"},
                    {"name": "양파", "quantity": 2.5, "unit": "kg"},
                ],
                "instruction": "강불에 빠르게 볶는다.",
                "note": "매콤하게",
            }
        ],
    )
    add_service(
        db,
        service_date=date(2026, 8, 17),
        meal_type="DINNER",
        planned_count=95,
        service_time=time(17, 30),
        concept_title=None,
        menus=[
            {
                "name": "미역국",
                "ingredients": [{"name": "미역", "quantity": 1.2, "unit": "kg"}],
                "instruction": "끓인다.",
                "note": "",
            }
        ],
    )
    add_service(
        db,
        service_date=date(2026, 8, 18),
        meal_type="LUNCH",
        planned_count=312,
        service_time=time(11, 50),
        concept_title=None,
        menus=[{"name": "카레", "ingredients": []}],
    )
    return template


def _seed_preservation_record(db, tmp_path):
    template = seed_template(db, tmp_path, "PRESERVATION_RECORD")
    add_service(
        db,
        service_date=date(2026, 8, 17),
        meal_type="LUNCH",
        planned_count=410,
        service_time=time(11, 40),
        concept_title=None,
        menus=[{"name": "불고기"}],
        preservation={
            "collected_at": datetime(2026, 8, 17, 13, 20, tzinfo=timezone.utc),
            "manager": "홍길동",
            "freezer_temperature": "-18",
            "disposal_at": datetime(2026, 8, 18, 13, 20, tzinfo=timezone.utc),
            "collector": "김수거",
            "collection_time": "13:20",
        },
    )
    add_service(
        db,
        service_date=date(2026, 8, 17),
        meal_type="DINNER",
        planned_count=120,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "된장국"}],
        preservation=None,
    )
    add_service(
        db,
        service_date=date(2026, 8, 18),
        meal_type="LUNCH",
        planned_count=380,
        service_time=time(11, 50),
        concept_title=None,
        menus=[{"name": "카레"}],
        preservation={
            "collected_at": datetime(2026, 8, 18, 13, 10, tzinfo=timezone.utc),
            "manager": None,
            "freezer_temperature": None,
            "disposal_at": None,
            "collector": None,
            "collection_time": None,
        },
    )
    add_service(
        db,
        service_date=date(2026, 8, 18),
        meal_type="DINNER",
        planned_count=140,
        service_time=time(17, 50),
        concept_title=None,
        menus=[{"name": "라면"}],
        preservation={
            "collected_at": datetime(2026, 8, 18, 17, 50, tzinfo=timezone.utc),
            "manager": "한관리",
            "freezer_temperature": "-18",
            "disposal_at": datetime(2026, 8, 19, 17, 50, tzinfo=timezone.utc),
            "collector": "오수거",
            "collection_time": "17:50",
        },
    )
    return template


def test_generate_pdf_bytes_uses_generated_hwpx(tmp_path, monkeypatch):
    db = make_db()
    template_row = _seed_meal_plan(db, tmp_path)
    services = db.query(MealService).order_by(MealService.id).all()
    seen: dict[str, object] = {}

    class FakeRenderer:
        def render(self, hwpx_bytes: bytes, *, source_name: str = "document.hwpx") -> bytes:
            seen["hwpx_bytes"] = hwpx_bytes
            seen["source_name"] = source_name
            return b"%PDF-1.4\nfake-pdf\n"

    monkeypatch.setattr("app.document_hwpx.default_pdf_renderer", lambda: FakeRenderer())

    pdf_bytes, filename = generate_pdf_bytes(
        "MEAL_PLAN",
        services,
        template_row.storage_path,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 17),
    )

    assert pdf_bytes.startswith(b"%PDF")
    assert filename.endswith(".pdf")
    assert isinstance(seen.get("hwpx_bytes"), (bytes, bytearray))
    assert str(seen.get("source_name", "")).endswith(".hwpx")


def test_pdf_download_route_uses_hwp_first_path(tmp_path, monkeypatch):
    db = make_db()
    user = make_user(db)
    _seed_meal_plan(db, tmp_path)
    services = db.query(MealService).order_by(MealService.id).all()
    preview = create_preview(db, "MEAL_PLAN", services, user.id)

    monkeypatch.setattr(
        documents_router,
        "render_pdf",
        lambda _db, _preview: (b"%PDF-1.4\nfake-pdf\n", "식단표_20260817_20260817.pdf"),
    )

    response = download_pdf(preview.token, db, user)

    assert response.media_type == "application/pdf"
    assert quote("식단표_20260817_20260817.pdf") in response.headers["content-disposition"]
    assert response.body.startswith(b"%PDF")
    assert len(response.body) > 10


def test_preview_range_body_rejects_inverted_dates():
    with pytest.raises(ValidationError):
        documents_router.PreviewRangeBody(start_date=date(2026, 8, 18), end_date=date(2026, 8, 17))


@pytest.mark.parametrize(
    ("endpoint", "document_type", "seed_func", "expected_filename"),
    [
        (documents_router.preview_meal_plan_pdf, "MEAL_PLAN", _seed_meal_plan, "식단표_20260817_20260817.pdf"),
        (
            documents_router.preview_cooking_instruction_pdf,
            "COOKING_INSTRUCTION",
            _seed_cooking_instruction,
            "조리지시서_20260817_20260818.pdf",
        ),
        (
            documents_router.preview_preserved_food_pdf,
            "PRESERVATION_RECORD",
            _seed_preservation_record,
            "보존식기록지_20260817_20260818.pdf",
        ),
    ],
)
def test_preview_endpoints_return_inline_pdf_from_date_range(tmp_path, monkeypatch, endpoint, document_type, seed_func, expected_filename):
    db = make_db()
    user = make_user(db)
    seed_func(db, tmp_path)
    seen: dict[str, object] = {}

    def fake_generate_pdf_bytes(doc_type, services, template_path, *, start_date=None, end_date=None):
        seen["document_type"] = doc_type
        seen["service_ids"] = [service.id for service in services]
        seen["template_path"] = template_path
        seen["start_date"] = start_date
        seen["end_date"] = end_date
        return b"%PDF-1.4\nfake-pdf\n", expected_filename

    monkeypatch.setattr(documents_router, "generate_pdf_bytes", fake_generate_pdf_bytes)

    response = endpoint(documents_router.PreviewRangeBody(start_date=date(2026, 8, 17), end_date=date(2026, 8, 18)), db, user)

    assert response.media_type == "application/pdf"
    assert response.body.startswith(b"%PDF")
    assert response.headers["content-disposition"].startswith("inline;")
    assert quote(expected_filename) in response.headers["content-disposition"]
    assert seen["document_type"] == document_type
    assert seen["start_date"] == date(2026, 8, 17)
    assert seen["end_date"] == date(2026, 8, 18)
    assert len(seen["service_ids"]) > 0
