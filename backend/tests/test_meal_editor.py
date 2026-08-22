"""Tests for meal editor batch save API and concept_title field."""
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import MealService, MealServiceMenu, MealServiceMenuIngredient, Ingredient, Menu, User
from app.routers.workspace import (
    MealEditorBody,
    MealEditorMenuBody,
    MealEditorIngredientBody,
    save_meal_editor,
    ServiceUpdateBody,
    PostServiceNoteBody,
    save_post_service_note,
    update_service,
)
from app.schema_upgrade import upgrade_existing_schema


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    upgrade_existing_schema(engine)
    return Session(engine, expire_on_commit=False)


def make_user(db: Session) -> User:
    user = User(username="tester", password_hash="x", display_name="Tester", active=True)
    db.add(user)
    db.flush()
    return user


def make_ingredient(db: Session, name="돼지고기", unit="kg") -> Ingredient:
    ing = Ingredient(name=name, stat_group="육류", default_unit=unit, active=True)
    db.add(ing)
    db.flush()
    return ing


def make_service(db: Session, meal_type="LUNCH", planned_count=100) -> MealService:
    svc = MealService(
        service_date=date(2025, 1, 1),
        meal_type=meal_type,
        planned_count=planned_count,
    )
    db.add(svc)
    db.flush()
    return svc


def make_menu(db: Session, name="돼지불고기") -> Menu:
    menu = Menu(name=name, canonical_name=name, role="주찬", active=True)
    db.add(menu)
    db.flush()
    return menu


def make_service_menu(db: Session, service: MealService, menu: Menu) -> MealServiceMenu:
    item = MealServiceMenu(
        meal_service_id=service.id,
        menu_id=menu.id,
        menu_name_snapshot=menu.name,
        sort_order=1,
    )
    db.add(item)
    db.flush()
    return item


def test_concept_title_saved_via_batch_api():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    service = make_service(db)
    sm = make_service_menu(db, service, menu)

    body = MealEditorBody(
        planned_count=150,
        service_time="12:30",
        concept_title="LA갈비 특식",
        note="내부 메모",
        menus=[
            MealEditorMenuBody(
                service_menu_id=sm.id,
                note="메뉴 비고",
                is_representative=True,
                ingredients=[
                    MealEditorIngredientBody(
                        ingredient_id=ing.id,
                        name="돼지고기",
                        quantity_total=12.0,
                        unit="kg",
                    ),
                ],
            ),
        ],
    )
    result = save_meal_editor(service.id, body, db, user)

    assert result["planned_count"] == 150
    assert result["concept_title"] == "LA갈비 특식"
    assert result["note"] == "내부 메모"

    # Verify ingredient was saved with correct per_100 calculation
    saved_ings = db.query(MealServiceMenuIngredient).filter_by(meal_service_menu_id=sm.id).all()
    assert len(saved_ings) == 1
    assert saved_ings[0].quantity_total == 12.0
    assert abs(saved_ings[0].quantity_per_100 - 8.0) < 0.01  # 12 * 100 / 150

    # Verify representative flag
    updated_sm = db.get(MealServiceMenu, sm.id)
    assert updated_sm.is_representative is True


def test_concept_title_saved_via_update_service():
    db = make_db()
    user = make_user(db)
    service = make_service(db)

    body = ServiceUpdateBody(
        planned_count=200,
        service_time="11:00",
        concept_title="명절 특별식",
        note=None,
    )
    result = update_service(service.id, body, db, user)
    assert result["concept_title"] == "명절 특별식"

    refreshed = db.get(MealService, service.id)
    assert refreshed.concept_title == "명절 특별식"


def test_post_service_note_is_saved_on_meal_service():
    db = make_db()
    user = make_user(db)
    service = make_service(db)

    result = save_post_service_note(service.id, PostServiceNoteBody(note="  배식 후 밥 부족  "), db, user)

    assert result["note"] == "배식 후 밥 부족"
    assert db.get(MealService, service.id).note == "배식 후 밥 부족"


def test_batch_save_replaces_ingredients():
    db = make_db()
    user = make_user(db)
    ing1 = make_ingredient(db, name="돼지고기")
    ing2 = make_ingredient(db, name="양파")
    menu = make_menu(db)
    service = make_service(db)
    sm = make_service_menu(db, service, menu)

    # First save with one ingredient
    body1 = MealEditorBody(
        planned_count=100,
        service_time=None,
        concept_title=None,
        note=None,
        menus=[
            MealEditorMenuBody(
                service_menu_id=sm.id,
                ingredients=[
                    MealEditorIngredientBody(ingredient_id=ing1.id, name="돼지고기", quantity_total=10.0, unit="kg"),
                ],
            ),
        ],
    )
    save_meal_editor(service.id, body1, db, user)
    assert db.query(MealServiceMenuIngredient).filter_by(meal_service_menu_id=sm.id).count() == 1

    # Second save with different ingredients - should replace, not append
    body2 = MealEditorBody(
        planned_count=100,
        service_time=None,
        concept_title=None,
        note=None,
        menus=[
            MealEditorMenuBody(
                service_menu_id=sm.id,
                ingredients=[
                    MealEditorIngredientBody(ingredient_id=ing1.id, name="돼지고기", quantity_total=8.0, unit="kg"),
                    MealEditorIngredientBody(ingredient_id=ing2.id, name="양파", quantity_total=3.0, unit="kg"),
                ],
            ),
        ],
    )
    save_meal_editor(service.id, body2, db, user)
    saved = db.query(MealServiceMenuIngredient).filter_by(meal_service_menu_id=sm.id).all()
    assert len(saved) == 2
    names = [s.ingredient_name_snapshot for s in saved]
    assert "돼지고기" in names
    assert "양파" in names


def test_batch_save_empty_ingredients_clears_all():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    service = make_service(db)
    sm = make_service_menu(db, service, menu)

    # Add an ingredient first
    body1 = MealEditorBody(
        planned_count=100,
        menus=[
            MealEditorMenuBody(
                service_menu_id=sm.id,
                ingredients=[
                    MealEditorIngredientBody(ingredient_id=ing.id, name="돼지고기", quantity_total=10.0, unit="kg"),
                ],
            ),
        ],
    )
    save_meal_editor(service.id, body1, db, user)
    assert db.query(MealServiceMenuIngredient).filter_by(meal_service_menu_id=sm.id).count() == 1

    # Save with empty ingredients
    body2 = MealEditorBody(
        planned_count=100,
        menus=[
            MealEditorMenuBody(
                service_menu_id=sm.id,
                ingredients=[],
            ),
        ],
    )
    save_meal_editor(service.id, body2, db, user)
    assert db.query(MealServiceMenuIngredient).filter_by(meal_service_menu_id=sm.id).count() == 0
