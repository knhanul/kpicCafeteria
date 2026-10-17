"""Simple meal-count analysis (식수 분석).

Everything is expressed in people only: the actual count (실제), the usual count (평소 식수) and the
difference between them (명). No index, score or statistical model.

평소 식수 of a meal = the average actual count of the same meal type (any weekday) during the
364 days (1 year) before that date. Only meals that have menu data and an actual count are used, so
closed days (no menu or no actual count) drop out by themselves. The date itself is never included.

Weather is the serving-time weather already stored by the weather upload (weather_meal_period):
temperature = mean of the meal's hourly observations, rain = sum of their precipitation.
"""
from __future__ import annotations

from bisect import bisect_left
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
# 요일별 통계에서만 빼는 평일 관공서 공휴일(대체공휴일·임시공휴일 포함).
# 주말은 요일 자체로 빠지므로 여기 넣지 않는다. 제헌절은 2026년부터 공휴일.
WEEKDAY_PUBLIC_HOLIDAYS = frozenset({
    date(2024, 1, 1), date(2024, 2, 9), date(2024, 2, 12), date(2024, 5, 6), date(2024, 5, 15),
    date(2024, 6, 6), date(2024, 8, 15), date(2024, 9, 16), date(2024, 9, 17), date(2024, 9, 18),
    date(2024, 10, 3), date(2024, 10, 9), date(2024, 12, 25),
    date(2025, 1, 1), date(2025, 1, 27), date(2025, 1, 28), date(2025, 1, 29), date(2025, 1, 30),
    date(2025, 3, 3), date(2025, 5, 5), date(2025, 5, 6), date(2025, 6, 6), date(2025, 8, 15),
    date(2025, 10, 3), date(2025, 10, 6), date(2025, 10, 7), date(2025, 10, 8), date(2025, 10, 9),
    date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18), date(2026, 3, 2),
    date(2026, 5, 1), date(2026, 5, 5), date(2026, 5, 25), date(2026, 6, 3), date(2026, 7, 17),
    date(2026, 8, 17), date(2026, 9, 24), date(2026, 9, 25), date(2026, 10, 5), date(2026, 10, 9),
    date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 3, 1), date(2027, 5, 5),
})
BASELINE_WEEKS = 52  # 364 days before the date
LOW_SAMPLE_DAYS = 5
HOT_TEMP = 28.0

