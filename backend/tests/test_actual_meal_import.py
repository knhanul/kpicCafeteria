from __future__ import annotations

from datetime import date, time

from openpyxl import Workbook
from sqlalchemy import func, select
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


def test_apply_preserves_existing_count_when_upload_cell_is_blank(tmp_path):
    path = tmp_path / "actual.xlsx"
    make_workbook(path, [{"date": date(2025, 4, 1), "lunch": None, "dinner": 80}])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        lunch = db.query(MealService).filter_by(meal_type="LUNCH").one()
        db.add(MealActual(meal_service_id=lunch.id, actual_count=350, note="기존 기록"))
        db.commit()
        preview = preview_actual_meals(path, db)
        assert preview["summary"]["candidate_count"] == 1
        result = apply_actual_meals(path, db, 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        assert result["new_count"] == 1
        actuals = {row.service.meal_type: row for row in db.query(MealActual).all()}
        assert actuals["LUNCH"].actual_count == 350
        assert actuals["LUNCH"].note == "기존 기록"
        assert actuals["DINNER"].actual_count == 80


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


def test_preview_does_not_write_missing_services(tmp_path):
    path = tmp_path / "actual.xlsx"
    make_workbook(path, [
        {"date": date(2025, 4, 1), "lunch": 390, "dinner": 90},
        {"date": date(2025, 4, 2), "lunch": 410, "dinner": 95},
    ])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        before = db.scalar(select(func.count()).select_from(MealService))
        result = preview_actual_meals(path, db)
        db.commit()  # the router commits after preview; nothing from preview may be persisted
    with Session(engine) as db:
        after = db.scalar(select(func.count()).select_from(MealService))
        assert db.scalar(select(func.count()).select_from(MealActual)) == 0
    assert before == after == 2
    assert result["summary"]["service_created_count"] == 2
    new_rows = [row for row in result["rows"] if row["service_created"]]
    assert {row["date"] for row in new_rows} == {"2025-04-02"}
    assert all(row["service_id"] is None and row["status"] == "신규" for row in new_rows)


def test_preview_then_apply_succeeds_when_new_dates_present(tmp_path):
    path = tmp_path / "actual.xlsx"
    make_workbook(path, [
        {"date": date(2025, 4, 1), "lunch": 390, "dinner": 90},
        {"date": date(2025, 4, 2), "lunch": 410, "dinner": None, "note": "신규일"},
    ])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = preview_actual_meals(path, db)
        db.commit()
    fingerprint = preview["summary"]["rows_fingerprint"]
    with Session(engine) as db:
        result = apply_actual_meals(path, db, 1, fingerprint)
        db.commit()
    assert result["new_count"] == 3
    assert result["service_created_count"] == 1
    with Session(engine) as db:
        service = db.scalar(select(MealService).where(MealService.service_date == date(2025, 4, 2), MealService.meal_type == "LUNCH"))
        assert service is not None and service.planned_count == 400 and service.service_time == time(12)
        assert service.actual.actual_count == 410 and service.actual.note == "신규일"
        assert db.scalar(select(func.count()).select_from(MealActual)) == 3
    # a second preview/apply of the same file is a no-op and still passes the fingerprint check
    with Session(engine) as db:
        again = preview_actual_meals(path, db)
        db.commit()
    with Session(engine) as db:
        result2 = apply_actual_meals(path, db, 1, again["summary"]["rows_fingerprint"])
        db.commit()
    assert result2["unchanged_count"] == 3 and result2["service_created_count"] == 0
