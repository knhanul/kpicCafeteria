from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, time, timedelta, timezone

from urllib.parse import quote

import pytest

from app.document_hwpx import generate_hwpx_bytes, generate_pdf_bytes
from app.hwpx_engine import HwpxPackage
from app.models import MealService
from app.routers.documents import (
    ExportBody,
    download_cooking_instruction_hwpx,
    download_meal_plan_hwpx,
    download_preserved_food_hwpx,
)
from tests.test_document_hwpx import add_service, make_db, make_user, seed_template


def _section_texts(hwpx_bytes: bytes) -> list[str]:
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as archive:
        for name in sorted(item for item in archive.namelist() if item.startswith("Contents/section") and item.endswith(".xml")):
            root = ET.fromstring(archive.read(name))
            texts.append("".join(node.text or "" for node in root.iter() if node.tag.split("}")[-1] == "t"))
    return texts


def _assert_valid_hwpx(path, hwpx_bytes: bytes) -> None:
    path.write_bytes(hwpx_bytes)
    package = HwpxPackage.load(path)
    result = package.validate()
    assert result["file_size"] == path.stat().st_size
    assert result["sections"] >= 1
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as archive:
        assert archive.testzip() is None
    assert "{{" not in "\n".join(_section_texts(hwpx_bytes))


def _meal_plan_full_week_dataset(db, tmp_path):
    template = seed_template(db, tmp_path, "MEAL_PLAN")
    monday = date(2026, 8, 17)
    menus = [
        ["현미밥", "육개장", "제육볶음"],
        ["김치볶음밥", "계란국"],
        ["돌솥비빔밥", "오이무침"],
        ["카레라이스", "배추김치"],
        ["불고기덮밥", "미소국"],
    ]
    for offset, day_menus in enumerate(menus):
        service_date = monday + timedelta(days=offset)
        add_service(
            db,
            service_date=service_date,
            meal_type="LUNCH",
            planned_count=300 + offset * 10,
            service_time=time(11, 40),
            concept_title="여름 보양식" if offset == 0 else None,
            menus=[{"name": name} for name in day_menus],
        )
        add_service(
            db,
            service_date=service_date,
            meal_type="DINNER",
            planned_count=90 + offset * 5,
            service_time=time(17, 30),
            concept_title=None,
            menus=[{"name": f"석식메뉴{offset + 1}"}],
        )
    return template, monday, monday + timedelta(days=4)


def _meal_plan_sparse_edge_dataset(db, tmp_path):
    template = seed_template(db, tmp_path, "MEAL_PLAN")
    monday = date(2026, 8, 17)
    add_service(
        db,
        service_date=monday,
        meal_type="LUNCH",
        planned_count=320,
        service_time=time(11, 40),
        concept_title="긴 메뉴명 테스트",
        menus=[
            {"name": "매우 매우 긴 메뉴명 테스트용 샘플 메뉴 이름입니다"},
            {"name": "국/탕/찌개 포함 메뉴"},
            {"name": "특수문자 & < > \" ' 포함 메뉴"},
        ],
    )
    add_service(
        db,
        service_date=monday + timedelta(days=1),
        meal_type="DINNER",
        planned_count=95,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "석식만 존재"}],
    )
    add_service(
        db,
        service_date=monday + timedelta(days=3),
        meal_type="LUNCH",
        planned_count=290,
        service_time=time(11, 45),
        concept_title=None,
        menus=[{"name": f"메뉴 {index}"} for index in range(1, 11)],
    )
    add_service(
        db,
        service_date=monday + timedelta(days=4),
        meal_type="DINNER",
        planned_count=88,
        service_time=time(17, 35),
        concept_title=None,
        menus=[{"name": "마지막 석식"}],
    )
    return template, monday, monday + timedelta(days=4)


