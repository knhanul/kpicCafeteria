from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .models import (
    DocumentPreview,
    MealService,
    MealServiceMenu,
    Menu,
    PreservationRecord,
    Recipe,
    RecipeIngredient,
)
from .serializers import MEAL_NAMES
from .hwpx_service import active_template

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _week_label(d: date) -> str:
    monday = d - timedelta(days=d.weekday())
    first_of_month = monday.replace(day=1)
    first_weekday = first_of_month.weekday()
    if first_weekday <= 4:
        week1_monday = first_of_month - timedelta(days=first_weekday)
    else:
        week1_monday = first_of_month + timedelta(days=7 - first_weekday)
    if monday < week1_monday:
        return _week_label(first_of_month - timedelta(days=1))
    week_num = (monday - week1_monday).days // 7 + 1
    return f"{monday.month}월 {week_num}주"


def _period_label(first: date, last: date) -> str:
    left = _week_label(first)
    right = _week_label(last)
    if left == right:
        return left
    if left.split("월")[0] == right.split("월")[0]:
        return f"{left.split(' ')[0]} {left.split(' ')[1]}~{right.split(' ')[1]}"
    return f"{left}~{right}"


def _service_query():
    return select(MealService).options(
        selectinload(MealService.menus).selectinload(MealServiceMenu.ingredients),
        selectinload(MealService.menus).selectinload(MealServiceMenu.menu),
        selectinload(MealService.menus)
        .selectinload(MealServiceMenu.source_recipe)
        .selectinload(Recipe.ingredients)
        .selectinload(RecipeIngredient.ingredient),
        selectinload(MealService.preservation),
        selectinload(MealService.actual),
    )


def resolve_services(
    db: Session,
    service_ids: list[int] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[MealService]:
    stmt = _service_query()
    if service_ids:
        stmt = stmt.where(MealService.id.in_(service_ids))
    elif start_date and end_date:
        stmt = stmt.where(MealService.service_date.between(start_date, end_date))
    else:
        return []
    return db.scalars(stmt.order_by(MealService.service_date, MealService.meal_type)).unique().all()


def _menu_ingredients(menu_item: MealServiceMenu) -> list[dict[str, Any]]:
    result = []
    if menu_item.ingredients:
        source = menu_item.ingredients
        for item in source:
            result.append(
                {
                    "name": item.ingredient_name_snapshot,
                    "quantity_total": item.quantity_total,
                    "quantity_per_100": item.quantity_per_100,
                    "unit": item.unit or "",
                }
            )
    elif menu_item.source_recipe:
        service_count = menu_item.service.planned_count or 0
        for item in menu_item.source_recipe.ingredients:
            total = item.quantity_per_100 * service_count / 100 if item.quantity_per_100 is not None else None
            result.append(
                {
                    "name": item.ingredient.name,
                    "quantity_total": total,
                    "quantity_per_100": item.quantity_per_100,
                    "unit": item.unit or item.ingredient.default_unit or "",
                }
            )
    return result


def build_payload(document_type: str, services: list[MealService]) -> dict[str, Any]:
    if document_type == "MEAL_PLAN":
        return _meal_plan_payload(services)
    if document_type == "COOKING_INSTRUCTION":
        return _cooking_payload(services)
    if document_type == "PRESERVATION_RECORD":
        return _preservation_payload(services)
    raise ValueError("지원하지 않는 문서 유형입니다.")


def _meal_plan_payload(services: list[MealService]) -> dict[str, Any]:
    by_date: dict[date, dict[str, Any]] = defaultdict(dict)
    for service in services:
        by_date[service.service_date][service.meal_type] = {
            "id": service.id,
            "meal_name": MEAL_NAMES.get(service.meal_type, service.meal_type),
            "planned_count": service.planned_count,
            "service_time": service.service_time.strftime("%H:%M") if service.service_time else "",
            "concept_title": service.concept_title,
            "menus": [f"★ {item.menu_name_snapshot}" if item.is_representative else item.menu_name_snapshot for item in service.menus],
        }
    if not by_date:
        return {"title": "식단표", "weeks": [], "service_ids": []}
    start = min(by_date)
    monday = start - timedelta(days=start.weekday())
    end = max(by_date)
    weeks = []
    cursor = monday
    while cursor <= end:
        days = []
        for offset in range(5):
            current = cursor + timedelta(days=offset)
            days.append(
                {
                    "date": current.isoformat(),
                    "date_label": f"{current:%m.%d}({['월', '화', '수', '목', '금'][offset]})",
                    "weekday": ["월", "화", "수", "목", "금"][offset],
                    "services": by_date.get(current, {}),
                }
            )
        weeks.append({"start": cursor.isoformat(), "end": (cursor + timedelta(days=4)).isoformat(), "week_label": _week_label(cursor), "days": days})
        cursor += timedelta(days=7)
    period_label = _period_label(monday, cursor - timedelta(days=7) + timedelta(days=4)) if weeks else ""
    return {"title": "식단표", "period_label": period_label, "weeks": weeks, "service_ids": [s.id for s in services]}


def _cooking_payload(services: list[MealService]) -> dict[str, Any]:
    days: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for service in services:
        menus = []
        for item in service.menus:
            menus.append(
                {
                    "name": item.menu_name_snapshot,
                    "ingredients": _menu_ingredients(item),
                    "instruction": "",
                    "note": item.note or "",
                }
            )
        days[service.service_date].append(
            {
                "id": service.id,
                "meal_type": service.meal_type,
                "meal_name": MEAL_NAMES.get(service.meal_type, service.meal_type),
                "planned_count": service.planned_count,
                "service_time": service.service_time.strftime("%H:%M") if service.service_time else "",
                "menus": menus,
            }
        )
    sorted_days = sorted(days.items())
    first_date = sorted_days[0][0]
    last_date = sorted_days[-1][0]
    return {
        "title": "조리지시서",
        "period_label": _period_label(first_date, last_date),
        "days": [
            {
                "date": current.isoformat(),
                "date_label": current.strftime("%Y년 %m월 %d일"),
                "weekday": ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][current.weekday()],
                "services": sorted(values, key=lambda x: 1 if x["meal_type"] == "LUNCH" else 2),
            }
            for current, values in sorted_days
        ],
        "service_ids": [s.id for s in services],
    }


