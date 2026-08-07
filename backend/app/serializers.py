from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from .models import MealService, MealServiceMenu

MEAL_NAMES = {"LUNCH": "중식", "DINNER": "석식"}
MEAL_SORT = {"LUNCH": 1, "DINNER": 2}


def iso(value: date | datetime | time | None) -> str | None:
    return value.isoformat() if value else None


def ingredient_snapshot_dict(item) -> dict[str, Any]:
    ingredient = item.ingredient
    return {
        "id": item.id,
        "ingredient_id": item.ingredient_id,
        "name": item.ingredient_name_snapshot,
        "stat_group": ingredient.stat_group if ingredient else "기타",
        "quantity_total": item.quantity_total,
        "quantity_per_100": item.quantity_per_100,
        "unit": item.unit,
        "source_note": item.source_note,
    }


def service_menu_dict(item: MealServiceMenu, include_ingredients: bool = True) -> dict[str, Any]:
    payload = {
        "id": item.id,
        "menu_id": item.menu_id,
        "recipe_id": item.recipe_id,
        "recipe_name": item.recipe_name_snapshot or (item.source_recipe.name if item.source_recipe else None),
        "recipe_version": item.recipe_version_snapshot or (item.source_recipe.version if item.source_recipe else None),
        "name": item.menu_name_snapshot,
        "sort_order": item.sort_order,
        "note": item.note or "",
        "is_representative": item.is_representative,
        "cooking_instruction": item.cooking_instruction or "",
        "cooking_note": item.cooking_note or "",
    }
    if include_ingredients:
        payload["ingredients"] = [ingredient_snapshot_dict(value) for value in item.ingredients]
    return payload


def meal_service_dict(service: MealService, detail: bool = True) -> dict[str, Any]:
    preservation = service.preservation
    actual = service.actual
    return {
        "id": service.id,
        "service_date": service.service_date.isoformat(),
        "meal_type": service.meal_type,
        "meal_type_name": MEAL_NAMES.get(service.meal_type, service.meal_type),
        "planned_count": service.planned_count,
        "service_time": iso(service.service_time),
        "concept_title": service.concept_title,
        "note": service.note or "",
        "menus": [service_menu_dict(menu, detail) for menu in service.menus],
        "menu_count": len(service.menus),
        "cooking_output": service.cooking_output_at is not None,
        "cooking_output_at": iso(service.cooking_output_at),
        "preservation_completed": bool(preservation and preservation.completed_at),
        "actual_recorded": bool(actual and actual.actual_count is not None),
        "actual_count": actual.actual_count if actual else None,
        "updated_at": iso(service.updated_at),
    }