def _cooking_instruction_dataset(db, tmp_path):
    template = seed_template(db, tmp_path, "COOKING_INSTRUCTION")
    service_date = date(2026, 8, 17)
    add_service(
        db,
        service_date=service_date,
        meal_type="LUNCH",
        planned_count=360,
        service_time=time(11, 40),
        concept_title=None,
        menus=[
            {
                "name": "제육볶음",
                "ingredients": [
                    {"name": "돼지고기", "quantity": 18.0, "quantity_per_100": 5.0, "unit": "kg", "remark": "앞다리살"},
                ],
                "instruction": "강불에 빠르게 볶는다.",
                "note": "매콤하게",
            },
            {
                "name": "대량 재료 메뉴",
                "ingredients": [
                    {"name": f"재료{index}", "quantity": None if index % 2 else float(index), "quantity_per_100": float(index) / 2, "unit": None if index % 3 == 0 else "kg", "remark": None}
                    for index in range(1, 12)
                ],
                "instruction": "재료를 순서대로 손질한다.",
                "note": "10개 이상 재료",
            },
            {
                "name": "긴 식재료명 메뉴",
                "ingredients": [
                    {"name": "아주아주길고상세한식재료명테스트용재료이름입니다", "quantity": 1.2, "quantity_per_100": None, "unit": "g", "remark": "긴 이름"},
                ],
                "instruction": "천천히 섞는다.",
                "note": None,
            },
        ],
    )
    add_service(
        db,
        service_date=service_date,
        meal_type="DINNER",
        planned_count=120,
        service_time=time(17, 30),
        concept_title=None,
        menus=[
            {
                "name": "미역국",
                "ingredients": [{"name": "미역", "quantity": 1.2, "quantity_per_100": 0.3, "unit": None, "remark": None}],
                "instruction": "끓인다.",
                "note": "비고 존재",
            },
        ],
    )
    return template, service_date, service_date


def _preservation_dataset(db, tmp_path):
    template = seed_template(db, tmp_path, "PRESERVATION_RECORD")
    monday = date(2026, 8, 17)
    add_service(
        db,
        service_date=monday,
        meal_type="LUNCH",
        planned_count=410,
        service_time=time(11, 40),
        concept_title=None,
        menus=[{"name": f"중식메뉴{index}"} for index in range(1, 7)],
        preservation={
            "collected_at": datetime(2026, 8, 17, 13, 20, tzinfo=timezone.utc),
            "manager": "홍길동",
            "freezer_temperature": "-18",
            "disposal_at": datetime(2026, 8, 18, 13, 20, tzinfo=timezone.utc),
            "collector": "김수거",
            "collection_time": "13:20",
            "note": "중식/석식 모두 존재",
        },
    )
    add_service(
        db,
        service_date=monday,
        meal_type="DINNER",
        planned_count=120,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "된장국"}],
        preservation={
            "collected_at": datetime(2026, 8, 17, 17, 40, tzinfo=timezone.utc),
            "manager": "이관리",
            "freezer_temperature": "-18",
            "disposal_at": datetime(2026, 8, 18, 17, 40, tzinfo=timezone.utc),
            "collector": "박수거",
            "collection_time": "17:40",
            "note": None,
        },
    )
    add_service(
        db,
        service_date=monday + timedelta(days=1),
        meal_type="LUNCH",
        planned_count=380,
        service_time=time(11, 50),
        concept_title=None,
        menus=[{"name": "카레"}],
        preservation={
            "collected_at": None,
            "manager": None,
            "freezer_temperature": None,
            "disposal_at": None,
            "collector": None,
            "collection_time": None,
            "note": None,
        },
    )
    add_service(
        db,
        service_date=monday + timedelta(days=2),
        meal_type="DINNER",
        planned_count=140,
        service_time=time(17, 50),
        concept_title=None,
        menus=[{"name": "라면"}],
        preservation={
            "collected_at": datetime(2026, 8, 19, 17, 50, tzinfo=timezone.utc),
            "manager": "한관리",
            "freezer_temperature": None,
            "disposal_at": datetime(2026, 8, 20, 17, 50, tzinfo=timezone.utc),
            "collector": None,
            "collection_time": "17:50",
            "note": "일부 기록 필드만 존재",
        },
    )
    return template, monday, monday + timedelta(days=2)


