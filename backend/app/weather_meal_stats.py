"""날씨별 식수 전용 집계.

다른 탭의 평소 식수(직전 364일)는 바꾸지 않는다. 이 화면의 비교 기준만
최근 같은 요일 평균이다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .meal_count_analysis import (
    LOW_SAMPLE_DAYS,
    MEAL_TYPES,
    TEMP_BANDS,
    WEEKDAY_PUBLIC_HOLIDAYS,
    WEEKDAYS,
    _build_points,
    _counted_meals,
    check_meal_type,
    check_period,
    date_label,
    earliest_counted_date,
    low_sample_note,
    temp_band,
)
from .models import MealPeriodWeather

SAME_WEEKDAY_WEEKS = 8
SAME_WEEKDAY_WEEKS_MAX = 12
SAME_WEEKDAY_MIN_DAYS = 4
SEASONAL_YEARS = 5
SEASONAL_MIN_YEARS = 3
SEASONAL_MIN_DAYS = 60
SEASONAL_WINDOW_DAYS = 15
SEASONAL_BAND = 3.0
PERIODS = {
    "all": "전체",
    "spring": "봄",
    "summer": "여름",
    "autumn": "가을",
    "winter": "겨울",
    **{f"m{month}": f"{month}월" for month in range(1, 13)},
}
SEASON_MONTHS = {"spring": {3, 4, 5}, "summer": {6, 7, 8}, "autumn": {9, 10, 11}, "winter": {12, 1, 2}}
SEASONAL_MIN_DATES_PER_YEAR = 200
TEMP_HINTS = {
    "lt-10": "매우 추움",
    "m10tom5": "많이 추움",
    "m5to0": "조금 추움",
    "28to32": "조금 더움",
    "32to35": "많이 더움",
    "35plus": "매우 더움",
}


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def same_weekday_baseline(counts: dict[date, int], target: date) -> dict[str, Any]:
    """직전 8주 같은 요일. 4일 미만이면 12주. 그래도 부족하면 기준 없음.

    8·12·4는 초기 운영값이다. 다른 요일이나 364일 평균으로 대체하지 않는다.
    """
    covered_years = {day.year for day in WEEKDAY_PUBLIC_HOLIDAYS}
    target_known = target.year in covered_years
    target_holiday = target in WEEKDAY_PUBLIC_HOLIDAYS
    unseparated = not target_known

    def allowed(day: date) -> bool:
        nonlocal unseparated
        if day.year not in covered_years or not target_known:
            unseparated = True
            return True
        if target_holiday:
            return day in WEEKDAY_PUBLIC_HOLIDAYS
        return day not in WEEKDAY_PUBLIC_HOLIDAYS

    chosen: list[int] = []
    weeks_used = None
    for weeks in (SAME_WEEKDAY_WEEKS, SAME_WEEKDAY_WEEKS_MAX):
        chosen = []
        for step in range(1, weeks + 1):
            day = target - timedelta(days=7 * step)
            if day not in counts or not allowed(day):
                continue
            chosen.append(counts[day])
        if len(chosen) >= SAME_WEEKDAY_MIN_DAYS:
            weeks_used = weeks
            break
    if weeks_used is None:
        return {"baseline": None, "days": len(chosen), "weeks": None, "holiday_unseparated": unseparated}
    return {
        "baseline": sum(chosen) / len(chosen),
        "days": len(chosen),
        "weeks": weeks_used,
        "holiday_unseparated": unseparated,
    }


def _in_period(day: date, period: str) -> bool:
    if period in ("", "all"):
        return True
    if period in SEASON_MONTHS:
        return day.month in SEASON_MONTHS[period]
    if period.startswith("m") and period[1:].isdigit():
        return day.month == int(period[1:])
    return True


def _off_day(day: date) -> bool:
    return day.weekday() >= 5 or day in WEEKDAY_PUBLIC_HOLIDAYS


def _station_choice(rows: list[MealPeriodWeather], requested: str) -> tuple[MealPeriodWeather | None, list[dict[str, str]]]:
    counts: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for row in rows:
        counts[row.station_id] += 1
        if row.station_name:
            names[row.station_id] = row.station_name
    options = [
        {"station_id": station_id, "station_name": names.get(station_id, ""), "days": days}
        for station_id, days in sorted(counts.items(), key=_station_sort_key)
    ]
    if not options:
        return None, []
    chosen = requested if requested in counts else options[0]["station_id"]
    picked = next(row for row in rows if row.station_id == chosen)
    return picked, options


def _station_sort_key(item: tuple[str, int]) -> tuple:
    station_id, days = item
    try:
        identity: tuple = (0, int(station_id))
    except ValueError:
        identity = (1, station_id)
    return (-days, identity)


def _usable_temp(row: MealPeriodWeather) -> bool:
    if row.avg_temp is None:
        return False
    if row.temp_complete is False:
        return False
    return True


def _usable_precip(row: MealPeriodWeather) -> bool:
    if row.precipitation is None:
        return False
    if row.precip_state == "unavailable":
        return False
    return True


def _band_payload(key: str, label: str, members: list[dict[str, Any]], hint: str = "") -> dict[str, Any]:
    comparable = [point for point in members if point["diff"] is not None]
    return {
        "key": key,
        "label": label,
        "hint": hint,
        "days": len(comparable),
        "avg_actual": _round(_mean([float(point["actual"]) for point in comparable])),
        "avg_baseline": _round(_mean([point["baseline_exact"] for point in comparable])),
        "avg_diff": _round(_mean([point["diff_exact"] for point in comparable])),
        "low_sample_note": low_sample_note(len(comparable)),
        "points": comparable,
        "uncompared": [point for point in members if point["diff"] is None],
    }


def _seasonal_status(db: Session, meal_type: str, station_id: str) -> dict[str, Any]:
    earliest = earliest_counted_date(db, meal_type)
    if earliest is None:
        return {"active": False, "reason": "식수 기록이 없어 이 시기 평균을 만들지 않습니다."}
    if not station_id:
        return {"active": False, "reason": "대표 관측지점이 없어 이 시기 평균을 만들지 않습니다."}
    needed = list(range(earliest.year - SEASONAL_YEARS, earliest.year))
    rows = db.execute(
        select(MealPeriodWeather.observation_date, MealPeriodWeather.temp_complete).where(
            MealPeriodWeather.meal_type == meal_type,
            MealPeriodWeather.station_id == station_id,
            MealPeriodWeather.avg_temp.is_not(None),
        )
    ).all()
    years: dict[int, set[date]] = defaultdict(set)
    for observed, complete in rows:
        if complete is False or observed.year not in needed:
            continue
        years[observed.year].add(observed)
    complete_years = [year for year in needed if len(years[year]) >= SEASONAL_MIN_DATES_PER_YEAR]
    if len(complete_years) < SEASONAL_YEARS:
        return {
            "active": False,
            "reason": (
                f"이 시기 평균은 식수 시작({earliest.isoformat()})보다 앞선 {needed[0]}~{needed[-1]}년에, "
                f"같은 지점·같은 배식의 기온이 연 {SEASONAL_MIN_DATES_PER_YEAR}일 이상인 자료가 있을 때만 켭니다. "
                "지금은 그 자료가 없습니다. 최근 15일 평균으로 대신 계산하지 않습니다."
            ),
            "needed_years": needed,
            "station_id": station_id,
        }
    return {
        "active": True,
        "years": complete_years,
        "reason": "기상청 관측으로 계산한 자체 기준이며 공식 30년 평년값이 아닙니다.",
        "station_id": station_id,
    }


def _window_dates(target: date, year: int) -> list[date]:
    anchor = _shift_year(target, year)
    if anchor is None:
        anchor = date(year, 2, 28)
    dates = []
    for offset in range(-SEASONAL_WINDOW_DAYS, SEASONAL_WINDOW_DAYS + 1):
        dates.append(anchor + timedelta(days=offset))
    return dates


def _seasonal_bands(db: Session, meal_type: str, points: list[dict[str, Any]], years: list[int], station_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(MealPeriodWeather).where(
            MealPeriodWeather.meal_type == meal_type,
            MealPeriodWeather.station_id == station_id,
            MealPeriodWeather.avg_temp.is_not(None),
        )
    ).all()
    temps = {row.observation_date: float(row.avg_temp) for row in rows if row.observation_date.year in years or row.observation_date.year == years[0] - 1}
    grouped = {"low": [], "near": [], "high": []}
    for point in points:
        if point["temp"] is None:
            continue
        target = date.fromisoformat(point["date"])
        sample = []
        seen_years = set()
        for year in years:
            for day in _window_dates(target, year):
                if day in temps and day.year in years:
                    sample.append(temps[day])
                    seen_years.add(day.year)
        if len(seen_years) < SEASONAL_MIN_YEARS or len(sample) < SEASONAL_MIN_DAYS:
            continue
        delta = point["temp"] - (sum(sample) / len(sample))
        bucket = "low" if delta < -SEASONAL_BAND else "high" if delta > SEASONAL_BAND else "near"
        grouped[bucket].append(point)
    labels = [("low", "이 시기 평균보다 낮음"), ("near", "이 시기 평균과 비슷함"), ("high", "이 시기 평균보다 높음")]
    return [_band_payload(key, label, grouped[key]) for key, label in labels]


def _shift_year(day: date, year: int) -> date | None:
    try:
        return day.replace(year=year)
    except ValueError:
        return None


def build_weather_bands(
    db: Session,
    meal_type: str,
    start: date,
    end: date,
    *,
    weekday: int | None = None,
    period: str = "all",
    include_off: bool = False,
    station_id: str = "",
) -> dict[str, Any]:
    check_meal_type(meal_type)
    check_period(start, end)
    if period not in PERIODS:
        period = "all"
    history = _counted_meals(db, meal_type, start - timedelta(weeks=SAME_WEEKDAY_WEEKS_MAX + 1), end)
    counts = {point.service_date: point.actual for point in history}
    built = _build_points(db, meal_type, start, end)
    weather_rows = db.scalars(
        select(MealPeriodWeather).where(
            MealPeriodWeather.meal_type == meal_type,
            MealPeriodWeather.observation_date >= start,
            MealPeriodWeather.observation_date <= end,
        )
    ).all()
    _anchor, station_options = _station_choice(weather_rows, station_id)
    chosen_id = station_id if station_id and any(item["station_id"] == station_id for item in station_options) else (station_options[0]["station_id"] if station_options else "")
    by_date = {row.observation_date: row for row in weather_rows if row.station_id == chosen_id}
    covered_years = {day.year for day in WEEKDAY_PUBLIC_HOLIDAYS}
    holiday_gap = False
    points = []
    for point in built:
        observed = date.fromisoformat(point["date"])
        if weekday is not None and observed.weekday() != weekday:
            continue
        if not _in_period(observed, period):
            continue
        if not include_off and _off_day(observed):
            continue
        if observed.year not in covered_years:
            holiday_gap = True
        base = same_weekday_baseline(counts, observed)
        if base["holiday_unseparated"]:
            holiday_gap = True
        weather = by_date.get(observed)
        temp_raw = float(weather.avg_temp) if weather is not None and weather.avg_temp is not None else None
        temp = temp_raw if weather is not None and _usable_temp(weather) else None
        precip_ok = weather is not None and _usable_precip(weather)
        snow_ok = weather is not None and weather.snow_depth is not None and weather.snow_state in (None, "ok", "legacy", "value")
        if weather is not None and weather.snow_state == "partial":
            snow_ok = False
        baseline = base["baseline"]
        diff = point["actual"] - baseline if baseline is not None else None
        notes = []
        if baseline is None:
            notes.append("비교 자료 부족")
        if temp is None and temp_raw is not None:
            notes.append("기온 부분 관측")
        if weather is not None and weather.snow_state == "partial":
            notes.append("적설 부분 관측")
        if weather is not None and weather.precip_state == "unavailable":
            notes.append("강수량 시간범위 미확인")
        if weather is not None and weather.precip_state == "legacy_blank":
            notes.append("기존 해석·확인 필요")
        points.append({
            "date": point["date"],
            "label": date_label(observed),
            "weekday": WEEKDAYS[observed.weekday()],
            "actual": point["actual"],
            "baseline": _round(baseline),
            "baseline_exact": baseline,
            "baseline_days": base["days"],
            "baseline_weeks": base["weeks"],
            "diff": _round(diff) if diff is not None else None,
            "diff_exact": diff,
            "compare_note": "" if baseline is not None else "비교 자료 부족",
            "notes": " · ".join(notes),
            "year_usual": point["usual"],
            "temp": temp,
            "temp_raw": temp_raw,
            "precip_mm": float(weather.precipitation) if precip_ok else None,
            "precip_state": weather.precip_state if weather is not None else None,
            "precip_legacy": bool(weather and weather.precip_state == "legacy_blank"),
            "pre_precip_mm": float(weather.pre_precip) if weather is not None and weather.pre_precip_state == "ok" and weather.pre_precip is not None else None,
            "pre_ok": bool(weather and weather.pre_precip_state == "ok" and precip_ok),
            "snow_cm": float(weather.snow_depth) if snow_ok else None,
            "snow_partial_cm": float(weather.snow_depth) if weather is not None and weather.snow_state == "partial" and weather.snow_depth is not None else None,
            "snow_new_cm": float(weather.snow_new_3h) if weather is not None and weather.snow_new_state == "value" and weather.snow_new_3h is not None else None,
            "humidity": float(weather.avg_humidity) if weather is not None and weather.avg_humidity is not None else None,
            "wind_speed": float(weather.avg_wind_speed) if weather is not None and weather.avg_wind_speed is not None else None,
            "station": (weather.station_name or weather.station_id) if weather is not None else "",
            "weather_text": _weather_line(weather, temp if temp is not None else temp_raw, precip_ok, snow_ok),
        })
    comparable = lambda pred: [point for point in points if pred(point) and point["diff"] is not None]
    rain_members_yes = [point for point in points if point["precip_mm"] is not None and point["precip_mm"] > 0]
    rain_members_no = [point for point in points if point["precip_mm"] is not None and point["precip_mm"] == 0]
    rain = [
        _band_payload("rain", "측정 강수량 있음", rain_members_yes),
        _band_payload("dry", "측정 강수량 없음", rain_members_no),
    ]
    detail_defs = [("zero", "0mm", lambda value: value == 0), ("under1", "0 초과~1mm 미만", lambda value: 0 < value < 1), ("1to5", "1~5mm 미만", lambda value: 1 <= value < 5), ("5plus", "5mm 이상", lambda value: value >= 5)]
    rain_detail = [
        _band_payload(key, label, [point for point in points if point["precip_mm"] is not None and test(point["precip_mm"])])
        for key, label, test in detail_defs
    ]
    both = [point for point in points if point["pre_ok"]]
    pre_rain = [
        _band_payload("neither", "직전·배식 모두 없음", [point for point in both if point["pre_precip_mm"] == 0 and point["precip_mm"] == 0]),
        _band_payload("before", "직전에만 있음", [point for point in both if point["pre_precip_mm"] > 0 and point["precip_mm"] == 0]),
        _band_payload("during", "배식 구간에만 있음", [point for point in both if point["pre_precip_mm"] == 0 and point["precip_mm"] > 0]),
        _band_payload("both", "두 구간 모두 있음", [point for point in both if point["pre_precip_mm"] > 0 and point["precip_mm"] > 0]),
    ]
    temperature = []
    for key, label, low, high in TEMP_BANDS:
        members = [point for point in points if point["temp"] is not None and temp_band(point["temp"]) == key]
        temperature.append(_band_payload(key, label, members, TEMP_HINTS.get(key, "")))
    snow = [
        _band_payload("snow", "적설 있음", [point for point in points if point["snow_cm"] is not None and point["snow_cm"] > 0], "쌓인 눈"),
        _band_payload("clear", "적설 없음", [point for point in points if point["snow_cm"] is not None and point["snow_cm"] == 0], "쌓인 눈"),
    ]
    snow_new_points = [point for point in points if point["snow_new_cm"] is not None]
    snow_new = [
        _band_payload("new", "최근 3시간 신적설 있음", [point for point in snow_new_points if point["snow_new_cm"] > 0]),
        _band_payload("none", "최근 3시간 신적설 없음", [point for point in snow_new_points if point["snow_new_cm"] == 0]),
    ] if snow_new_points else []
    precip_unavailable = sum(1 for point in points if point["precip_mm"] is None)
    scatter = [
        {"date": point["date"], "temp": point["temp"], "diff": point["diff"], "rain": point["precip_mm"] is not None and point["precip_mm"] > 0}
        for point in points if point["temp"] is not None and point["diff"] is not None
    ]
    legacy = any(point["precip_legacy"] for point in points)
    seasonal = _seasonal_status(db, meal_type, chosen_id)
    if seasonal.get("active") and chosen_id:
        seasonal["bands"] = _seasonal_bands(db, meal_type, points, seasonal["years"], chosen_id)
    return {
        "meal_type": meal_type,
        "meal_type_name": MEAL_TYPES[meal_type],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "weather_window": "11:00~12:00" if meal_type == "LUNCH" else "17:00~18:00",
        "days": len(points),
        "baseline_name": "최근 같은 요일 평균",
        "baseline_rule": f"직전 {SAME_WEEKDAY_WEEKS}주의 같은 요일. {SAME_WEEKDAY_MIN_DAYS}일 미만이면 {SAME_WEEKDAY_WEEKS_MAX}주까지. 초기 운영값이며 다른 요일·최근 1년 평균으로 바꾸지 않습니다.",
        "help": "행사·출근 인원·메뉴 선호는 보정하지 않았습니다. 이 차이는 날씨만의 영향이 아닙니다.",
        "holiday_notice": "이 기간은 공휴일 목록이 없어 공휴일을 구분하지 않았습니다." if holiday_gap else "",
        "include_off": include_off,
        "period": period,
        "period_name": PERIODS.get(period, "전체"),
        "station": next((item for item in station_options if item["station_id"] == chosen_id), None),
        "stations": station_options,
        "counts": {
            "meal_days": len(points),
            "temp_days": len(comparable(lambda point: point["temp"] is not None)),
            "precip_days": len(comparable(lambda point: point["precip_mm"] is not None)),
            "snow_days": len(comparable(lambda point: point["snow_cm"] is not None)),
            "snow_new_days": len(comparable(lambda point: point["snow_new_cm"] is not None)),
            "baseline_missing": sum(point["diff"] is None for point in points),
            "precip_unavailable": precip_unavailable,
        },
        "precip_note": (
            "ASOS 강수량은 1시간량인지 3시간량인지 이 파일의 헤더만으로 확인하지 못했습니다. "
            "기상자료개방포털은 11~3월 강수량을 3시간 간격으로 제공한다고 안내합니다. "
            "그래서 배식 구간 강수량은 계산하지 않습니다. 헤더가 1시간강수량이면 그 시각의 값만 씁니다."
            if precip_unavailable and not any(point["precip_mm"] is not None for point in points)
            else ("빈 강수칸을 0으로 넣었던 값이 있습니다. 기존 해석·확인 필요. ASOS 시간자료를 다시 올리면 그 시각은 갱신됩니다." if legacy else "")
        ),
        "points": points,
        "rain": rain,
        "rain_detail": rain_detail,
        "pre_rain": pre_rain,
        "temperature": temperature,
        "snow": snow,
        "snow_new": snow_new,
        "scatter": scatter,
        "seasonal": seasonal,
        "settings": {
            "weeks": SAME_WEEKDAY_WEEKS,
            "weeks_max": SAME_WEEKDAY_WEEKS_MAX,
            "min_days": SAME_WEEKDAY_MIN_DAYS,
            "low_sample_days": LOW_SAMPLE_DAYS,
        },
    }


def _weather_line(weather: MealPeriodWeather | None, temp: float | None, precip_ok: bool, snow_ok: bool) -> str:
    if weather is None:
        return ""
    parts = []
    if precip_ok and weather.precipitation is not None:
        parts.append(f"강수 {weather.precipitation:g}mm" if weather.precipitation > 0 else "측정 강수량 없음")
    elif weather.precip_state == "unavailable":
        parts.append("강수량 시간범위 미확인")
    if temp is not None:
        parts.append(f"{temp:.1f}℃")
    if snow_ok and weather.snow_depth is not None and weather.snow_depth > 0:
        parts.append(f"적설 {weather.snow_depth:g}cm")
    return " · ".join(parts)
