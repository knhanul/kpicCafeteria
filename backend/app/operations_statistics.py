from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import MealService
from .statistics_service import MEAL_TYPE_NAMES, WEEKDAY_NAMES

LATE_INPUT_DAYS = 1


def _meal_type_code(meal_type: str) -> str | None:
    return {"lunch": "LUNCH", "dinner": "DINNER"}.get(meal_type)


def _services(db: Session, start: date, end: date, meal_type: str | None) -> list[MealService]:
    stmt = (
        select(MealService)
        .where(MealService.service_date.between(start, end))
        .options(selectinload(MealService.actual), selectinload(MealService.preservation))
        .order_by(MealService.service_date, MealService.meal_type)
    )
    if meal_type:
        stmt = stmt.where(MealService.meal_type == meal_type)
    return list(db.scalars(stmt).unique().all())


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total * 100, 1)


def _service_row(service: MealService) -> dict[str, Any]:
    actual = service.actual
    preservation = service.preservation
    actual_count = actual.actual_count if actual else None
    recorded_at = actual.recorded_at if actual else None
    late = False
    if recorded_at is not None:
        recorded_date = recorded_at.date()
        late = (recorded_date - service.service_date).days > LATE_INPUT_DAYS
    return {
        "date": service.service_date.isoformat(),
        "weekday": WEEKDAY_NAMES[service.service_date.weekday()],
        "meal_type": service.meal_type,
        "meal_type_name": MEAL_TYPE_NAMES.get(service.meal_type, service.meal_type),
        "planned_count": service.planned_count,
        "actual_count": actual_count,
        "actual_input": actual_count is not None,
        "actual_recorded_at": recorded_at.isoformat() if recorded_at else None,
        "actual_late": late,
        "meal_plan_output": service.meal_plan_output_at is not None,
        "meal_plan_output_at": service.meal_plan_output_at.isoformat() if service.meal_plan_output_at else None,
        "cooking_output": service.cooking_output_at is not None,
        "cooking_output_at": service.cooking_output_at.isoformat() if service.cooking_output_at else None,
        "preservation_completed": bool(preservation and preservation.completed_at),
        "preservation_collected": bool(preservation and preservation.collected_at),
        "preservation_disposed": bool(preservation and preservation.disposal_at),
        "preservation_manager": (preservation.manager_name if preservation else None),
        "preservation_temperature": (preservation.freezer_temperature if preservation else None),
    }


