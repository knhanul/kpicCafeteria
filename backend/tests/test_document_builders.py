from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.document_builders import (
    CookingInstructionDocumentBuilder,
    MealPlanDocumentBuilder,
    PreservationRecordDocumentBuilder,
)
from app.models import MealService, MealServiceMenu, MealServiceMenuIngredient, PreservationRecord


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def add_service(
    db: Session,
    *,
    service_date: date,
    meal_type: str,
    planned_count: int,
    service_time: time | None,
    concept_title: str | None,
    menus: list[dict],
    preservation: dict | None = None,
) -> MealService:
    service = MealService(
        service_date=service_date,
        meal_type=meal_type,
        planned_count=planned_count,
        service_time=service_time,
        concept_title=concept_title,
    )
    db.add(service)
    db.flush()

    for menu_index, menu_data in enumerate(menus, start=1):
        service_menu = MealServiceMenu(
            meal_service_id=service.id,
            sort_order=menu_index,
            menu_name_snapshot=menu_data["name"],
            recipe_name_snapshot=menu_data.get("recipe_name"),
            recipe_version_snapshot=menu_data.get("recipe_version"),
            note=menu_data.get("note"),
            cooking_instruction=menu_data.get("instruction"),
            cooking_note=menu_data.get("cooking_note"),
        )
        db.add(service_menu)
        db.flush()

        for ingredient_index, ingredient_data in enumerate(menu_data.get("ingredients", []), start=1):
            db.add(
                MealServiceMenuIngredient(
                    meal_service_menu_id=service_menu.id,
                    sort_order=ingredient_index,
                    ingredient_name_snapshot=ingredient_data["name"],
                    quantity_total=ingredient_data.get("quantity"),
                    quantity_per_100=ingredient_data.get("quantity_per_100"),
                    unit=ingredient_data.get("unit"),
                    source_note=ingredient_data.get("remark"),
                )
            )

    if preservation:
        db.add(
            PreservationRecord(
                meal_service_id=service.id,
                collected_at=preservation.get("collected_at"),
                manager_name=preservation.get("manager"),
                freezer_temperature=preservation.get("freezer_temperature"),
                disposal_at=preservation.get("disposal_at"),
                collector_name=preservation.get("collector"),
                collection_time=preservation.get("collection_time"),
                note=preservation.get("note"),
                completed_at=preservation.get("completed_at"),
            )
        )

    db.commit()
    return service


def test_meal_plan_builder_groups_services_by_week_and_preserves_menu_order():
    db = make_db()
    monday = date(2026, 8, 3)
    tuesday = date(2026, 8, 4)

    add_service(
        db,
        service_date=monday,
        meal_type="LUNCH",
        planned_count=400,
        service_time=time(11, 40),
        concept_title="여름 보양식",
        menus=[
            {"name": "비빔밥"},
            {"name": "국수"},
        ],
    )
    add_service(
        db,
        service_date=monday,
        meal_type="DINNER",
        planned_count=100,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "된장찌개"}],
    )
    add_service(
        db,
        service_date=tuesday,
        meal_type="LUNCH",
        planned_count=420,
        service_time=time(11, 50),
        concept_title=None,
        menus=[{"name": "카레"}],
    )

    document = MealPlanDocumentBuilder().build(db, start_date=monday, end_date=tuesday)

    assert document.period.start_date == monday
    assert document.period.end_date == tuesday
    assert len(document.weeks) == 1

    first_day = document.weeks[0].days[0]
    assert first_day.date == monday
    assert first_day.weekday == "월요일"
    assert first_day.lunch.meal_count == 400
    assert first_day.lunch.menus == ["비빔밥", "국수"]
    assert first_day.dinner.menus == ["된장찌개"]

    second_day = document.weeks[0].days[1]
    assert second_day.date == tuesday
    assert second_day.lunch.menus == ["카레"]
    assert second_day.dinner.menus == []


def test_cooking_instruction_builder_preserves_ingredient_order_and_nulls():
    db = make_db()
    service_date = date(2026, 8, 5)

    service = add_service(
        db,
        service_date=service_date,
        meal_type="LUNCH",
        planned_count=360,
        service_time=time(11, 45),
        concept_title=None,
        menus=[
            {
                "name": "제육볶음",
                "instruction": "강불에 빠르게 볶는다.",
                "note": "매콤하게",
                "ingredients": [
                    {"name": "돼지고기", "quantity": 18.0, "quantity_per_100": 5.0, "unit": "kg", "remark": "앞다리살"},
                    {"name": "양파", "quantity": None, "quantity_per_100": 2.5, "unit": "kg", "remark": None},
                ],
            },
            {
                "name": "미역국",
                "ingredients": [
                    {"name": "미역", "quantity": 1.2, "quantity_per_100": 0.3, "unit": "kg", "remark": "불리기"},
                ],
            },
        ],
    )

    document = CookingInstructionDocumentBuilder().build(db, service_ids=[service.id])

    assert len(document.days) == 1
    day = document.days[0]
    assert day.date == service_date
    assert day.lunch.meal_count == 360
    assert day.lunch.menus[0].name == "제육볶음"
    assert day.lunch.menus[0].ingredients[0].name == "돼지고기"
    assert day.lunch.menus[0].ingredients[0].quantity == 18.0
    assert day.lunch.menus[0].ingredients[0].quantity_per_100 == 5.0
    assert day.lunch.menus[0].ingredients[0].unit == "kg"
    assert day.lunch.menus[0].ingredients[0].remark == "앞다리살"
    assert day.lunch.menus[0].ingredients[1].name == "양파"
    assert day.lunch.menus[0].ingredients[1].quantity is None
    assert day.lunch.menus[0].ingredients[1].remark is None
    assert day.lunch.menus[1].name == "미역국"
    assert day.lunch.menus[1].ingredients[0].name == "미역"
    assert day.lunch.menus[1].ingredients[0].quantity_per_100 == 0.3
    assert day.dinner.menus == []


def test_preservation_record_builder_handles_nulls_and_keeps_service_order():
    db = make_db()
    service_date = date(2026, 8, 6)

    add_service(
        db,
        service_date=service_date,
        meal_type="LUNCH",
        planned_count=410,
        service_time=time(11, 40),
        concept_title=None,
        menus=[{"name": "불고기", "ingredients": []}],
        preservation={
            "collected_at": datetime(2026, 8, 6, 13, 20, tzinfo=timezone.utc),
            "manager": "홍길동",
            "freezer_temperature": "-18",
            "disposal_at": datetime(2026, 8, 7, 13, 20, tzinfo=timezone.utc),
            "collector": "김수거",
            "collection_time": "13:20",
        },
    )
    add_service(
        db,
        service_date=service_date,
        meal_type="DINNER",
        planned_count=120,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "된장국"}],
        preservation=None,
    )

    document = PreservationRecordDocumentBuilder().build(db, start_date=service_date, end_date=service_date)

    assert len(document.records) == 2
    lunch_block = document.records[0]
    dinner_block = document.records[1]

    assert lunch_block.meal_type == "lunch"
    assert lunch_block.menus == ["불고기"]
    assert lunch_block.collection_time == "13:20"
    assert lunch_block.manager == "홍길동"
    assert lunch_block.freezer_temperature == "-18"
    assert lunch_block.discard_date == date(2026, 8, 7)
    assert lunch_block.collector == "김수거"

    assert dinner_block.meal_type == "dinner"
    assert dinner_block.menus == ["된장국"]
    assert dinner_block.collection_time is None
    assert dinner_block.manager is None
    assert dinner_block.freezer_temperature is None
    assert dinner_block.discard_date is None
    assert dinner_block.collector is None
