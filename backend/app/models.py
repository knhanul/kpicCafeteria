from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=dialect.name != "sqlite"))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.replace(tzinfo=None) if dialect.name == "sqlite" else normalized

    def process_result_value(self, value, _dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str] = mapped_column(String(100), default="영양사")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(20), default="user")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class MealTypeSetting(Base):
    __tablename__ = "meal_type_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    default_planned_count: Mapped[int] = mapped_column(Integer, default=0)
    default_service_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(200), index=True)
    role: Mapped[str] = mapped_column(String(40), default="기타", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    review_status: Mapped[str] = mapped_column(String(40), default="정상")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    recipes: Mapped[list[Recipe]] = relationship(
        back_populates="menu", cascade="all, delete-orphan", order_by="Recipe.version"
    )


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_code: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    stat_group: Mapped[str] = mapped_column(String(60), default="기타", index=True)
    default_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    kg_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    review_status: Mapped[str] = mapped_column(String(40), default="정상")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    aliases: Mapped[list[IngredientAlias]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")


class IngredientAlias(Base):
    __tablename__ = "ingredient_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id", ondelete="CASCADE"), index=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)

    ingredient: Mapped[Ingredient] = relationship(back_populates="aliases")


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        UniqueConstraint("menu_id", "version", name="uq_recipe_menu_version"),
        UniqueConstraint("menu_id", "composition_key", name="uq_recipe_menu_composition"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="기본 레시피")
    version: Mapped[int] = mapped_column(Integer, default=1)
    composition_key: Mapped[str] = mapped_column(String(1000), default="", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    menu: Mapped[Menu] = relationship(back_populates="recipes")
    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeIngredient.sort_order"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=1)
    quantity_per_100: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(60), default="정상")

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship()


class MealService(Base):
    __tablename__ = "meal_services"
    __table_args__ = (UniqueConstraint("service_date", "meal_type", name="uq_meal_service_date_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    meal_type: Mapped[str] = mapped_column(String(30), index=True)
    planned_count: Mapped[int] = mapped_column(Integer, default=0)
    service_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    concept_title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    meal_plan_output_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cooking_output_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    menus: Mapped[list[MealServiceMenu]] = relationship(
        back_populates="service", cascade="all, delete-orphan", order_by="MealServiceMenu.sort_order"
    )
    preservation: Mapped[PreservationRecord | None] = relationship(
        back_populates="service", uselist=False, cascade="all, delete-orphan"
    )
    actual: Mapped[MealActual | None] = relationship(
        back_populates="service", uselist=False, cascade="all, delete-orphan"
    )


class MealServiceMenu(Base):
    __tablename__ = "meal_service_menus"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_service_id: Mapped[int] = mapped_column(ForeignKey("meal_services.id", ondelete="CASCADE"), index=True)
    menu_id: Mapped[int | None] = mapped_column(ForeignKey("menus.id", ondelete="SET NULL"), nullable=True, index=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=1)
    menu_name_snapshot: Mapped[str] = mapped_column(String(200))
    recipe_name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipe_version_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_representative: Mapped[bool] = mapped_column(Boolean, default=False)

    service: Mapped[MealService] = relationship(back_populates="menus")
    menu: Mapped[Menu | None] = relationship(foreign_keys=[menu_id])
    source_recipe: Mapped[Recipe | None] = relationship(foreign_keys=[recipe_id])
    ingredients: Mapped[list[MealServiceMenuIngredient]] = relationship(
        back_populates="service_menu", cascade="all, delete-orphan", order_by="MealServiceMenuIngredient.sort_order"
    )


class MealServiceMenuIngredient(Base):
    __tablename__ = "meal_service_menu_ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_service_menu_id: Mapped[int] = mapped_column(
        ForeignKey("meal_service_menus.id", ondelete="CASCADE"), index=True
    )
    ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=1)
    ingredient_name_snapshot: Mapped[str] = mapped_column(String(200))
    quantity_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_per_100: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_row: Mapped[str | None] = mapped_column(Text, nullable=True)

    service_menu: Mapped[MealServiceMenu] = relationship(back_populates="ingredients")
    ingredient: Mapped[Ingredient | None] = relationship()


class PreservationRecord(Base):
    __tablename__ = "preservation_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_service_id: Mapped[int] = mapped_column(
        ForeignKey("meal_services.id", ondelete="CASCADE"), unique=True, index=True
    )
    collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    manager_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    freezer_temperature: Mapped[str | None] = mapped_column(String(30), nullable=True)
    disposal_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    collector_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    collection_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    service: Mapped[MealService] = relationship(back_populates="preservation")


class MealActual(Base):
    __tablename__ = "meal_actuals"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_service_id: Mapped[int] = mapped_column(
        ForeignKey("meal_services.id", ondelete="CASCADE"), unique=True, index=True
    )
    actual_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    service: Mapped[MealService] = relationship(back_populates="actual")


class DocumentTemplate(Base):
    __tablename__ = "document_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(600))
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    placeholder_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class DocumentPreview(Base):
    __tablename__ = "document_previews"

    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_type: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    service_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(600))
    status: Mapped[str] = mapped_column(String(30), default="PREVIEWED")
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class WeatherUploadHistory(Base):
    __tablename__ = "weather_upload_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    stations: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0)
    updated_rows: Mapped[int] = mapped_column(Integer, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED", index=True)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class WeatherHistory(Base):
    __tablename__ = "weather_history"
    __table_args__ = (UniqueConstraint("observation_date", "station_id", name="uq_weather_history_date_station"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    observation_date: Mapped[date] = mapped_column(Date, index=True)
    station_id: Mapped[str] = mapped_column(String(80), index=True)
    station_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    avg_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    snow_depth: Mapped[float | None] = mapped_column(Float, nullable=True)
    sunshine_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="KMA_FILE")
    upload_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("weather_upload_history.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BackupRecord(Base):
    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backup_type: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="completed")
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class DataArchive(Base):
    __tablename__ = "data_archives"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class OrderGroup(Base):
    __tablename__ = "order_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True, index=True)
    ingredient_name_snapshot: Mapped[str] = mapped_column(String(200))
    order_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_required_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    required_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("service_date", "ingredient_id", name="uq_order_item_date_ingredient"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ingredient_name_snapshot: Mapped[str] = mapped_column(String(200))
    required_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    required_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    order_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    ingredient: Mapped[Ingredient | None] = relationship()
    order_group: Mapped[OrderGroup | None] = relationship()
