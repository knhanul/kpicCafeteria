"""메인 메뉴(MealServiceMenu.is_representative): 이관(06.메인메뉴여부) · 식단 편집 API 일관성 테스트."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.importer import MigrationImporter
from app.models import MealService, MealServiceMenu, Menu, User
from app.routers.workspace import (
    AddMenuBody,
    BatchAddMenuBody,
    BatchAddMenuItemBody,
    MealEditorBody,
    MealEditorMenuBody,
    ReorderBody,
    ServiceMenuBody,
    add_menu,
    batch_add_menus,
    reorder_menus,
    save_meal_editor,
    update_service_menu,
)
from app.schema_upgrade import upgrade_existing_schema

MENUS = [
    ["M001", "쌀밥", "쌀밥", "밥·죽", "Y", "정상"],
    ["M002", "돈가스", "돈가스", "주찬", "Y", "정상"],
    ["M003", "비빔밥", "비빔밥", "밥·죽", "Y", "정상"],
    ["M004", "제육볶음", "제육볶음", "주찬", "Y", "정상"],
    ["M005", "배추김치", "배추김치", "김치·절임", "Y", "정상"],
]
NAMES = {row[0]: row[1] for row in MENUS}
HISTORY_HEADERS = ["일자", "배식유형", "계획식수", "배식시간", "메뉴순서", "메뉴ID", "메뉴명", "메뉴비고"]
HISTORY_HEADERS_MAIN = ["일자", "배식유형", "계획식수", "배식시간", "메뉴순서", "메뉴ID", "메뉴명", "메인메뉴여부", "메뉴비고"]


def history(day: str, meal: str, order: int, code: str, flag: object = "__absent__") -> list[object]:
    row: list[object] = [day, meal, 400, "12:00", order, code, NAMES[code]]
    if flag != "__absent__":
        row.append(flag)
    row.append("")
    return row


def make_workbook(path: Path, rows: list[list[object]], with_main_column: bool = True) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "01_배식설정"
    sheet.append(["배식유형", "기본계획식수", "기본배식시간", "사용여부", "설명"])
    sheet.append(["중식", 400, "12:00", "Y", ""])
    sheet.append(["석식", 100, "18:00", "Y", ""])
    for name, headers, data in [
        ("02_메뉴기준정보", ["메뉴ID", "메뉴명", "통계집계메뉴명", "메뉴역할", "사용여부", "검토상태"], MENUS),
        ("03_재료기준정보", ["재료ID", "표준재료명", "통계분석군", "기본단위", "kg환산계수", "분석제외", "사용여부", "검토상태"], []),
        ("04_재료별칭_선택", ["원재료별칭", "재료ID", "표준재료명", "출처"], []),
        ("05_메뉴별재료_기준", ["메뉴ID", "메뉴명", "레시피명", "재료ID", "표준재료명", "100인기준수량", "단위", "원본행", "원본비고", "검토상태", "재료순서"], []),
        ("06_식단이력_이관", HISTORY_HEADERS_MAIN if with_main_column else HISTORY_HEADERS, rows),
        ("07_식단재료_이관", ["일자", "배식유형", "메뉴순서", "메뉴ID", "메뉴명", "재료순서", "재료ID", "표준재료명", "원본재료명", "수량", "단위", "원본비고", "원본행"], []),
    ]:
        ws = workbook.create_sheet(name)
        ws.append(headers)
        for row in data:
            ws.append(row)
    workbook.save(path)
    return path


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    upgrade_existing_schema(engine)
    return Session(engine, expire_on_commit=False)


def main_flags(db: Session, day: str = "2025-04-01", meal_type: str = "LUNCH") -> dict[str, bool]:
    service = db.scalar(select(MealService).where(MealService.service_date == date.fromisoformat(day), MealService.meal_type == meal_type))
    assert service is not None
    items = db.scalars(select(MealServiceMenu).where(MealServiceMenu.meal_service_id == service.id)).all()
    return {item.menu_name_snapshot: bool(item.is_representative) for item in items}


def mains(db: Session, **kwargs) -> list[str]:
    return sorted(name for name, flag in main_flags(db, **kwargs).items() if flag)


# ---------------------------------------------------------------- import: explicit 메인메뉴여부


@pytest.mark.parametrize("mode", ["replace", "merge"])
def test_explicit_y_on_one_dish_rice_wins_over_earlier_juchan(tmp_path, mode):
    path = make_workbook(
        tmp_path / "main.xlsx",
        [
            history("2025-04-01", "중식", 1, "M001", "N"),
            history("2025-04-01", "중식", 2, "M002", "N"),  # 주찬 earlier in order but N
            history("2025-04-01", "중식", 3, "M003", "Y"),  # 비빔밥 (일품밥류) is the main menu
            history("2025-04-01", "중식", 4, "M005", "N"),
        ],
    )
    summary, errors = MigrationImporter(path).preview()
    assert errors == [] and summary["main_menu_column"] is True
    with make_db() as db:
        result = MigrationImporter(path).apply(db, mode=mode)
        assert mains(db) == ["비빔밥"]
        assert main_flags(db)["돈가스"] is False
        assert result["main_menus"] == 1
        # role is not changed to match the main designation
        assert db.scalar(select(Menu).where(Menu.source_code == "M003")).role == "밥·죽"


def test_without_one_dish_rice_first_juchan_y_is_imported(tmp_path):
    path = make_workbook(
        tmp_path / "main.xlsx",
        [
            history("2025-04-01", "중식", 1, "M001", "N"),
            history("2025-04-01", "중식", 2, "M002", "Y"),
            history("2025-04-01", "중식", 3, "M004", "N"),
            history("2025-04-01", "중식", 4, "M005", "N"),
        ],
    )
    with make_db() as db:
        MigrationImporter(path).apply(db, mode="replace")
        assert mains(db) == ["돈가스"]
        assert main_flags(db)["제육볶음"] is False


def test_service_with_all_n_has_no_main_menu(tmp_path):
    path = make_workbook(
        tmp_path / "main.xlsx",
        [
            history("2025-04-01", "중식", 1, "M001", "N"),
            history("2025-04-01", "중식", 2, "M002", "n"),  # case-insensitive
            history("2025-04-01", "석식", 1, "M004", "Y"),
        ],
    )
    assert MigrationImporter(path).preview()[1] == []
    with make_db() as db:
        MigrationImporter(path).apply(db, mode="replace")
        assert mains(db) == []  # the 주찬 is NOT auto-picked when the column says N
        assert mains(db, meal_type="DINNER") == ["제육볶음"]


def test_duplicate_y_is_rejected_with_row_numbers_and_nothing_is_written(tmp_path):
    path = make_workbook(
        tmp_path / "dup.xlsx",
        [
            history("2025-04-01", "중식", 1, "M002", "Y"),
            history("2025-04-01", "중식", 2, "M003", "Y"),
            history("2025-04-01", "석식", 1, "M004", "Y"),  # other service: fine
        ],
    )
    summary, errors = MigrationImporter(path).preview()
    assert summary["ready"] is False
    duplicate = [error for error in errors if error["type"] == "DUPLICATE_MAIN_MENU"]
    assert len(duplicate) == 1
    message = duplicate[0]["message"]
    assert "2025-04-01" in message and "중식" in message and "2행 돈가스" in message and "3행 비빔밥" in message

    with make_db() as db:
        existing = MealService(service_date=date(2024, 1, 2), meal_type="LUNCH", planned_count=1)
        db.add(existing)
        db.commit()
        with pytest.raises(ValueError, match="Y인 행이 2개"):
            MigrationImporter(path).apply(db, mode="replace")
        db.rollback()
        # validation happens before the replace wipe
        assert db.scalar(select(MealService).where(MealService.service_date == date(2024, 1, 2))) is not None
        assert db.scalar(select(MealServiceMenu)) is None


@pytest.mark.parametrize("bad_value", ["X", "", "예", 1])
def test_invalid_flag_value_is_rejected_with_row_number(tmp_path, bad_value):
    path = make_workbook(
        tmp_path / "bad.xlsx",
        [
            history("2025-04-01", "중식", 1, "M001", "N"),
            history("2025-04-01", "중식", 2, "M002", bad_value),
        ],
    )
    summary, errors = MigrationImporter(path).preview()
    assert summary["ready"] is False
    assert [error["type"] for error in errors] == ["INVALID_MAIN_MENU_FLAG"]
    assert errors[0]["row"] == 3
    assert "06_식단이력_이관 3행" in errors[0]["message"] and "돈가스" in errors[0]["message"]
    with make_db() as db, pytest.raises(ValueError, match="Y 또는 N"):
        MigrationImporter(path).apply(db, mode="merge")


# ---------------------------------------------------------------- import: legacy file (no column)


@pytest.mark.parametrize("mode", ["replace", "merge"])
def test_legacy_file_without_column_still_imports_and_auto_picks_lowest_order_juchan(tmp_path, mode):
    path = make_workbook(
        tmp_path / "legacy.xlsx",
        [
            history("2025-04-01", "중식", 1, "M001"),
            history("2025-04-01", "중식", 3, "M004"),  # 주찬, listed first but 메뉴순서 3
            history("2025-04-01", "중식", 2, "M002"),  # 주찬 with the lowest 메뉴순서
            history("2025-04-01", "중식", 4, "M003"),
            history("2025-04-01", "석식", 1, "M001"),  # no 주찬 → no main
        ],
        with_main_column=False,
    )
    summary, errors = MigrationImporter(path).preview()
    assert errors == [] and summary["main_menu_column"] is False
    with make_db() as db:
        result = MigrationImporter(path).apply(db, mode=mode)
        assert result["meal_history_rows"] == 5
        assert mains(db) == ["돈가스"]
        assert mains(db, meal_type="DINNER") == []


def test_legacy_merge_does_not_add_second_main_to_service_that_already_has_one(tmp_path):
    first = make_workbook(tmp_path / "first.xlsx", [history("2025-04-01", "중식", 1, "M004", "Y")])
    legacy = make_workbook(
        tmp_path / "legacy.xlsx",
        [history("2025-04-01", "중식", 1, "M004"), history("2025-04-01", "중식", 2, "M002")],
        with_main_column=False,
    )
    with make_db() as db:
        MigrationImporter(first).apply(db, mode="merge")
        MigrationImporter(legacy).apply(db, mode="merge")
        assert mains(db) == ["제육볶음"]


# ---------------------------------------------------------------- import: re-import updates stale Y


def test_reimport_merge_explicit_n_overwrites_previous_y(tmp_path):
    first = make_workbook(
        tmp_path / "first.xlsx",
        [
            history("2025-04-01", "중식", 1, "M002", "Y"),
            history("2025-04-01", "중식", 2, "M003", "N"),
            history("2025-04-02", "중식", 1, "M004", "Y"),
        ],
    )
    second = make_workbook(
        tmp_path / "second.xlsx",
        [
            history("2025-04-01", "중식", 1, "M002", "N"),
            history("2025-04-01", "중식", 2, "M003", "Y"),
            history("2025-04-02", "중식", 1, "M004", "N"),  # all N now
        ],
    )
    with make_db() as db:
        MigrationImporter(first).apply(db, mode="merge")
        assert mains(db) == ["돈가스"]
        ids_before = {name: item_id for name, item_id in db.execute(select(MealServiceMenu.menu_name_snapshot, MealServiceMenu.id))}
        MigrationImporter(second).apply(db, mode="merge")
        db.expire_all()
        assert mains(db) == ["비빔밥"]
        assert mains(db, day="2025-04-02") == []
        # the same rows were reused (no duplicates created)
        ids_after = {name: item_id for name, item_id in db.execute(select(MealServiceMenu.menu_name_snapshot, MealServiceMenu.id))}
        assert ids_after == ids_before


def test_reimport_merge_clears_stale_main_on_menu_not_in_file(tmp_path):
    second = make_workbook(
        tmp_path / "second.xlsx",
        [history("2025-04-01", "중식", 1, "M002", "N"), history("2025-04-01", "중식", 2, "M003", "Y")],
    )
    with make_db() as db:
        service = MealService(service_date=date(2025, 4, 1), meal_type="LUNCH", planned_count=400)
        db.add(service)
        db.flush()
        db.add(MealServiceMenu(meal_service_id=service.id, sort_order=9, menu_name_snapshot="수기 추가 메뉴", is_representative=True))
        db.commit()
        MigrationImporter(second).apply(db, mode="merge")
        db.expire_all()
        assert mains(db) == ["비빔밥"]
        assert main_flags(db)["수기 추가 메뉴"] is False


def test_reimport_replace_uses_new_flags(tmp_path):
    first = make_workbook(tmp_path / "first.xlsx", [history("2025-04-01", "중식", 1, "M002", "Y"), history("2025-04-01", "중식", 2, "M003", "N")])
    second = make_workbook(tmp_path / "second.xlsx", [history("2025-04-01", "중식", 1, "M002", "N"), history("2025-04-01", "중식", 2, "M003", "N")])
    with make_db() as db:
        MigrationImporter(first).apply(db, mode="replace")
        MigrationImporter(second).apply(db, mode="replace")
        assert mains(db) == []


# ---------------------------------------------------------------- 식단 편집 API


def make_user(db: Session) -> User:
    user = User(username="tester", password_hash="x", display_name="Tester", active=True)
    db.add(user)
    db.flush()
    return user


def make_menu(db: Session, name: str, role: str) -> Menu:
    menu = Menu(name=name, canonical_name=name, role=role, active=True)
    db.add(menu)
    db.flush()
    return menu


def make_editor_service(db: Session) -> tuple[MealService, list[MealServiceMenu]]:
    service = MealService(service_date=date(2025, 1, 1), meal_type="LUNCH", planned_count=100)
    db.add(service)
    db.flush()
    items = []
    for order, (name, role, is_main) in enumerate([("쌀밥", "밥·죽", False), ("돈가스", "주찬", True), ("비빔밥", "밥·죽", False)], start=1):
        menu = make_menu(db, name, role)
        item = MealServiceMenu(meal_service_id=service.id, menu_id=menu.id, menu_name_snapshot=name, sort_order=order, is_representative=is_main)
        db.add(item)
        items.append(item)
    db.commit()
    return service, items


def service_mains(result: dict) -> list[str]:
    return [menu["name"] for menu in result["menus"] if menu["is_representative"]]


def test_update_service_menu_switches_and_clears_main_without_duplicates():
    db = make_db()
    user = make_user(db)
    service, (rice, pork, bibim) = make_editor_service(db)

    result = update_service_menu(bibim.id, ServiceMenuBody(note=None, is_representative=True), db, user)
    assert service_mains(result) == ["비빔밥"]

    result = update_service_menu(bibim.id, ServiceMenuBody(note=None, is_representative=False), db, user)
    assert service_mains(result) == []  # clearing leaves no main; nothing is auto-picked
    # role untouched
    assert db.get(Menu, bibim.menu_id).role == "밥·죽"


def test_meal_editor_save_keeps_at_most_one_main():
    db = make_db()
    user = make_user(db)
    service, (rice, pork, bibim) = make_editor_service(db)

    def body(flags: dict[int, bool], ids=None) -> MealEditorBody:
        return MealEditorBody(
            planned_count=100,
            menus=[MealEditorMenuBody(service_menu_id=item_id, is_representative=flags.get(item_id, False)) for item_id in (ids or flags)],
        )

    result = save_meal_editor(service.id, body({rice.id: False, pork.id: False, bibim.id: True}), db, user)
    assert service_mains(result) == ["비빔밥"]

    # a partial payload choosing another main still clears the old one
    result = save_meal_editor(service.id, body({pork.id: True}), db, user)
    assert service_mains(result) == ["돈가스"]

    result = save_meal_editor(service.id, body({rice.id: False, pork.id: False, bibim.id: False}), db, user)
    assert service_mains(result) == []

    with pytest.raises(HTTPException) as error:
        save_meal_editor(service.id, body({pork.id: True, bibim.id: True}), db, user)
    assert error.value.status_code == 400
    db.rollback()
    assert [item.menu_name_snapshot for item in db.scalars(select(MealServiceMenu).where(MealServiceMenu.is_representative.is_(True)))] == []


def test_adding_and_reordering_menus_does_not_duplicate_or_change_main():
    db = make_db()
    user = make_user(db)
    service, (rice, pork, bibim) = make_editor_service(db)
    update_service_menu(bibim.id, ServiceMenuBody(is_representative=True), db, user)

    extra_juchan = make_menu(db, "제육볶음", "주찬")
    result = add_menu(service.id, AddMenuBody(menu_id=extra_juchan.id), db, user)
    assert service_mains(result) == ["비빔밥"]

    batch_juchan = make_menu(db, "닭갈비", "주찬")
    result = batch_add_menus(service.id, BatchAddMenuBody(items=[BatchAddMenuItemBody(menu_id=batch_juchan.id, sort_order=1)]), db, user)
    assert service_mains(result) == ["비빔밥"]

    # deliberately no main: adding a 주찬 must not silently re-create one
    update_service_menu(bibim.id, ServiceMenuBody(is_representative=False), db, user)
    another = make_menu(db, "생선구이", "주찬")
    result = add_menu(service.id, AddMenuBody(menu_id=another.id), db, user)
    assert service_mains(result) == []

    update_service_menu(pork.id, ServiceMenuBody(is_representative=True), db, user)
    ids = [menu["id"] for menu in result["menus"]]
    result = reorder_menus(service.id, ReorderBody(menu_ids=list(reversed(ids))), db, user)
    assert service_mains(result) == ["돈가스"]


def test_empty_service_gets_lowest_sort_order_juchan_as_main_on_batch_add():
    db = make_db()
    user = make_user(db)
    service = MealService(service_date=date(2025, 1, 2), meal_type="LUNCH", planned_count=100)
    db.add(service)
    db.commit()
    side = make_menu(db, "배추김치", "김치·절임")
    later = make_menu(db, "제육볶음", "주찬")
    first = make_menu(db, "돈가스", "주찬")
    result = batch_add_menus(
        service.id,
        BatchAddMenuBody(
            items=[
                BatchAddMenuItemBody(menu_id=later.id, sort_order=3),
                BatchAddMenuItemBody(menu_id=side.id, sort_order=1),
                BatchAddMenuItemBody(menu_id=first.id, sort_order=2),
            ]
        ),
        db,
        user,
    )
    assert service_mains(result) == ["돈가스"]