WEATHER_FILTERS = {
    "all": "전체",
    "rain": "비 오는 날",
    "hot": "더운 날(28℃ 이상)",
    "cold": "추운 날(영하)",
}
RAIN_BANDS = [("rain", "강수 있음"), ("dry", "강수 없음")]
SNOW_BANDS = [("snow", "적설 있음"), ("clear", "적설 없음")]
# 보통 기온은 10℃ 단위. 더위(28℃부터)와 추위(영하)만 정도별로 나눈다. 배식시간 평균기온 기준.
TEMP_BANDS = [
    ("lt-10", "매우 추움 · 영하 10℃ 미만", None, -10.0),
    ("m10tom5", "많이 추움 · 영하 10~5℃", -10.0, -5.0),
    ("m5to0", "조금 추움 · 영하 5~0℃", -5.0, 0.0),
    ("0to10", "0~10℃", 0.0, 10.0),
    ("10to20", "10~20℃", 10.0, 20.0),
    ("20to28", "20~28℃", 20.0, HOT_TEMP),
    ("28to32", "조금 더움 · 28~32℃", HOT_TEMP, 32.0),
    ("32to35", "많이 더움 · 32~35℃", 32.0, 35.0),
    ("35plus", "매우 더움 · 35℃ 이상", 35.0, None),
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


def earliest_counted_date(db: Session, meal_type: str | None = None) -> date | None:
    """The earliest service_date with actual meal count recorded in the system."""
    stmt = (
        select(func.min(MealService.service_date))
        .join(MealActual, MealActual.meal_service_id == MealService.id)
        .where(
            MealActual.actual_count.is_not(None),
            MealActual.actual_count > 0,
        )
    )
    if meal_type:
        val = db.scalar(stmt.where(MealService.meal_type == meal_type))
        if val is not None:
            return val
    val = db.scalar(stmt)
    if val is not None:
        return val
    return db.scalar(select(func.min(MealService.service_date)))


def usual_counts(history: Iterable[MealPoint], targets: Iterable[date]) -> dict[date, tuple[int | None, int]]:
    """평소 식수 per target date: (rounded average, number of days used).

    Average of all counted meals (same meal type, any weekday) in the 364 days before the date,
    never the date itself.
    """
    points = sorted(history, key=lambda p: p.service_date)
    dates = [p.service_date for p in points]
    prefix = [0]
    for point in points:
        prefix.append(prefix[-1] + point.actual)
    result: dict[date, tuple[int | None, int]] = {}
    for target in targets:
        lo = bisect_left(dates, target - timedelta(weeks=BASELINE_WEEKS))
        hi = bisect_left(dates, target)
        count = hi - lo
        result[target] = (int((prefix[hi] - prefix[lo]) / count + 0.5) if count else None, count)
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
        snow = round(row.snow_depth, 1) if row.snow_depth is not None else None
        result[row.observation_date] = {
            "window": window,
            "temp": temp,
            "rain_mm": rain,
            "is_rain": bool(rain and rain > 0),
            "snow_cm": snow,
            "has_snow": bool(snow and snow > 0),
            "station": row.station_name or row.station_id,
            "text": weather_text(window, rain, temp, snow),
        }
    return result


def weather_text(window: str, rain: float | None, temp: float | None, snow: float | None = None) -> str:
    parts = [window] if window else []
    if rain is not None:
        parts.append(f"강수 {_num(rain)}mm" if rain > 0 else "강수 없음")
    if temp is not None:
        parts.append(f"{_num(temp)}℃")
    if snow is not None and snow > 0:
        parts.append(f"적설 {_num(snow)}cm")
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
            f"평소 {usual_value}명 · {diff_text(diff)}" if usual_value is not None else "평소 식수 없음(지난 1년 기록 없음)"
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
        raise AnalysisError("메뉴(대표 메뉴명)를 선택해 주세요.")
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
        band(key, label, [p for p in points if p["weather"]["rain_mm"] is not None and (p["weather"]["is_rain"] if key == "rain" else not p["weather"]["is_rain"])])
        for key, label in RAIN_BANDS
    ]
    temp_groups = [band(key, label, [p for p in points if temp_band(p["weather"]["temp"]) == key]) for key, label, _low, _high in TEMP_BANDS]
    known_snow = [p for p in points if p["weather"].get("snow_cm") is not None]
    snow_groups = [
        band(key, label, [p for p in known_snow if p["weather"]["has_snow"] == (key == "snow")])
        for key, label in SNOW_BANDS
    ]
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weather_window": weather_window_label(meal_type),
        "days": len(points),
        "rain": rain_groups,
        "temperature": temp_groups,
        "snow": snow_groups,
    }


def _stat_group(key: str, label: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    with_usual = [p for p in members if p["usual"] is not None]
    return {
        "key": key,
        "label": label,
        "days": len(members),
        "avg_actual": _avg([p["actual"] for p in members]),
        "avg_usual": _avg([p["usual"] for p in with_usual]),
        "avg_diff": _avg([p["diff"] for p in with_usual]),
        "low_sample_note": low_sample_note(len(members)),
        "points": members,
    }


def _grouped_stats(meal_type: str, start: date, end: date, points: list[dict[str, Any]], groups: list[dict[str, Any]]) -> dict[str, Any]:
    with_usual = [p for p in points if p["usual"] is not None]
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": len(points),
        "avg_actual": _avg([p["actual"] for p in points]),
        "avg_usual": _avg([p["usual"] for p in with_usual]),
        "avg_diff": _avg([p["diff"] for p in with_usual]),
        "groups": groups,
    }


