from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user
from ..models import (
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    MealTypeSetting,
    OrderGroup,
    OrderItem,
    User,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])

ORDER_STATUSES = {"pending", "ordered", "skipped"}


def _resolved_range(start_date: date, end_date: date) -> tuple[date, date]:
    if start_date > end_date:
        return end_date, start_date
    return start_date, end_date


def _default_order_date(service_date: date) -> date:
    return service_date - timedelta(days=1)


def _load_plan_items(db: Session, start: date, end: date) -> dict[tuple[Any, Any], dict[str, Any]]:
    """Aggregate meal-plan ingredients by (service_date, ingredient_key)."""
    services = db.scalars(
        select(MealService)
        .where(MealService.service_date.between(start, end))
        .options(
            selectinload(MealService.menus).selectinload(MealServiceMenu.ingredients).selectinload(MealServiceMenuIngredient.ingredient),
        )
        .order_by(MealService.service_date, MealService.meal_type)
    ).unique().all()

    meal_type_names = {s.code: s.name for s in db.scalars(select(MealTypeSetting))}
    agg: dict[tuple[Any, Any], dict[str, Any]] = defaultdict(
        lambda: {"required": 0.0, "unit": None, "name": "", "menus": []}
    )
    for service in services:
        for menu in service.menus:
            for ing in menu.ingredients:
                if ing.quantity_total is None:
                    continue
                key = (service.service_date, ing.ingredient_id if ing.ingredient_id else f"name:{ing.ingredient_name_snapshot}")
                row = agg[key]
                row["required"] += ing.quantity_total
                row["name"] = ing.ingredient_name_snapshot
                if not row["unit"] and ing.unit:
                    row["unit"] = ing.unit
                row["menus"].append(
                    {
                        "menu_name": menu.menu_name_snapshot,
                        "quantity": ing.quantity_total,
                        "unit": ing.unit,
                        "service_date": service.service_date.isoformat(),
                        "meal_type": service.meal_type,
                        "meal_type_name": meal_type_names.get(service.meal_type, service.meal_type),
                    }
                )
    return agg


def _ingredient_key(ingredient_id: int | None, name: str) -> Any:
    return ingredient_id if ingredient_id else f"name:{name}"


def _load_stored_items(db: Session, start: date, end: date) -> dict[tuple[Any, Any], OrderItem]:
    rows = db.scalars(
        select(OrderItem)
        .where(OrderItem.service_date.between(start, end))
        .options(selectinload(OrderItem.order_group))
    ).all()
    return {(_ingredient_key(r.ingredient_id, r.ingredient_name_snapshot), r.service_date): r for r in rows}


def _item_payload(item: OrderItem, required: float | None, unit: str | None, menus: list[dict], in_plan: bool) -> dict[str, Any]:
    group = item.order_group
    return {
        "id": item.id,
        "service_date": item.service_date.isoformat(),
        "ingredient_id": item.ingredient_id,
        "ingredient_name": item.ingredient_name_snapshot,
        "required_quantity": required,
        "required_unit": unit,
        "order_quantity": item.order_quantity,
        "order_unit": item.order_unit,
        "order_date": item.order_date.isoformat() if item.order_date else None,
        "delivery_date": item.delivery_date.isoformat() if item.delivery_date else None,
        "status": item.status,
        "in_plan": in_plan,
        "menus": menus,
        "order_group_id": item.order_group_id,
        "order_group_quantity": group.order_quantity if group else None,
        "order_group_unit": group.order_unit if group else None,
    }


@router.get("")
def list_orders(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    plan = _load_plan_items(db, start, end)
    stored = _load_stored_items(db, start, end)

    items: list[dict[str, Any]] = []
    # 1. Rows from the current meal plan (required quantity always from the plan).
    for (service_date, ing_key), row in sorted(
        plan.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])
    ):
        stored_item = stored.get((ing_key, service_date))
        if stored_item:
            items.append(
                _item_payload(
                    stored_item,
                    required=row["required"],
                    unit=row["unit"],
                    menus=row["menus"],
                    in_plan=True,
                )
            )
        else:
            items.append(
                {
                    "id": None,
                    "service_date": service_date.isoformat(),
                    "ingredient_id": ing_key if isinstance(ing_key, int) else None,
                    "ingredient_name": row["name"],
                    "required_quantity": row["required"],
                    "required_unit": row["unit"],
                    "order_quantity": row["required"],
                    "order_unit": row["unit"],
                    "order_date": _default_order_date(service_date).isoformat(),
                    "delivery_date": service_date.isoformat(),
                    "status": "pending",
                    "in_plan": True,
                    "menus": row["menus"],
                    "order_group_id": None,
                    "order_group_quantity": None,
                    "order_group_unit": None,
                }
            )

    # 2. Stored rows whose (date, ingredient) no longer exists in the plan.
    #    User input must never be silently dropped.
    for (ing_key, service_date), stored_item in stored.items():
        if (service_date, ing_key) not in plan:
            items.append(
                _item_payload(
                    stored_item,
                    required=stored_item.required_quantity,
                    unit=stored_item.required_unit,
                    menus=[],
                    in_plan=False,
                )
            )

    items.sort(key=lambda x: (x["ingredient_name"], x["service_date"]))
    return {"items": items, "start_date": start.isoformat(), "end_date": end.isoformat()}


