from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import MealActual, MealService

WEEKDAY_NAMES = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
MEAL_TYPE_NAMES = {"LUNCH": "중식", "DINNER": "석식"}
LOOKBACK_DAYS = 56
MIN_COMPARISON = 4
CHECK_THRESHOLD = 10.0
IMPORTANT_THRESHOLD = 15.0


def _meal_type_code(meal_type: str) -> str | None:
    return {"lunch": "LUNCH", "dinner": "DINNER"}.get(meal_type)


def _services(db: Session, start: date, end: date, meal_type: str | None) -> list[MealService]:
    stmt = (
        select(MealService)
        .where(MealService.service_date.between(start, end))
        .options(selectinload(MealService.actual))
        .order_by(MealService.service_date, MealService.meal_type)
    )
    if meal_type:
        stmt = stmt.where(MealService.meal_type == meal_type)
    return list(db.scalars(stmt).unique().all())


def _actual_history(db: Session, start: date, end: date) -> list[tuple[date, str, int]]:
    rows = db.execute(
        select(MealService.service_date, MealService.meal_type, MealActual.actual_count)
        .join(MealActual, MealActual.meal_service_id == MealService.id)
        .where(
            MealService.service_date.between(start, end),
            MealActual.actual_count.is_not(None),
        )
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


def _deviation_rate(actual: int | None, base: int | None) -> float | None:
    if actual is None or base is None or base <= 0:
        return None
    return round((actual - base) / base * 100, 1)


def _usual_median(history: list[tuple[date, str, int]], service_date: date, meal_type: str) -> tuple[float | None, int]:
    cutoff = service_date - timedelta(days=LOOKBACK_DAYS)
    values = [row[2] for row in history if row[0] < service_date and row[0] >= cutoff and row[1] == meal_type]
    if len(values) < MIN_COMPARISON:
        return None, len(values)
    return round(median(values), 1), len(values)


def meal_statistics(db: Session, start: date, end: date, meal_type: str = "all") -> dict[str, Any]:
    meal_type_code = _meal_type_code(meal_type)
    services = _services(db, start, end, meal_type_code)
    history = _actual_history(db, start - timedelta(days=LOOKBACK_DAYS), end)

    planned_sum = sum(s.planned_count for s in services)
    actual_rows = [s for s in services if s.actual and s.actual.actual_count is not None]
    actual_sum = sum(s.actual.actual_count for s in actual_rows) if actual_rows else None
    input_rate = round(len(actual_rows) / len(services) * 100, 1) if services else None

    breakdown: dict[str, dict[str, Any]] = {}
    for code, name in MEAL_TYPE_NAMES.items():
        subset = [s for s in services if s.meal_type == code]
        p = sum(s.planned_count for s in subset)
        a_rows = [s for s in subset if s.actual and s.actual.actual_count is not None]
        a = sum(s.actual.actual_count for s in a_rows) if a_rows else None
        breakdown[code.lower()] = {
            "meal_type_name": name,
            "service_count": len(subset),
            "planned_sum": p,
            "actual_sum": a,
            "diff": (a - p) if a is not None else None,
            "deviation_rate": _deviation_rate(a, p) if a is not None else None,
            "input_count": len(a_rows),
            "input_rate": round(len(a_rows) / len(subset) * 100, 1) if subset else None,
        }

    weekday_groups: dict[int, list[tuple[int, int | None]]] = defaultdict(list)
    for s in services:
        weekday_groups[s.service_date.weekday()].append(
            (s.planned_count, s.actual.actual_count if s.actual else None)
        )
    weekday_averages = []
    for wd in range(5):
        rows = weekday_groups.get(wd, [])
        planned_avg = round(sum(r[0] for r in rows) / len(rows), 1) if rows else None
        actual_rows = [r[1] for r in rows if r[1] is not None]
        actual_avg = round(sum(actual_rows) / len(actual_rows), 1) if actual_rows else None
        weekday_averages.append(
            {
                "weekday": WEEKDAY_NAMES[wd],
                "planned_average": planned_avg,
                "actual_average": actual_avg,
                "records": len(rows),
                "actual_records": len(actual_rows),
            }
        )

    backdata: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for s in services:
        actual = s.actual.actual_count if s.actual else None
        planned = s.planned_count
        dev = _deviation_rate(actual, planned)
        usual_median_value, usual_count = _usual_median(history, s.service_date, s.meal_type)
        usual_dev = _deviation_rate(actual, usual_median_value) if usual_median_value is not None else None
        row = {
            "date": s.service_date.isoformat(),
            "weekday": WEEKDAY_NAMES[s.service_date.weekday()],
            "meal_type": s.meal_type,
            "meal_type_name": MEAL_TYPE_NAMES.get(s.meal_type, s.meal_type),
            "planned_count": planned,
            "actual_count": actual,
            "diff": (actual - planned) if actual is not None else None,
            "deviation_rate": dev,
            "usual_median": usual_median_value,
            "usual_count": usual_count,
            "usual_deviation_rate": usual_dev,
            "input": actual is not None,
        }
        backdata.append(row)

        reasons = []
        if dev is not None and abs(dev) >= CHECK_THRESHOLD:
            level = "중요" if abs(dev) >= IMPORTANT_THRESHOLD else "확인"
            reasons.append({"basis": "계획 대비", "value": dev, "level": level})
        if usual_dev is not None and abs(usual_dev) >= CHECK_THRESHOLD:
            level = "중요" if abs(usual_dev) >= IMPORTANT_THRESHOLD else "확인"
            reasons.append({"basis": "평소 대비", "value": usual_dev, "level": level})
        if reasons:
            top = max(reasons, key=lambda r: abs(r["value"]))
            anomalies.append(
                {
                    "type": "식수 급감" if top["value"] < 0 else "식수 급증",
                    "level": top["level"],
                    "date": s.service_date.isoformat(),
                    "weekday": WEEKDAY_NAMES[s.service_date.weekday()],
                    "meal_type_name": MEAL_TYPE_NAMES.get(s.meal_type, s.meal_type),
                    "planned_count": planned,
                    "actual_count": actual,
                    "diff": row["diff"],
                    "deviation_rate": dev,
                    "usual_median": usual_median_value,
                    "usual_count": usual_count,
                    "usual_deviation_rate": usual_dev,
                    "reasons": reasons,
                    "insufficient_comparison": usual_median_value is None and usual_count < MIN_COMPARISON,
                }
            )

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "meal_type": meal_type,
        "summary": {
            "service_count": len(services),
            "input_count": len(actual_rows),
            "input_rate": input_rate,
            "planned_sum": planned_sum,
            "actual_sum": actual_sum,
            "diff": (actual_sum - planned_sum) if actual_sum is not None else None,
            "deviation_rate": _deviation_rate(actual_sum, planned_sum) if actual_sum is not None else None,
        },
        "breakdown": breakdown,
        "weekday_averages": weekday_averages,
        "backdata": backdata,
        "anomalies": sorted(anomalies, key=lambda a: (a["date"], a["meal_type_name"]), reverse=True),
    }


def meal_trend(db: Session, start: date, end: date, meal_type: str = "all") -> dict[str, Any]:
    meal_type_code = _meal_type_code(meal_type)
    services = _services(db, start, end, meal_type_code)
    months: dict[str, dict[str, Any]] = {}
    for s in services:
        key = s.service_date.strftime("%Y-%m")
        bucket = months.setdefault(
            key, {"month": key, "planned": 0, "actual": 0, "planned_days": 0, "actual_days": 0}
        )
        bucket["planned"] += s.planned_count
        bucket["planned_days"] += 1
        if s.actual and s.actual.actual_count is not None:
            bucket["actual"] += s.actual.actual_count
            bucket["actual_days"] += 1
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "meal_type": meal_type,
        "trend": list(months.values()),
    }
