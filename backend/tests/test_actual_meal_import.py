from __future__ import annotations

from datetime import date, time

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.actual_meal_import import EXPECTED_SHEET, apply_actual_meals, preview_actual_meals
from app.db import Base, create_database_engine
from app.models import MealActual, MealService, MealTypeSetting


def make_workbook(path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = EXPECTED_SHEET
    sheet.append(["특이사항", "석식", "일자", "중식"])
    for row in rows:
        sheet.append([row.get("note", ""), row.get("dinner"), row.get("date"), row.get("lunch")])
    workbook.save(path)


def make_db(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            MealTypeSetting(code="LUNCH", name="중식", default_planned_count=400, default_service_time=time(12), active=True),
            MealTypeSetting(code="DINNER", name="석식", default_planned_count=100, default_service_time=time(17), active=True),
            MealService(service_date=date(2025, 4, 1), meal_type="LUNCH", planned_count=400),
            MealService(service_date=date(2025, 4, 1), meal_type="DINNER", planned_count=100),
        ])
        db.commit()
    return engine


def test_preview_transforms_counts_and_compares_existing(tmp_path):
    path = tmp_path / "actual.xlsx"
    make_workbook(path, [{"date": date(2025, 4, 1), "lunch": 400, "dinner": 80, "note": "  행사  "}])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        result = preview_actual_meals(path, db)
    assert result["summary"]["source_row_count"] == 1
    assert result["summary"]["candidate_count"] == 2
    assert result["summary"]["lunch_sum"] == 400
    assert result["summary"]["dinner_sum"] == 80
    assert {row["meal_type"] for row in result["rows"]} == {"LUNCH", "DINNER"}
    assert all(row["status"] == "신규" for row in result["rows"])
    assert all(row["note"] == "행사" for row in result["rows"])


def test_preview_rejects_invalid_values_and_duplicate_keys(tmp_path):
    path = tmp_path / "actual.xlsx"
    make_workbook(path, [
        {"date": date(2025, 4, 1), "lunch": 10, "dinner": 0},
        {"date": date(2025, 4, 1), "lunch": 20.5, "dinner": None},
        {"date": date(2025, 4, 2), "lunch": -1, "dinner": None},
    ])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        result = preview_actual_meals(path, db)
    assert result["summary"]["error_count"] >= 2
    assert any("음수" in error["message"] for error in result["errors"])
    assert any("소수" in error["message"] for error in result["errors"])
    assert any("중복" in error["message"] for error in result["errors"])


def test_apply_is_idempotent_and_updates_note(tmp_path):
    path = tmp_path / "actual.xlsx"
    make_workbook(path, [{"date": date(2025, 4, 1), "lunch": 400, "dinner": 80, "note": "메모"}])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = preview_actual_meals(path, db)
        first = apply_actual_meals(path, db, 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        assert first["new_count"] == 2
        second_preview = preview_actual_meals(path, db)
        second = apply_actual_meals(path, db, 1, second_preview["summary"]["rows_fingerprint"])
        assert second["unchanged_count"] == 2
        assert second["new_count"] == 0
        assert second["update_count"] == 0
        db.rollback()

        actuals = db.query(MealActual).all()
        assert len(actuals) == 2
        assert {row.note for row in actuals} == {"메모"}
