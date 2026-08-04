from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import (
    MealActual,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    Menu,
    Recipe,
    RecipeIngredient,
)

PROTEIN_GROUPS = ["소고기", "돼지고기", "닭·오리", "수산물", "달걀", "두류·두부"]
VEGETABLE_GROUPS = {"채소", "버섯·해조", "과일·견과"}
PROCESSED_GROUPS = {"가공식품", "장류·소스·조미료"}


def _service_query(start: date, end: date):
    return (
        select(MealService)
        .where(MealService.service_date.between(start, end))
        .options(
            selectinload(MealService.menus)
            .selectinload(MealServiceMenu.ingredients)
            .selectinload(MealServiceMenuIngredient.ingredient),
            selectinload(MealService.menus)
            .selectinload(MealServiceMenu.source_recipe)
            .selectinload(Recipe.ingredients)
            .selectinload(RecipeIngredient.ingredient),
            selectinload(MealService.menus).selectinload(MealServiceMenu.menu),
            selectinload(MealService.preservation),
            selectinload(MealService.actual),
        )
        .order_by(MealService.service_date, MealService.meal_type)
    )


def _service_ingredients(service: MealService):
    for menu_item in service.menus:
        if menu_item.ingredients:
            for ingredient in menu_item.ingredients:
                yield ingredient.ingredient, ingredient.quantity_per_100, ingredient.unit, ingredient.ingredient_name_snapshot
        elif menu_item.source_recipe:
            for recipe_item in menu_item.source_recipe.ingredients:
                yield recipe_item.ingredient, recipe_item.quantity_per_100, recipe_item.unit, recipe_item.ingredient.name


def _aggregate(db: Session, start: date, end: date) -> dict[str, Any]:
    services = db.scalars(_service_query(start, end)).unique().all()
    protein_services: Counter[str] = Counter()
    ingredient_group_usage: Counter[str] = Counter()
    ingredient_kg: defaultdict[str, float] = defaultdict(float)
    menu_names: Counter[str] = Counter()
    menu_roles: Counter[str] = Counter()
    lunch_actual: list[tuple[int, int]] = []
    dinner_actual: list[tuple[int, int]] = []

    for service in services:
        service_proteins: set[str] = set()
        for menu_item in service.menus:
            menu_names[menu_item.menu_name_snapshot] += 1
            menu_roles[(menu_item.menu.role if menu_item.menu else "기타")] += 1
        for ingredient, quantity_per_100, unit, _ in _service_ingredients(service):
            if not ingredient or ingredient.analysis_excluded:
                continue
            group = ingredient.stat_group or "기타"
            ingredient_group_usage[group] += 1
            if group in PROTEIN_GROUPS:
                service_proteins.add(group)
            if quantity_per_100 is not None:
                total = quantity_per_100 * service.planned_count / 100
                if unit == "kg":
                    ingredient_kg[group] += total
                elif unit == "g":
                    ingredient_kg[group] += total / 1000
                elif ingredient.kg_factor:
                    ingredient_kg[group] += total * ingredient.kg_factor
        protein_services.update(service_proteins)
        if service.actual and service.actual.actual_count is not None:
            pair = (service.planned_count, service.actual.actual_count)
            (lunch_actual if service.meal_type == "LUNCH" else dinner_actual).append(pair)

    previous_start = start - timedelta(days=28)
    previous_end = start - timedelta(days=1)
    history = db.scalars(
        select(MealServiceMenu)
        .join(MealService)
        .where(MealService.service_date.between(previous_start, previous_end))
        .options(selectinload(MealServiceMenu.service))
        .order_by(MealService.service_date.desc())
    ).all()
    history_count: Counter[str] = Counter(value.menu_name_snapshot for value in history)
    last_date: dict[str, date] = {}
    for value in history:
        last_date.setdefault(value.menu_name_snapshot, value.service.service_date)

    repeats = []
    for menu_name, period_count in menu_names.most_common():
        previous = history_count.get(menu_name, 0)
        if previous or period_count > 1:
            repeats.append(
                {
                    "menu_name": menu_name,
                    "period_count": period_count,
                    "previous_4_weeks": previous,
                    "last_served": last_date.get(menu_name).isoformat() if last_date.get(menu_name) else None,
                }
            )

    def actual_summary(rows: list[tuple[int, int]]) -> dict[str, Any]:
        if not rows:
            return {"records": 0, "planned_average": None, "actual_average": None, "achievement_rate": None}
        planned = sum(row[0] for row in rows)
        actual = sum(row[1] for row in rows)
        return {
            "records": len(rows),
            "planned_average": round(planned / len(rows), 1),
            "actual_average": round(actual / len(rows), 1),
            "achievement_rate": round(actual / planned * 100, 1) if planned else None,
        }

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "service_count": len(services),
        "unique_menu_count": len(menu_names),
        "menu_usage": [{"menu_name": name, "count": count} for name, count in menu_names.most_common(15)],
        "menu_roles": [{"role": role, "count": count} for role, count in menu_roles.most_common()],
        "protein_balance": [{"group": group, "services": protein_services.get(group, 0)} for group in PROTEIN_GROUPS],
        "ingredient_groups": [
            {"group": group, "usage_rows": count, "estimated_kg": round(ingredient_kg.get(group, 0.0), 2)}
            for group, count in ingredient_group_usage.most_common(15)
        ],
        "repeated_menus": repeats[:15],
        "actual_meals": {
            "lunch": actual_summary(lunch_actual),
            "dinner": actual_summary(dinner_actual),
        },
        "workflow": {
            "cooking_output": sum(1 for service in services if service.cooking_output_at),
            "preservation_completed": sum(1 for service in services if service.preservation and service.preservation.completed_at),
            "actual_recorded": sum(1 for service in services if service.actual and service.actual.actual_count is not None),
        },
        "summary": {
            "vegetable_group_rows": sum(ingredient_group_usage.get(group, 0) for group in VEGETABLE_GROUPS),
            "processed_group_rows": sum(ingredient_group_usage.get(group, 0) for group in PROCESSED_GROUPS),
            "unique_menu_count": len(menu_names),
        },
    }


def week_statistics(db: Session, week_start: date) -> dict[str, Any]:
    return _aggregate(db, week_start, week_start + timedelta(days=4))


def dashboard_statistics(db: Session, start_date: date, end_date: date) -> dict[str, Any]:
    return _aggregate(db, start_date, end_date)
