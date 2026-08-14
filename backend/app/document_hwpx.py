from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .document_builders import (
    CookingInstructionDocumentBuilder,
    MealPlanDocumentBuilder,
    PreservationRecordDocumentBuilder,
)
from .document_service import _period_label, _week_label
from .document_dtos import (
    CookingInstructionDayDTO,
    CookingInstructionDocumentDTO,
    CookingInstructionIngredientDTO,
    CookingInstructionMealDTO,
    CookingInstructionMenuDTO,
    MealPlanDayDTO,
    MealPlanDocumentDTO,
    MealPlanMealDTO,
    MealPlanWeekDTO,
    PreservationRecordBlockDTO,
    PreservationRecordDocumentDTO,
)
from .hwpx_engine import render_document
from .hwpx_pdf_renderer import default_pdf_renderer
from .models import MealService


@dataclass(slots=True)
class HwpxRenderRequest:
    document_type: str
    payload: dict[str, Any]


DocumentDTOType = MealPlanDocumentDTO | CookingInstructionDocumentDTO | PreservationRecordDocumentDTO


def build_document_dto(
    document_type: str,
    services: list[MealService],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DocumentDTOType:
    if document_type == "MEAL_PLAN":
        return MealPlanDocumentBuilder().from_services(services, start_date=start_date, end_date=end_date)
    if document_type == "COOKING_INSTRUCTION":
        return CookingInstructionDocumentBuilder().from_services(services, start_date=start_date, end_date=end_date)
    if document_type == "PRESERVATION_RECORD":
        return PreservationRecordDocumentBuilder().from_services(services, start_date=start_date, end_date=end_date)
    raise ValueError(f"지원하지 않는 문서 유형입니다: {document_type}")


def build_hwpx_render_request(document_type: str, dto: DocumentDTOType) -> HwpxRenderRequest:
    return HwpxRenderRequest(document_type=document_type, payload=_dto_to_payload(dto))


def generate_hwpx_bytes(
    document_type: str,
    services: list[MealService],
    template_path: str | Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[bytes, str]:
    dto = build_document_dto(document_type, services, start_date=start_date, end_date=end_date)
    render_request = build_hwpx_render_request(document_type, dto)
    content = render_document(template_path, render_request)
    return content, filename_for_dto(dto)


def generate_pdf_bytes(
    document_type: str,
    services: list[MealService],
    template_path: str | Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[bytes, str]:
    hwpx_bytes, hwpx_filename = generate_hwpx_bytes(
        document_type,
        services,
        template_path,
        start_date=start_date,
        end_date=end_date,
    )
    pdf_bytes = default_pdf_renderer().render(hwpx_bytes, source_name=hwpx_filename)
    return pdf_bytes, hwpx_filename[:-5] + ".pdf"


def filename_for_dto(dto: DocumentDTOType) -> str:
    if isinstance(dto, MealPlanDocumentDTO):
        return f"식단표_{dto.period.start_date:%Y%m%d}_{dto.period.end_date:%Y%m%d}.hwpx"
    if isinstance(dto, CookingInstructionDocumentDTO):
        return _dated_filename("조리지시서", [day.date for day in dto.days])
    if isinstance(dto, PreservationRecordDocumentDTO):
        return _dated_filename("보존식기록지", [record.date for record in dto.records])
    raise TypeError(f"지원하지 않는 DTO입니다: {type(dto)!r}")


def _dated_filename(prefix: str, dates: list[date]) -> str:
    if not dates:
        return f"{prefix}.hwpx"
    start = min(dates)
    end = max(dates)
    if start == end:
        return f"{prefix}_{start:%Y%m%d}.hwpx"
    return f"{prefix}_{start:%Y%m%d}_{end:%Y%m%d}.hwpx"


def _dto_to_payload(dto: DocumentDTOType) -> dict[str, Any]:
    if isinstance(dto, MealPlanDocumentDTO):
        return _meal_plan_payload(dto)
    if isinstance(dto, CookingInstructionDocumentDTO):
        return _cooking_payload(dto)
    if isinstance(dto, PreservationRecordDocumentDTO):
        return _preservation_payload(dto)
    raise TypeError(f"지원하지 않는 DTO입니다: {type(dto)!r}")


def _meal_plan_payload(dto: MealPlanDocumentDTO) -> dict[str, Any]:
    weeks: list[dict[str, Any]] = []
    for week in dto.weeks:
        weeks.append(
            {
                "start": week.start_date.isoformat(),
                "end": week.end_date.isoformat(),
                "week_label": _week_label(week.start_date),
                "days": [
                    {
                        "date": day.date.isoformat(),
                        "date_label": day.date_label,
                        "weekday": day.weekday,
                        "services": {
                            "LUNCH": _meal_plan_service(day.lunch),
                            "DINNER": _meal_plan_service(day.dinner),
                        },
                    }
                    for day in week.days
                ],
            }
        )
    period_label = _period_label(dto.weeks[0].start_date, dto.weeks[-1].end_date) if dto.weeks else ""
    return {
        "title": dto.title,
        "period_label": period_label,
        "weeks": weeks,
        "origin_info": "",
        "notice": "",
    }


def _meal_plan_service(meal: MealPlanMealDTO) -> dict[str, Any]:
    return {
        "meal_type": meal.meal_type.upper(),
        "meal_name": meal.meal_name,
        "planned_count": meal.meal_count,
        "service_time": meal.service_time.strftime("%H:%M") if meal.service_time else "",
        "concept_title": meal.concept_title,
        "menus": list(meal.menus),
    }


def _cooking_payload(dto: CookingInstructionDocumentDTO) -> dict[str, Any]:
    first_date = dto.days[0].date if dto.days else None
    last_date = dto.days[-1].date if dto.days else None
    period_label = _period_label(first_date, last_date) if first_date and last_date else ""
    return {
        "title": dto.title,
        "period_label": period_label,
        "days": [
            {
                "date": day.date.isoformat(),
                "date_label": day.date_label,
                "weekday": day.weekday,
                "services": [
                    _cooking_service(day.lunch),
                    _cooking_service(day.dinner),
                ],
            }
            for day in dto.days
        ],
    }


def _cooking_service(meal: CookingInstructionMealDTO) -> dict[str, Any]:
    return {
        "meal_type": meal.meal_type.upper(),
        "meal_name": meal.meal_name,
        "planned_count": meal.meal_count,
        "service_time": meal.service_time.strftime("%H:%M") if meal.service_time else "",
        "menus": [_cooking_menu(menu) for menu in meal.menus],
    }


def _cooking_menu(menu: CookingInstructionMenuDTO) -> dict[str, Any]:
    return {
        "name": menu.name,
        "ingredients": [_cooking_ingredient(item) for item in menu.ingredients],
        "instruction": menu.instruction or "",
        "note": menu.note or "",
    }


def _cooking_ingredient(item: CookingInstructionIngredientDTO) -> dict[str, Any]:
    return {
        "name": item.name,
        "quantity_total": item.quantity,
        "quantity_per_100": item.quantity_per_100,
        "unit": item.unit or "",
        "remark": item.remark or "",
    }


def _preservation_payload(dto: PreservationRecordDocumentDTO) -> dict[str, Any]:
    first_date = dto.records[0].date if dto.records else None
    last_date = dto.records[-1].date if dto.records else None
    period_label = _period_label(first_date, last_date) if first_date and last_date else ""
    return {
        "title": dto.title,
        "period_label": period_label,
        "records": [_preservation_record(record) for record in dto.records],
    }


def _preservation_record(record: PreservationRecordBlockDTO) -> dict[str, Any]:
    collected = record.collected_at
    sample_datetime = collected.strftime("%Y년 %m월 %d일 %H시 %M분") if collected else ""
    disposal = record.disposal_at
    discard_datetime = disposal.strftime("%Y년 %m월 %d일 %H시 %M분") if disposal else ""
    return {
        "service_id": None,
        "date": record.date.isoformat(),
        "date_label": f"{record.date_label} {record.weekday} {record.meal_name}",
        "weekday": record.weekday,
        "meal_name": record.meal_name,
        "sample_datetime": sample_datetime,
        "manager_name": record.manager or "",
        "menu_items": list(record.menus),
        "freezer_temperature": record.freezer_temperature or "",
        "discard_datetime": discard_datetime,
        "collector_name": record.collector or "",
        "collection_time": record.collection_time or "",
    }