def _preservation_payload(services: list[MealService]) -> dict[str, Any]:
    records = []
    for service in services:
        record = service.preservation
        collected = record.collected_at if record else None
        disposal = record.disposal_at if record else None
        date_label = service.service_date.strftime("%Y년 %m월 %d일")
        weekday = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][service.service_date.weekday()]
        meal_name = MEAL_NAMES.get(service.meal_type, service.meal_type)
        records.append(
            {
                "service_id": service.id,
                "date": service.service_date.isoformat(),
                "date_label": f"{date_label} {weekday} {meal_name}",
                "weekday": weekday,
                "meal_name": meal_name,
                "sample_datetime": collected.strftime("%Y년 %m월 %d일 %H시 %M분") if collected else "",
                "manager_name": record.manager_name if record else "",
                "menu_items": [item.menu_name_snapshot for item in service.menus],
                "freezer_temperature": record.freezer_temperature if record else "",
                "discard_datetime": disposal.strftime("%Y년 %m월 %d일 %H시 %M분") if disposal else "",
                "collector_name": record.collector_name if record else "",
                "collection_time": record.collection_time if record else "",
            }
        )
    first_date = min((s.service_date for s in services), default=None)
    last_date = max((s.service_date for s in services), default=None)
    period_label = _period_label(first_date, last_date) if first_date and last_date else ""
    return {"title": "보존식 기록지", "period_label": period_label, "records": records, "service_ids": [s.id for s in services]}


def create_preview(db: Session, document_type: str, services: list[MealService], user_id: int | None) -> DocumentPreview:
    payload = build_payload(document_type, services)
    token = secrets.token_urlsafe(30)
    preview = DocumentPreview(
        token=token,
        document_type=document_type,
        payload=payload,
        service_ids=[service.id for service in services],
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
    )
    db.add(preview)
    db.commit()
    return preview


def render_preview_html(preview: DocumentPreview, toolbar: bool = True) -> str:
    template_map = {
        "MEAL_PLAN": "documents/meal_plan.html",
        "COOKING_INSTRUCTION": "documents/cooking_instruction.html",
        "PRESERVATION_RECORD": "documents/preservation.html",
    }
    template = TEMPLATES.get_template(template_map[preview.document_type])
    return template.render(
        preview=preview,
        document=preview.payload,
        toolbar=toolbar,
        pdf_enabled=not settings.desktop_hwp_only,
    )


def render_pdf(db: Session, preview: DocumentPreview) -> tuple[bytes, str]:
    from .document_hwpx import generate_pdf_bytes

    template = active_template(db, preview.document_type)
    if not template:
        raise ValueError("활성 HWPX 템플릿이 없습니다.")
    services = resolve_services(db, preview.service_ids)
    if not services:
        raise ValueError("출력할 배식이 없습니다.")
    return generate_pdf_bytes(preview.document_type, services, template.storage_path)
