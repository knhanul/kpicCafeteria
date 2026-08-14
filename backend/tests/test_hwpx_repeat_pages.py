from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from app.document_hwpx import generate_hwpx_bytes
from app.hwpx_engine import HwpxPackage
from app.models import MealService
from tests.test_document_hwpx import add_service, make_db


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _repeat_template_path(filename: str) -> Path:
    return _repo_root() / "docs" / "template" / filename


def _section0_root(hwpx_bytes: bytes) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as archive:
        return ET.fromstring(archive.read("Contents/section0.xml"))


def _all_section_text(hwpx_bytes: bytes) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as archive:
        for name in sorted(item for item in archive.namelist() if item.startswith("Contents/section") and item.endswith(".xml")):
            root = ET.fromstring(archive.read(name))
            parts.append("".join(node.text or "" for node in root.iter() if node.tag.split("}")[-1] == "t"))
    return "\n".join(parts)


def _top_level_page_count(section_root: ET.Element) -> int:
    top_ps = [node for node in list(section_root) if node.tag.split("}")[-1] == "p"]
    if not top_ps:
        return 0
    page_breaks = sum(1 for node in top_ps if node.attrib.get("pageBreak") == "1")
    return page_breaks + 1


def _assert_valid_no_placeholders(tmp_path: Path, filename: str, hwpx_bytes: bytes) -> None:
    output = tmp_path / filename
    output.write_bytes(hwpx_bytes)
    package = HwpxPackage.load(output)
    result = package.validate()
    assert result["sections"] >= 1
    assert "{{" not in _all_section_text(hwpx_bytes)


def _count_not_followed_by_digit(text: str, token: str) -> int:
    pattern = rf"{re.escape(token)}(?!\d)"
    return len(re.findall(pattern, text))


def _seed_meal_plan_weeks(db, week_count: int) -> tuple[date, date]:
    monday = date(2026, 8, 17)
    for week_index in range(week_count):
        week_start = monday + timedelta(days=week_index * 7)
        for day_offset in range(5):
            service_date = week_start + timedelta(days=day_offset)
            week_label = week_index + 1
            day_label = day_offset + 1
            add_service(
                db,
                service_date=service_date,
                meal_type="LUNCH",
                planned_count=300 + week_index,
                service_time=time(11, 40),
                concept_title=None,
                menus=[{"name": f"ML_W{week_label}_D{day_label}"}],
            )
            add_service(
                db,
                service_date=service_date,
                meal_type="DINNER",
                planned_count=100 + week_index,
                service_time=time(17, 30),
                concept_title=None,
                menus=[{"name": f"MD_W{week_label}_D{day_label}"}],
            )
    end_date = monday + timedelta(days=(week_count - 1) * 7 + 4)
    return monday, end_date


def _seed_cooking_days(db, day_count: int) -> tuple[date, date]:
    start = date(2026, 8, 17)
    for day_index in range(day_count):
        service_date = start + timedelta(days=day_index)
        label = day_index + 1
        add_service(
            db,
            service_date=service_date,
            meal_type="LUNCH",
            planned_count=280,
            service_time=time(11, 40),
            concept_title=None,
            menus=[
                {
                    "name": f"COOK_LUNCH_{label}",
                    "ingredients": [{"name": f"ING_L{label}", "quantity": float(label), "unit": "kg"}],
                    "instruction": f"LUNCH_INST_{label}",
                    "note": "",
                }
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
                    "name": f"COOK_DINNER_{label}",
                    "ingredients": [{"name": f"ING_D{label}", "quantity": float(label), "unit": "kg"}],
                    "instruction": f"DINNER_INST_{label}",
                    "note": "",
                }
            ],
        )
    return start, start + timedelta(days=day_count - 1)


