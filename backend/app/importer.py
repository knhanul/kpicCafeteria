from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
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

# Optional column of 06_식단이력_이관. When present it is authoritative for MealServiceMenu.is_representative
# (shown to users as "메인 메뉴"); when absent the legacy automatic rule (first 주찬) is used.
MAIN_MENU_COLUMN = "메인메뉴여부"
MAIN_MENU_ERROR_LIMIT = 20


def parse_main_menu_flag(value: object) -> bool | None:
    """Strict Y/N parser for 메인메뉴여부. Returns None for anything else (including blank)."""
    text = clean_text(value).upper()
    if text == "Y":
        return True
    if text == "N":
        return False
    return None


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
                if "06_식단이력_이관" in reader.sheets:
                    has_main_column = MAIN_MENU_COLUMN in reader.sheet_headers("06_식단이력_이관")
                    summary["main_menu_column"] = has_main_column
                    if has_main_column:
                        errors.extend(self._validate_main_menu_flags(reader))
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
        # In replace mode every business table is emptied first, so per-row "does it already exist?"
        # queries can only ever match rows created earlier in this same run. Those are tracked in local
        # dict caches instead (same matching keys as the original queries), which removes tens of
        # thousands of DB round trips and per-row flushes. Merge mode keeps the original query/flush path.
        is_replace = mode == "replace"
        self._settings_cache: dict[str, MealTypeSetting | None] = {}
        flush_guard = db.no_autoflush if is_replace else nullcontext()
        with SimpleXlsxReader(self.path) as reader, flush_guard:
            missing = [name for name in EXPECTED_SHEETS if name not in reader.sheets]
            if missing:
                raise ValueError(f"필수 시트가 없습니다: {', '.join(missing)}")

            # Validate 메인메뉴여부 before anything is cleared or written, so a bad file never half-applies.
            has_main_column = MAIN_MENU_COLUMN in reader.sheet_headers("06_식단이력_이관")
            if has_main_column:
                main_menu_errors = self._validate_main_menu_flags(reader)
                if main_menu_errors:
                    raise ValueError("\n".join(error["message"] for error in main_menu_errors))

            preserved_records: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
            if mode == "replace":
                # Actual meal counts and preservation records are operational results that are not part of the
                # base-data workbook; keep them across the wipe and re-attach them by (service_date, meal_type).
                preserved_records = self._snapshot_service_records(db)
                self._clear_business_data(db)

            menu_by_code: dict[str, Menu] = {}
            ingredient_by_code: dict[str, Ingredient] = {}

            for row in reader.sheet_rows("01_배식설정"):
                name = clean_text(row.get("배식유형"))
                if not name:
                    continue
                code = MEAL_CODE_MAP.get(name, name.upper())
                setting = None if is_replace else db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == code))
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

            # replace-mode caches mirroring the source_code / name lookups below
            menus_by_source: dict[str, Menu] = {}
            menus_by_name: dict[str, Menu] = {}
            for row in reader.sheet_rows("02_메뉴기준정보"):
                code = clean_text(row.get("메뉴ID"))
                name = clean_text(row.get("메뉴명"))
                if not name:
                    continue
                menu = None
                if is_replace:
                    if code:
                        menu = menus_by_source.get(code)
                    if not menu:
                        menu = menus_by_name.get(name)
                else:
                    if code:
                        menu = db.scalar(select(Menu).where(Menu.source_code == code))
                    if not menu:
                        menu = db.scalar(select(Menu).where(Menu.name == name))
                if not menu:
                    menu = Menu(name=name, canonical_name=name)
                    db.add(menu)
                if is_replace:
                    self._reindex(menus_by_source, menu, menu.source_code, code or menu.source_code)
                    self._reindex(menus_by_name, menu, menu.name, name)
                menu.source_code = code or menu.source_code
                menu.name = name
                menu.canonical_name = clean_text(row.get("통계집계메뉴명")) or name
                menu.role = clean_text(row.get("메뉴역할")) or "기타"
                menu.active = clean_bool(row.get("사용여부"), True)
                menu.review_status = clean_text(row.get("검토상태")) or "정상"
                if not is_replace:
                    db.flush()
                if code:
                    menu_by_code[code] = menu
                counters["menus"] += 1
            db.flush()

            ingredients_by_source: dict[str, Ingredient] = {}
            ingredients_by_name: dict[str, Ingredient] = {}
            for row in reader.sheet_rows("03_재료기준정보"):
                code = clean_text(row.get("재료ID"))
                name = clean_text(row.get("표준재료명"))
                if not name:
                    continue
                ingredient = None
                if is_replace:
                    if code:
                        ingredient = ingredients_by_source.get(code)
                    if not ingredient:
                        ingredient = ingredients_by_name.get(name)
                else:
                    if code:
                        ingredient = db.scalar(select(Ingredient).where(Ingredient.source_code == code))
                    if not ingredient:
                        ingredient = db.scalar(select(Ingredient).where(Ingredient.name == name))
                if not ingredient:
                    ingredient = Ingredient(name=name)
                    db.add(ingredient)
                if is_replace:
                    self._reindex(ingredients_by_source, ingredient, ingredient.source_code, code or ingredient.source_code)
                    self._reindex(ingredients_by_name, ingredient, ingredient.name, name)
                ingredient.source_code = code or ingredient.source_code
                ingredient.name = name
                ingredient.stat_group = clean_text(row.get("통계분석군")) or "기타"
                ingredient.default_unit = clean_text(row.get("기본단위")) or None
                ingredient.kg_factor = clean_float(row.get("kg환산계수"))
                ingredient.analysis_excluded = clean_bool(row.get("분석제외"), False)
                ingredient.active = clean_bool(row.get("사용여부"), True)
                ingredient.review_status = clean_text(row.get("검토상태")) or "정상"
                if not is_replace:
                    db.flush()
                if code:
                    ingredient_by_code[code] = ingredient
                counters["ingredients"] += 1
            db.flush()

            for row in reader.sheet_rows("04_재료별칭_선택"):
                alias_name = clean_text(row.get("원재료별칭"))
                ingredient_code = clean_text(row.get("재료ID"))
                if not alias_name or ingredient_code not in ingredient_by_code:
                    continue
                alias = None if is_replace else db.scalar(select(IngredientAlias).where(IngredientAlias.alias == alias_name))
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
            max_version_by_menu: dict[int, int] = {}

            for menu_id, recipe_groups in grouped_rows.items():
                for composition_key, rows_in_group in recipe_groups.items():
                    recipe = existing_recipes_by_menu.get(menu_id, {}).get(composition_key)
                    if not recipe:
                        if is_replace:
                            max_version = max_version_by_menu.get(menu_id, 0)
                        else:
                            max_version = db.scalar(select(Recipe.version).where(Recipe.menu_id == menu_id).order_by(Recipe.version.desc())) or 0
                        max_version_by_menu[menu_id] = max_version + 1
                        recipe = Recipe(
                            menu_id=menu_id,
                            name=f"기본 레시피 v{max_version + 1}",
                            version=max_version + 1,
                            composition_key=composition_key,
                            is_default=False,
                            active=True,
                        )
                        db.add(recipe)
                        if not is_replace:
                            db.flush()

                    item_by_ingredient_id: dict[int, RecipeIngredient] = {}
                    for row_data in rows_in_group:
                        ingredient: Ingredient = row_data["ingredient"]
                        item = item_by_ingredient_id.get(ingredient.id)
                        if not item and not is_replace:
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
            # 메인 메뉴 bookkeeping (see MAIN_MENU_COLUMN)
            explicit_main_by_service: dict[int, MealServiceMenu | None] = {}  # column present: file's choice per service
            explicit_services: dict[int, MealService] = {}
            fallback_candidate: dict[int, tuple[int, int, MealServiceMenu]] = {}  # column absent: lowest 메뉴순서 주찬
            fallback_services: dict[int, MealService] = {}
            new_service_menu_keys: set[int] = set()
            row_sequence = 0
            # replace mode: (service object identity, sort_order, menu_name) -> MealServiceMenu created this run
            service_menu_by_natural_key: dict[tuple[int, int, str], MealServiceMenu] = {}
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
                    service = None if is_replace else db.scalar(
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
                    if not is_replace:
                        db.flush()
                    service_map[service_key] = service
                    counters["services"] += 1
                menu = menu_by_code.get(menu_code)
                menu_key = (service_date.isoformat(), meal_type, menu_code or menu_name, menu_order)
                service_key_id = id(service) if is_replace else service.id
                service_menu = service_menu_map.get(menu_key)
                if not service_menu:
                    if is_replace:
                        service_menu = service_menu_by_natural_key.get((service_key_id, menu_order, menu_name))
                    else:
                        service_menu = db.scalar(
                            select(MealServiceMenu).where(
                                MealServiceMenu.meal_service_id == service.id,
                                MealServiceMenu.sort_order == menu_order,
                                MealServiceMenu.menu_name_snapshot == menu_name,
                            )
                        )
                created = False
                if not service_menu:
                    created = True
                    source_recipe = default_recipe_by_menu.get(menu.id) if menu else None
                    service_menu = MealServiceMenu(
                        service=service,
                        menu=menu,
                        recipe_id=source_recipe.id if source_recipe else None,
                        sort_order=menu_order,
                        menu_name_snapshot=menu_name,
                        recipe_name_snapshot=source_recipe.name if source_recipe else None,
                        recipe_version_snapshot=source_recipe.version if source_recipe else None,
                        is_representative=False,
                    )
                    db.add(service_menu)
                    if is_replace:
                        service_menu_by_natural_key[(service_key_id, menu_order, menu_name)] = service_menu
                service_menu.note = clean_text(row.get("메뉴비고")) or None
                row_sequence += 1
                if has_main_column:
                    # Explicit Y and explicit N both overwrite the stored value (values were validated above).
                    is_main = parse_main_menu_flag(row.get(MAIN_MENU_COLUMN)) is True
                    service_menu.is_representative = is_main
                    explicit_services[service_key_id] = service
                    if is_main:
                        explicit_main_by_service[service_key_id] = service_menu
                        counters["main_menus"] += 1
                    else:
                        explicit_main_by_service.setdefault(service_key_id, None)
                else:
                    if created:
                        new_service_menu_keys.add(id(service_menu))
                    if id(service_menu) in new_service_menu_keys and menu is not None and menu.role == "주찬":
                        current = fallback_candidate.get(service_key_id)
                        if current is None or (menu_order, row_sequence) < (current[0], current[1]):
                            fallback_candidate[service_key_id] = (menu_order, row_sequence, service_menu)
                        fallback_services[service_key_id] = service
                if not is_replace:
                    db.flush()
                    service_menu_by_id[service_menu.id] = service_menu
                service_menu_map[menu_key] = service_menu
                counters["meal_history_rows"] += 1
            if is_replace:
                # one flush for the whole sheet; IDs are needed from here on
                db.flush()
                for service_menu in service_menu_map.values():
                    service_menu_by_id[service_menu.id] = service_menu
            self._finalize_main_menus(
                db,
                is_replace,
                has_main_column,
                explicit_main_by_service,
                explicit_services,
                fallback_candidate,
                fallback_services,
                counters,
            )

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
                existing = None if is_replace else db.scalar(
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

            if mode == "replace":
                self._restore_service_records(db, preserved_records, service_map, counters)
                # origin/main contract name for the same count (kept alongside actuals_restored).
                counters["actuals_preserved"] = counters["actuals_restored"]

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
    def _validate_main_menu_flags(reader: SimpleXlsxReader) -> list[dict[str, Any]]:
        """Check 메인메뉴여부: only Y/N, and at most one Y per 일자×배식유형. Never picks a row on the user's behalf."""
        errors: list[dict[str, Any]] = []
        sheet = "06_식단이력_이관"
        flags_by_menu: dict[tuple[str, str, str, int], tuple[bool, int]] = {}
        main_rows_by_service: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
        meal_label: dict[str, str] = {}
        for row_number, row in reader.sheet_rows_with_numbers(sheet):
            service_date = excel_serial_to_date(row.get("일자"))
            meal_name = clean_text(row.get("배식유형"))
            meal_type = MEAL_CODE_MAP.get(meal_name, meal_name.upper())
            menu_code = clean_text(row.get("메뉴ID"))
            menu_name = clean_text(row.get("메뉴명"))
            menu_order = clean_int(row.get("메뉴순서")) or 1
            if not service_date or not meal_type or not menu_name:
                continue  # the importer skips these rows as well
            raw = row.get(MAIN_MENU_COLUMN)
            flag = parse_main_menu_flag(raw)
            where = f"{sheet} {row_number}행({service_date.isoformat()} {meal_name} 메뉴순서 {menu_order} {menu_name})"
            if flag is None:
                shown = clean_text(raw) or "빈 값"
                errors.append(
                    {
                        "type": "INVALID_MAIN_MENU_FLAG",
                        "sheet": sheet,
                        "row": row_number,
                        "message": f"{where}: {MAIN_MENU_COLUMN} 값 '{shown}'이(가) 올바르지 않습니다. Y 또는 N만 입력해 주세요.",
                    }
                )
                continue
            menu_key = (service_date.isoformat(), meal_type, menu_code or menu_name, menu_order)
            previous = flags_by_menu.get(menu_key)
            if previous is not None:
                if previous[0] != flag:
                    errors.append(
                        {
                            "type": "CONFLICTING_MAIN_MENU_FLAG",
                            "sheet": sheet,
                            "row": row_number,
                            "message": f"{where}: 같은 메뉴가 {previous[1]}행과 다른 {MAIN_MENU_COLUMN} 값을 가지고 있습니다.",
                        }
                    )
                continue
            flags_by_menu[menu_key] = (flag, row_number)
            if flag:
                main_rows_by_service[(service_date.isoformat(), meal_type)].append((row_number, menu_name))
                meal_label.setdefault(meal_type, meal_name or meal_type)
        for (service_date_iso, meal_type), rows in main_rows_by_service.items():
            meal_name = meal_label.get(meal_type, meal_type)
            if len(rows) > 1:
                listed = ", ".join(f"{row_number}행 {menu_name}" for row_number, menu_name in rows)
                errors.append(
                    {
                        "type": "DUPLICATE_MAIN_MENU",
                        "sheet": sheet,
                        "row": rows[1][0],
                        "message": f"{sheet} {service_date_iso} {meal_name}: {MAIN_MENU_COLUMN}가 Y인 행이 {len(rows)}개입니다({listed}). 한 식단에는 Y를 하나만 지정해 주세요.",
                    }
                )
        errors.sort(key=lambda error: error.get("row", 0))
        if len(errors) > MAIN_MENU_ERROR_LIMIT:
            hidden = len(errors) - MAIN_MENU_ERROR_LIMIT
            errors = errors[:MAIN_MENU_ERROR_LIMIT] + [
                {"type": "MAIN_MENU_FLAG_MORE", "sheet": sheet, "message": f"{MAIN_MENU_COLUMN} 오류가 {hidden}건 더 있습니다."}
            ]
        return errors

    @staticmethod
    def _finalize_main_menus(
        db: Session,
        is_replace: bool,
        has_main_column: bool,
        explicit_main_by_service: dict[int, MealServiceMenu | None],
        explicit_services: dict[int, MealService],
        fallback_candidate: dict[int, tuple[int, int, MealServiceMenu]],
        fallback_services: dict[int, MealService],
        counters: dict[str, int],
    ) -> None:
        """Enforce "at most one 메인 메뉴 per 일자×배식유형" after sheet 06 has been read and flushed.

        Replace mode: every service menu was created from the file, so the in-loop values are already final and
        no queries are issued. Merge mode: service menus that exist in the DB but not in the file are reconciled
        with set-based queries per chunk of services (no per-row queries).
        """
        if has_main_column:
            if is_replace:
                return
            keep_ids = {menu.id for menu in explicit_main_by_service.values() if menu is not None}
            service_ids = [service.id for service in explicit_services.values()]
            for start in range(0, len(service_ids), 500):
                chunk = service_ids[start : start + 500]
                stale = db.scalars(
                    select(MealServiceMenu).where(
                        MealServiceMenu.meal_service_id.in_(chunk),
                        MealServiceMenu.is_representative.is_(True),
                    )
                ).all()
                for item in stale:
                    if item.id not in keep_ids:
                        item.is_representative = False
                        counters["main_menus_cleared"] += 1
            db.flush()
            return

        # Column absent (legacy file): automatic rule — the 주찬 with the lowest 메뉴순서 among menus created by
        # this import, only when the 일자×배식유형 has no 메인 메뉴 yet.
        services_with_main: set[int] = set()
        if not is_replace and fallback_candidate:
            service_ids = [service.id for service in fallback_services.values()]
            for start in range(0, len(service_ids), 500):
                chunk = service_ids[start : start + 500]
                services_with_main.update(
                    db.scalars(
                        select(MealServiceMenu.meal_service_id).where(
                            MealServiceMenu.meal_service_id.in_(chunk),
                            MealServiceMenu.is_representative.is_(True),
                        )
                    ).all()
                )
        for key, (_, _, service_menu) in fallback_candidate.items():
            if not is_replace and fallback_services[key].id in services_with_main:
                continue
            service_menu.is_representative = True
            counters["main_menus"] += 1
        db.flush()

    def _meal_type_setting(self, db: Session, meal_type: str) -> MealTypeSetting | None:
        # Settings are only written in sheet 01 (and flushed) before any service row is read,
        # so caching the lookup per meal type does not change results.
        cache = getattr(self, "_settings_cache", None)
        if cache is None:
            cache = self._settings_cache = {}
        if meal_type not in cache:
            cache[meal_type] = db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == meal_type))
        return cache[meal_type]

    def _default_count(self, db: Session, meal_type: str) -> int:
        setting = self._meal_type_setting(db, meal_type)
        return setting.default_planned_count if setting else 0

    def _default_time(self, db: Session, meal_type: str) -> time | None:
        setting = self._meal_type_setting(db, meal_type)
        return setting.default_service_time if setting else None

    @staticmethod
    def _reindex(index: dict[str, Any], obj: Any, old_key: str | None, new_key: str | None) -> None:
        """Keep a key -> object cache in sync when an object's lookup key changes (mirrors DB lookups)."""
        if old_key and old_key != new_key and index.get(old_key) is obj:
            del index[old_key]
        if new_key and new_key not in index:
            index[new_key] = obj

    _PRESERVED_MODELS = (("actuals", MealActual), ("preservation", PreservationRecord))

    @classmethod
    def _snapshot_service_records(cls, db: Session) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
        """Copy MealActual / PreservationRecord values keyed by (service_date ISO, meal_type).

        Column-level selects are used on purpose so no ORM instances of the soon-to-be-deleted rows
        stay in the session identity map.
        """
        snapshot: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        for label, model in cls._PRESERVED_MODELS:
            columns = [c for c in model.__table__.columns if c.name not in ("id", "meal_service_id")]
            rows = db.execute(
                select(MealService.service_date, MealService.meal_type, *columns).join(
                    MealService, MealService.id == model.meal_service_id
                )
            ).all()
            snapshot[label] = {
                (row[0].isoformat(), row[1]): {column.key: row[index + 2] for index, column in enumerate(columns)}
                for row in rows
            }
        return snapshot

    def _restore_service_records(
        self,
        db: Session,
        snapshot: dict[str, dict[tuple[str, str], dict[str, Any]]],
        service_map: dict[tuple[str, str], MealService],
        counters: dict[str, int],
    ) -> None:
        for label, model in self._PRESERVED_MODELS:
            counter_key = "actuals_restored" if label == "actuals" else "preservation_restored"
            counters[counter_key] += 0
            for (service_date_iso, meal_type), values in snapshot.get(label, {}).items():
                if label == "actuals" and values.get("actual_count") is None and not values.get("note"):
                    # An actual row with neither a count nor a note carries no data; do not resurrect it.
                    continue
                service = service_map.get((service_date_iso, meal_type))
                if service is None:
                    # The new workbook has no menu for this date/meal: keep the record on an empty default service.
                    service = MealService(
                        service_date=datetime.fromisoformat(service_date_iso).date(),
                        meal_type=meal_type,
                        planned_count=self._default_count(db, meal_type),
                        service_time=self._default_time(db, meal_type),
                    )
                    db.add(service)
                    service_map[(service_date_iso, meal_type)] = service
                    counters["services_created_for_restore"] += 1
                db.add(model(service=service, **values))
                counters[counter_key] += 1
        db.flush()

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
