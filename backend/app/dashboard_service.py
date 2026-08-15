from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import MealService, MealServiceMenu
from .statistics_service import MEAL_TYPE_NAMES, meal_statistics, meal_trend
from .stats_service import dashboard_statistics as legacy_dashboard


def _months_back(value: date, months: int) -> date:
    total = value.year * 12 + (value.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def _previous_period(start: date, end: date) -> tuple[date, date]:
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=days - 1), prev_end


def _unique_menu_count(db: Session, start: date, end: date) -> int:
    rows = db.execute(
        select(MealServiceMenu.menu_id, MealServiceMenu.menu_name_snapshot)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .where(MealService.service_date.between(start, end))
    ).all()
    ids = {row[0] for row in rows if row[0] is not None}
    names = {row[1] for row in rows if row[0] is None}
    return len(ids) + len(names)


def _max_in_window(dates: list[date], window_days: int) -> int:
    dates = sorted(set(dates))
    best = 0
    for i in range(len(dates)):
        j = i
        while j < len(dates) and (dates[j] - dates[i]).days <= window_days:
            j += 1
        best = max(best, j - i)
    return best


def _menu_repeats(db: Session, start: date, end: date) -> list[dict[str, Any]]:
    rows = db.execute(
        select(MealService.service_date, MealServiceMenu.menu_id, MealServiceMenu.menu_name_snapshot)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .where(MealService.service_date.between(start, end), MealServiceMenu.menu_id.is_not(None))
    ).all()
    by_menu: dict[int, list[date]] = defaultdict(list)
    names: dict[int, str] = {}
    for service_date, menu_id, menu_name in rows:
        by_menu[menu_id].append(service_date)
        names[menu_id] = menu_name
    repeats: list[dict[str, Any]] = []
    for menu_id, dates in by_menu.items():
        short = _max_in_window(dates, 14)
        long = _max_in_window(dates, 28)
        if short >= 2:
            repeats.append(
                {"menu_id": menu_id, "menu_name": names[menu_id], "type": "단기 반복", "count": short, "window_days": 14}
            )
        if long >= 3:
            repeats.append(
                {"menu_id": menu_id, "menu_name": names[menu_id], "type": "과다 반복", "count": long, "window_days": 28}
            )
    repeats.sort(key=lambda r: r["count"], reverse=True)
    return repeats[:5]


def _record_gaps(db: Session, start: date, end: date) -> list[dict[str, Any]]:
    services = db.scalars(
        select(MealService)
        .where(MealService.service_date.between(start, end))
        .options(selectinload(MealService.actual), selectinload(MealService.preservation))
        .order_by(MealService.service_date, MealService.meal_type)
    ).unique().all()
    gaps: list[dict[str, Any]] = []
    for service in services:
        meal_name = MEAL_TYPE_NAMES.get(service.meal_type, service.meal_type)
        if not (service.actual and service.actual.actual_count is not None):
            gaps.append(
                {"type": "실제 식수 미입력", "date": service.service_date.isoformat(), "meal_type_name": meal_name}
            )
        if not (service.preservation and service.preservation.completed_at):
            gaps.append(
                {"type": "보존식 기록 미완료", "date": service.service_date.isoformat(), "meal_type_name": meal_name}
            )
        if not service.cooking_output_at:
            gaps.append(
                {"type": "조리지시서 미출력", "date": service.service_date.isoformat(), "meal_type_name": meal_name}
            )
    return gaps[:10]


def _ingredient_changes(current: dict[str, Any], previous: dict[str, Any]) -> list[dict[str, Any]]:
    cur_map = {group["group"]: group["estimated_kg"] for group in current["ingredient_groups"]}
    prev_map = {group["group"]: group["estimated_kg"] for group in previous["ingredient_groups"]}
    changes: list[dict[str, Any]] = []
    for group, kg in cur_map.items():
        prev_kg = prev_map.get(group)
        if prev_kg is None or prev_kg <= 0 or kg is None or kg <= 0:
            continue
        rate = (kg - prev_kg) / prev_kg * 100
        if abs(rate) >= 25:
            changes.append(
                {
                    "group": group,
                    "current_kg": round(kg, 1),
                    "previous_kg": round(prev_kg, 1),
                    "rate": round(rate, 1),
                    "level": "중요" if abs(rate) >= 40 else "확인",
                }
            )
    return sorted(changes, key=lambda c: abs(c["rate"]), reverse=True)


def operations_dashboard(db: Session, start: date, end: date, meal_type: str = "all") -> dict[str, Any]:
    meals = meal_statistics(db, start, end, meal_type)
    trend_start = _months_back(end, 11)
    trend = meal_trend(db, trend_start, end, meal_type)
    legacy = legacy_dashboard(db, start, end)
    prev_start, prev_end = _previous_period(start, end)
    prev_legacy = legacy_dashboard(db, prev_start, prev_end)

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "meal_type": meal_type,
        "kpis": {
            "operating_days": meals["summary"]["service_count"],
            "unique_menu_count": _unique_menu_count(db, start, end),
            "lunch": meals["breakdown"].get("lunch"),
            "dinner": meals["breakdown"].get("dinner"),
        },
        "trend": trend["trend"],
        "anomalies": {
            "meal": meals["anomalies"],
            "menu_repeats": _menu_repeats(db, start, end),
            "ingredient_changes": _ingredient_changes(legacy, prev_legacy),
            "record_gaps": _record_gaps(db, start, end),
        },
        "menu_usage": legacy["menu_usage"][:5],
        "repeated_menus": legacy["repeated_menus"][:5],
        "ingredient_groups": legacy["ingredient_groups"][:6],
        "workflow": legacy["workflow"],
    }