def operations_statistics(
    db: Session, start: date, end: date, meal_type: str = "all"
) -> dict[str, Any]:
    meal_type_code = _meal_type_code(meal_type)
    services = _services(db, start, end, meal_type_code)
    rows = [_service_row(s) for s in services]

    actual_input_count = sum(1 for r in rows if r["actual_input"])
    preservation_count = sum(1 for r in rows if r["preservation_completed"])
    meal_plan_count = sum(1 for r in rows if r["meal_plan_output"])
    cooking_count = sum(1 for r in rows if r["cooking_output"])
    total = len(rows)

    breakdown: dict[str, dict[str, Any]] = {}
    for code, name in MEAL_TYPE_NAMES.items():
        subset = [r for r in rows if r["meal_type"] == code]
        sub_total = len(subset)
        breakdown[code.lower()] = {
            "meal_type_name": name,
            "service_count": sub_total,
            "actual_input_count": sum(1 for r in subset if r["actual_input"]),
            "actual_input_rate": _rate(sum(1 for r in subset if r["actual_input"]), sub_total),
            "preservation_count": sum(1 for r in subset if r["preservation_completed"]),
            "preservation_rate": _rate(sum(1 for r in subset if r["preservation_completed"]), sub_total),
            "meal_plan_output_count": sum(1 for r in subset if r["meal_plan_output"]),
            "meal_plan_output_rate": _rate(sum(1 for r in subset if r["meal_plan_output"]), sub_total),
            "cooking_output_count": sum(1 for r in subset if r["cooking_output"]),
            "cooking_output_rate": _rate(sum(1 for r in subset if r["cooking_output"]), sub_total),
        }

    months: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["date"][:7]
        bucket = months.setdefault(
            key,
            {
                "month": key,
                "service_count": 0,
                "actual_input_count": 0,
                "preservation_count": 0,
                "meal_plan_output_count": 0,
                "cooking_output_count": 0,
            },
        )
        bucket["service_count"] += 1
        if r["actual_input"]:
            bucket["actual_input_count"] += 1
        if r["preservation_completed"]:
            bucket["preservation_count"] += 1
        if r["meal_plan_output"]:
            bucket["meal_plan_output_count"] += 1
        if r["cooking_output"]:
            bucket["cooking_output_count"] += 1
    trend = []
    for bucket in months.values():
        trend.append(
            {
                "month": bucket["month"],
                "service_count": bucket["service_count"],
                "actual_input_rate": _rate(bucket["actual_input_count"], bucket["service_count"]),
                "preservation_rate": _rate(bucket["preservation_count"], bucket["service_count"]),
                "meal_plan_output_rate": _rate(bucket["meal_plan_output_count"], bucket["service_count"]),
                "cooking_output_rate": _rate(bucket["cooking_output_count"], bucket["service_count"]),
            }
        )

    record_gaps: list[dict[str, Any]] = []
    late_inputs: list[dict[str, Any]] = []
    for r in rows:
        if not r["actual_input"]:
            record_gaps.append(
                {"type": "실제 식수 미입력", "date": r["date"], "weekday": r["weekday"], "meal_type_name": r["meal_type_name"]}
            )
        if not r["preservation_completed"]:
            record_gaps.append(
                {"type": "보존식 기록 미완료", "date": r["date"], "weekday": r["weekday"], "meal_type_name": r["meal_type_name"]}
            )
        if not r["meal_plan_output"]:
            record_gaps.append(
                {"type": "식단표 미출력", "date": r["date"], "weekday": r["weekday"], "meal_type_name": r["meal_type_name"]}
            )
        if not r["cooking_output"]:
            record_gaps.append(
                {"type": "조리지시서 미출력", "date": r["date"], "weekday": r["weekday"], "meal_type_name": r["meal_type_name"]}
            )
        if r["actual_late"]:
            late_inputs.append(
                {
                    "date": r["date"],
                    "weekday": r["weekday"],
                    "meal_type_name": r["meal_type_name"],
                    "planned_count": r["planned_count"],
                    "actual_count": r["actual_count"],
                    "recorded_at": r["actual_recorded_at"],
                }
            )

    by_manager: dict[str, int] = defaultdict(int)
    temperature_records: list[dict[str, Any]] = []
    collected_count = 0
    disposed_count = 0
    for r in rows:
        if r["preservation_collected"]:
            collected_count += 1
        if r["preservation_disposed"]:
            disposed_count += 1
        if r["preservation_manager"]:
            by_manager[r["preservation_manager"]] += 1
        if r["preservation_temperature"]:
            temperature_records.append(
                {
                    "date": r["date"],
                    "meal_type_name": r["meal_type_name"],
                    "temperature": r["preservation_temperature"],
                    "manager_name": r["preservation_manager"],
                }
            )

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "meal_type": meal_type,
        "summary": {
            "service_count": total,
            "actual_input_count": actual_input_count,
            "actual_input_rate": _rate(actual_input_count, total),
            "preservation_count": preservation_count,
            "preservation_rate": _rate(preservation_count, total),
            "meal_plan_output_count": meal_plan_count,
            "meal_plan_output_rate": _rate(meal_plan_count, total),
            "cooking_output_count": cooking_count,
            "cooking_output_rate": _rate(cooking_count, total),
        },
        "breakdown": breakdown,
        "trend": trend,
        "anomalies": {
            "record_gaps": record_gaps,
            "late_inputs": late_inputs,
        },
        "preservation": {
            "collected_count": collected_count,
            "collected_rate": _rate(collected_count, total),
            "disposed_count": disposed_count,
            "disposed_rate": _rate(disposed_count, total),
            "by_manager": [
                {"manager_name": name, "count": count}
                for name, count in sorted(by_manager.items(), key=lambda x: x[1], reverse=True)
            ],
            "temperature_records": temperature_records,
        },
        "backdata": rows,
    }
