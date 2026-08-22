from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.importer import MigrationImporter
from app.models import Ingredient, MealService, MealServiceMenu, MealServiceMenuIngredient, Menu, Recipe, RecipeIngredient


def test_repository_migration_workbook_previews_and_applies_in_isolated_db():
    workbook = next((Path(__file__).resolve().parents[2] / "data" / "source").glob("*.xlsx"))
    importer = MigrationImporter(workbook)
    summary, errors = importer.preview()
    assert summary["ready"] is True
    assert errors == []

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = importer.apply(db, mode="merge")
        assert result["menus"] > 0
        assert result["ingredients"] > 0
        assert result["recipe_rows"] > 0
        assert result["meal_history_rows"] > 0
        assert db.scalar(select(func.count()).select_from(Menu)) > 0
        assert db.scalar(select(func.count()).select_from(Ingredient)) > 0
        assert db.scalar(select(func.count()).select_from(Recipe)) > 0
        assert db.scalar(select(func.count()).select_from(RecipeIngredient)) > 0
        assert db.scalar(select(func.count()).select_from(MealService)) > 0
        assert db.scalar(select(func.count()).select_from(MealServiceMenu)) > 0
        assert db.scalar(select(func.count()).select_from(MealServiceMenuIngredient)) > 0
