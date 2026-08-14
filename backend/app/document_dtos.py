from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentPeriodDTO(DocumentDTO):
    start_date: date
    end_date: date


class MealPlanMealDTO(DocumentDTO):
    meal_type: Literal["lunch", "dinner"]
    meal_name: str
    meal_count: int | None = None
    service_time: time | None = None
    concept_title: str | None = None
    menus: list[str] = Field(default_factory=list)


class MealPlanDayDTO(DocumentDTO):
    date: date
    date_label: str
    weekday: str
    lunch: MealPlanMealDTO
    dinner: MealPlanMealDTO


class MealPlanWeekDTO(DocumentDTO):
    start_date: date
    end_date: date
    days: list[MealPlanDayDTO] = Field(default_factory=list)


class MealPlanDocumentDTO(DocumentDTO):
    period: DocumentPeriodDTO
    title: str = "식단표"
    weeks: list[MealPlanWeekDTO] = Field(default_factory=list)


class CookingInstructionIngredientDTO(DocumentDTO):
    name: str
    quantity: float | None = None
    quantity_per_100: float | None = None
    unit: str | None = None
    remark: str | None = None


class CookingInstructionMenuDTO(DocumentDTO):
    name: str
    ingredients: list[CookingInstructionIngredientDTO] = Field(default_factory=list)
    instruction: str | None = None
    note: str | None = None


class CookingInstructionMealDTO(DocumentDTO):
    meal_type: Literal["lunch", "dinner"]
    meal_name: str
    meal_count: int | None = None
    service_time: time | None = None
    menus: list[CookingInstructionMenuDTO] = Field(default_factory=list)


class CookingInstructionDayDTO(DocumentDTO):
    date: date
    date_label: str
    weekday: str
    lunch: CookingInstructionMealDTO
    dinner: CookingInstructionMealDTO


class CookingInstructionDocumentDTO(DocumentDTO):
    title: str = "조리지시서"
    days: list[CookingInstructionDayDTO] = Field(default_factory=list)


class PreservationRecordBlockDTO(DocumentDTO):
    date: date
    date_label: str
    weekday: str
    meal_type: Literal["lunch", "dinner"]
    meal_name: str
    menus: list[str] = Field(default_factory=list)
    collection_time: str | None = None
    collected_at: datetime | None = None
    manager: str | None = None
    freezer_temperature: str | None = None
    discard_date: date | None = None
    disposal_at: datetime | None = None
    collector: str | None = None


class PreservationRecordDocumentDTO(DocumentDTO):
    title: str = "보존식 기록지"
    records: list[PreservationRecordBlockDTO] = Field(default_factory=list)
