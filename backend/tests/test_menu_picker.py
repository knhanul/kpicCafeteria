"""Tests for menu picker search API and batch add menus API."""
from datetime import date
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Ingredient,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    Menu,
    Recipe,
    RecipeIngredient,
    User,
)
from app.routers.master import picker_list_menus
from app.routers.workspace import (
    BatchAddMenuBody,
    BatchAddMenuItemBody,
    batch_add_menus,
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


def make_menu(db: Session, name="돼지불고기", role="주찬") -> Menu:
    menu = Menu(name=name, canonical_name=name, role=role, active=True)
    db.add(menu)
    db.flush()
    return menu


def make_recipe(db: Session, menu: Menu, name="기본 레시피", is_default=True, active=True, ingredients=None) -> Recipe:
    recipe = Recipe(menu_id=menu.id, name=name, version=1, composition_key="", is_default=is_default, active=active)
    db.add(recipe)
    db.flush()
    for ing, qty in (ingredients or []):
        db.add(RecipeIngredient(
            recipe_id=recipe.id, ingredient_id=ing.id, sort_order=1,
            quantity_per_100=qty, unit=ing.default_unit, is_primary=True,
        ))
    db.flush()
    return recipe


def make_service(db: Session, meal_type="LUNCH", planned_count=100) -> MealService:
    svc = MealService(service_date=date(2025, 1, 1), meal_type=meal_type, planned_count=planned_count)
    db.add(svc)
    db.flush()
    return svc


def make_service_menu(db: Session, service: MealService, menu: Menu) -> MealServiceMenu:
    item = MealServiceMenu(
        meal_service_id=service.id, menu_id=menu.id,
        menu_name_snapshot=menu.name, sort_order=1,
    )
    db.add(item)
    db.flush()
    return item


# --- Picker API tests ---

def test_picker_returns_menus_with_recipes():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    make_recipe(db, menu, ingredients=[(ing, 8.0)])

    result = picker_list_menus(q="", db=db, user=user, offset=0, limit=50)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["id"] == menu.id
    assert item["name"] == "돼지불고기"
    assert item["role"] == "주찬"
    assert item["already_added"] is False
    assert len(item["recipes"]) == 1
    assert item["recipes"][0]["ingredient_count"] == 1
    assert "돼지고기" in item["recipes"][0]["ingredient_summary"]


def test_picker_marks_already_added_menus():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    make_recipe(db, menu, ingredients=[(ing, 8.0)])
    service = make_service(db)
    make_service_menu(db, service, menu)

    result = picker_list_menus(q="", service_id=service.id, db=db, user=user, offset=0, limit=50)
    item = result["items"][0]
    assert item["already_added"] is True


def test_picker_filters_by_role():
    db = make_db()
    user = make_user(db)
    menu1 = make_menu(db, name="백미밥", role="밥·죽")
    menu2 = make_menu(db, name="돼지불고기", role="주찬")

    result = picker_list_menus(q="", role="주찬", db=db, user=user, offset=0, limit=50)
    assert len(result["items"]) == 1
    assert result["items"][0]["name"] == "돼지불고기"


def test_picker_filters_by_query():
    db = make_db()
    user = make_user(db)
    menu1 = make_menu(db, name="백미밥")
    menu2 = make_menu(db, name="LA갈비구이")

    result = picker_list_menus(q="갈비", db=db, user=user, offset=0, limit=50)
    assert len(result["items"]) == 1
    assert result["items"][0]["name"] == "LA갈비구이"


def test_picker_returns_total_count():
    db = make_db()
    user = make_user(db)
    for i in range(5):
        make_menu(db, name=f"메뉴{i}")

    result = picker_list_menus(q="", db=db, user=user, offset=0, limit=3)
    assert result["total"] == 5
    assert len(result["items"]) == 3
    assert result["offset"] == 0
    assert result["limit"] == 3


# --- Batch add API tests ---

def test_batch_add_multiple_menus():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu1 = make_menu(db, name="백미밥", role="밥·죽")
    menu2 = make_menu(db, name="돼지불고기", role="주찬")
    recipe1 = make_recipe(db, menu1, name="밥 레시피", ingredients=[(ing, 5.0)])
    recipe2 = make_recipe(db, menu2, name="불고기 레시피", ingredients=[(ing, 8.0)])
    service = make_service(db)

    body = BatchAddMenuBody(items=[
        BatchAddMenuItemBody(menu_id=menu1.id, recipe_id=recipe1.id, sort_order=1),
        BatchAddMenuItemBody(menu_id=menu2.id, recipe_id=recipe2.id, sort_order=2),
    ])
    result = batch_add_menus(service.id, body, db, user)

    assert len(result["menus"]) == 2
    assert result["menus"][0]["name"] == "백미밥"
    assert result["menus"][1]["name"] == "돼지불고기"
    # Verify ingredients were copied
    ings = db.query(MealServiceMenuIngredient).all()
    assert len(ings) == 2


def test_batch_add_with_null_recipe():
    db = make_db()
    user = make_user(db)
    menu = make_menu(db, name="물", role="기타")
    service = make_service(db)

    body = BatchAddMenuBody(items=[
        BatchAddMenuItemBody(menu_id=menu.id, recipe_id=None, sort_order=1),
    ])
    result = batch_add_menus(service.id, body, db, user)

    assert len(result["menus"]) == 1
    assert result["menus"][0]["name"] == "물"
    ings = db.query(MealServiceMenuIngredient).filter_by(
        meal_service_menu_id=result["menus"][0]["id"]
    ).all()
    assert len(ings) == 0


def test_batch_add_duplicate_menu_in_request_rejected():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    recipe = make_recipe(db, menu, ingredients=[(ing, 8.0)])
    service = make_service(db)

    body = BatchAddMenuBody(items=[
        BatchAddMenuItemBody(menu_id=menu.id, recipe_id=recipe.id, sort_order=1),
        BatchAddMenuItemBody(menu_id=menu.id, recipe_id=recipe.id, sort_order=2),
    ])
    try:
        batch_add_menus(service.id, body, db, user)
        raise AssertionError("중복 메뉴 요청이 허용되었습니다.")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_batch_add_already_added_menu_rejected():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    recipe = make_recipe(db, menu, ingredients=[(ing, 8.0)])
    service = make_service(db)
    make_service_menu(db, service, menu)

    body = BatchAddMenuBody(items=[
        BatchAddMenuItemBody(menu_id=menu.id, recipe_id=recipe.id, sort_order=1),
    ])
    try:
        batch_add_menus(service.id, body, db, user)
        raise AssertionError("이미 추가된 메뉴가 허용되었습니다.")
    except HTTPException as exc:
        assert exc.status_code == 409


def test_batch_add_invalid_recipe_rejected():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu1 = make_menu(db, name="메뉴1")
    menu2 = make_menu(db, name="메뉴2")
    recipe1 = make_recipe(db, menu1, ingredients=[(ing, 8.0)])
    recipe2 = make_recipe(db, menu2, ingredients=[(ing, 5.0)])
    service = make_service(db)

    # recipe2 belongs to menu2, not menu1
    body = BatchAddMenuBody(items=[
        BatchAddMenuItemBody(menu_id=menu1.id, recipe_id=recipe2.id, sort_order=1),
    ])
    try:
        batch_add_menus(service.id, body, db, user)
        raise AssertionError("다른 메뉴의 레시피가 허용되었습니다.")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_batch_add_empty_items_rejected():
    db = make_db()
    user = make_user(db)
    service = make_service(db)

    body = BatchAddMenuBody(items=[])
    try:
        batch_add_menus(service.id, body, db, user)
        raise AssertionError("빈 요청이 허용되었습니다.")
    except HTTPException as exc:
        assert exc.status_code == 400


def test_batch_add_inactive_menu_rejected():
    db = make_db()
    user = make_user(db)
    menu = make_menu(db)
    menu.active = False
    db.flush()
    service = make_service(db)

    body = BatchAddMenuBody(items=[
        BatchAddMenuItemBody(menu_id=menu.id, recipe_id=None, sort_order=1),
    ])
    try:
        batch_add_menus(service.id, body, db, user)
        raise AssertionError("비활성 메뉴가 허용되었습니다.")
    except HTTPException as exc:
        assert exc.status_code == 404


def test_batch_add_recipe_snapshot_copied():
    db = make_db()
    user = make_user(db)
    ing = make_ingredient(db)
    menu = make_menu(db)
    recipe = make_recipe(db, menu, name="특식 레시피", ingredients=[(ing, 12.0)])
    service = make_service(db, planned_count=100)

    body = BatchAddMenuBody(items=[
        BatchAddMenuItemBody(menu_id=menu.id, recipe_id=recipe.id, sort_order=1),
    ])
    result = batch_add_menus(service.id, body, db, user)

    sm = db.query(MealServiceMenu).filter_by(meal_service_id=service.id).first()
    assert sm.recipe_id == recipe.id
    assert sm.recipe_name_snapshot == "특식 레시피"
    assert sm.recipe_version_snapshot == 1
    # Verify quantity_total = 12.0 * 100 / 100 = 12.0
    ing_row = db.query(MealServiceMenuIngredient).filter_by(meal_service_menu_id=sm.id).first()
    assert ing_row.quantity_total == 12.0
    assert ing_row.quantity_per_100 == 12.0
