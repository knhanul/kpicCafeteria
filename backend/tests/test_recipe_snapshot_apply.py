from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Ingredient, MealService, MealServiceMenu, MealServiceMenuIngredient, Recipe, RecipeIngredient
from app.routers.master import (
    IngredientBody,
    MenuBody,
    RecipeBody,
    RecipeItemBody,
    SnapshotRecipeCreateBody,
    SnapshotRecipePreviewBody,
    apply_snapshot_to_recipe,
    create_menu,
    create_recipe,
    create_recipe_from_snapshot,
    create_ingredient,
    preview_snapshot_recipe,
)


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def add_snapshot(db, menu_id, recipe_id, ingredients, day_offset=0):
    service = MealService(service_date=date(2026, 8, 1 + day_offset), meal_type="LUNCH", planned_count=400)
    item = MealServiceMenu(service=service, menu_id=menu_id, recipe_id=recipe_id, menu_name_snapshot="[TEST-P8] 갈비찜", recipe_name_snapshot="[TEST-P8] 기본", recipe_version_snapshot=1)
    db.add(item)
    db.flush()
    for index, (ingredient_id, name, total, per_100, unit) in enumerate(ingredients, start=1):
        db.add(MealServiceMenuIngredient(meal_service_menu_id=item.id, ingredient_id=ingredient_id, ingredient_name_snapshot=name, quantity_total=total, quantity_per_100=per_100, unit=unit, sort_order=index))
    db.commit()
    return item


def test_snapshot_preview_update_create_and_history_immutability():
    db = make_db()
    user = object()
    onion = create_ingredient(IngredientBody(name="[TEST-P8] 양파", default_unit="kg"), db, user)
    carrot = create_ingredient(IngredientBody(name="[TEST-P8] 당근", default_unit="kg"), db, user)
    green_onion = create_ingredient(IngredientBody(name="[TEST-P8] 대파", default_unit="kg"), db, user)
    menu = create_menu(MenuBody(name="[TEST-P8] 갈비찜", role="주찬"), db, user)
    recipe = create_recipe(menu["id"], RecipeBody(name="[TEST-P8] 기본", is_default=True, ingredients=[RecipeItemBody(ingredient_id=onion["id"], quantity_per_100=1, unit="kg", is_primary=True), RecipeItemBody(ingredient_id=carrot["id"], quantity_per_100=2, unit="kg")]), db, user)
    update_snapshot = add_snapshot(db, menu["id"], recipe["id"], [(onion["id"], onion["name"], 6, 1.5, "kg"), (carrot["id"], carrot["name"], 8, 2, "kg")])

    before = [(row.ingredient_id, row.quantity_total, row.quantity_per_100, row.unit) for row in db.scalars(select(MealServiceMenuIngredient).where(MealServiceMenuIngredient.meal_service_menu_id == update_snapshot.id)).all()]
    preview = preview_snapshot_recipe(menu["id"], SnapshotRecipePreviewBody(meal_service_menu_id=update_snapshot.id, mode="update", target_recipe_id=recipe["id"]), db, user)
    assert preview["can_apply"] is True
    assert preview["diff"]["summary"] == {"added": 0, "removed": 0, "changed": 1, "same": 1}

    updated = apply_snapshot_to_recipe(menu["id"], recipe["id"], SnapshotRecipePreviewBody(meal_service_menu_id=update_snapshot.id, mode="update"), db, user)
    assert [row["quantity_per_100"] for row in updated["ingredients"]] == [1.5, 2]
    assert db.scalar(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe["id"], RecipeIngredient.ingredient_id == onion["id"])).is_primary is True
    after = [(row.ingredient_id, row.quantity_total, row.quantity_per_100, row.unit) for row in db.scalars(select(MealServiceMenuIngredient).where(MealServiceMenuIngredient.meal_service_menu_id == update_snapshot.id)).all()]
    assert after == before

    create_snapshot = add_snapshot(db, menu["id"], recipe["id"], [(onion["id"], onion["name"], 6, 1.5, "kg"), (carrot["id"], carrot["name"], 8, 2, "kg"), (green_onion["id"], green_onion["name"], 2, 0.5, "kg")], day_offset=1)
    created = create_recipe_from_snapshot(menu["id"], SnapshotRecipeCreateBody(meal_service_menu_id=create_snapshot.id, recipe_name="[TEST-P8] 확장", make_default=False), db, user)
    assert created["version"] == 2
    assert created["is_default"] is False
    assert [(row["ingredient_id"], row["quantity_per_100"]) for row in created["ingredients"]] == [(onion["id"], 1.5), (carrot["id"], 2), (green_onion["id"], 0.5)]


