from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    AuditLog,
    Ingredient,
    IngredientAlias,
    MealActual,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    MealTypeSetting,
    Menu,
    PreservationRecord,
    Recipe,
    RecipeIngredient,
)
from .xlsx_reader import SimpleXlsxReader, excel_serial_to_date

EXPECTED_SHEETS = [
    "01_배식설정",
    "02_메뉴기준정보",
    "03_재료기준정보",
    "04_재료별칭_선택",
    "05_메뉴별재료_기준",
    "06_식단이력_이관",
    "07_식단재료_이관",
]

MEAL_CODE_MAP = {"중식": "LUNCH", "석식": "DINNER", "LUNCH": "LUNCH", "DINNER": "DINNER"}


def clean_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def clean_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_int(value: object) -> int | None:
    number = clean_float(value)
    return None if number is None else int(number)


def clean_bool(value: object, default: bool = False) -> bool:
    text = clean_text(value).upper()
    if text in {"Y", "YES", "TRUE", "1", "사용", "포함"}:
        return True
    if text in {"N", "NO", "FALSE", "0", "미사용", "제외"}:
        return False
    return default


def parse_time(value: object) -> time | None:
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    if isinstance(value, (float, int)):
        total_seconds = int(float(value) * 24 * 3600)
        return time((total_seconds // 3600) % 24, (total_seconds // 60) % 60)
    return None


class MigrationImporter:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def preview(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        summary: dict[str, Any] = {"filename": self.path.name, "sheets": {}, "ready": True}
        try:
            with SimpleXlsxReader(self.path) as reader:
                missing = [name for name in EXPECTED_SHEETS if name not in reader.sheets]
                if missing:
                    errors.append({"type": "MISSING_SHEET", "message": ", ".join(missing)})
                for sheet in EXPECTED_SHEETS:
                    if sheet in reader.sheets:
                        count = sum(1 for _ in reader.sheet_rows(sheet))
                        summary["sheets"][sheet] = count
                summary.update(
                    {
                        "meal_types": summary["sheets"].get("01_배식설정", 0),
                        "menus": summary["sheets"].get("02_메뉴기준정보", 0),
                        "ingredients": summary["sheets"].get("03_재료기준정보", 0),
                        "aliases": summary["sheets"].get("04_재료별칭_선택", 0),
                        "recipe_rows": summary["sheets"].get("05_메뉴별재료_기준", 0),
                        "meal_history_rows": summary["sheets"].get("06_식단이력_이관", 0),
                        "meal_ingredient_rows": summary["sheets"].get("07_식단재료_이관", 0),
                    }
                )
        except Exception as exc:
            errors.append({"type": "WORKBOOK_ERROR", "message": str(exc)})
        summary["ready"] = not errors
        return summary, errors

    def apply(self, db: Session, mode: str = "replace", user_id: int | None = None) -> dict[str, int]:
        if mode not in {"replace", "merge"}:
            raise ValueError("mode must be replace or merge")
        counters = defaultdict(int)
        with SimpleXlsxReader(self.path) as reader:
            missing = [name for name in EXPECTED_SHEETS if name not in reader.sheets]
            if missing:
                raise ValueError(f"필수 시트가 없습니다: {', '.join(missing)}")

            if mode == "replace":
                self._clear_business_data(db)

            menu_by_code: dict[str, Menu] = {}
            ingredient_by_code: dict[str, Ingredient] = {}

            for row in reader.sheet_rows("01_배식설정"):
                name = clean_text(row.get("배식유형"))
                if not name:
                    continue
                code = MEAL_CODE_MAP.get(name, name.upper())
                setting = db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == code))
                if not setting:
                    setting = MealTypeSetting(code=code, name=name)
                    db.add(setting)
                setting.name = name
                setting.default_planned_count = clean_int(row.get("기본계획식수")) or 0
                setting.default_service_time = parse_time(row.get("기본배식시간"))
                setting.active = clean_bool(row.get("사용여부"), True)
                setting.description = clean_text(row.get("설명")) or None
                counters["meal_types"] += 1
            db.flush()

            for row in reader.sheet_rows("02_메뉴기준정보"):
                code = clean_text(row.get("메뉴ID"))
                name = clean_text(row.get("메뉴명"))
                if not name:
                    continue
                menu = None
                if code:
                    menu = db.scalar(select(Menu).where(Menu.source_code == code))
                if not menu:
                    menu = db.scalar(select(Menu).where(Menu.name == name))
                if not menu:
                    menu = Menu(name=name, canonical_name=name)
                    db.add(menu)
                menu.source_code = code or menu.source_code
                menu.name = name
                menu.canonical_name = clean_text(row.get("통계집계메뉴명")) or name
                menu.role = clean_text(row.get("메뉴역할")) or "기타"
                menu.active = clean_bool(row.get("사용여부"), True)
                menu.review_status = clean_text(row.get("검토상태")) or "정상"
                db.flush()
                if code:
                    menu_by_code[code] = menu
                counters["menus"] += 1

            for row in reader.sheet_rows("03_재료기준정보"):
                code = clean_text(row.get("재료ID"))
                name = clean_text(row.get("표준재료명"))
                if not name:
                    continue
                ingredient = None
                if code:
                    ingredient = db.scalar(select(Ingredient).where(Ingredient.source_code == code))
                if not ingredient:
                    ingredient = db.scalar(select(Ingredient).where(Ingredient.name == name))
                if not ingredient:
                    ingredient = Ingredient(name=name)
                    db.add(ingredient)
                ingredient.source_code = code or ingredient.source_code
                ingredient.name = name
                ingredient.stat_group = clean_text(row.get("통계분석군")) or "기타"
                ingredient.default_unit = clean_text(row.get("기본단위")) or None
                ingredient.kg_factor = clean_float(row.get("kg환산계수"))
                ingredient.analysis_excluded = clean_bool(row.get("분석제외"), False)
                ingredient.active = clean_bool(row.get("사용여부"), True)
                ingredient.review_status = clean_text(row.get("검토상태")) or "정상"
                db.flush()
                if code:
                    ingredient_by_code[code] = ingredient
                counters["ingredients"] += 1

            for row in reader.sheet_rows("04_재료별칭_선택"):
                alias_name = clean_text(row.get("원재료별칭"))
                ingredient_code = clean_text(row.get("재료ID"))
                if not alias_name or ingredient_code not in ingredient_by_code:
                    continue
                alias = db.scalar(select(IngredientAlias).where(IngredientAlias.alias == alias_name))
                if not alias:
                    alias = IngredientAlias(alias=alias_name, ingredient=ingredient_by_code[ingredient_code])
                    db.add(alias)
                else:
                    alias.ingredient = ingredient_by_code[ingredient_code]
                alias.source = clean_text(row.get("출처")) or "기존데이터"
                counters["aliases"] += 1

            recipe_source_rows: list[dict[str, Any]] = []
            for row in reader.sheet_rows("05_메뉴별재료_기준"):
                menu_code = clean_text(row.get("메뉴ID"))
                ingredient_code = clean_text(row.get("재료ID"))
                menu = menu_by_code.get(menu_code)
                ingredient = ingredient_by_code.get(ingredient_code)
                if not menu or not ingredient:
                    continue
                recipe_source_rows.append(
                    {
                        "menu": menu,
                        "ingredient": ingredient,
                        "sort_order": clean_int(row.get("재료순서")) or 1,
                        "quantity_per_100": clean_float(row.get("100인기준수량")),
                        "unit": clean_text(row.get("단위")) or ingredient.default_unit,
                        "review_status": clean_text(row.get("검토상태")) or "정상",
                    }
                )
                counters["recipe_rows"] += 1

            existing_recipes_by_menu: dict[int, dict[str, Recipe]] = defaultdict(dict)
            existing_recipes = db.scalars(select(Recipe).where(Recipe.active.is_(True))).all()
            for recipe in existing_recipes:
                existing_recipes_by_menu[recipe.menu_id][recipe.composition_key] = recipe

            grouped_rows = self._group_recipe_rows_by_composition(recipe_source_rows)
            recipe_map_by_menu: dict[int, dict[str, Recipe]] = defaultdict(dict)
            default_recipe_by_menu: dict[int, Recipe] = {}

            for menu_id, recipe_groups in grouped_rows.items():
                for composition_key, rows_in_group in recipe_groups.items():
                    recipe = existing_recipes_by_menu.get(menu_id, {}).get(composition_key)
                    if not recipe:
                        max_version = db.scalar(select(Recipe.version).where(Recipe.menu_id == menu_id).order_by(Recipe.version.desc())) or 0
                        recipe = Recipe(
                            menu_id=menu_id,
                            name=f"기본 레시피 v{max_version + 1}",
                            version=max_version + 1,
                            composition_key=composition_key,
                            is_default=False,
                            active=True,
                        )
                        db.add(recipe)
                        db.flush()

                    item_by_ingredient_id: dict[int, RecipeIngredient] = {}
                    for row_data in rows_in_group:
                        ingredient: Ingredient = row_data["ingredient"]
                        item = item_by_ingredient_id.get(ingredient.id)
                        if not item:
                            item = db.scalar(
                                select(RecipeIngredient).where(
                                    RecipeIngredient.recipe_id == recipe.id,
                                    RecipeIngredient.ingredient_id == ingredient.id,
                                )
                            )
                        if not item:
                            item = RecipeIngredient(recipe=recipe, ingredient=ingredient)
                            db.add(item)
                        item.sort_order = row_data["sort_order"]
                        item.quantity_per_100 = row_data["quantity_per_100"]
                        item.unit = row_data["unit"]
                        item.review_status = row_data["review_status"]
                        item_by_ingredient_id[ingredient.id] = item

                    recipe_map_by_menu[menu_id][composition_key] = recipe
                    if recipe.is_default:
                        default_recipe_by_menu[menu_id] = recipe

                if menu_id not in default_recipe_by_menu and recipe_map_by_menu[menu_id]:
                    first_recipe = min(recipe_map_by_menu[menu_id].values(), key=lambda r: r.version)
                    first_recipe.is_default = True
                    default_recipe_by_menu[menu_id] = first_recipe
            db.flush()

            service_map: dict[tuple[str, str], MealService] = {}
            service_menu_map: dict[tuple[str, str, str, int], MealServiceMenu] = {}
            service_menu_by_id: dict[int, MealServiceMenu] = {}
            service_menu_ingredient_ids: dict[int, set[int]] = defaultdict(set)
            for row in reader.sheet_rows("06_식단이력_이관"):
                service_date = excel_serial_to_date(row.get("일자"))
                meal_name = clean_text(row.get("배식유형"))
                meal_type = MEAL_CODE_MAP.get(meal_name, meal_name.upper())
                menu_code = clean_text(row.get("메뉴ID"))
                menu_name = clean_text(row.get("메뉴명"))
                menu_order = clean_int(row.get("메뉴순서")) or 1
                if not service_date or not meal_type or not menu_name:
                    continue
                service_key = (service_date.isoformat(), meal_type)
                service = service_map.get(service_key)
                if not service:
                    service = db.scalar(
                        select(MealService).where(
                            MealService.service_date == service_date,
                            MealService.meal_type == meal_type,
                        )
                    )
                    if not service:
                        service = MealService(service_date=service_date, meal_type=meal_type)
                        db.add(service)
                    service.planned_count = clean_int(row.get("계획식수")) or self._default_count(db, meal_type)
                    service.service_time = parse_time(row.get("배식시간")) or self._default_time(db, meal_type)
                    db.flush()
                    service_map[service_key] = service
                    counters["services"] += 1
                menu = menu_by_code.get(menu_code)
                menu_key = (service_date.isoformat(), meal_type, menu_code or menu_name, menu_order)
                service_menu = service_menu_map.get(menu_key)
                if not service_menu:
                    service_menu = db.scalar(
                        select(MealServiceMenu).where(
                            MealServiceMenu.meal_service_id == service.id,
                            MealServiceMenu.sort_order == menu_order,
                            MealServiceMenu.menu_name_snapshot == menu_name,
                        )
                    )
                if not service_menu:
                    source_recipe = default_recipe_by_menu.get(menu.id) if menu else None
                    service_menu = MealServiceMenu(
                        service=service,
                        menu=menu,
                        recipe_id=source_recipe.id if source_recipe else None,
                        sort_order=menu_order,
                        menu_name_snapshot=menu_name,
                        recipe_name_snapshot=source_recipe.name if source_recipe else None,
                        recipe_version_snapshot=source_recipe.version if source_recipe else None,
                    )
                    db.add(service_menu)
                service_menu.note = clean_text(row.get("메뉴비고")) or None
                db.flush()
                service_menu_map[menu_key] = service_menu
                service_menu_by_id[service_menu.id] = service_menu
                counters["meal_history_rows"] += 1

            for row in reader.sheet_rows("07_식단재료_이관"):
                service_date = excel_serial_to_date(row.get("일자"))
                meal_name = clean_text(row.get("배식유형"))
                meal_type = MEAL_CODE_MAP.get(meal_name, meal_name.upper())
                menu_code = clean_text(row.get("메뉴ID"))
                menu_name = clean_text(row.get("메뉴명"))
                menu_order = clean_int(row.get("메뉴순서")) or 1
                ingredient_code = clean_text(row.get("재료ID"))
                if not service_date:
                    continue
                menu_key = (service_date.isoformat(), meal_type, menu_code or menu_name, menu_order)
                service_menu = service_menu_map.get(menu_key)
                if not service_menu:
                    continue
                ingredient = ingredient_by_code.get(ingredient_code)
                ingredient_name = clean_text(row.get("표준재료명")) or clean_text(row.get("원본재료명"))
                if not ingredient_name:
                    continue
                if ingredient:
                    service_menu_ingredient_ids[service_menu.id].add(ingredient.id)
                sort_order = clean_int(row.get("재료순서")) or 1
                existing = db.scalar(
                    select(MealServiceMenuIngredient).where(
                        MealServiceMenuIngredient.meal_service_menu_id == service_menu.id,
                        MealServiceMenuIngredient.sort_order == sort_order,
                        MealServiceMenuIngredient.ingredient_name_snapshot == ingredient_name,
                    )
                )
                if not existing:
                    existing = MealServiceMenuIngredient(service_menu=service_menu)
                    db.add(existing)
                total = clean_float(row.get("수량"))
                planned = service_menu.service.planned_count or 0
                existing.ingredient = ingredient
                existing.sort_order = sort_order
                existing.ingredient_name_snapshot = ingredient_name
                existing.quantity_total = total
                existing.quantity_per_100 = (total * 100 / planned) if total is not None and planned else None
                existing.unit = clean_text(row.get("단위")) or (ingredient.default_unit if ingredient else None)
                existing.source_note = clean_text(row.get("원본비고")) or None
                existing.source_row = clean_text(row.get("원본행")) or None
                counters["meal_ingredient_rows"] += 1

            for service_menu_id, ingredient_ids in service_menu_ingredient_ids.items():
                service_menu = service_menu_by_id.get(service_menu_id)
                if not service_menu or not service_menu.menu_id:
                    continue
                composition_key = self._composition_key_from_ingredient_ids(ingredient_ids)
                recipe = recipe_map_by_menu.get(service_menu.menu_id, {}).get(composition_key)
                if not recipe:
                    recipe = default_recipe_by_menu.get(service_menu.menu_id)
                if not recipe:
                    continue
                service_menu.recipe_id = recipe.id
                service_menu.recipe_name_snapshot = recipe.name
                service_menu.recipe_version_snapshot = recipe.version

            db.add(
                AuditLog(
                    user_id=user_id,
                    action="MIGRATION_IMPORT",
                    entity_type="WORKBOOK",
                    entity_id=self.path.name,
                    detail={"mode": mode, **dict(counters)},
                )
            )
            db.commit()
        return dict(counters)

    @staticmethod
    def _default_count(db: Session, meal_type: str) -> int:
        setting = db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == meal_type))
        return setting.default_planned_count if setting else 0

    @staticmethod
    def _default_time(db: Session, meal_type: str) -> time | None:
        setting = db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == meal_type))
        return setting.default_service_time if setting else None

    @staticmethod
    def _clear_business_data(db: Session) -> None:
        # Keep users, document templates and audit logs.
        for model in (
            MealActual,
            PreservationRecord,
            MealServiceMenuIngredient,
            MealServiceMenu,
            MealService,
            RecipeIngredient,
            Recipe,
            IngredientAlias,
            Ingredient,
            Menu,
            MealTypeSetting,
        ):
            db.execute(delete(model))
        db.flush()

    @staticmethod
    def _composition_key_from_ingredient_ids(ingredient_ids: set[int] | list[int]) -> str:
        ids = sorted({int(value) for value in ingredient_ids})
        return ",".join(str(value) for value in ids) if ids else "EMPTY"

    @classmethod
    def _group_recipe_rows_by_composition(cls, recipe_rows: list[dict[str, Any]]) -> dict[int, dict[str, list[dict[str, Any]]]]:
        grouped: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
        current_block_rows_by_menu: dict[int, list[dict[str, Any]]] = defaultdict(list)
        last_sort_order_by_menu: dict[int, int] = {}

        def flush_block(menu_id: int) -> None:
            rows = current_block_rows_by_menu.get(menu_id) or []
            if not rows:
                return
            composition_key = cls._composition_key_from_ingredient_ids(
                [row["ingredient"].id for row in rows if row.get("ingredient")]
            )
            if composition_key not in grouped[menu_id]:
                grouped[menu_id][composition_key] = []
            grouped[menu_id][composition_key].extend(rows)
            current_block_rows_by_menu[menu_id] = []

        for row in recipe_rows:
            menu: Menu = row["menu"]
            menu_id = menu.id
            sort_order = int(row.get("sort_order") or 0)
            last_sort = last_sort_order_by_menu.get(menu_id)
            if last_sort is not None and sort_order <= last_sort:
                flush_block(menu_id)
            current_block_rows_by_menu[menu_id].append(row)
            last_sort_order_by_menu[menu_id] = sort_order

        for menu_id in list(current_block_rows_by_menu.keys()):
            flush_block(menu_id)

        return grouped