def weekday_stats(db: Session, meal_type: str, start: date, end: date) -> dict[str, Any]:
    """요일별 식수: 월~금만.

    토요일·일요일과 평일 공휴일은 식수 합(분자)과 일수(분모)에서 모두 뺀다.
    공휴일에 실제 식수가 있어도 넣지 않고, 식수가 없는 날을 0명으로 세지도 않는다.
    """
    check_meal_type(meal_type)
    check_period(start, end)
    points = _build_points(db, meal_type, start, end)
    kept: list[dict[str, Any]] = []
    excluded_weekend = 0
    excluded_holiday = 0
    for point in points:
        day = date.fromisoformat(point["date"])
        if day.weekday() >= 5:
            excluded_weekend += 1
            continue
        if day in WEEKDAY_PUBLIC_HOLIDAYS:
            excluded_holiday += 1
            continue
        kept.append(point)
    by_day: dict[int, list[dict[str, Any]]] = {i: [] for i in range(5)}
    for point in kept:
        by_day[date.fromisoformat(point["date"]).weekday()].append(point)
    groups = [_stat_group(str(i), WEEKDAYS[i], by_day[i]) for i in range(5)]
    result = _grouped_stats(meal_type, start, end, kept, groups)
    result["excluded_weekend_days"] = excluded_weekend
    result["excluded_holidays"] = excluded_holiday
    return result


def _month_service_counts(db: Session, meal_type: str, start: date, end: date) -> dict[str, tuple[int, int]]:
    """각 달의 (편성된 식단 수, 실식수가 입력된 식단 수).

    편성은 메뉴가 있는 배식. 실식수 입력은 그 중 실제 식수가 0보다 큰 배식이다. 0은 입력으로 세지 않는다.
    """
    rows = db.execute(
        select(MealService.service_date, MealActual.actual_count)
        .outerjoin(MealActual, MealActual.meal_service_id == MealService.id)
        .where(
            MealService.meal_type == meal_type,
            MealService.service_date >= start,
            MealService.service_date <= end,
            _has_menu(),
        )
    ).all()
    planned: dict[str, int] = defaultdict(int)
    entered: dict[str, int] = defaultdict(int)
    for service_date, actual in rows:
        key = f"{service_date.year:04d}-{service_date.month:02d}"
        planned[key] += 1
        if actual is not None and actual > 0:
            entered[key] += 1
    return {key: (planned[key], entered[key]) for key in planned}


def monthly_stats(db: Session, meal_type: str, start: date, end: date) -> dict[str, Any]:
    """월별 식수: 기간 안의 모든 달을 순서대로(배식이 없던 달은 0일).

    공휴일은 따로 빼지 않는다. 실식수가 있는 식단만 평균에 들어가므로 배식하지 않은 날은 빠진다.
    """
    check_meal_type(meal_type)
    check_period(start, end)
    points = _build_points(db, meal_type, start, end)
    coverage = _month_service_counts(db, meal_type, start, end)
    by_month: dict[str, list[dict[str, Any]]] = {}
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        by_month[f"{year:04d}-{month:02d}"] = []
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    for point in points:
        by_month.setdefault(point["date"][:7], []).append(point)
    groups = []
    for key, members in by_month.items():
        group = _stat_group(key, f"{int(key[:4])}년 {int(key[5:])}월", members)
        planned, entered = coverage.get(key, (0, 0))
        group["planned_count"] = planned
        group["entered_count"] = entered
        groups.append(group)
    return _grouped_stats(meal_type, start, end, points, groups)


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


