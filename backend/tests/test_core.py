from pathlib import Path
from types import SimpleNamespace

from app.importer import MigrationImporter
from app.xlsx_reader import SimpleXlsxReader


def test_migration_workbook_has_expected_counts():
    workbook = Path(__file__).resolve().parents[2] / "data" / "source" / "식재료_마이그레이션_기준정보.xlsx"
    summary, errors = MigrationImporter(workbook).preview()
    assert not errors
    assert summary["meal_types"] == 2
    assert summary["menus"] > 100
    assert summary["ingredients"] > 100
    assert summary["meal_history_rows"] > 1000


def test_reader_reads_lunch_and_dinner():
    workbook = Path(__file__).resolve().parents[2] / "data" / "source" / "식재료_마이그레이션_기준정보.xlsx"
    with SimpleXlsxReader(workbook) as reader:
        rows = list(reader.sheet_rows("01_배식설정"))
    assert [row["배식유형"] for row in rows] == ["중식", "석식"]
    assert [row["기본계획식수"] for row in rows] == [400, 100]


def test_group_recipe_rows_by_composition_splits_different_ingredients():
    menu = SimpleNamespace(id=101)
    ing1 = SimpleNamespace(id=1)
    ing2 = SimpleNamespace(id=2)
    ing3 = SimpleNamespace(id=3)

    rows = [
        {"menu": menu, "ingredient": ing1, "sort_order": 1, "quantity_per_100": 10.0, "unit": "kg", "review_status": "정상"},
        {"menu": menu, "ingredient": ing2, "sort_order": 2, "quantity_per_100": 5.0, "unit": "kg", "review_status": "정상"},
        {"menu": menu, "ingredient": ing1, "sort_order": 1, "quantity_per_100": 12.0, "unit": "kg", "review_status": "정상"},
        {"menu": menu, "ingredient": ing3, "sort_order": 2, "quantity_per_100": 3.0, "unit": "g", "review_status": "정상"},
    ]

    grouped = MigrationImporter._group_recipe_rows_by_composition(rows)

    assert 101 in grouped
    assert set(grouped[101].keys()) == {"1,2", "1,3"}


def test_group_recipe_rows_by_composition_ignores_quantity_and_unit_changes():
    menu = SimpleNamespace(id=202)
    ing1 = SimpleNamespace(id=1)
    ing2 = SimpleNamespace(id=2)

    rows = [
        {"menu": menu, "ingredient": ing1, "sort_order": 1, "quantity_per_100": 10.0, "unit": "kg", "review_status": "정상"},
        {"menu": menu, "ingredient": ing2, "sort_order": 2, "quantity_per_100": 2.0, "unit": "kg", "review_status": "정상"},
        {"menu": menu, "ingredient": ing1, "sort_order": 1, "quantity_per_100": 8.0, "unit": "g", "review_status": "정상"},
        {"menu": menu, "ingredient": ing2, "sort_order": 2, "quantity_per_100": 4.0, "unit": "ml", "review_status": "정상"},
    ]

    grouped = MigrationImporter._group_recipe_rows_by_composition(rows)

    assert 202 in grouped
    assert set(grouped[202].keys()) == {"1,2"}
    assert len(grouped[202]["1,2"]) == 4
