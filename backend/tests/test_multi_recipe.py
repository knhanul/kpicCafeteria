from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Ingredient, Menu, Recipe
from app.routers.master import IngredientBody, MenuBody, RecipeBody, RecipeItemBody, create_ingredient, create_menu, create_recipe, update_recipe


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def test_same_menu_can_have_multiple_ingredient_compositions():
    db = make_db()
    user = object()
    meat = create_ingredient(IngredientBody(name="돼지고기", stat_group="돼지고기", default_unit="kg"), db, user)
    onion = create_ingredient(IngredientBody(name="양파", stat_group="채소", default_unit="kg"), db, user)
    menu = create_menu(MenuBody(name="돼지불고기", role="주찬"), db, user)

    first = create_recipe(
        menu["id"],
        RecipeBody(name="기본", is_default=True, ingredients=[RecipeItemBody(ingredient_id=meat["id"], quantity_per_100=8)]),
        db,
        user,
    )
    second = create_recipe(
        menu["id"],
        RecipeBody(
            name="양파 포함",
            ingredients=[
                RecipeItemBody(ingredient_id=meat["id"], quantity_per_100=8),
                RecipeItemBody(ingredient_id=onion["id"], quantity_per_100=3),
            ],
        ),
        db,
        user,
    )

    assert first["composition_key"] != second["composition_key"]
    assert len(db.scalars(select(Recipe)).all()) == 2


def test_quantity_only_change_updates_existing_recipe_and_duplicate_composition_is_blocked():
    db = make_db()
    user = object()
    ingredient = create_ingredient(IngredientBody(name="두부", stat_group="두류·두부", default_unit="kg"), db, user)
    menu = create_menu(MenuBody(name="두부조림", role="부찬"), db, user)
    recipe = create_recipe(
        menu["id"],
        RecipeBody(name="기본", ingredients=[RecipeItemBody(ingredient_id=ingredient["id"], quantity_per_100=5)]),
        db,
        user,
    )

    updated = update_recipe(
        recipe["id"],
        RecipeBody(name="기본", ingredients=[RecipeItemBody(ingredient_id=ingredient["id"], quantity_per_100=7)]),
        db,
        user,
    )
    assert updated["id"] == recipe["id"]
    assert updated["ingredients"][0]["quantity_per_100"] == 7

    try:
        create_recipe(
            menu["id"],
            RecipeBody(name="중복", ingredients=[RecipeItemBody(ingredient_id=ingredient["id"], quantity_per_100=9)]),
            db,
            user,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("같은 재료 구성의 중복 레시피가 허용되었습니다.")