def date_detail(
    db: Session, meal_type: str, service_date: date, ingredient_id: int | None = None, ingredient_ids: set[int] | None = None,
) -> dict[str, Any]:
    check_meal_type(meal_type)
    wanted_ids = set(ingredient_ids or set())
    if ingredient_id is not None:
        wanted_ids.add(ingredient_id)
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
            "has_ingredient": any(i.ingredient_id in wanted_ids for i in ingredients),
            "ingredients": [
                {
                    "name": i.ingredient_name_snapshot,
                    "quantity": i.quantity_total,
                    "unit": i.unit,
                    "highlight": i.ingredient_id in wanted_ids,
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


# ---------------------------------------------------------------------------
# 인기 메뉴 / 메뉴 이름·대표 메뉴명 조회 / 여러 메뉴 비교
# ---------------------------------------------------------------------------
MENU_MODES = {"name": "메뉴 이름", "group": "대표 메뉴명"}
DEFAULT_MIN_DAYS = {"LUNCH": 1, "DINNER": 1}
# 메뉴 범위. 역할(role)은 식단 줄에 따로 저장되지 않아 메뉴 기준정보(Menu.role)를 씁니다.
MENU_SCOPES = {"main_dish": "주찬만", "main_menu": "메인 메뉴만", "with_side": "부찬 포함", "all": "전체"}
SCOPE_ROLES = {"main_dish": ("주찬",), "with_side": ("주찬", "부찬")}
MAIN_MENU_MIN_DAYS = {"LUNCH": 1, "DINNER": 1}


def check_menu_scope(scope: str) -> str:
    if scope not in MENU_SCOPES:
        raise AnalysisError("메뉴 범위는 주찬만, 메인 메뉴만, 부찬 포함, 전체 중에서 골라 주세요.")
    return scope


def default_min_days(meal_type: str, scope: str = "all") -> int:
    return (MAIN_MENU_MIN_DAYS if scope == "main_menu" else DEFAULT_MIN_DAYS)[meal_type]


def _scope_conditions(scope: str) -> list:
    check_menu_scope(scope)
    if scope == "main_menu":
        return [MealServiceMenu.is_representative.is_(True)]
    if scope in SCOPE_ROLES:
        return [Menu.role.in_(SCOPE_ROLES[scope])]
    return []
MAX_COMPARE_ITEMS = 5


def check_menu_mode(mode: str) -> str:
    if mode not in MENU_MODES:
        raise AnalysisError("조회 기준은 메뉴 이름 또는 대표 메뉴명만 선택할 수 있습니다.")
    return mode


def _menu_key_column(mode: str):
    return Menu.name if mode == "name" else Menu.canonical_name


def _service_menu_keys(
    db: Session, meal_type: str, start: date, end: date, mode: str,
    keys: list[str] | None = None, main_only: bool = False, scope: str = "all",
) -> dict[str, set[int]]:
    """{menu key: set of meal_service ids} for meals in the period (one key counted once per meal)."""
    column = _menu_key_column(mode)
    stmt = (
        select(column, MealService.id)
        .join(MealServiceMenu, MealServiceMenu.menu_id == Menu.id)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .where(MealService.meal_type == meal_type, MealService.service_date >= start, MealService.service_date <= end, column != "")
        .distinct()
    )
    if keys is not None:
        stmt = stmt.where(column.in_(keys))
    if main_only:
        scope = "main_menu"
    conditions = _scope_conditions(scope)
    if conditions:
        stmt = stmt.where(*conditions)
    result: dict[str, set[int]] = defaultdict(set)
    for key, service_id in db.execute(stmt).all():
        result[key].add(service_id)
    return result


def popular_menus(
    db: Session, meal_type: str, start: date, end: date, basis: str = "name", order: str = "top",
    limit: int = 10, min_days: int | None = None, main_only: bool = False, scope: str | None = None,
) -> dict[str, Any]:
    """Menus ranked by the average difference (actual - 평소 식수, people) on the days they were served."""
    check_meal_type(meal_type)
    check_period(start, end)
    check_menu_mode(basis)
    if order not in {"top", "bottom"}:
        raise AnalysisError("상위 또는 하위만 선택할 수 있습니다.")
    if limit not in {10, 20, 50}:
        raise AnalysisError("10개, 20개 또는 50개만 볼 수 있습니다.")
    if scope is None:
        scope = "main_menu" if main_only else "all"
    check_menu_scope(scope)
    main_only = scope == "main_menu"
    if min_days is None:
        min_days = default_min_days(meal_type, scope)
    if min_days < 1 or min_days > 365:
        raise AnalysisError("최소 등장 횟수는 1~365 사이로 입력해 주세요.")
    points = {p["service_id"]: p for p in _build_points(db, meal_type, start, end) if p["usual"] is not None}
    rows = []
    too_few = 0
    max_days = 0
    for key, service_ids in _service_menu_keys(db, meal_type, start, end, basis, scope=scope).items():
        members = [points[sid] for sid in service_ids if sid in points]
        if not members:
            continue
        max_days = max(max_days, len(members))
        if len(members) < min_days:
            too_few += 1
            continue
        rows.append({
            "name": key,
            "days": len(members),
            "avg_actual": _avg([p["actual"] for p in members]),
            "avg_usual": _avg([p["usual"] for p in members]),
            "avg_diff": _avg([p["diff"] for p in members]),
            "avg_diff_exact": sum(p["diff"] for p in members) / len(members),
        })
    sign = -1 if order == "top" else 1
    rows.sort(key=lambda r: (sign * r["avg_diff_exact"], -r["days"], r["name"]))
    ranked = rows[:limit]
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
        row["diff_text"] = diff_text(row["avg_diff"])
        row.pop("avg_diff_exact")
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "basis": basis,
        "basis_name": MENU_MODES[basis],
        "order": order,
        "limit": limit,
        "min_days": min_days,
        "main_only": main_only,
        "scope": scope,
        "scope_name": MENU_SCOPES[scope],
        "max_days": max_days,
        "candidates": len(rows),
        "excluded_too_few": too_few,
        "items": ranked,
    }


def menu_compare(
    db: Session, meal_type: str, start: date, end: date, mode: str, names: list[str], weather_filter: str = "all",
    scope: str = "all", scopes: list[str] | None = None,
) -> dict[str, Any]:
    """One series per selected menu (by exact name or 대표 메뉴명) plus the shared 평소 식수 line."""
    check_meal_type(meal_type)
    check_period(start, end)
    check_menu_mode(mode)
    clean = _clean_compare_names(names, "메뉴")
    if weather_filter not in WEATHER_FILTERS:
        raise AnalysisError("날씨 조건이 올바르지 않습니다.")
    check_menu_scope(scope)
    # 메뉴마다 범위를 따로 줄 수 있습니다(인기 메뉴에서 서로 다른 범위로 고른 메뉴를 그 범위 그대로 비교).
    item_scope: dict[str, str] = {}
    if scopes:
        if len(scopes) != len(names):
            raise AnalysisError("메뉴와 범위 개수가 맞지 않습니다.")
        for name, item in zip(names, scopes):
            item_scope.setdefault((name or "").strip(), check_menu_scope(item or scope))
    by_scope: dict[str, list[str]] = defaultdict(list)
    for name in clean:
        by_scope[item_scope.get(name, scope)].append(name)
    by_key: dict[str, set[int]] = {}
    for one_scope, group in by_scope.items():
        by_key.update(_service_menu_keys(db, meal_type, start, end, mode, keys=group, scope=one_scope))
    items, used, usual_line = _compare_series(db, meal_type, start, end, by_key, clean, weather_filter)
    for item in items:
        item["scope"] = item_scope.get(item["name"], scope)
        item["scope_name"] = MENU_SCOPES[item["scope"]]
        if not item["days"]:
            item["no_data_note"] = f"{item['name']}: 이 기간·조건({item['scope_name']})에 실제 식수가 있는 날이 없어 그래프에 선이 없어요."
    return {
        "scope": scope,
        "scope_name": MENU_SCOPES[scope],
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weather_window": weather_window_label(meal_type),
        "mode": mode,
        "mode_name": MENU_MODES[mode],
        "weather_filter": weather_filter,
        "weather_filter_name": WEATHER_FILTERS[weather_filter],
        "items": items,
        "dates": used,
        "usual_line": usual_line,
    }


def search_menus(db: Session, mode: str = "group", query: str = "", limit: int = 30, scope: str = "all") -> list[dict[str, Any]]:
    check_menu_mode(mode)
    conditions = _scope_conditions(scope)
    if mode == "group" and not conditions:
        return search_menu_groups(db, query, limit)
    column = _menu_key_column(mode)
    count = func.count(func.distinct(MealServiceMenu.meal_service_id))
    stmt = (
        select(column, count)
        .join(MealServiceMenu, MealServiceMenu.menu_id == Menu.id)
        .where(column != "", *conditions)
        .group_by(column)
    )
    query = (query or "").strip()
    if query:
        stmt = stmt.where(column.ilike(f"%{query}%"))
    rows = db.execute(stmt.order_by(count.desc(), column).limit(limit)).all()
    return [{"name": name, "served": int(c)} for name, c in rows]


def _clean_compare_names(names: list[str], noun: str, *, limit: int | None = MAX_COMPARE_ITEMS) -> list[str]:
    clean: list[str] = []
    for name in names:
        name = (name or "").strip()
        if name and name not in clean:
            clean.append(name)
    if not clean:
        raise AnalysisError(f"{noun}를 하나 이상 선택해 주세요.")
    if limit is not None and len(clean) > limit:
        raise AnalysisError(f"{noun}는 최대 {limit}개까지 비교할 수 있습니다.")
    return clean


def _compare_series(
    db: Session, meal_type: str, start: date, end: date, by_key: dict[str, set[int]], clean: list[str], weather_filter: str,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Build one series per key from a single points query; returns (items, used dates, shared 평소 line)."""
    wanted = set().union(*by_key.values()) if by_key else set()
    all_points = _apply_weather_filter(_build_points(db, meal_type, start, end, wanted), weather_filter) if wanted else []
    by_id = {p["service_id"]: p for p in all_points}
    items = []
    for name in clean:
        members = sorted((by_id[sid] for sid in by_key.get(name, set()) if sid in by_id), key=lambda p: p["date"])
        with_usual = [p for p in members if p["usual"] is not None]
        items.append({
            "name": name,
            "points": members,
            "days": len(members),
            "avg_actual": _avg([p["actual"] for p in members]),
            "avg_usual": _avg([p["usual"] for p in with_usual]),
            "avg_diff": _avg([p["diff"] for p in with_usual]),
            "low_sample_note": low_sample_note(len(members)),
        })
    unique = {p["date"]: p for item in items for p in item["points"]}
    used = sorted(unique)
    usual_line = [{"date": d, "label": unique[d]["label"], "usual": unique[d]["usual"]} for d in used]
    return items, used, usual_line


# ---------------------------------------------------------------------------
# 재료 이름·대표 재료명 조회 / 여러 재료 비교
# ---------------------------------------------------------------------------
INGREDIENT_MODES = {"name": "재료 이름", "group": "대표 재료명"}


def check_ingredient_mode(mode: str) -> str:
    if mode not in INGREDIENT_MODES:
        raise AnalysisError("조회 기준은 재료 이름 또는 대표 재료명만 선택할 수 있습니다.")
    return mode


def _ingredient_key_filter(mode: str):
    """Key column plus extra conditions. 대표 재료명 mode skips ingredients marked '통계 분석 제외'."""
    if mode == "name":
        return Ingredient.name, []
    return Ingredient.stat_group, [Ingredient.analysis_excluded.is_(False), Ingredient.stat_group != ""]


def _service_ingredient_keys(
    db: Session, meal_type: str, start: date, end: date, mode: str, keys: list[str] | None = None,
) -> dict[str, set[int]]:
    column, extra = _ingredient_key_filter(mode)
    stmt = (
        select(column, MealService.id)
        .join(MealServiceMenuIngredient, MealServiceMenuIngredient.ingredient_id == Ingredient.id)
        .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .where(MealService.meal_type == meal_type, MealService.service_date >= start, MealService.service_date <= end, *extra)
        .distinct()
    )
    if keys is not None:
        stmt = stmt.where(column.in_(keys))
    result: dict[str, set[int]] = defaultdict(set)
    for key, service_id in db.execute(stmt).all():
        result[key].add(service_id)
    return result


def ingredient_compare(
    db: Session, meal_type: str, start: date, end: date, mode: str, names: list[str], weather_filter: str = "all",
) -> dict[str, Any]:
    """One series per selected ingredient (재료 이름 or 대표 재료명) plus the shared 평소 식수 line."""
    check_meal_type(meal_type)
    check_period(start, end)
    check_ingredient_mode(mode)
    clean = _clean_compare_names(names, "재료", limit=None if mode == "group" else MAX_COMPARE_ITEMS)
    if weather_filter not in WEATHER_FILTERS:
        raise AnalysisError("날씨 조건이 올바르지 않습니다.")
    by_key = _service_ingredient_keys(db, meal_type, start, end, mode, keys=clean)
    items, used, usual_line = _compare_series(db, meal_type, start, end, by_key, clean, weather_filter)
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weather_window": weather_window_label(meal_type),
        "mode": mode,
        "mode_name": INGREDIENT_MODES[mode],
        "weather_filter": weather_filter,
        "weather_filter_name": WEATHER_FILTERS[weather_filter],
        "items": items,
        "dates": used,
        "usual_line": usual_line,
    }


def search_ingredient_keys(db: Session, mode: str = "name", query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    check_ingredient_mode(mode)
    if mode == "name":
        return search_ingredients(db, query, limit)
    column, extra = _ingredient_key_filter(mode)
    count = func.count(func.distinct(MealServiceMenu.meal_service_id))
    stmt = (
        select(column, count)
        .join(MealServiceMenuIngredient, MealServiceMenuIngredient.ingredient_id == Ingredient.id)
        .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
        .where(*extra)
        .group_by(column)
    )
    query = (query or "").strip()
    if query:
        stmt = stmt.where(column.ilike(f"%{query}%"))
    rows = db.execute(stmt.order_by(count.desc(), column).limit(limit)).all()
    return [{"name": name, "served": int(c)} for name, c in rows]


def ingredient_ids_for(db: Session, mode: str, names: list[str]) -> set[int]:
    """Ingredient ids matched by the selected names (used to highlight menus in the date detail)."""
    check_ingredient_mode(mode)
    names = [n for n in (x.strip() for x in names) if n]
    if not names:
        return set()
    column, extra = _ingredient_key_filter(mode)
    return set(db.scalars(select(Ingredient.id).where(column.in_(names), *extra)).all())


def _months_between(start: date, end: date) -> list[str]:
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def ingredient_monthly_usage(
    db: Session, meal_type: str, start: date, end: date, names: list[str],
) -> dict[str, Any]:
    """월별 대표 재료명 사용 횟수: 그 배식에 대표 재료명이 들어간 식단 수."""
    check_meal_type(meal_type)
    check_period(start, end)
    clean = _clean_compare_names(names, "대표 재료명", limit=None)
    column, extra = _ingredient_key_filter("group")
    rows = db.execute(
        select(column, MealService.id, MealService.service_date)
        .join(MealServiceMenuIngredient, MealServiceMenuIngredient.ingredient_id == Ingredient.id)
        .join(MealServiceMenu, MealServiceMenu.id == MealServiceMenuIngredient.meal_service_menu_id)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .where(
            MealService.meal_type == meal_type,
            MealService.service_date >= start,
            MealService.service_date <= end,
            column.in_(clean),
            *extra,
        )
        .distinct()
    ).all()
    by_month: dict[str, dict[str, set[int]]] = {name: defaultdict(set) for name in clean}
    for key, service_id, service_date in rows:
        by_month[key][f"{service_date.year:04d}-{service_date.month:02d}"].add(service_id)
    months = _months_between(start, end)
    items = []
    for name in clean:
        counts = [len(by_month[name].get(month, ())) for month in months]
        items.append({"name": name, "counts": counts, "total": sum(counts)})
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "months": months,
        "items": items,
    }
