from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Ingredient, MealActual, MealService, MealServiceMenu, MealServiceMenuIngredient

WEEKDAY_NAMES = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
MEAL_TYPE_NAMES = {"LUNCH": "중식", "DINNER": "석식"}


def _meal_type_code(meal_type: str) -> str | None:
    return {"lunch": "LUNCH", "dinner": "DINNER"}.get(meal_type)


def _usage_rows(
    db: Session, start: date, end: date, meal_type: str = "all", ingredient_id: int | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(
            MealService.id,
            MealServiceMenuIngredient.meal_service_menu_id,
            MealService.service_date,
            MealService.meal_type,
            MealService.planned_count,
            MealActual.actual_count,
            MealServiceMenuIngredient.ingredient_id,
            MealServiceMenuIngredient.ingredient_name_snapshot,
            MealServiceMenuIngredient.quantity_total,
            MealServiceMenuIngredient.quantity_per_100,
            MealServiceMenuIngredient.unit,
            Ingredient.stat_group,
            MealServiceMenu.menu_name_snapshot,
            Ingredient.kg_factor,
            Ingredient.analysis_excluded,
        )
        .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .outerjoin(MealActual, MealActual.meal_service_id == MealService.id)
        .outerjoin(Ingredient, Ingredient.id == MealServiceMenuIngredient.ingredient_id)
        .where(MealService.service_date.between(start, end))
        .order_by(MealService.service_date, MealService.meal_type, MealServiceMenuIngredient.sort_order)
    )
    if ingredient_id is not None:
        stmt = stmt.where(MealServiceMenuIngredient.ingredient_id == ingredient_id)
    else:
        code = _meal_type_code(meal_type)
        if code:
            stmt = stmt.where(MealService.meal_type == code)
    rows = db.execute(stmt).all()
    result = []
    for row in rows:
        if row[14]:
            continue
        quantity = row[8]
        if quantity is None and row[9] is not None and row[4]:
            quantity = row[9] * row[4] / 100
        unit = (row[10] or "").strip()
        normalized_unit = unit.lower()
        quantity_kg = None
        if quantity is not None:
            if normalized_unit == "kg":
                quantity_kg = quantity
            elif normalized_unit == "g":
                quantity_kg = quantity / 1000
            elif row[13]:
                quantity_kg = quantity * row[13]
        result.append(
            {
                "service_id": row[0],
                "service_menu_id": row[1],
                "date": row[2],
                "meal_type": row[3],
                "meal_type_name": MEAL_TYPE_NAMES.get(row[3], row[3]),
                "planned_count": row[4],
                "actual_count": row[5],
                "ingredient_id": row[6],
                "ingredient_name": row[7],
                "quantity_total": quantity,
                "quantity_kg": quantity_kg,
                "quantity_g": quantity_kg * 1000 if quantity_kg is not None else None,
                "unit": unit or None,
                "stat_group": row[11] or "기타",
                "menu_name": row[12],
            }
        )
    return result


def _ingredient_key(row: dict[str, Any]) -> str:
    return str(row["ingredient_id"]) if row["ingredient_id"] is not None else f"name:{row['ingredient_name']}"


def _max_in_window(dates: list[date], window_days: int) -> int:
    dates = sorted(set(dates))
    best = 0
    for i in range(len(dates)):
        j = i
        while j < len(dates) and (dates[j] - dates[i]).days <= window_days:
            j += 1
        best = max(best, j - i)
    return best


def _unused_ingredients(db: Session, end: date, unused_days: int) -> list[dict[str, Any]]:
    cutoff = end - timedelta(days=unused_days)
    ingredients = db.scalars(select(Ingredient).where(Ingredient.active.is_(True))).all()
    ids = [ingredient.id for ingredient in ingredients]
    used_in_window: set[int] = set()
    last_dates: dict[int, date] = {}
    if ids:
        used_in_window = set(
            db.scalars(
                select(MealServiceMenuIngredient.ingredient_id)
                .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
                .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
                .where(
                    MealService.service_date.between(cutoff, end),
                    MealServiceMenuIngredient.ingredient_id.is_not(None),
                )
            ).all()
        )
        history = db.execute(
            select(MealServiceMenuIngredient.ingredient_id, MealService.service_date)
            .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
            .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
            .where(MealServiceMenuIngredient.ingredient_id.in_(ids), MealService.service_date < cutoff)
            .order_by(MealService.service_date)
        ).all()
        for ingredient_id, service_date in history:
            last_dates[ingredient_id] = service_date
    result = []
    for ingredient in ingredients:
        if ingredient.id in used_in_window:
            continue
        last = last_dates.get(ingredient.id)
        result.append(
            {
                "ingredient_id": ingredient.id,
                "ingredient_name": ingredient.name,
                "stat_group": ingredient.stat_group,
                "last_used": last.isoformat() if last else None,
                "days_since_last": (end - last).days if last else None,
            }
        )
    result.sort(key=lambda x: x["days_since_last"] if x["days_since_last"] is not None else 10**9, reverse=True)
    return result


