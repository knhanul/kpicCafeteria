"""Simple meal-count analysis (식수 분석).

Everything is expressed in people only: the actual count (실제), the usual count (평소 식수) and the
difference between them (명). No index, score or statistical model.

평소 식수 of a meal = the average actual count of the same meal type on the same weekday during the
52 weeks (1 year) before that date. Only meals that have menu data and an actual count are used, so
closed days (no menu or no actual count) drop out by themselves. The date itself is never included.

Weather is the serving-time weather already stored by the weather upload (weather_meal_period):
temperature = mean of the meal's hourly observations, rain = sum of their precipitation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    Ingredient,
    MealActual,
    MealPeriodWeather,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    Menu,
)
from .weather_import import MEAL_WEATHER_HOURS

MEAL_TYPES = {"LUNCH": "중식", "DINNER": "석식"}
WEEKDAYS = "월화수목금토일"
BASELINE_WEEKS = 52
LOW_SAMPLE_DAYS = 5
HOT_TEMP = 28.0

WEATHER_FILTERS = {
    "all": "전체",
    "rain": "비 오는 날",
    "hot": "더운 날(28℃ 이상)",
    "cold": "추운 날(영하)",
}
RAIN_BANDS = [("rain", "비 옴"), ("dry", "비 안 옴")]
TEMP_BANDS = [
    ("below0", "영하", None, 0.0),
    ("0to10", "0~10℃", 0.0, 10.0),
    ("10to20", "10~20℃", 10.0, 20.0),
    ("20to28", "20~28℃", 20.0, HOT_TEMP),
    ("28plus", "28℃ 이상", HOT_TEMP, None),
]


class AnalysisError(ValueError):
    pass


@dataclass
class MealPoint:
    service_id: int
    service_date: date
    actual: int


def check_meal_type(meal_type: str) -> str:
    if meal_type not in MEAL_TYPES:
        raise AnalysisError("배식은 중식 또는 석식만 선택할 수 있습니다.")
    return meal_type


def check_period(start: date, end: date) -> None:
    if start > end:
        raise AnalysisError("시작일이 종료일보다 늦습니다.")
    if (end - start).days > 366 * 3:
        raise AnalysisError("조회 기간은 3년 이내로 선택해 주세요.")


def weather_window_label(meal_type: str) -> str:
    hours = MEAL_WEATHER_HOURS.get(meal_type) or ()
    if not hours:
        return ""
    return f"{min(hours):02d}:00~{max(hours):02d}:00"


def date_label(value: date) -> str:
    return f"{value.month}/{value.day}({WEEKDAYS[value.weekday()]})"


def _has_menu():
    return exists().where(MealServiceMenu.meal_service_id == MealService.id)


def _counted_meals(db: Session, meal_type: str, start: date, end: date) -> list[MealPoint]:
    """Meals with menu data and an actual count (> 0) in [start, end], oldest first."""
    rows = db.execute(
        select(MealService.id, MealService.service_date, MealActual.actual_count)
        .join(MealActual, MealActual.meal_service_id == MealService.id)
        .where(
            MealService.meal_type == meal_type,
            MealService.service_date >= start,
            MealService.service_date <= end,
            MealActual.actual_count.is_not(None),
            MealActual.actual_count > 0,
            _has_menu(),
        )
        .order_by(MealService.service_date)
    ).all()
    return [MealPoint(row[0], row[1], int(row[2])) for row in rows]


def usual_counts(history: Iterable[MealPoint], targets: Iterable[date]) -> dict[date, tuple[int | None, int]]:
    """평소 식수 per target date: (rounded average, number of days used).

    Uses the same weekday within the previous 52 weeks, never the date itself.
    """
    by_weekday: dict[int, list[MealPoint]] = defaultdict(list)
    for point in history:
        by_weekday[point.service_date.weekday()].append(point)
    result: dict[date, tuple[int | None, int]] = {}
    for target in targets:
        window_start = target - timedelta(weeks=BASELINE_WEEKS)
        values = [p.actual for p in by_weekday.get(target.weekday(), []) if window_start <= p.service_date < target]
        result[target] = (int(sum(values) / len(values) + 0.5) if values else None, len(values))
    return result


def _weather_map(db: Session, meal_type: str, dates: list[date]) -> dict[date, dict[str, Any]]:
    if not dates:
        return {}
    rows = db.scalars(
        select(MealPeriodWeather)
        .where(
            MealPeriodWeather.meal_type == meal_type,
            MealPeriodWeather.observation_date >= min(dates),
            MealPeriodWeather.observation_date <= max(dates),
        )
        .order_by(MealPeriodWeather.observation_date, MealPeriodWeather.sample_count.desc(), MealPeriodWeather.station_id)
    ).all()
    wanted = set(dates)
    window = weather_window_label(meal_type)
    result: dict[date, dict[str, Any]] = {}
    for row in rows:
        # When several stations exist, the one with the most observations in the window wins.
        if row.observation_date not in wanted or row.observation_date in result:
            continue
        if row.avg_temp is None and row.precipitation is None:
            continue
        rain = round(row.precipitation, 1) if row.precipitation is not None else None
        temp = round(row.avg_temp, 1) if row.avg_temp is not None else None
        result[row.observation_date] = {
            "window": window,
            "temp": temp,
            "rain_mm": rain,
            "is_rain": bool(rain and rain > 0),
            "station": row.station_name or row.station_id,
            "text": weather_text(window, rain, temp),
        }
    return result


def weather_text(window: str, rain: float | None, temp: float | None) -> str:
    parts = [window] if window else []
    if rain is not None:
        parts.append(f"비 {_num(rain)}mm" if rain > 0 else "비 안 옴")
    if temp is not None:
        parts.append(f"{_num(temp)}℃")
    return " · ".join(parts)


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def diff_text(diff: int | None) -> str:
    if diff is None:
        return "평소 식수 없음"
    if diff > 0:
        return f"{diff}명 많음"
    if diff < 0:
        return f"{-diff}명 적음"
    return "평소와 같음"


def _build_points(db: Session, meal_type: str, start: date, end: date, only_ids: set[int] | None = None) -> list[dict[str, Any]]:
    history = _counted_meals(db, meal_type, start - timedelta(weeks=BASELINE_WEEKS), end)
    targets = [p for p in history if p.service_date >= start and (only_ids is None or p.service_id in only_ids)]
    usual = usual_counts(history, [p.service_date for p in targets])
    weather = _weather_map(db, meal_type, [p.service_date for p in targets])
    meal_name = MEAL_TYPES[meal_type]
    points = []
    for p in targets:
        usual_value, usual_days = usual[p.service_date]
        diff = p.actual - usual_value if usual_value is not None else None
        w = weather.get(p.service_date)
        sentence = f"{date_label(p.service_date)} {meal_name} · 실제 {p.actual}명 · " + (
            f"평소 {usual_value}명 · {diff_text(diff)}" if usual_value is not None else "평소 식수 없음(지난 1년 같은 요일 기록 없음)"
        )
        points.append({
            "date": p.service_date.isoformat(),
            "label": date_label(p.service_date),
            "weekday": WEEKDAYS[p.service_date.weekday()],
            "service_id": p.service_id,
            "actual": p.actual,
            "usual": usual_value,
            "usual_days": usual_days,
            "diff": diff,
            "diff_text": diff_text(diff),
            "weather": w,
            "sentence": sentence,
        })
    return points


def _apply_weather_filter(points: list[dict[str, Any]], weather_filter: str) -> list[dict[str, Any]]:
    if weather_filter not in WEATHER_FILTERS:
        raise AnalysisError("날씨 조건이 올바르지 않습니다.")
    if weather_filter == "all":
        return points
    def keep(point: dict[str, Any]) -> bool:
        w = point.get("weather")
        if not w:
            return False
        if weather_filter == "rain":
            return bool(w["is_rain"])
        if weather_filter == "hot":
            return w["temp"] is not None and w["temp"] >= HOT_TEMP
        return w["temp"] is not None and w["temp"] < 0
    return [p for p in points if keep(p)]


def _envelope(meal_type: str, start: date, end: date, points: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    with_usual = [p for p in points if p["usual"] is not None]
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weather_window": weather_window_label(meal_type),
        "points": points,
        "days": len(points),
        "avg_actual": _avg([p["actual"] for p in points]),
        "avg_usual": _avg([p["usual"] for p in with_usual]),
        "avg_diff": _avg([p["diff"] for p in with_usual]),
        "low_sample_note": low_sample_note(len(points)),
        **extra,
    }


def _avg(values: list[int]) -> int | None:
    return int(round(sum(values) / len(values))) if values else None


def low_sample_note(days: int) -> str | None:
    if 0 < days < LOW_SAMPLE_DAYS:
        return f"{days}일뿐이라 참고만 하세요."
    return None


def daily(db: Session, meal_type: str, start: date, end: date) -> dict[str, Any]:
    check_meal_type(meal_type)
    check_period(start, end)
    return _envelope(meal_type, start, end, _build_points(db, meal_type, start, end))


def _service_ids_for_menu_group(db: Session, meal_type: str, start: date, end: date, name: str) -> set[int]:
    return set(db.scalars(
        select(MealService.id)
        .join(MealServiceMenu, MealServiceMenu.meal_service_id == MealService.id)
        .join(Menu, Menu.id == MealServiceMenu.menu_id)
        .where(MealService.meal_type == meal_type, MealService.service_date >= start, MealService.service_date <= end, Menu.canonical_name == name)
    ).all())


def _service_ids_for_ingredient(db: Session, meal_type: str, start: date, end: date, ingredient_id: int) -> set[int]:
    return set(db.scalars(
        select(MealService.id)
        .join(MealServiceMenu, MealServiceMenu.meal_service_id == MealService.id)
        .join(MealServiceMenuIngredient, MealServiceMenuIngredient.meal_service_menu_id == MealServiceMenu.id)
        .where(
            MealService.meal_type == meal_type,
            MealService.service_date >= start,
            MealService.service_date <= end,
            MealServiceMenuIngredient.ingredient_id == ingredient_id,
        )
    ).all())


def menu_group(db: Session, meal_type: str, start: date, end: date, name: str, weather_filter: str = "all") -> dict[str, Any]:
    check_meal_type(meal_type)
    check_period(start, end)
    name = (name or "").strip()
    if not name:
        raise AnalysisError("메뉴(통계 집계명)를 선택해 주세요.")
    ids = _service_ids_for_menu_group(db, meal_type, start, end, name)
    points = _apply_weather_filter(_build_points(db, meal_type, start, end, ids), weather_filter)
    return _envelope(meal_type, start, end, points, menu_group=name, weather_filter=weather_filter, weather_filter_name=WEATHER_FILTERS[weather_filter])


def ingredient(db: Session, meal_type: str, start: date, end: date, ingredient_id: int, weather_filter: str = "all") -> dict[str, Any]:
    check_meal_type(meal_type)
    check_period(start, end)
    item = db.get(Ingredient, ingredient_id)
    if not item:
        raise AnalysisError("재료를 찾을 수 없습니다.")
    ids = _service_ids_for_ingredient(db, meal_type, start, end, ingredient_id)
    points = _apply_weather_filter(_build_points(db, meal_type, start, end, ids), weather_filter)
    return _envelope(
        meal_type, start, end, points,
        ingredient={"id": item.id, "name": item.name},
        weather_filter=weather_filter, weather_filter_name=WEATHER_FILTERS[weather_filter],
    )


def temp_band(temp: float | None) -> str | None:
    if temp is None:
        return None
    for key, _label, low, high in TEMP_BANDS:
        if (low is None or temp >= low) and (high is None or temp < high):
            return key
    return None


def weather_bands(db: Session, meal_type: str, start: date, end: date) -> dict[str, Any]:
    check_meal_type(meal_type)
    check_period(start, end)
    points = [p for p in _build_points(db, meal_type, start, end) if p["weather"] and p["usual"] is not None]

    def band(key: str, label: str, members: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "days": len(members),
            "avg_actual": _avg([p["actual"] for p in members]),
            "avg_usual": _avg([p["usual"] for p in members]),
            "avg_diff": _avg([p["diff"] for p in members]),
            "low_sample_note": low_sample_note(len(members)),
            "points": members,
        }

    rain_groups = [
        band("rain", "비 옴", [p for p in points if p["weather"]["rain_mm"] is not None and p["weather"]["is_rain"]]),
        band("dry", "비 안 옴", [p for p in points if p["weather"]["rain_mm"] is not None and not p["weather"]["is_rain"]]),
    ]
    temp_groups = [band(key, label, [p for p in points if temp_band(p["weather"]["temp"]) == key]) for key, label, _low, _high in TEMP_BANDS]
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weather_window": weather_window_label(meal_type),
        "days": len(points),
        "rain": rain_groups,
        "temperature": temp_groups,
    }


def search_menu_groups(db: Session, query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    stmt = (
        select(Menu.canonical_name, func.count(func.distinct(MealServiceMenu.meal_service_id)))
        .join(MealServiceMenu, MealServiceMenu.menu_id == Menu.id)
        .where(Menu.canonical_name != "")
        .group_by(Menu.canonical_name)
    )
    query = (query or "").strip()
    if query:
        stmt = stmt.where(Menu.canonical_name.ilike(f"%{query}%"))
    rows = db.execute(stmt.order_by(func.count(func.distinct(MealServiceMenu.meal_service_id)).desc(), Menu.canonical_name).limit(limit)).all()
    return [{"name": name, "served": int(count)} for name, count in rows]


def search_ingredients(db: Session, query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    stmt = (
        select(Ingredient.id, Ingredient.name, func.count(func.distinct(MealServiceMenu.meal_service_id)))
        .join(MealServiceMenuIngredient, MealServiceMenuIngredient.ingredient_id == Ingredient.id)
        .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
        .group_by(Ingredient.id, Ingredient.name)
    )
    query = (query or "").strip()
    if query:
        stmt = stmt.where(Ingredient.name.ilike(f"%{query}%"))
    rows = db.execute(stmt.order_by(func.count(func.distinct(MealServiceMenu.meal_service_id)).desc(), Ingredient.name).limit(limit)).all()
    return [{"id": item_id, "name": name, "served": int(count)} for item_id, name, count in rows]


def date_detail(db: Session, meal_type: str, service_date: date, ingredient_id: int | None = None) -> dict[str, Any]:
    check_meal_type(meal_type)
    service = db.scalar(
        select(MealService)
        .where(MealService.service_date == service_date, MealService.meal_type == meal_type)
        .options(
            selectinload(MealService.menus).selectinload(MealServiceMenu.ingredients),
            selectinload(MealService.menus).selectinload(MealServiceMenu.source_recipe),
            selectinload(MealService.actual),
        )
    )
    if not service:
        raise AnalysisError("해당 날짜의 식단이 없습니다.")
    history = _counted_meals(db, meal_type, service_date - timedelta(weeks=BASELINE_WEEKS), service_date - timedelta(days=1))
    usual_value, usual_days = usual_counts(history, [service_date])[service_date]
    actual = service.actual.actual_count if service.actual and service.actual.actual_count else None
    diff = actual - usual_value if actual is not None and usual_value is not None else None
    menus = []
    for item in sorted(service.menus, key=lambda m: (m.sort_order, m.id)):
        ingredients = sorted(item.ingredients, key=lambda i: (i.sort_order, i.id))
        recipe_name = item.recipe_name_snapshot or (item.source_recipe.name if item.source_recipe else None)
        menus.append({
            "id": item.id,
            "order": item.sort_order,
            "name": item.menu_name_snapshot,
            "is_main": bool(item.is_representative),
            "recipe_name": recipe_name,
            "has_ingredient": ingredient_id is not None and any(i.ingredient_id == ingredient_id for i in ingredients),
            "ingredients": [
                {
                    "name": i.ingredient_name_snapshot,
                    "quantity": i.quantity_total,
                    "unit": i.unit,
                    "highlight": ingredient_id is not None and i.ingredient_id == ingredient_id,
                }
                for i in ingredients
            ],
        })
    weather = _weather_map(db, meal_type, [service_date]).get(service_date)
    return {
        "date": service_date.isoformat(),
        "label": date_label(service_date),
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "service_id": service.id,
        "actual": actual,
        "usual": usual_value,
        "usual_days": usual_days,
        "diff": diff,
        "diff_text": diff_text(diff) if actual is not None else "실제 식수 없음",
        "weather": weather,
        "weather_window": weather_window_label(meal_type),
        "menus": menus,
    }
