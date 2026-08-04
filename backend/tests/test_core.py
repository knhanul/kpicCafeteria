from pathlib import Path

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