def ingredient_statistics(
    db: Session, start: date, end: date, meal_type: str = "all", unused_days: int = 90
) -> dict[str, Any]:
    rows = _usage_rows(db, start, end, meal_type)
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _ingredient_key(row)
        group = groups.setdefault(
            key,
            {
                "key": key,
                "ingredient_id": row["ingredient_id"],
                "ingredient_name": row["ingredient_name"],
                "stat_group": row["stat_group"],
                "dates": [],
                "lunch": 0,
                "dinner": 0,
                "quantity_kg": 0.0,
                "converted_count": 0,
                "unit_totals": defaultdict(float),
                "rows": [],
            },
        )
        group["dates"].append(row["date"])
        if row["meal_type"] == "LUNCH":
            group["lunch"] += 1
        else:
            group["dinner"] += 1
        if row["quantity_kg"] is not None:
            group["quantity_kg"] += row["quantity_kg"]
            group["converted_count"] += 1
        elif row["quantity_total"] is not None and row["unit"]:
            group["unit_totals"][row["unit"]] += row["quantity_total"]
        group["rows"].append(row)

    used_ids = {group["ingredient_id"] for group in groups.values() if group["ingredient_id"] is not None}
    prev_ids: set[int] = set()
    if used_ids:
        prev_ids = set(
            db.scalars(
                select(MealServiceMenuIngredient.ingredient_id)
                .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
                .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
                .where(MealService.service_date < start, MealServiceMenuIngredient.ingredient_id.in_(used_ids))
            ).all()
        )

    top: list[dict[str, Any]] = []
    new_count = 0
    for group in groups.values():
        dates = sorted(set(group["dates"]))
        group["usage_count"] = len(group["rows"])
        group["first_used"] = dates[0].isoformat()
        group["last_used"] = dates[-1].isoformat()
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        group["avg_interval"] = round(sum(gaps) / len(gaps), 1) if gaps else None
        if group["ingredient_id"] is not None and group["ingredient_id"] not in prev_ids:
            new_count += 1
        top.append(group)
    top.sort(key=lambda g: g["usage_count"], reverse=True)

    backdata: list[dict[str, Any]] = []
    for group in groups.values():
        group["rows"].sort(key=lambda r: (r["date"], r["meal_type"]))
        prev_date: date | None = None
        for row in group["rows"]:
            backdata.append(
                {
                    "date": row["date"].isoformat(),
                    "weekday": WEEKDAY_NAMES[row["date"].weekday()],
                    "meal_type_name": row["meal_type_name"],
                    "ingredient_name": row["ingredient_name"],
                    "ingredient_id": row["ingredient_id"],
                    "quantity_kg": row["quantity_kg"],
                    "quantity_total": row["quantity_total"],
                    "unit": row["unit"],
                    "quantity_g": row["quantity_g"],
                    "planned_count": row["planned_count"],
                    "actual_count": row["actual_count"],
                    "previous_used_date": prev_date.isoformat() if prev_date else None,
                    "days_since_previous": (row["date"] - prev_date).days if prev_date else None,
                }
            )
            prev_date = row["date"]

    unused = _unused_ingredients(db, end, unused_days)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "meal_type": meal_type,
        "unused_days": unused_days,
        "summary": {
            "unique_ingredient_count": len(groups),
            "total_usage_count": len(rows),
            "new_ingredient_count": new_count,
            "unused_ingredient_count": len(unused),
        },
        "top_ingredients": [
            {
                "ingredient_id": group["ingredient_id"],
                "ingredient_name": group["ingredient_name"],
                "stat_group": group["stat_group"],
                "usage_count": group["usage_count"],
                "quantity_kg": round(group["quantity_kg"], 3) if group["converted_count"] else None,
                "quantity_g": round(group["quantity_kg"] * 1000, 1) if group["converted_count"] else None,
                "unconverted_amounts": {unit: round(value, 3) for unit, value in sorted(group["unit_totals"].items())},
                "lunch_count": group["lunch"],
                "dinner_count": group["dinner"],
                "first_used": group["first_used"],
                "last_used": group["last_used"],
                "avg_interval": group["avg_interval"],
            }
            for group in top[:15]
        ],
        "unused_ingredients": unused,
        "backdata": backdata,
    }


