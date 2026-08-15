from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MealActual, MealService, MealServiceMenu, Menu

WEEKDAY_NAMES = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
MEAL_TYPE_NAMES = {"LUNCH": "중식", "DINNER": "석식"}


def _meal_type_code(meal_type: str) -> str | None:
    return {"lunch": "LUNCH", "dinner": "DINNER"}.get(meal_type)


def _usage_rows(
    db: Session, start: date, end: date, meal_type: str = "all", menu_id: int | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(
            MealService.id,
            MealService.service_date,
            MealService.meal_type,
            MealService.planned_count,
            MealActual.actual_count,
            MealServiceMenu.menu_id,
            MealServiceMenu.menu_name_snapshot,
            Menu.role,
        )
        .join(MealServiceMenu, MealServiceMenu.meal_service_id == MealService.id)
        .outerjoin(MealActual, MealActual.meal_service_id == MealService.id)
        .outerjoin(Menu, Menu.id == MealServiceMenu.menu_id)
        .where(MealService.service_date.between(start, end))
        .order_by(MealService.service_date, MealService.meal_type, MealServiceMenu.sort_order)
    )
    if menu_id is not None:
        stmt = stmt.where(MealServiceMenu.menu_id == menu_id)
    else:
        code = _meal_type_code(meal_type)
        if code:
            stmt = stmt.where(MealService.meal_type == code)
    rows = db.execute(stmt).all()
    return [
        {
            "service_id": row[0],
            "date": row[1],
            "meal_type": row[2],
            "meal_type_name": MEAL_TYPE_NAMES.get(row[2], row[2]),
            "planned_count": row[3],
            "actual_count": row[4],
            "menu_id": row[5],
            "menu_name": row[6],
            "role": row[7] or "기타",
        }
        for row in rows
    ]


def _menu_key(row: dict[str, Any]) -> str:
    return str(row["menu_id"]) if row["menu_id"] is not None else f"name:{row['menu_name']}"


def _max_in_window(dates: list[date], window_days: int) -> int:
    dates = sorted(set(dates))
    best = 0
    for i in range(len(dates)):
        j = i
        while j < len(dates) and (dates[j] - dates[i]).days <= window_days:
            j += 1
        best = max(best, j - i)
    return best


def _unused_menus(db: Session, end: date, unused_days: int) -> list[dict[str, Any]]:
    cutoff = end - timedelta(days=unused_days)
    menus = db.scalars(select(Menu).where(Menu.active.is_(True))).all()
    menu_ids = [menu.id for menu in menus]
    used_in_window: set[int] = set()
    last_dates: dict[int, date] = {}
    if menu_ids:
        used_in_window = set(
            db.scalars(
                select(MealServiceMenu.menu_id)
                .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
                .where(MealService.service_date.between(cutoff, end), MealServiceMenu.menu_id.is_not(None))
            ).all()
        )
        history = db.execute(
            select(MealServiceMenu.menu_id, MealService.service_date)
            .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
            .where(MealServiceMenu.menu_id.in_(menu_ids), MealService.service_date < cutoff)
            .order_by(MealService.service_date)
        ).all()
        for menu_id, service_date in history:
            last_dates[menu_id] = service_date
    result = []
    for menu in menus:
        if menu.id in used_in_window:
            continue
        last = last_dates.get(menu.id)
        result.append(
            {
                "menu_id": menu.id,
                "menu_name": menu.name,
                "last_used": last.isoformat() if last else None,
                "days_since_last": (end - last).days if last else None,
            }
        )
    result.sort(key=lambda m: m["days_since_last"] if m["days_since_last"] is not None else 10**9, reverse=True)
    return result


