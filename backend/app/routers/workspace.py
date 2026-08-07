from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user
from ..models import (
    Ingredient,
    MealActual,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    MealTypeSetting,
    Menu,
    PreservationRecord,
    Recipe,
    RecipeIngredient,
    User,
)
from ..serializers import MEAL_NAMES, MEAL_SORT, meal_service_dict

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class ServiceCreateBody(BaseModel):
    service_date: date
    meal_type: str


class ServiceUpdateBody(BaseModel):
    planned_count: int = Field(ge=0)
    service_time: str | None = None
    concept_title: str | None = None
    note: str | None = None


class AddMenuBody(BaseModel):
    menu_id: int
    recipe_id: int | None = None


class ChangeRecipeBody(BaseModel):
    recipe_id: int


class ServiceMenuBody(BaseModel):
    note: str | None = None
    is_representative: bool = False
    cooking_instruction: str | None = None
    cooking_note: str | None = None


class IngredientSnapshotBody(BaseModel):
    ingredient_id: int | None = None
    name: str
    quantity_total: float | None = None
    quantity_per_100: float | None = None
    unit: str | None = None
    source_note: str | None = None


class ReorderBody(BaseModel):
    menu_ids: list[int]


class PreservationBody(BaseModel):
    collected_at: datetime | None = None
    manager_name: str | None = None
    freezer_temperature: str | None = None
    disposal_at: datetime | None = None
    collector_name: str | None = None
    collection_time: str | None = None
    note: str | None = None
    completed: bool = True


class ActualBody(BaseModel):
    actual_count: int | None = Field(default=None, ge=0)
    note: str | None = None


def parse_clock(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="배식시간 형식은 HH:MM이어야 합니다.") from exc


def service_detail(db: Session, service_id: int) -> MealService:
    service = db.scalar(
        select(MealService)
        .where(MealService.id == service_id)
        .options(
            selectinload(MealService.menus).selectinload(MealServiceMenu.ingredients).selectinload(MealServiceMenuIngredient.ingredient),
            selectinload(MealService.menus).selectinload(MealServiceMenu.menu),
            selectinload(MealService.menus).selectinload(MealServiceMenu.source_recipe),
            selectinload(MealService.preservation),
            selectinload(MealService.actual),
        )
    )
    if not service:
        raise HTTPException(status_code=404, detail="배식을 찾을 수 없습니다.")
    return service


@router.get("/weeks")
def weeks(
    week_start: date,
    weeks: int = Query(2, ge=1, le=8),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    monday = week_start - timedelta(days=week_start.weekday())
    end = monday + timedelta(days=weeks * 7 - 1)
    services = db.scalars(
        select(MealService)
        .where(MealService.service_date.between(monday, end))
        .options(
            selectinload(MealService.menus),
            selectinload(MealService.preservation),
            selectinload(MealService.actual),
        )
        .order_by(MealService.service_date, MealService.meal_type)
    ).unique().all()
    by_date: dict[str, list[dict]] = {}
    for service in services:
        by_date.setdefault(service.service_date.isoformat(), []).append(meal_service_dict(service, detail=False))
    result = []
    for week_index in range(weeks):
        start = monday + timedelta(days=week_index * 7)
        days = []
        for day_index in range(5):
            current = start + timedelta(days=day_index)
            service_rows = sorted(by_date.get(current.isoformat(), []), key=lambda row: MEAL_SORT.get(row["meal_type"], 99))
            days.append(
                {
                    "date": current.isoformat(),
                    "day": current.day,
                    "weekday": ["월요일", "화요일", "수요일", "목요일", "금요일"][day_index],
                    "services": service_rows,
                }
            )
        result.append(
            {
                "week_start": start.isoformat(),
                "week_end": (start + timedelta(days=4)).isoformat(),
                "days": days,
            }
        )
    return {"weeks": result, "start": monday.isoformat(), "end": end.isoformat()}


@router.post("/services")
def create_service(body: ServiceCreateBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.service_date.weekday() >= 5:
        raise HTTPException(status_code=400, detail="기본 화면에서는 평일 배식만 작성합니다.")
    existing = db.scalar(
        select(MealService).where(
            MealService.service_date == body.service_date,
            MealService.meal_type == body.meal_type,
        )
    )
    if existing:
        return meal_service_dict(service_detail(db, existing.id))
    setting = db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == body.meal_type, MealTypeSetting.active.is_(True)))
    if not setting:
        raise HTTPException(status_code=400, detail="사용 가능한 배식유형이 아닙니다.")
    service = MealService(
        service_date=body.service_date,
        meal_type=body.meal_type,
        planned_count=setting.default_planned_count,
        service_time=setting.default_service_time,
    )
    db.add(service)
    db.commit()
    return meal_service_dict(service_detail(db, service.id))