def ingredient_detail(
    db: Session, ingredient_id: int, start: date, end: date, meal_type: str = "all"
) -> dict[str, Any] | None:
    rows = _usage_rows(db, start, end, meal_type, ingredient_id=ingredient_id)
    ingredient = db.get(Ingredient, ingredient_id)
    if not rows:
        if not ingredient:
            return None
        return {
            "ingredient_id": ingredient_id,
            "ingredient_name": ingredient.name,
            "stat_group": ingredient.stat_group,
            "summary": {
                "usage_count": 0,
                "lunch_count": 0,
                "dinner_count": 0,
                "quantity_kg": None,
                "quantity_g": None,
                "unconverted_amounts": {},
                "first_used": None,
                "last_used": None,
                "avg_interval": None,
            },
            "monthly_usage": [],
            "recent_history": [],
            "co_used": [],
            "backdata": [],
        }
    rows.sort(key=lambda r: (r["date"], r["meal_type"]))
    dates = sorted({row["date"] for row in rows})
    lunch = sum(1 for row in rows if row["meal_type"] == "LUNCH")
    dinner = len(rows) - lunch
    converted_rows = [row for row in rows if row["quantity_kg"] is not None]
    total_quantity_kg = sum(row["quantity_kg"] for row in converted_rows)
    unit_totals: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        if row["quantity_kg"] is None and row["quantity_total"] is not None and row["unit"]:
            unit_totals[row["unit"]] += row["quantity_total"]
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    monthly: Counter[str] = Counter()
    for row in rows:
        monthly[row["date"].strftime("%Y-%m")] += 1

    service_menu_ids = list({row["service_menu_id"] for row in rows})
    co_rows = db.execute(
        select(MealServiceMenuIngredient.ingredient_id, MealServiceMenuIngredient.ingredient_name_snapshot)
        .where(
            MealServiceMenuIngredient.meal_service_menu_id.in_(service_menu_ids),
            MealServiceMenuIngredient.ingredient_id != ingredient_id,
        )
    ).all()
    co_count: Counter[str] = Counter()
    co_names: dict[str, str] = {}
    for iid, name in co_rows:
        key = str(iid) if iid is not None else f"name:{name}"
        co_count[key] += 1
        co_names[key] = name
    co_used = [
        {"ingredient_id": int(key) if key.isdigit() else None, "ingredient_name": co_names[key], "count": count}
        for key, count in co_count.most_common(10)
    ]

    full_dates = db.scalars(
        select(MealService.service_date)
        .select_from(MealServiceMenuIngredient)
        .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .where(MealServiceMenuIngredient.ingredient_id == ingredient_id, MealService.service_date <= end)
        .order_by(MealService.service_date)
    ).all()
    backdata: list[dict[str, Any]] = []
    history_index = 0
    for row in rows:
        while history_index < len(full_dates) and full_dates[history_index] < row["date"]:
            history_index += 1
        prev_date = full_dates[history_index - 1] if history_index > 0 else None
        backdata.append(
            {
                "date": row["date"].isoformat(),
                "weekday": WEEKDAY_NAMES[row["date"].weekday()],
                "meal_type_name": row["meal_type_name"],
                "ingredient_name": row["ingredient_name"],
                "ingredient_id": row["ingredient_id"],
                "quantity_g": row["quantity_g"],
                "planned_count": row["planned_count"],
                "actual_count": row["actual_count"],
                "previous_used_date": prev_date.isoformat() if prev_date else None,
                "days_since_previous": (row["date"] - prev_date).days if prev_date else None,
            }
        )

    return {
        "ingredient_id": ingredient_id,
        "ingredient_name": rows[0]["ingredient_name"],
        "stat_group": rows[0]["stat_group"],
        "summary": {
            "usage_count": len(rows),
            "lunch_count": lunch,
            "dinner_count": dinner,
            "quantity_kg": round(total_quantity_kg, 3) if converted_rows else None,
            "quantity_g": round(total_quantity_kg * 1000, 1) if converted_rows else None,
            "unconverted_amounts": {unit: round(value, 3) for unit, value in sorted(unit_totals.items())},
            "first_used": dates[0].isoformat(),
            "last_used": dates[-1].isoformat(),
            "avg_interval": round(sum(gaps) / len(gaps), 1) if gaps else None,
        },
        "monthly_usage": [{"month": month, "count": count} for month, count in sorted(monthly.items())],
        "recent_history": [
            {
                "date": row["date"].isoformat(),
                "meal_type_name": row["meal_type_name"],
                "menu_name": row["menu_name"],
                "quantity_kg": row["quantity_kg"],
                "quantity_total": row["quantity_total"],
                "unit": row["unit"],
                "quantity_g": row["quantity_g"],
                "actual_count": row["actual_count"],
            }
            for row in rows[-20:]
        ],
        "co_used": co_used,
        "backdata": backdata,
    }