@pytest.mark.parametrize(
    ("dataset_builder", "expected_strings"),
    [
        (
            _meal_plan_full_week_dataset,
            ["여름 보양식", "현미밥", "석식메뉴5", "08.17", "08.21"],
        ),
        (
            _meal_plan_sparse_edge_dataset,
            ["매우 매우 긴 메뉴명 테스트용 샘플 메뉴 이름입니다", "국/탕/찌개 포함 메뉴", "특수문자 & < >", "메뉴 10", "마지막 석식"],
        ),
    ],
)
def test_meal_plan_hwpx_output_cases_are_valid_and_editable_like_source(tmp_path, dataset_builder, expected_strings):
    db = make_db()
    user = make_user(db)
    _template, start_date, end_date = dataset_builder(db, tmp_path)

    response = download_meal_plan_hwpx(ExportBody(start_date=start_date, end_date=end_date), db, user)

    assert response.media_type == "application/vnd.hancom.hwpx"
    assert quote("식단표_20260817_20260821.hwpx") in response.headers["content-disposition"]
    _assert_valid_hwpx(tmp_path / "meal-plan-out.hwpx", response.body)
    text = "\n".join(_section_texts(response.body))
    for expected in expected_strings:
        assert expected in text
    assert db.query(MealService).filter(MealService.meal_plan_output_at.isnot(None)).count() > 0


def test_cooking_instruction_hwpx_output_cases_are_valid_and_editable_like_source(tmp_path):
    db = make_db()
    user = make_user(db)
    template, start_date, end_date = _cooking_instruction_dataset(db, tmp_path)

    hwpx_bytes, _ = generate_hwpx_bytes("COOKING_INSTRUCTION", db.query(MealService).order_by(MealService.id).all(), template.storage_path, start_date=start_date, end_date=end_date)
    assert hwpx_bytes.startswith(b"PK")

    response = download_cooking_instruction_hwpx(ExportBody(start_date=start_date, end_date=end_date), db, user)

    assert response.media_type == "application/vnd.hancom.hwpx"
    _assert_valid_hwpx(tmp_path / "cooking-out.hwpx", response.body)
    text = "\n".join(_section_texts(response.body))
    assert "제육볶음" in text
    assert "대량 재료 메뉴" in text
    assert "긴 식재료명 메뉴" in text
    assert "아주아주길고상세한식재료명테스트용재료이름입니다" in text
    assert "비고 존재" in text
    assert "매콤하게" in text


def test_preservation_record_hwpx_output_cases_are_valid_and_editable_like_source(tmp_path):
    db = make_db()
    user = make_user(db)
    template, start_date, end_date = _preservation_dataset(db, tmp_path)

    response = download_preserved_food_hwpx(ExportBody(start_date=start_date, end_date=end_date), db, user)

    assert response.media_type == "application/vnd.hancom.hwpx"
    _assert_valid_hwpx(tmp_path / "preservation-out.hwpx", response.body)
    text = "\n".join(_section_texts(response.body))
    assert "중식메뉴1" in text
    assert "중식메뉴6" in text
    assert "홍길동" in text
    assert "김수거" in text
    assert "라면" in text


@pytest.mark.parametrize(
    ("document_type", "dataset_builder", "expected_hwpx_filename"),
    [
        ("MEAL_PLAN", _meal_plan_full_week_dataset, "식단표_20260817_20260821.hwpx"),
        ("COOKING_INSTRUCTION", _cooking_instruction_dataset, "조리지시서_20260817.hwpx"),
        ("PRESERVATION_RECORD", _preservation_dataset, "보존식기록지_20260817_20260819.hwpx"),
    ],
)
def test_pdf_generation_uses_same_hwpx_bytes_as_hwpx_download(tmp_path, monkeypatch, document_type, dataset_builder, expected_hwpx_filename):
    db = make_db()
    template, start_date, end_date = dataset_builder(db, tmp_path)
    services = db.query(MealService).order_by(MealService.id).all()

    hwpx_bytes, hwpx_filename = generate_hwpx_bytes(document_type, services, template.storage_path, start_date=start_date, end_date=end_date)
    assert hwpx_filename == expected_hwpx_filename

    seen: dict[str, bytes | str] = {}

    class FakeRenderer:
        def render(self, hwpx_bytes: bytes, *, source_name: str = "document.hwpx") -> bytes:
            seen["hwpx_bytes"] = hwpx_bytes
            seen["source_name"] = source_name
            return b"%PDF-1.4\nfake-pdf\n"

    monkeypatch.setattr("app.document_hwpx.default_pdf_renderer", lambda: FakeRenderer())

    pdf_bytes, pdf_filename = generate_pdf_bytes(document_type, services, template.storage_path, start_date=start_date, end_date=end_date)

    assert pdf_bytes.startswith(b"%PDF")
    assert pdf_filename.endswith(".pdf")
    assert seen["hwpx_bytes"] == hwpx_bytes
    assert seen["source_name"] == hwpx_filename