@router.get("/services/{service_id}")
def get_service(service_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return meal_service_dict(service_detail(db, service_id))


@router.put("/services/{service_id}")
def update_service(
    service_id: int,
    body: ServiceUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service = service_detail(db, service_id)
    service.planned_count = body.planned_count
    service.service_time = parse_clock(body.service_time)
    service.concept_title = body.concept_title
    service.note = body.note
    # Recalculate total quantities from per-100 quantities when the plan count changes.
    for menu in service.menus:
        for ingredient in menu.ingredients:
            if ingredient.quantity_per_100 is not None:
                ingredient.quantity_total = ingredient.quantity_per_100 * service.planned_count / 100
    db.commit()
    return meal_service_dict(service_detail(db, service_id))


@router.delete("/services/{service_id}")
def delete_service(service_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    service = db.get(MealService, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="배식을 찾을 수 없습니다.")
    db.delete(service)
    db.commit()
    return {"ok": True}


def _select_recipe(menu: Menu, recipe_id: int | None) -> Recipe | None:
    active = [recipe for recipe in menu.recipes if recipe.active]
    if recipe_id is not None:
        recipe = next((value for value in active if value.id == recipe_id), None)
        if not recipe:
            raise HTTPException(status_code=400, detail="선택한 메뉴의 사용 가능한 레시피가 아닙니다.")
        return recipe
    return next((value for value in active if value.is_default), None) or (active[0] if active else None)


def _copy_recipe_to_service_menu(db: Session, item: MealServiceMenu, recipe: Recipe | None) -> None:
    db.query(MealServiceMenuIngredient).filter(
        MealServiceMenuIngredient.meal_service_menu_id == item.id
    ).delete(synchronize_session=False)
    item.recipe_id = recipe.id if recipe else None
    item.recipe_name_snapshot = recipe.name if recipe else None
    item.recipe_version_snapshot = recipe.version if recipe else None
    if not recipe:
        return
    for recipe_item in recipe.ingredients:
        total = (
            recipe_item.quantity_per_100 * item.service.planned_count / 100
            if recipe_item.quantity_per_100 is not None
            else None
        )
        db.add(
            MealServiceMenuIngredient(
                service_menu=item,
                ingredient=recipe_item.ingredient,
                sort_order=recipe_item.sort_order,
                ingredient_name_snapshot=recipe_item.ingredient.name,
                quantity_total=total,
                quantity_per_100=recipe_item.quantity_per_100,
                unit=recipe_item.unit or recipe_item.ingredient.default_unit,
            )
        )


@router.post("/services/{service_id}/menus")
def add_menu(
    service_id: int,
    body: AddMenuBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service = service_detail(db, service_id)
    menu = db.scalar(
        select(Menu)
        .where(Menu.id == body.menu_id, Menu.active.is_(True))
        .options(selectinload(Menu.recipes).selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient))
    )
    if not menu:
        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    if any(item.menu_id == menu.id for item in service.menus):
        raise HTTPException(status_code=409, detail="이미 추가된 메뉴입니다.")
    recipe = _select_recipe(menu, body.recipe_id)
    item = MealServiceMenu(
        service=service,
        menu=menu,
        sort_order=len(service.menus) + 1,
        menu_name_snapshot=menu.name,
        is_representative=not any(value.is_representative for value in service.menus) and menu.role == "주찬",
    )
    db.add(item)
    db.flush()
    _copy_recipe_to_service_menu(db, item, recipe)
    db.commit()
    return meal_service_dict(service_detail(db, service_id))


class BatchAddMenuItemBody(BaseModel):
    menu_id: int
    recipe_id: int | None = None
    sort_order: int = 0


class BatchAddMenuBody(BaseModel):
    items: list[BatchAddMenuItemBody] = Field(default_factory=list)


@router.post("/services/{service_id}/menus/batch")
def batch_add_menus(
    service_id: int,
    body: BatchAddMenuBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service = service_detail(db, service_id)
    if not body.items:
        raise HTTPException(status_code=400, detail="추가할 메뉴를 선택해 주세요.")

    # Check for duplicate menu_ids within the request
    menu_ids = [item.menu_id for item in body.items]
    if len(set(menu_ids)) != len(menu_ids):
        raise HTTPException(status_code=400, detail="요청에 중복된 메뉴가 있습니다.")

    # Check for duplicate sort_order within the request
    sort_orders = [item.sort_order for item in body.items]
    if len(set(sort_orders)) != len(sort_orders):
        raise HTTPException(status_code=400, detail="요청에 중복된 정렬 순서가 있습니다.")

    # Check for duplicates with existing menus
    existing_menu_ids = {item.menu_id for item in service.menus}
    for mid in menu_ids:
        if mid in existing_menu_ids:
            raise HTTPException(status_code=409, detail="이미 추가된 메뉴가 있습니다.")

    # Load all menus with recipes in one query
    menu_rows = db.scalars(
        select(Menu)
        .where(Menu.id.in_(menu_ids), Menu.active.is_(True))
        .options(selectinload(Menu.recipes).selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient))
    ).unique().all()
    menu_map = {m.id: m for m in menu_rows}

    # Validate all menus exist and are active
    for mid in menu_ids:
        if mid not in menu_map:
            raise HTTPException(status_code=404, detail=f"메뉴를 찾을 수 없습니다: {mid}")

    # Validate recipes belong to their respective menus and are active
    for item in body.items:
        menu = menu_map[item.menu_id]
        if item.recipe_id is not None:
            recipe = next((r for r in menu.recipes if r.id == item.recipe_id), None)
            if not recipe:
                raise HTTPException(status_code=400, detail=f"{menu.name}의 선택한 레시피를 찾을 수 없습니다.")
            if not recipe.active:
                raise HTTPException(status_code=400, detail=f"{menu.name}의 선택한 레시피는 사용 중지 상태입니다.")

    # All validation passed — create service menus in a transaction
    base_sort = len(service.menus)
    for item in body.items:
        menu = menu_map[item.menu_id]
        active_recipes = [r for r in menu.recipes if r.active]
        if item.recipe_id is not None:
            recipe = next(r for r in active_recipes if r.id == item.recipe_id)
        else:
            recipe = next((r for r in active_recipes if r.is_default), None) or (active_recipes[0] if active_recipes else None)

        new_item = MealServiceMenu(
            service=service,
            menu=menu,
            sort_order=base_sort + item.sort_order,
            menu_name_snapshot=menu.name,
            is_representative=False,
        )
        db.add(new_item)
        db.flush()
        _copy_recipe_to_service_menu(db, new_item, recipe)

    db.commit()
    return meal_service_dict(service_detail(db, service_id))


@router.put("/service-menus/{item_id}/recipe")
def change_service_menu_recipe(
    item_id: int,
    body: ChangeRecipeBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    item = db.scalar(
        select(MealServiceMenu)
        .where(MealServiceMenu.id == item_id)
        .options(
            selectinload(MealServiceMenu.service),
            selectinload(MealServiceMenu.menu)
            .selectinload(Menu.recipes)
            .selectinload(Recipe.ingredients)
            .selectinload(RecipeIngredient.ingredient),
        )
    )
    if not item or not item.menu:
        raise HTTPException(status_code=404, detail="식단 메뉴를 찾을 수 없습니다.")
    recipe = _select_recipe(item.menu, body.recipe_id)
    _copy_recipe_to_service_menu(db, item, recipe)
    db.commit()
    return meal_service_dict(service_detail(db, item.meal_service_id))


@router.put("/service-menus/{item_id}")
def update_service_menu(
    item_id: int,
    body: ServiceMenuBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    item = db.get(MealServiceMenu, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="식단 메뉴를 찾을 수 없습니다.")
    item.note = body.note
    item.cooking_instruction = body.cooking_instruction
    item.cooking_note = body.cooking_note
    if body.is_representative:
        for sibling in item.service.menus:
            sibling.is_representative = sibling.id == item.id
    else:
        item.is_representative = False
    db.commit()
    return meal_service_dict(service_detail(db, item.meal_service_id))


@router.put("/service-menus/{item_id}/ingredients")
def update_service_menu_ingredients(
    item_id: int,
    body: list[IngredientSnapshotBody],
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    item = db.get(MealServiceMenu, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="식단 메뉴를 찾을 수 없습니다.")
    db.query(MealServiceMenuIngredient).filter(MealServiceMenuIngredient.meal_service_menu_id == item_id).delete(
        synchronize_session=False
    )
    for index, row in enumerate(body, start=1):
        ingredient = db.get(Ingredient, row.ingredient_id) if row.ingredient_id else None
        per_100 = row.quantity_per_100
        total = row.quantity_total
        if per_100 is None and total is not None and item.service.planned_count:
            per_100 = total * 100 / item.service.planned_count
        if total is None and per_100 is not None:
            total = per_100 * item.service.planned_count / 100
        db.add(
            MealServiceMenuIngredient(
                meal_service_menu_id=item_id,
                ingredient_id=ingredient.id if ingredient else None,
                sort_order=index,
                ingredient_name_snapshot=row.name.strip(),
                quantity_total=total,
                quantity_per_100=per_100,
                unit=row.unit or (ingredient.default_unit if ingredient else None),
                source_note=row.source_note,
            )
        )
    db.commit()
    return meal_service_dict(service_detail(db, item.meal_service_id))


class MealEditorIngredientBody(BaseModel):
    ingredient_id: int | None = None
    name: str
    quantity_total: float | None = None
    unit: str | None = None


class MealEditorMenuBody(BaseModel):
    service_menu_id: int | None = None
    note: str | None = None
    is_representative: bool = False
    ingredients: list[MealEditorIngredientBody] = []


class MealEditorBody(BaseModel):
    planned_count: int = Field(ge=0)
    service_time: str | None = None
    concept_title: str | None = None
    note: str | None = None
    menus: list[MealEditorMenuBody] = []


@router.put("/services/{service_id}/meal-editor")
def save_meal_editor(
    service_id: int,
    body: MealEditorBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service = service_detail(db, service_id)

    # 1. Save service basic info
    service.planned_count = body.planned_count
    service.service_time = parse_clock(body.service_time)
    service.concept_title = body.concept_title
    service.note = body.note

    # 2. Save each menu's note, representative, and ingredients
    representative_set = False
    for menu_body in body.menus:
        if menu_body.service_menu_id:
            item = db.get(MealServiceMenu, menu_body.service_menu_id)
            if not item or item.meal_service_id != service_id:
                continue
            item.note = menu_body.note
            # Representative: only first True wins; unchecking is allowed
            if menu_body.is_representative and not representative_set:
                item.is_representative = True
                representative_set = True
            else:
                item.is_representative = False

            # Replace ingredients
            db.query(MealServiceMenuIngredient).filter(
                MealServiceMenuIngredient.meal_service_menu_id == item.id
            ).delete(synchronize_session=False)
            for index, row in enumerate(menu_body.ingredients, start=1):
                ingredient = db.get(Ingredient, row.ingredient_id) if row.ingredient_id else None
                per_100 = None
                total = row.quantity_total
                if total is not None and service.planned_count:
                    per_100 = total * 100 / service.planned_count
                db.add(
                    MealServiceMenuIngredient(
                        meal_service_menu_id=item.id,
                        ingredient_id=ingredient.id if ingredient else None,
                        sort_order=index,
                        ingredient_name_snapshot=row.name.strip(),
                        quantity_total=total,
                        quantity_per_100=per_100,
                        unit=row.unit or (ingredient.default_unit if ingredient else None),
                    )
                )

    db.commit()
    return meal_service_dict(service_detail(db, service_id))


@router.delete("/service-menus/{item_id}")
def delete_service_menu(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.get(MealServiceMenu, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="식단 메뉴를 찾을 수 없습니다.")
    service_id = item.meal_service_id
    db.delete(item)
    db.flush()
    siblings = db.scalars(
        select(MealServiceMenu).where(MealServiceMenu.meal_service_id == service_id).order_by(MealServiceMenu.sort_order)
    ).all()
    for index, sibling in enumerate(siblings, start=1):
        sibling.sort_order = index
    db.commit()
    return meal_service_dict(service_detail(db, service_id))


@router.post("/services/{service_id}/reorder")
def reorder_menus(
    service_id: int,
    body: ReorderBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service = service_detail(db, service_id)
    item_map = {item.id: item for item in service.menus}
    if set(body.menu_ids) != set(item_map):
        raise HTTPException(status_code=400, detail="메뉴 목록이 현재 식단과 일치하지 않습니다.")
    for index, item_id in enumerate(body.menu_ids, start=1):
        item_map[item_id].sort_order = index
    db.commit()
    return meal_service_dict(service_detail(db, service_id))


@router.get("/services/{service_id}/preservation")
def get_preservation(service_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    service = service_detail(db, service_id)
    record = service.preservation
    return {
        "service_id": service.id,
        "collected_at": record.collected_at.isoformat() if record and record.collected_at else None,
        "manager_name": record.manager_name if record else "",
        "freezer_temperature": record.freezer_temperature if record else "",
        "disposal_at": record.disposal_at.isoformat() if record and record.disposal_at else None,
        "collector_name": record.collector_name if record else "",
        "collection_time": record.collection_time if record else "",
        "note": record.note if record else "",
        "completed": bool(record and record.completed_at),
    }


@router.put("/services/{service_id}/preservation")
def save_preservation(
    service_id: int,
    body: PreservationBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service = service_detail(db, service_id)
    record = service.preservation or PreservationRecord(service=service)
    record.collected_at = body.collected_at
    record.manager_name = body.manager_name
    record.freezer_temperature = body.freezer_temperature
    record.disposal_at = body.disposal_at
    record.collector_name = body.collector_name
    record.collection_time = body.collection_time
    record.note = body.note
    record.completed_at = datetime.now(timezone.utc) if body.completed else None
    db.add(record)
    db.commit()
    return get_preservation(service_id, db, user)


@router.get("/services/{service_id}/actual")
def get_actual(service_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    service = service_detail(db, service_id)
    actual = service.actual
    return {
        "service_id": service.id,
        "planned_count": service.planned_count,
        "actual_count": actual.actual_count if actual else None,
        "note": actual.note if actual else "",
        "recorded_at": actual.recorded_at.isoformat() if actual and actual.recorded_at else None,
    }


@router.put("/services/{service_id}/actual")
def save_actual(
    service_id: int,
    body: ActualBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service = service_detail(db, service_id)
    actual = service.actual or MealActual(service=service)
    actual.actual_count = body.actual_count
    actual.note = body.note
    actual.recorded_at = datetime.now(timezone.utc) if body.actual_count is not None else None
    db.add(actual)
    db.commit()
    return get_actual(service_id, db, user)