def menu_statistics(db: Session, start: date, end: date, meal_type: str = "all", unused_days: int = 90) -> dict[str, Any]:
    rows = _usage_rows(db, start, end, meal_type)
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _menu_key(row)
        group = groups.setdefault(
            key,
            {
                "key": key,
                "menu_id": row["menu_id"],
                "menu_name": row["menu_name"],
                "role": row["role"],
                "dates": [],
                "lunch": 0,
                "dinner": 0,
                "rows": [],
            },
        )
        group["dates"].append(row["date"])
        if row["meal_type"] == "LUNCH":
            group["lunch"] += 1
        else:
            group["dinner"] += 1
        group["rows"].append(row)

    used_ids = {group["menu_id"] for group in groups.values() if group["menu_id"] is not None}
    prev_ids: set[int] = set()
    if used_ids:
        prev_ids = set(
            db.scalars(
                select(MealServiceMenu.menu_id)
                .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
                .where(MealService.service_date < start, MealServiceMenu.menu_id.in_(used_ids))
            ).all()
        )

    top: list[dict[str, Any]] = []
    repeats: list[dict[str, Any]] = []
    new_count = 0
    for group in groups.values():
        dates = sorted(set(group["dates"]))
        group["usage_count"] = len(group["rows"])
        group["first_used"] = dates[0].isoformat()
        group["last_used"] = dates[-1].isoformat()
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        group["avg_interval"] = round(sum(gaps) / len(gaps), 1) if gaps else None
        if group["menu_id"] is not None and group["menu_id"] not in prev_ids:
            new_count += 1
        short = _max_in_window(dates, 14)
        long = _max_in_window(dates, 28)
        if short >= 2:
            repeats.append(
                {"menu_id": group["menu_id"], "menu_name": group["menu_name"], "type": "단기 반복", "count": short, "window_days": 14}
            )
        if long >= 3:
            repeats.append(
                {"menu_id": group["menu_id"], "menu_name": group["menu_name"], "type": "과다 반복", "count": long, "window_days": 28}
            )
        top.append(group)
    top.sort(key=lambda g: g["usage_count"], reverse=True)
    repeats.sort(key=lambda r: r["count"], reverse=True)

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
                    "role": row["role"],
                    "menu_name": row["menu_name"],
                    "menu_id": row["menu_id"],
                    "planned_count": row["planned_count"],
                    "actual_count": row["actual_count"],
                    "previous_used_date": prev_date.isoformat() if prev_date else None,
                    "days_since_previous": (row["date"] - prev_date).days if prev_date else None,
                }
            )
            prev_date = row["date"]

    unused = _unused_menus(db, end, unused_days)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "meal_type": meal_type,
        "unused_days": unused_days,
        "summary": {
            "unique_menu_count": len(groups),
            "total_usage_count": len(rows),
            "new_menu_count": new_count,
            "repeat_menu_count": len({r["menu_name"] for r in repeats}),
            "unused_menu_count": len(unused),
        },
        "top_menus": [
            {
                "menu_id": group["menu_id"],
                "menu_name": group["menu_name"],
                "role": group["role"],
                "usage_count": group["usage_count"],
                "lunch_count": group["lunch"],
                "dinner_count": group["dinner"],
                "first_used": group["first_used"],
                "last_used": group["last_used"],
                "avg_interval": group["avg_interval"],
            }
            for group in top[:15]
        ],
        "repeats": repeats[:10],
        "unused_menus": unused,
        "backdata": backdata,
    }


def menu_detail(db: Session, menu_id: int, start: date, end: date, meal_type: str = "all") -> dict[str, Any] | None:
    rows = _usage_rows(db, start, end, meal_type, menu_id=menu_id)
    menu = db.get(Menu, menu_id)
    if not rows:
        if not menu:
            return None
        return {
            "menu_id": menu_id,
            "menu_name": menu.name,
            "role": menu.role,
            "summary": {
                "usage_count": 0,
                "lunch_count": 0,
                "dinner_count": 0,
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
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    monthly: Counter[str] = Counter()
    for row in rows:
        monthly[row["date"].strftime("%Y-%m")] += 1

    service_ids = list({row["service_id"] for row in rows})
    co_rows = db.execute(
        select(MealServiceMenu.menu_id, MealServiceMenu.menu_name_snapshot)
        .where(MealServiceMenu.meal_service_id.in_(service_ids), MealServiceMenu.menu_id != menu_id)
    ).all()
    co_count: Counter[str] = Counter()
    co_names: dict[str, str] = {}
    for mid, name in co_rows:
        key = str(mid) if mid is not None else f"name:{name}"
        co_count[key] += 1
        co_names[key] = name
    co_used = [
        {"menu_id": int(key) if key.isdigit() else None, "menu_name": co_names[key], "count": count}
        for key, count in co_count.most_common(10)
    ]

    full_dates = db.scalars(
        select(MealService.service_date)
        .join(MealServiceMenu, MealServiceMenu.meal_service_id == MealService.id)
        .where(MealServiceMenu.menu_id == menu_id, MealService.service_date <= end)
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
                "role": row["role"],
                "menu_name": row["menu_name"],
                "menu_id": row["menu_id"],
                "planned_count": row["planned_count"],
                "actual_count": row["actual_count"],
                "previous_used_date": prev_date.isoformat() if prev_date else None,
                "days_since_previous": (row["date"] - prev_date).days if prev_date else None,
            }
        )

    return {
        "menu_id": menu_id,
        "menu_name": rows[0]["menu_name"],
        "role": rows[0]["role"],
        "summary": {
            "usage_count": len(rows),
            "lunch_count": lunch,
            "dinner_count": dinner,
            "first_used": dates[0].isoformat(),
            "last_used": dates[-1].isoformat(),
            "avg_interval": round(sum(gaps) / len(gaps), 1) if gaps else None,
        },
        "monthly_usage": [{"month": month, "count": count} for month, count in sorted(monthly.items())],
        "recent_history": [
            {
                "date": row["date"].isoformat(),
                "meal_type_name": row["meal_type_name"],
                "planned_count": row["planned_count"],
                "actual_count": row["actual_count"],
            }
            for row in rows[-20:]
        ],
        "co_used": co_used,
        "backdata": backdata,
    }
