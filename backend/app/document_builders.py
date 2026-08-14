from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Generic, Literal, TypeVar

from sqlalchemy.orm import Session

from .document_dtos import (
    CookingInstructionDayDTO,
    CookingInstructionDocumentDTO,
    CookingInstructionIngredientDTO,
    CookingInstructionMealDTO,
    CookingInstructionMenuDTO,
    DocumentPeriodDTO,
    MealPlanDayDTO,
    MealPlanDocumentDTO,
    MealPlanMealDTO,
    MealPlanWeekDTO,
    PreservationRecordBlockDTO,
    PreservationRecordDocumentDTO,
)
from .document_service import resolve_services
from .models import MealService, MealServiceMenu, MealServiceMenuIngredient
from .serializers import MEAL_NAMES, MEAL_SORT

TDocument = TypeVar("TDocument")
MealBlockType = Literal["lunch", "dinner"]


WEEKDAY_LABELS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


class BaseDocumentBuilder(Generic[TDocument]):
    def build(
        self,
        db: Session,
        *,
        service_ids: list[int] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TDocument:
        services = resolve_services(db, service_ids=service_ids, start_date=start_date, end_date=end_date)
        if not services:
            raise ValueError("출력할 배식이 없습니다.")
        return self.from_services(services, start_date=start_date, end_date=end_date)

    def from_services(
        self,
        services: list[MealService],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TDocument:
        raise NotImplementedError


class MealPlanDocumentBuilder(BaseDocumentBuilder[MealPlanDocumentDTO]):
    def from_services(
        self,
        services: list[MealService],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> MealPlanDocumentDTO:
        services_by_date = self._services_by_date(services)
        if start_date is None:
            start_date = min(service.service_date for service in services)
        if end_date is None:
            end_date = max(service.service_date for service in services)
        monday = start_date - timedelta(days=start_date.weekday())
        weeks: list[MealPlanWeekDTO] = []
        cursor = monday
        while cursor <= end_date:
            days = [self._build_day(cursor + timedelta(days=offset), services_by_date) for offset in range(5)]
            week_end = cursor + timedelta(days=4)
            weeks.append(MealPlanWeekDTO(start_date=cursor, end_date=week_end, days=days))
            cursor += timedelta(days=7)
        return MealPlanDocumentDTO(
            period=DocumentPeriodDTO(start_date=start_date, end_date=end_date),
            weeks=weeks,
        )

    def _services_by_date(self, services: list[MealService]) -> dict[date, dict[str, MealService]]:
        result: dict[date, dict[str, MealService]] = defaultdict(dict)
        for service in services:
            result[service.service_date][service.meal_type] = service
        return result

    def _build_day(self, current: date, services_by_date: dict[date, dict[str, MealService]]) -> MealPlanDayDTO:
        date_services = services_by_date.get(current, {})
        lunch = self._build_meal_block("lunch", date_services.get("LUNCH"))
        dinner = self._build_meal_block("dinner", date_services.get("DINNER"))
        return MealPlanDayDTO(
            date=current,
            date_label=f"{current:%m.%d}({WEEKDAY_LABELS[current.weekday()][0]})",
            weekday=WEEKDAY_LABELS[current.weekday()],
            lunch=lunch,
            dinner=dinner,
        )

    def _build_meal_block(self, meal_type: MealBlockType, service: MealService | None) -> MealPlanMealDTO:
        if not service:
            return MealPlanMealDTO(
                meal_type=meal_type,
                meal_name=MEAL_NAMES.get(meal_type.upper(), meal_type),
                meal_count=None,
                service_time=None,
                concept_title=None,
                menus=[],
            )
        return MealPlanMealDTO(
            meal_type=meal_type,
            meal_name=MEAL_NAMES.get(service.meal_type, service.meal_type),
            meal_count=service.planned_count,
            service_time=service.service_time,
            concept_title=service.concept_title,
            menus=[menu.menu_name_snapshot for menu in service.menus],
        )


class CookingInstructionDocumentBuilder(BaseDocumentBuilder[CookingInstructionDocumentDTO]):
    def from_services(
        self,
        services: list[MealService],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> CookingInstructionDocumentDTO:
        grouped = defaultdict(list)
        for service in services:
            grouped[service.service_date].append(service)
        days: list[CookingInstructionDayDTO] = []
        for current in sorted(grouped):
            by_type = {service.meal_type: service for service in grouped[current]}
            days.append(
                CookingInstructionDayDTO(
                    date=current,
                    date_label=current.strftime("%Y년 %m월 %d일"),
                    weekday=WEEKDAY_LABELS[current.weekday()],
                    lunch=self._build_meal_block("lunch", by_type.get("LUNCH")),
                    dinner=self._build_meal_block("dinner", by_type.get("DINNER")),
                )
            )
        return CookingInstructionDocumentDTO(days=days)

    def _build_meal_block(self, meal_type: MealBlockType, service: MealService | None) -> CookingInstructionMealDTO:
        if not service:
            return CookingInstructionMealDTO(
                meal_type=meal_type,
                meal_name=MEAL_NAMES.get(meal_type.upper(), meal_type),
                meal_count=None,
                service_time=None,
                menus=[],
            )
        return CookingInstructionMealDTO(
            meal_type=meal_type,
            meal_name=MEAL_NAMES.get(service.meal_type, service.meal_type),
            meal_count=service.planned_count,
            service_time=service.service_time,
            menus=[self._build_menu(menu) for menu in service.menus],
        )

    def _build_menu(self, menu: MealServiceMenu) -> CookingInstructionMenuDTO:
        ingredients = [self._build_ingredient(item) for item in menu.ingredients]
        return CookingInstructionMenuDTO(
            name=menu.menu_name_snapshot,
            ingredients=ingredients,
            instruction=menu.cooking_instruction or "",
            note=menu.cooking_note or menu.note or "",
        )

    def _build_ingredient(self, item: MealServiceMenuIngredient) -> CookingInstructionIngredientDTO:
        return CookingInstructionIngredientDTO(
            name=item.ingredient_name_snapshot,
            quantity=item.quantity_total,
            quantity_per_100=item.quantity_per_100,
            unit=item.unit,
            remark=item.source_note,
        )


class PreservationRecordDocumentBuilder(BaseDocumentBuilder[PreservationRecordDocumentDTO]):
    def from_services(
        self,
        services: list[MealService],
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> PreservationRecordDocumentDTO:
        records: list[PreservationRecordBlockDTO] = []
        ordered_services = sorted(services, key=lambda service: (service.service_date, MEAL_SORT.get(service.meal_type, 99)))
        for service in ordered_services:
            record = service.preservation
            records.append(
                PreservationRecordBlockDTO(
                    date=service.service_date,
                    date_label=service.service_date.strftime("%Y년 %m월 %d일"),
                    weekday=WEEKDAY_LABELS[service.service_date.weekday()],
                    meal_type="lunch" if service.meal_type == "LUNCH" else "dinner",
                    meal_name=MEAL_NAMES.get(service.meal_type, service.meal_type),
                    menus=[menu.menu_name_snapshot for menu in service.menus],
                    collection_time=record.collection_time if record else None,
                    collected_at=record.collected_at if record else None,
                    manager=record.manager_name if record else None,
                    freezer_temperature=record.freezer_temperature if record else None,
                    discard_date=record.disposal_at.date() if record and record.disposal_at else None,
                    disposal_at=record.disposal_at if record else None,
                    collector=record.collector_name if record else None,
                )
            )
        return PreservationRecordDocumentDTO(records=records)