def test_invalid_snapshot_and_duplicate_composition_are_blocked():
    db = make_db()
    user = object()
    ingredient = create_ingredient(IngredientBody(name="[TEST-P8] 재료", default_unit="kg"), db, user)
    menu = create_menu(MenuBody(name="[TEST-P8] 메뉴", role="주찬"), db, user)
    recipe = create_recipe(menu["id"], RecipeBody(name="[TEST-P8] 기본", ingredients=[RecipeItemBody(ingredient_id=ingredient["id"], quantity_per_100=1, unit="kg")]), db, user)
    duplicate = add_snapshot(db, menu["id"], recipe["id"], [(ingredient["id"], ingredient["name"], 4, 1, "kg")])
    with pytest.raises(HTTPException) as duplicate_error:
        create_recipe_from_snapshot(menu["id"], SnapshotRecipeCreateBody(meal_service_menu_id=duplicate.id, recipe_name="[TEST-P8] 중복"), db, user)
    assert duplicate_error.value.status_code == 409

    invalid = add_snapshot(db, menu["id"], recipe["id"], [(None, "[TEST-P8] 미연결", 4, None, "kg")], day_offset=1)
    preview = preview_snapshot_recipe(menu["id"], SnapshotRecipePreviewBody(meal_service_menu_id=invalid.id, mode="update", target_recipe_id=recipe["id"]), db, user)
    assert preview["can_apply"] is False
    assert {warning["type"] for warning in preview["warnings"]} == {"ingredient_id_missing"}
    with pytest.raises(HTTPException) as invalid_error:
        apply_snapshot_to_recipe(menu["id"], recipe["id"], SnapshotRecipePreviewBody(meal_service_menu_id=invalid.id, mode="update"), db, user)
    assert invalid_error.value.status_code == 400


def test_snapshot_apply_rejects_recipe_from_another_menu():
    db = make_db()
    user = object()
    ingredient = create_ingredient(IngredientBody(name="[TEST-P8] 재료", default_unit="kg"), db, user)
    menu_a = create_menu(MenuBody(name="[TEST-P8] 메뉴A"), db, user)
    menu_b = create_menu(MenuBody(name="[TEST-P8] 메뉴B"), db, user)
    recipe_a = create_recipe(menu_a["id"], RecipeBody(name="[TEST-P8] 레시피A", ingredients=[RecipeItemBody(ingredient_id=ingredient["id"], quantity_per_100=1, unit="kg")]), db, user)
    recipe_b = create_recipe(menu_b["id"], RecipeBody(name="[TEST-P8] 레시피B", ingredients=[RecipeItemBody(ingredient_id=ingredient["id"], quantity_per_100=1, unit="kg")]), db, user)
    snapshot = add_snapshot(db, menu_a["id"], recipe_a["id"], [(ingredient["id"], ingredient["name"], 4, 1, "kg")])
    with pytest.raises(HTTPException) as error:
        apply_snapshot_to_recipe(menu_a["id"], recipe_b["id"], SnapshotRecipePreviewBody(meal_service_menu_id=snapshot.id, mode="update"), db, user)
    assert error.value.status_code == 400


def test_snapshot_apply_rejects_recipe_changed_after_preview():
    db = make_db()
    user = object()
    ingredient = create_ingredient(IngredientBody(name="[TEST-P8] 재료", default_unit="kg"), db, user)
    menu = create_menu(MenuBody(name="[TEST-P8] 동시성 메뉴"), db, user)
    recipe = create_recipe(menu["id"], RecipeBody(name="[TEST-P8] 기본", ingredients=[RecipeItemBody(ingredient_id=ingredient["id"], quantity_per_100=1, unit="kg")]), db, user)
    snapshot = add_snapshot(db, menu["id"], recipe["id"], [(ingredient["id"], ingredient["name"], 4, 2, "kg")])
    preview = preview_snapshot_recipe(menu["id"], SnapshotRecipePreviewBody(meal_service_menu_id=snapshot.id, mode="update", target_recipe_id=recipe["id"]), db, user)
    db.execute(select(Recipe).where(Recipe.id == recipe["id"]))
    recipe_row = db.get(Recipe, recipe["id"])
    recipe_row.ingredients[0].quantity_per_100 = 3
    db.commit()
    with pytest.raises(HTTPException) as error:
        apply_snapshot_to_recipe(menu["id"], recipe["id"], SnapshotRecipePreviewBody(meal_service_menu_id=snapshot.id, mode="update", expected_recipe_fingerprint=preview["recipe_fingerprint"]), db, user)
    assert error.value.status_code == 409
    assert db.get(RecipeIngredient, recipe_row.ingredients[0].id).quantity_per_100 == 3


def test_snapshot_create_can_explicitly_make_new_recipe_default():
    db = make_db()
    user = object()
    ingredient_a = create_ingredient(IngredientBody(name="[TEST-P8] 재료A", default_unit="kg"), db, user)
    ingredient_b = create_ingredient(IngredientBody(name="[TEST-P8] 재료B", default_unit="kg"), db, user)
    menu = create_menu(MenuBody(name="[TEST-P8] 기본 변경 메뉴"), db, user)
    base = create_recipe(menu["id"], RecipeBody(name="[TEST-P8] 기존", is_default=True, ingredients=[RecipeItemBody(ingredient_id=ingredient_a["id"], quantity_per_100=1, unit="kg")]), db, user)
    snapshot = add_snapshot(db, menu["id"], base["id"], [(ingredient_a["id"], ingredient_a["name"], 4, 1, "kg"), (ingredient_b["id"], ingredient_b["name"], 2, 0.5, "kg")])
    created = create_recipe_from_snapshot(menu["id"], SnapshotRecipeCreateBody(meal_service_menu_id=snapshot.id, recipe_name="[TEST-P8] 새 기본", make_default=True), db, user)
    assert created["is_default"] is True
    assert db.get(Recipe, base["id"]).is_default is False