class OrderItemBody(BaseModel):
    service_date: date
    ingredient_id: int | None = None
    ingredient_name: str = Field(min_length=1, max_length=200)
    required_quantity: float | None = None
    required_unit: str | None = None
    order_quantity: float | None = None
    order_unit: str | None = None
    order_date: date | None = None
    delivery_date: date | None = None
    status: str = "pending"


class OrderItemsSaveBody(BaseModel):
    items: list[OrderItemBody] = Field(min_length=1)


def _upsert_order_item(db: Session, row: OrderItemBody) -> OrderItem:
    if row.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="발주 상태 값이 올바르지 않습니다.")
    existing = None
    if row.ingredient_id:
        existing = db.scalar(
            select(OrderItem).where(
                OrderItem.service_date == row.service_date,
                OrderItem.ingredient_id == row.ingredient_id,
            )
        )
    else:
        existing = db.scalar(
            select(OrderItem).where(
                OrderItem.service_date == row.service_date,
                OrderItem.ingredient_id.is_(None),
                OrderItem.ingredient_name_snapshot == row.ingredient_name,
            )
        )
    if existing:
        existing.ingredient_name_snapshot = row.ingredient_name
        existing.required_quantity = row.required_quantity
        existing.required_unit = row.required_unit
        existing.order_quantity = row.order_quantity
        existing.order_unit = row.order_unit
        existing.order_date = row.order_date
        existing.delivery_date = row.delivery_date
        existing.status = row.status
        return existing
    item = OrderItem(
        service_date=row.service_date,
        ingredient_id=row.ingredient_id,
        ingredient_name_snapshot=row.ingredient_name,
        required_quantity=row.required_quantity,
        required_unit=row.required_unit,
        order_quantity=row.order_quantity,
        order_unit=row.order_unit,
        order_date=row.order_date,
        delivery_date=row.delivery_date,
        status=row.status,
    )
    db.add(item)
    db.flush()
    return item


@router.put("/items")
def save_order_items(
    body: OrderItemsSaveBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    for row in body.items:
        _upsert_order_item(db, row)
    db.commit()
    return {"ok": True}


class OrderGroupBody(BaseModel):
    items: list[OrderItemBody] = Field(min_length=1)
    order_quantity: float | None = None
    order_unit: str | None = None
    order_date: date | None = None
    delivery_date: date | None = None


@router.post("/group")
def create_order_group(
    body: OrderGroupBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    rows = []
    for row in body.items:
        item = _upsert_order_item(db, row)
        if item not in rows:
            rows.append(item)
    if not rows:
        raise HTTPException(status_code=404, detail="선택한 발주 항목을 찾을 수 없습니다.")
    ingredient_id = rows[0].ingredient_id
    ingredient_name = rows[0].ingredient_name_snapshot

    total_required = sum(r.required_quantity for r in rows if r.required_quantity is not None)
    required_unit = next((r.required_unit for r in rows if r.required_unit), None)
    group = OrderGroup(
        ingredient_id=ingredient_id,
        ingredient_name_snapshot=ingredient_name,
        order_quantity=body.order_quantity,
        order_unit=body.order_unit,
        order_date=body.order_date,
        delivery_date=body.delivery_date,
        total_required_quantity=total_required,
        required_unit=required_unit,
        created_by=user.username,
    )
    db.add(group)
    db.flush()
    for row in rows:
        row.order_group_id = group.id
        row.order_date = body.order_date
        row.delivery_date = body.delivery_date
        row.status = "ordered"
    db.commit()
    return {"ok": True, "group_id": group.id}


class BulkUpdateBody(BaseModel):
    items: list[OrderItemBody] = Field(min_length=1)
    order_date: date | None = None
    delivery_date: date | None = None
    status: str | None = None


@router.put("/bulk")
def bulk_update_items(
    body: BulkUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if body.status is not None and body.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="발주 상태 값이 올바르지 않습니다.")
    if body.order_date is None and body.delivery_date is None and body.status is None:
        raise HTTPException(status_code=400, detail="변경할 항목이 없습니다.")

    rows = []
    for row in body.items:
        item = _upsert_order_item(db, row)
        if body.order_date is not None:
            item.order_date = body.order_date
        if body.delivery_date is not None:
            item.delivery_date = body.delivery_date
        if body.status is not None:
            item.status = body.status
        if item not in rows:
            rows.append(item)
    db.commit()
    return {"ok": True, "updated": len(rows)}