def _seed_preservation_meals(db, meal_count: int) -> tuple[date, date]:
    start = date(2026, 8, 17)
    for index in range(meal_count):
        current_date = start + timedelta(days=index // 2)
        meal_type = "LUNCH" if index % 2 == 0 else "DINNER"
        label = index + 1
        hour = 12 if meal_type == "LUNCH" else 18
        minute = (10 + index) % 60
        add_service(
            db,
            service_date=current_date,
            meal_type=meal_type,
            planned_count=200,
            service_time=time(11, 40) if meal_type == "LUNCH" else time(17, 30),
            concept_title=None,
            menus=[{"name": f"PRESERVE_MENU_{label}"}],
            preservation={
                "collected_at": datetime(current_date.year, current_date.month, current_date.day, hour, minute, tzinfo=timezone.utc),
                "manager": f"MANAGER_{label}",
                "freezer_temperature": "-18",
                "disposal_at": datetime(current_date.year, current_date.month, current_date.day, hour, minute, tzinfo=timezone.utc),
                "collector": f"COLLECTOR_{label}",
                "collection_time": f"{hour:02d}:{minute:02d}",
            },
        )
    end = start + timedelta(days=(meal_count - 1) // 2)
    return start, end


@pytest.mark.parametrize("week_count", [2, 3, 4, 5, 6])
def test_meal_plan_repeat_pages_by_two_weeks(tmp_path, week_count):
    db = make_db()
    start_date, end_date = _seed_meal_plan_weeks(db, week_count)
    template_path = _repeat_template_path("식단표_반복페이지템플릿.hwpx")

    services = db.query(MealService).order_by(MealService.service_date, MealService.meal_type, MealService.id).all()
    hwpx_bytes, _ = generate_hwpx_bytes("MEAL_PLAN", services, template_path, start_date=start_date, end_date=end_date)

    _assert_valid_no_placeholders(tmp_path, f"meal-plan-{week_count}.hwpx", hwpx_bytes)
    section_root = _section0_root(hwpx_bytes)
    assert _top_level_page_count(section_root) == math.ceil(week_count / 2)

    text = _all_section_text(hwpx_bytes)
    for week in range(1, week_count + 1):
        assert f"ML_W{week}_D1" in text
        assert f"MD_W{week}_D1" in text
    if week_count == 5:
        assert "ML_W6_D1" not in text


@pytest.mark.parametrize("day_count", [1, 2, 5, 10])
def test_cooking_instruction_repeat_pages_by_day(tmp_path, day_count):
    db = make_db()
    start_date, end_date = _seed_cooking_days(db, day_count)
    template_path = _repeat_template_path("조리지시서_반복페이지템플릿.hwpx")

    services = db.query(MealService).order_by(MealService.service_date, MealService.meal_type, MealService.id).all()
    hwpx_bytes, _ = generate_hwpx_bytes("COOKING_INSTRUCTION", services, template_path, start_date=start_date, end_date=end_date)

    _assert_valid_no_placeholders(tmp_path, f"cooking-{day_count}.hwpx", hwpx_bytes)
    section_root = _section0_root(hwpx_bytes)
    assert _top_level_page_count(section_root) == day_count

    text = _all_section_text(hwpx_bytes)
    last_pos = -1
    for day in range(1, day_count + 1):
        lunch_marker = f"COOK_LUNCH_{day}"
        dinner_marker = f"COOK_DINNER_{day}"
        assert _count_not_followed_by_digit(text, lunch_marker) == 1
        assert _count_not_followed_by_digit(text, dinner_marker) == 1
        lunch_pos = text.find(lunch_marker)
        assert lunch_pos > last_pos
        last_pos = lunch_pos


@pytest.mark.parametrize("meal_count", [1, 3, 4, 6, 7, 10])
def test_preservation_repeat_pages_by_three_meals(tmp_path, meal_count):
    db = make_db()
    start_date, end_date = _seed_preservation_meals(db, meal_count)
    template_path = _repeat_template_path("보존식기록지_반복페이지템플릿.hwpx")

    services = db.query(MealService).order_by(MealService.service_date, MealService.meal_type, MealService.id).all()
    hwpx_bytes, _ = generate_hwpx_bytes("PRESERVATION_RECORD", services, template_path, start_date=start_date, end_date=end_date)

    _assert_valid_no_placeholders(tmp_path, f"preservation-{meal_count}.hwpx", hwpx_bytes)
    section_root = _section0_root(hwpx_bytes)
    assert _top_level_page_count(section_root) == math.ceil(meal_count / 3)

    text = _all_section_text(hwpx_bytes)
    for idx in range(1, meal_count + 1):
        assert _count_not_followed_by_digit(text, f"PRESERVE_MENU_{idx}") == 1
        assert _count_not_followed_by_digit(text, f"MANAGER_{idx}") == 1
    assert f"PRESERVE_MENU_{meal_count + 1}" not in text
