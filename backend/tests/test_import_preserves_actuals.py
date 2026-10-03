from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.importer import MigrationImporter
from app.models import MealActual, MealService, PreservationRecord


def _workbook() -> Path:
    return next((Path(__file__).resolve().parents[2] / "data" / "source").glob("*.xlsx"))


def test_replace_import_keeps_actuals_and_preservation_records():
    importer = MigrationImporter(_workbook())
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    recorded = datetime(2026, 9, 12, 6, 29, tzinfo=timezone.utc)
    with Session(engine) as db:
        importer.apply(db, mode="replace")
        services = db.scalars(select(MealService).order_by(MealService.service_date, MealService.meal_type).limit(2)).all()
        assert len(services) == 2
        keys = [(s.service_date, s.meal_type) for s in services]
        db.add(MealActual(service=services[0], actual_count=321, note="행사", recorded_at=recorded))
        db.add(PreservationRecord(service=services[1], manager_name="홍길동", freezer_temperature="-18", note="보존"))
        # an actual on a date that the workbook does not contain
        orphan = MealService(service_date=date(2001, 1, 2), meal_type="LUNCH", planned_count=1)
        db.add(orphan)
        db.add(MealActual(service=orphan, actual_count=7))
        db.commit()

    with Session(engine) as db:
        result = importer.apply(db, mode="replace")
        assert result["actuals_restored"] == 2
        assert result["preservation_restored"] == 1
        assert result["services_created_for_restore"] == 1
        assert db.scalar(select(func.count()).select_from(MealActual)) == 2
        assert db.scalar(select(func.count()).select_from(PreservationRecord)) == 1
        first = db.scalar(select(MealService).where(MealService.service_date == keys[0][0], MealService.meal_type == keys[0][1]))
        assert first.actual.actual_count == 321 and first.actual.note == "행사"
        assert first.actual.recorded_at.replace(tzinfo=timezone.utc) == recorded or first.actual.recorded_at == recorded
        assert first.menus, "restored actual must be attached to the re-imported service that has menus"
        second = db.scalar(select(MealService).where(MealService.service_date == keys[1][0], MealService.meal_type == keys[1][1]))
        assert second.preservation.manager_name == "홍길동" and second.preservation.freezer_temperature == "-18"
        restored_orphan = db.scalar(select(MealService).where(MealService.service_date == date(2001, 1, 2), MealService.meal_type == "LUNCH"))
        assert restored_orphan is not None and restored_orphan.actual.actual_count == 7
        assert restored_orphan.menus == []


def test_merge_import_does_not_report_restore_counters():
    importer = MigrationImporter(_workbook())
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = importer.apply(db, mode="merge")
    assert "actuals_restored" not in result and "preservation_restored" not in result
