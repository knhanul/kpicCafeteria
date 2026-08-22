from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user
from ..models import Ingredient, IngredientAlias, MealService, MealServiceMenu, MealServiceMenuIngredient, MealActual, Menu, Recipe, RecipeIngredient, User

router = APIRouter(prefix="/api/master", tags=["master"])

MENU_ROLES = ["밥·죽", "면·떡", "국·탕", "찌개·전골", "주찬", "부찬", "김치·절임", "샐러드", "후식·음료", "기타"]
STAT_GROUPS = [
    "곡류·주식", "면·떡·전분", "소고기", "돼지고기", "닭·오리", "수산물", "달걀", "두류·두부",
    "채소", "버섯·해조", "과일·견과", "유제품", "김치·절임", "가공식품", "장류·소스·조미료", "기타"
]
UNITS = ["kg", "g", "L", "ml", "개", "봉", "팩", "판", "통", "캔", "병", "박스", "단", "묶음", "장", "줄", "포", "관", "밧트"]


class MenuBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    canonical_name: str | None = None
    role: str = "기타"
    active: bool = True


class IngredientBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stat_group: str = "기타"
    default_unit: str | None = None
    kg_factor: float | None = None
    analysis_excluded: bool = False
    active: bool = True


class RecipeItemBody(BaseModel):
    ingredient_id: int | None = None
    ingredient_name: str | None = None
    quantity_per_100: float | None = None
    unit: str | None = None
    is_primary: bool = False

    @model_validator(mode="after")
    def validate_identity(self):
        if not self.ingredient_id and not (self.ingredient_name or "").strip():
            raise ValueError("재료 ID 또는 재료명이 필요합니다.")
        return self


class RecipeBody(BaseModel):
    name: str | None = None
    note: str | None = None
    is_default: bool = False
    active: bool = True
    ingredients: list[RecipeItemBody] = Field(default_factory=list)


class SnapshotRecipePreviewBody(BaseModel):
    meal_service_menu_id: int = Field(ge=1)
    mode: str
    target_recipe_id: int | None = Field(default=None, ge=1)
    recipe_name: str | None = Field(default=None, min_length=1, max_length=120)
    make_default: bool = False
    expected_recipe_fingerprint: str | None = None


class SnapshotRecipeCreateBody(BaseModel):
    meal_service_menu_id: int = Field(ge=1)
    recipe_name: str = Field(min_length=1, max_length=120)
    make_default: bool = False


def _menu_query():
    return select(Menu).options(
        selectinload(Menu.recipes).selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient)
    )


def recipe_payload(recipe: Recipe, detail: bool = True, usage: dict[int, dict[str, str]] | None = None) -> dict[str, Any]:
    payload = {
        "id": recipe.id,
        "menu_id": recipe.menu_id,
        "name": recipe.name,
        "version": recipe.version,
        "note": recipe.note or "",
        "is_default": recipe.is_default,
        "active": recipe.active,
        "composition_key": recipe.composition_key,
        "ingredient_count": len(recipe.ingredients),
    }
    last_used = usage.get(recipe.id) if usage else None
    payload["last_used_date"] = last_used["date"] if last_used else None
    payload["last_used_meal_type"] = last_used["meal_type"] if last_used else None
    if detail:
        payload["ingredients"] = [
            {
                "id": item.id,
                "ingredient_id": item.ingredient_id,
                "ingredient_name": item.ingredient.name,
                "stat_group": item.ingredient.stat_group,
                "quantity_per_100": item.quantity_per_100,
                "unit": item.unit or item.ingredient.default_unit,
                "is_primary": item.is_primary,
                "sort_order": item.sort_order,
            }
            for item in recipe.ingredients
        ]
    return payload


def menu_payload(menu: Menu, detail: bool = False) -> dict[str, Any]:
    active_recipes = [recipe for recipe in menu.recipes if recipe.active]
    default_recipe = next((recipe for recipe in active_recipes if recipe.is_default), None)
    result = {
        "id": menu.id,
        "source_code": menu.source_code,
        "name": menu.name,
        "canonical_name": menu.canonical_name,
        "role": menu.role,
        "active": menu.active,
        "review_status": menu.review_status,
        "recipe_count": len(active_recipes),
        "default_recipe_id": default_recipe.id if default_recipe else (active_recipes[0].id if active_recipes else None),
        "recipes": [recipe_payload(recipe, detail=detail) for recipe in menu.recipes],
    }
    return result


def recipe_usage_map(db: Session, recipe_ids: list[int]) -> dict[int, dict[str, str]]:
    if not recipe_ids:
        return {}
    rows = db.execute(
        select(MealServiceMenu.recipe_id, MealService.service_date, MealService.meal_type)
        .join(MealService, MealService.id == MealServiceMenu.meal_service_id)
        .where(MealServiceMenu.recipe_id.in_(recipe_ids))
        .order_by(MealService.service_date.desc(), MealService.meal_type.desc())
    ).all()
    result: dict[int, dict[str, str]] = {}
    for recipe_id, service_date, meal_type in rows:
        if recipe_id not in result:
            result[recipe_id] = {"date": service_date.isoformat(), "meal_type": meal_type}
    return result


def ingredient_payload(row: Ingredient) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_code": row.source_code,
        "name": row.name,
        "stat_group": row.stat_group,
        "default_unit": row.default_unit,
        "kg_factor": row.kg_factor,
        "analysis_excluded": row.analysis_excluded,
        "active": row.active,
        "review_status": row.review_status,
    }


def resolve_recipe_items(db: Session, items: list[RecipeItemBody]) -> list[tuple[Ingredient, RecipeItemBody]]:
    resolved: list[tuple[Ingredient, RecipeItemBody]] = []
    seen: set[int] = set()
    for item in items:
        ingredient = db.get(Ingredient, item.ingredient_id) if item.ingredient_id else None
        name = (item.ingredient_name or "").strip()
        if not ingredient and name:
            ingredient = db.scalar(select(Ingredient).where(func.lower(Ingredient.name) == name.lower()))
        if not ingredient and name:
            ingredient = Ingredient(
                name=name,
                stat_group="기타",
                default_unit=item.unit or None,
                review_status="자동등록-분류필요",
                active=True,
            )
            db.add(ingredient)
            db.flush()
        if not ingredient:
            raise HTTPException(status_code=400, detail="재료를 찾을 수 없습니다.")
        if ingredient.id in seen:
            raise HTTPException(status_code=400, detail=f"레시피에 같은 재료가 중복되었습니다: {ingredient.name}")
        seen.add(ingredient.id)
        resolved.append((ingredient, item))
    return resolved


def composition_key(resolved: list[tuple[Ingredient, RecipeItemBody]]) -> str:
    # 수량과 단위는 레시피 구분 기준이 아니다. 재료 구성만 비교한다.
    return ",".join(str(value) for value in sorted(ingredient.id for ingredient, _ in resolved)) or "EMPTY"


def set_default_recipe(db: Session, recipe: Recipe) -> None:
    for sibling in db.scalars(select(Recipe).where(Recipe.menu_id == recipe.menu_id)).all():
        sibling.is_default = sibling.id == recipe.id


def replace_recipe_items(db: Session, recipe: Recipe, resolved: list[tuple[Ingredient, RecipeItemBody]]) -> None:
    existing_rows = db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)).all()
    for existing in existing_rows:
        db.delete(existing)
    db.flush()
    for index, (ingredient, item) in enumerate(resolved, start=1):
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                sort_order=index,
                quantity_per_100=item.quantity_per_100,
                unit=item.unit or ingredient.default_unit,
                is_primary=item.is_primary,
            )
        )


def load_snapshot_for_recipe(db: Session, menu_id: int, meal_service_menu_id: int):
    snapshot = db.scalar(
        select(MealServiceMenu).where(
            MealServiceMenu.id == meal_service_menu_id,
            MealServiceMenu.menu_id == menu_id,
        ).options(
            selectinload(MealServiceMenu.service),
            selectinload(MealServiceMenu.source_recipe).selectinload(Recipe.ingredients),
            selectinload(MealServiceMenu.ingredients).selectinload(MealServiceMenuIngredient.ingredient),
        )
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="현재 메뉴에 속한 과거 식단 Snapshot을 찾을 수 없습니다.")
    ingredient_ids={row.ingredient_id for row in snapshot.ingredients if row.ingredient_id is not None}
    masters={row.id:row for row in db.scalars(select(Ingredient).where(Ingredient.id.in_(ingredient_ids))).all()} if ingredient_ids else {}
    warnings=[]
    resolved=[]
    seen_ids=set()
    for row in snapshot.ingredients:
        if row.ingredient_id is None:
            warnings.append({"type":"ingredient_id_missing","name":row.ingredient_name_snapshot,"message":"현재 재료 기준정보와 연결되어 있지 않습니다."})
            continue
        if row.ingredient_id not in masters:
            warnings.append({"type":"ingredient_deleted","name":row.ingredient_name_snapshot,"ingredient_id":row.ingredient_id,"message":"현재 기준정보에서 삭제된 재료입니다."})
            continue
        if row.ingredient_id in seen_ids:
            warnings.append({"type":"duplicate_ingredient","name":row.ingredient_name_snapshot,"message":"같은 재료가 Snapshot에 중복되어 있습니다."})
            continue
        seen_ids.add(row.ingredient_id)
        if row.quantity_per_100 is None:
            warnings.append({"type":"quantity_per_100_missing","name":row.ingredient_name_snapshot,"message":"100인 기준 수량이 저장되어 있지 않습니다."})
            continue
        if not row.unit or not row.unit.strip():
            warnings.append({"type":"unit_missing","name":row.ingredient_name_snapshot,"message":"단위가 저장되어 있지 않습니다."})
            continue
        resolved.append(row)
    return snapshot, warnings, resolved


def snapshot_recipe_diff(snapshot, target: Recipe, resolved) -> dict[str, Any]:
    source_map={row.ingredient_id:row for row in resolved}
    target_map={row.ingredient_id:row for row in target.ingredients}
    diff=[]
    for ingredient_id in sorted(set(source_map)|set(target_map)):
        source=source_map.get(ingredient_id); current=target_map.get(ingredient_id)
        name=(source.ingredient_name_snapshot if source else current.ingredient.name)
        if not current:
            diff.append({"type":"added","ingredient_id":ingredient_id,"name":name,"current":None,"snapshot":{"quantity_per_100":source.quantity_per_100,"unit":source.unit}})
        elif not source:
            diff.append({"type":"removed","ingredient_id":ingredient_id,"name":name,"current":{"quantity_per_100":current.quantity_per_100,"unit":current.unit},"snapshot":None})
        elif current.quantity_per_100 != source.quantity_per_100 or (current.unit or "") != (source.unit or ""):
            diff.append({"type":"changed","ingredient_id":ingredient_id,"name":name,"current":{"quantity_per_100":current.quantity_per_100,"unit":current.unit},"snapshot":{"quantity_per_100":source.quantity_per_100,"unit":source.unit}})
    return {"items":diff,"summary":{"added":sum(item["type"]=="added" for item in diff),"removed":sum(item["type"]=="removed" for item in diff),"changed":sum(item["type"]=="changed" for item in diff),"same":len(target.ingredients)-sum(item["type"]=="removed" for item in diff)-sum(item["type"]=="changed" for item in diff)}}


def snapshot_composition_key(rows) -> str:
    return ",".join(str(row.ingredient_id) for row in sorted(rows, key=lambda item: item.ingredient_id)) or "EMPTY"


def recipe_fingerprint(recipe: Recipe) -> str:
    rows=[{"ingredient_id":row.ingredient_id,"quantity_per_100":row.quantity_per_100,"unit":row.unit or "","is_primary":row.is_primary,"sort_order":row.sort_order} for row in sorted(recipe.ingredients,key=lambda item:item.sort_order)]
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def snapshot_recipe_body(rows, target: Recipe | None = None):
    primary={row.ingredient_id:row.is_primary for row in (target.ingredients if target else [])}
    return [(row.ingredient, RecipeItemBody(ingredient_id=row.ingredient_id, ingredient_name=row.ingredient_name_snapshot, quantity_per_100=row.quantity_per_100, unit=row.unit, is_primary=primary.get(row.ingredient_id, False))) for row in rows]


@router.get("/codes")
def codes(user: User = Depends(current_user)):
    return {"menu_roles": MENU_ROLES, "stat_groups": STAT_GROUPS, "units": UNITS}


@router.get("/menus")
def list_menus(
    q: str = "",
    role: str | None = None,
    active: bool | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = _menu_query()
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Menu.name.ilike(term), Menu.canonical_name.ilike(term)))
    if role:
        stmt = stmt.where(Menu.role == role)
    if active is not None:
        stmt = stmt.where(Menu.active == active)
    rows = db.scalars(stmt.order_by(Menu.name).offset(offset).limit(limit + 1)).unique().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return {'items': [menu_payload(row) for row in items], 'has_more': has_more, 'offset': offset, 'limit': limit}


@router.get("/menus/picker")
def picker_list_menus(
    q: str = "",
    role: str | None = None,
    active: bool | None = True,
    service_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = _menu_query()
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Menu.name.ilike(term), Menu.canonical_name.ilike(term)))
    if role and role != "ALL":
        stmt = stmt.where(Menu.role == role)
    if active is not None:
        stmt = stmt.where(Menu.active == active)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0

    rows = db.scalars(stmt.order_by(Menu.name).offset(offset).limit(limit)).unique().all()
    recipe_ids = [recipe.id for menu in rows for recipe in menu.recipes if recipe.active]
    usage = recipe_usage_map(db, recipe_ids)

    # Determine already_added menus for the given service
    added_map: dict[int, int | None] = {}
    if service_id:
        existing = db.execute(
            select(MealServiceMenu.menu_id, MealServiceMenu.recipe_id).where(MealServiceMenu.meal_service_id == service_id)
        ).all()
        added_map = {row[0]: row[1] for row in existing}

    items = []
    for menu in rows:
        active_recipes = [r for r in menu.recipes if r.active]
        default_recipe = next((r for r in active_recipes if r.is_default), None)
        already_added = menu.id in added_map
        current_recipe_id = added_map.get(menu.id) if already_added else None

        recipes_payload = []
        for recipe in active_recipes:
            ingredient_names = [ri.ingredient.name for ri in recipe.ingredients[:5]]
            recipes_payload.append({
                "id": recipe.id,
                "name": recipe.name,
                "version": recipe.version,
                "is_default": recipe.is_default,
                "active": recipe.active,
                "ingredient_count": len(recipe.ingredients),
                "ingredient_summary": ingredient_names,
                "note": recipe.note or "",
                "last_used_date": usage.get(recipe.id, {}).get("date"),
                "last_used_meal_type": usage.get(recipe.id, {}).get("meal_type"),
            })

        items.append({
            "id": menu.id,
            "name": menu.name,
            "role": menu.role,
            "active": menu.active,
            "already_added": already_added,
            "current_recipe_id": current_recipe_id,
            "default_recipe_id": default_recipe.id if default_recipe else (active_recipes[0].id if active_recipes else None),
            "recipes": recipes_payload,
        })

    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/menus/{menu_id}/recipes/from-snapshot/preview")
def preview_snapshot_recipe(
    menu_id: int,
    body: SnapshotRecipePreviewBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if body.mode not in {"update", "create"}:
        raise HTTPException(status_code=400, detail="mode는 update 또는 create여야 합니다.")
    snapshot, warnings, resolved = load_snapshot_for_recipe(db, menu_id, body.meal_service_menu_id)
    target=None
    if body.mode == "update":
        if body.target_recipe_id is None:
            warnings.append({"type":"target_recipe_missing","message":"업데이트할 레시피를 선택해 주세요."})
        else:
            target=db.scalar(select(Recipe).where(Recipe.id == body.target_recipe_id, Recipe.menu_id == menu_id).options(selectinload(Recipe.ingredients)))
            if not target:
                warnings.append({"type":"target_recipe_invalid","message":"선택한 레시피가 현재 메뉴에 속하지 않습니다."})
    elif not body.recipe_name or not body.recipe_name.strip():
        warnings.append({"type":"recipe_name_missing","message":"새 레시피 이름을 입력해 주세요."})
    diff=snapshot_recipe_diff(snapshot,target,resolved) if target and not warnings else None
    if body.mode == "create" and not warnings:
        key=snapshot_composition_key(resolved)
        duplicate=db.scalar(select(Recipe).where(Recipe.menu_id == menu_id, Recipe.composition_key == key))
        if duplicate:
            warnings.append({"type":"duplicate_composition","message":f"동일한 재료 구성의 레시피가 이미 있습니다: {duplicate.name}"})
    return {"can_apply":not warnings,"warnings":warnings,"source":{"meal_service_menu_id":snapshot.id,"date":snapshot.service.service_date.isoformat(),"meal_type":snapshot.service.meal_type,"planned_count":snapshot.service.planned_count,"menu_name":snapshot.menu_name_snapshot},"target_recipe":{"id":target.id,"name":target.name,"version":target.version} if target else None,"recipe_fingerprint":recipe_fingerprint(target) if target else None,"snapshot_ingredients":[{"ingredient_id":row.ingredient_id,"name":row.ingredient_name_snapshot,"quantity_per_100":row.quantity_per_100,"unit":row.unit} for row in resolved],"diff":diff}


@router.post("/menus/{menu_id}/recipes/{recipe_id}/apply-snapshot")
def apply_snapshot_to_recipe(
    menu_id: int,
    recipe_id: int,
    body: SnapshotRecipePreviewBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if body.mode != "update":
        raise HTTPException(status_code=400, detail="기존 레시피 반영에는 update 모드만 사용할 수 있습니다.")
    snapshot, warnings, resolved = load_snapshot_for_recipe(db, menu_id, body.meal_service_menu_id)
    recipe=db.scalar(select(Recipe).where(Recipe.id == recipe_id, Recipe.menu_id == menu_id).options(selectinload(Recipe.ingredients)))
    if not recipe:
        raise HTTPException(status_code=400, detail="선택한 레시피가 현재 메뉴에 속하지 않습니다.")
    if warnings:
        raise HTTPException(status_code=400, detail="Snapshot을 레시피로 저장할 수 없습니다: " + ", ".join(w["message"] for w in warnings))
    if body.expected_recipe_fingerprint and recipe_fingerprint(recipe) != body.expected_recipe_fingerprint:
        raise HTTPException(status_code=409, detail="레시피가 비교 이후 변경되었습니다. 다시 비교한 후 저장해 주세요.")
    try:
        replace_recipe_items(db, recipe, snapshot_recipe_body(resolved, recipe))
        db.commit()
        db.refresh(recipe)
        return recipe_payload(recipe)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="레시피가 다른 작업과 충돌했습니다. 다시 비교한 후 저장해 주세요.") from exc
    except Exception:
        db.rollback()
        raise


@router.post("/menus/{menu_id}/recipes/from-snapshot")
def create_recipe_from_snapshot(
    menu_id: int,
    body: SnapshotRecipeCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    snapshot, warnings, resolved = load_snapshot_for_recipe(db, menu_id, body.meal_service_menu_id)
    if warnings:
        raise HTTPException(status_code=400, detail="Snapshot을 레시피로 저장할 수 없습니다: " + ", ".join(w["message"] for w in warnings))
    key=snapshot_composition_key(resolved)
    if db.scalar(select(Recipe).where(Recipe.menu_id == menu_id, Recipe.composition_key == key)):
        raise HTTPException(status_code=409, detail="동일한 재료 구성의 레시피가 이미 있습니다.")
    try:
        next_version=(db.scalar(select(func.max(Recipe.version)).where(Recipe.menu_id == menu_id)) or 0)+1
        recipe=Recipe(menu_id=menu_id,name=body.recipe_name.strip(),version=next_version,composition_key=key,is_default=body.make_default,active=True)
        db.add(recipe);db.flush();replace_recipe_items(db,recipe,snapshot_recipe_body(resolved))
        if body.make_default:set_default_recipe(db,recipe)
        db.commit();db.refresh(recipe)
        return recipe_payload(recipe)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="새 레시피 생성이 다른 작업과 충돌했습니다. 다시 시도해 주세요.") from exc
    except Exception:
        db.rollback()
        raise


@router.get("/menus/{menu_id}/usage-history")
def menu_usage_history(
    menu_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    meal_type: str | None = Query(None),
    recipe_id: int | None = Query(None, ge=1),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not db.get(Menu, menu_id):
        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    if meal_type is not None and meal_type not in {"LUNCH", "DINNER"}:
        raise HTTPException(status_code=400, detail="meal_type은 LUNCH 또는 DINNER여야 합니다.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from은 date_to보다 늦을 수 없습니다.")
    filters = [MealServiceMenu.menu_id == menu_id]
    if meal_type:
        filters.append(MealService.meal_type == meal_type)
    if recipe_id:
        filters.append(MealServiceMenu.recipe_id == recipe_id)
    if date_from:
        filters.append(MealService.service_date >= date_from)
    if date_to:
        filters.append(MealService.service_date <= date_to)
    count = db.scalar(select(func.count(func.distinct(MealService.id))).select_from(MealService).join(MealServiceMenu).where(*filters)) or 0
    stmt = select(MealService).join(MealServiceMenu).where(*filters).distinct().options(
        selectinload(MealService.actual),
        selectinload(MealService.menus).selectinload(MealServiceMenu.source_recipe)
    ).order_by(MealService.service_date.desc(), MealService.meal_type.desc()).offset(offset).limit(limit)
    services = db.scalars(stmt).unique().all()
    histories = []
    for service in services:
        current = next((item for item in service.menus if item.menu_id == menu_id), None)
        if not current:
            continue
        menus = [{
            "meal_service_menu_id": item.id, "menu_id": item.menu_id,
            "name": item.menu_name_snapshot, "sort_order": item.sort_order,
            "is_representative": item.is_representative,
            "recipe_id": item.recipe_id,
            "recipe_name": item.recipe_name_snapshot or (item.source_recipe.name if item.source_recipe else None),
            "recipe_version": item.recipe_version_snapshot or (item.source_recipe.version if item.source_recipe else None),
            "recipe_active": bool(item.source_recipe and item.source_recipe.active),
        } for item in service.menus]
        target_recipe = {"recipe_id": current.recipe_id, "name": current.recipe_name_snapshot,
                         "version": current.recipe_version_snapshot} if current.recipe_id or current.recipe_name_snapshot else None
        companions = [item for item in menus if item["menu_id"] and item["menu_id"] != menu_id]
        histories.append({
            "meal_service_id": service.id, "service_id": service.id,
            "date": service.service_date.isoformat(), "service_date": service.service_date.isoformat(),
            "meal_type": service.meal_type, "planned_count": service.planned_count,
            "actual_count": service.actual.actual_count if service.actual else None,
            "target_meal_service_menu_id": current.id,
            "target_recipe": target_recipe,
            "recipe_id": current.recipe_id, "recipe_name": current.recipe_name_snapshot,
            "recipe_version": current.recipe_version_snapshot,
            "menus": menus, "companions": companions,
        })
    return {"items": histories, "offset": offset, "limit": limit, "total": count, "has_more": offset + len(histories) < count}


@router.get("/meal-service-menus/{meal_service_menu_id}/snapshot")
def meal_service_menu_snapshot(
    meal_service_menu_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    item = db.scalar(
        select(MealServiceMenu).where(MealServiceMenu.id == meal_service_menu_id).options(
            selectinload(MealServiceMenu.service),
            selectinload(MealServiceMenu.source_recipe),
            selectinload(MealServiceMenu.ingredients),
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="식단 메뉴 기록을 찾을 수 없습니다.")
    return {
        "meal_service_menu_id": item.id,
        "menu_id": item.menu_id,
        "menu_name": item.menu_name_snapshot,
        "recipe": {"recipe_id": item.recipe_id, "name": item.recipe_name_snapshot, "version": item.recipe_version_snapshot} if item.recipe_id or item.recipe_name_snapshot else None,
        "date": item.service.service_date.isoformat(), "meal_type": item.service.meal_type,
        "planned_count": item.service.planned_count,
        "ingredients": [{"ingredient_id": row.ingredient_id, "name": row.ingredient_name_snapshot,
                         "quantity_total": row.quantity_total, "quantity_per_100": row.quantity_per_100,
                         "unit": row.unit, "sort_order": row.sort_order} for row in item.ingredients],
    }


@router.get("/menus/{menu_id}")
def get_menu(menu_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    menu = db.scalar(_menu_query().where(Menu.id == menu_id))
    if not menu:
        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    usage = recipe_usage_map(db, [recipe.id for recipe in menu.recipes])
    return {
        **menu_payload(menu, True),
        "recipes": [recipe_payload(recipe, detail=True, usage=usage) for recipe in menu.recipes],
    }


@router.post("/menus")
def create_menu(body: MenuBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = body.name.strip()
    if db.scalar(select(Menu).where(Menu.name == name)):
        raise HTTPException(status_code=409, detail="같은 이름의 메뉴가 있습니다.")
    menu = Menu(name=name, canonical_name=(body.canonical_name or name).strip(), role=body.role, active=body.active)
    db.add(menu)
    db.commit()
    return menu_payload(menu)


@router.put("/menus/{menu_id}")
def update_menu(menu_id: int, body: MenuBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    menu = db.get(Menu, menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    name = body.name.strip()
    if db.scalar(select(Menu).where(Menu.name == name, Menu.id != menu_id)):
        raise HTTPException(status_code=409, detail="같은 이름의 메뉴가 있습니다.")
    menu.name = name
    menu.canonical_name = (body.canonical_name or name).strip()
    menu.role = body.role
    menu.active = body.active
    db.commit()
    return menu_payload(menu)


@router.delete("/menus/{menu_id}")
def archive_menu(menu_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    menu = db.get(Menu, menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    menu.active = False
    for recipe in menu.recipes:
        recipe.active = False
    db.commit()
    return {"ok": True, "archived": True}


@router.post("/menus/{menu_id}/recipes")
def create_recipe(menu_id: int, body: RecipeBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    menu = db.get(Menu, menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    resolved = resolve_recipe_items(db, body.ingredients)
    key = composition_key(resolved)
    duplicate = db.scalar(select(Recipe).where(Recipe.menu_id == menu_id, Recipe.composition_key == key))
    if duplicate:
        raise HTTPException(status_code=409, detail=f"같은 재료 구성의 레시피가 이미 있습니다: {duplicate.name}")
    next_version = (db.scalar(select(func.max(Recipe.version)).where(Recipe.menu_id == menu_id)) or 0) + 1
    recipe = Recipe(
        menu_id=menu_id,
        name=(body.name or f"레시피 {next_version}").strip(),
        version=next_version,
        composition_key=key,
        note=body.note,
        active=body.active,
        is_default=body.is_default or not db.scalar(select(Recipe.id).where(Recipe.menu_id == menu_id, Recipe.active.is_(True))),
    )
    db.add(recipe)
    db.flush()
    replace_recipe_items(db, recipe, resolved)
    if recipe.is_default:
        set_default_recipe(db, recipe)
    db.commit()
    db.expire_all()
    created = db.scalar(
        select(Recipe).where(Recipe.id == recipe.id).options(selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient))
    )
    return recipe_payload(created)


@router.put("/recipes/{recipe_id}")
def update_recipe(recipe_id: int, body: RecipeBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    recipe = db.scalar(
        select(Recipe).where(Recipe.id == recipe_id).options(selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient))
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="레시피를 찾을 수 없습니다.")
    resolved = resolve_recipe_items(db, body.ingredients)
    key = composition_key(resolved)
    duplicate = db.scalar(
        select(Recipe).where(Recipe.menu_id == recipe.menu_id, Recipe.composition_key == key, Recipe.id != recipe_id)
    )
    if duplicate:
        raise HTTPException(status_code=409, detail=f"같은 재료 구성의 레시피가 이미 있습니다: {duplicate.name}")
    recipe.name = (body.name or recipe.name).strip()
    recipe.note = body.note
    recipe.active = body.active
    recipe.composition_key = key
    replace_recipe_items(db, recipe, resolved)
    if body.is_default:
        set_default_recipe(db, recipe)
    elif recipe.is_default and not recipe.active:
        replacement = db.scalar(
            select(Recipe).where(Recipe.menu_id == recipe.menu_id, Recipe.id != recipe.id, Recipe.active.is_(True)).order_by(Recipe.version)
        )
        if replacement:
            set_default_recipe(db, replacement)
    db.commit()
    db.expire_all()
    return recipe_payload(
        db.scalar(select(Recipe).where(Recipe.id == recipe_id).options(selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient)))
    )


@router.delete("/recipes/{recipe_id}")
def archive_recipe(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    recipe = db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="레시피를 찾을 수 없습니다.")
    recipe.active = False
    recipe.is_default = False
    replacement = db.scalar(
        select(Recipe).where(Recipe.menu_id == recipe.menu_id, Recipe.id != recipe.id, Recipe.active.is_(True)).order_by(Recipe.version)
    )
    if replacement:
        set_default_recipe(db, replacement)
    db.commit()
    return {"ok": True, "archived": True}


@router.post("/recipes/{recipe_id}/default")
def make_default_recipe(recipe_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    recipe = db.get(Recipe, recipe_id)
    if not recipe or not recipe.active:
        raise HTTPException(status_code=404, detail="사용 가능한 레시피를 찾을 수 없습니다.")
    set_default_recipe(db, recipe)
    db.commit()
    return {"ok": True, "recipe_id": recipe.id}


# 이전 클라이언트 호환용: 기본 레시피를 갱신한다.
@router.put("/menus/{menu_id}/recipe")
def save_legacy_recipe(menu_id: int, body: RecipeBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    recipe = db.scalar(select(Recipe).where(Recipe.menu_id == menu_id, Recipe.is_default.is_(True)))
    if recipe:
        body.is_default = True
        return update_recipe(recipe.id, body, db, user)
    body.is_default = True
    return create_recipe(menu_id, body, db, user)


@router.get("/ingredients")
def list_ingredients(
    q: str = "",
    stat_group: str | None = None,
    active: bool | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = select(Ingredient)
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Ingredient.name.ilike(term), IngredientAlias.alias.ilike(term))).outerjoin(IngredientAlias)
    if stat_group:
        stmt = stmt.where(Ingredient.stat_group == stat_group)
    if active is not None:
        stmt = stmt.where(Ingredient.active == active)
    rows = db.scalars(stmt.order_by(Ingredient.name).offset(offset).limit(limit + 1)).unique().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return {'items': [ingredient_payload(row) for row in items], 'has_more': has_more, 'offset': offset, 'limit': limit}


@router.get("/ingredients/{ingredient_id}/usage-menus")
def ingredient_usage_menus(
    ingredient_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not db.get(Ingredient, ingredient_id):
        raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
    current_rows=db.execute(select(Recipe.menu_id, Recipe.id, RecipeIngredient.quantity_per_100, RecipeIngredient.unit, RecipeIngredient.is_primary, Menu.name, Menu.role, Menu.canonical_name, Menu.active).join(RecipeIngredient, RecipeIngredient.recipe_id==Recipe.id).join(Menu, Menu.id==Recipe.menu_id).where(RecipeIngredient.ingredient_id==ingredient_id, Recipe.active.is_(True))).all()
    historical_rows=db.execute(select(MealServiceMenu.menu_id, MealServiceMenu.menu_name_snapshot, MealServiceMenu.id, MealService.service_date, MealService.meal_type, MealActual.actual_count, MealServiceMenuIngredient.quantity_total, MealServiceMenuIngredient.quantity_per_100, MealServiceMenuIngredient.unit).join(MealServiceMenu, MealServiceMenu.id==MealServiceMenuIngredient.meal_service_menu_id).join(MealService, MealService.id==MealServiceMenu.meal_service_id).outerjoin(MealActual, MealActual.meal_service_id==MealService.id).where(MealServiceMenuIngredient.ingredient_id==ingredient_id).order_by(MealService.service_date.desc(), MealService.meal_type.desc())).all()
    grouped={}
    for menu_id, recipe_id, quantity, unit, is_primary, name, role, canonical_name, active in current_rows:
        item=grouped.setdefault(menu_id,{"menu_id":menu_id,"menu_name":name,"menu_role":role,"menu_canonical_name":canonical_name,"menu_active":active,"recipes":[],"history":[]})
        item["recipes"].append({"recipe_id":recipe_id,"quantity_per_100":quantity,"unit":unit,"is_primary":is_primary})
    for menu_id, snapshot_name, service_menu_id, service_date, meal_type, actual_count, total_quantity, per_100, unit in historical_rows:
        if not menu_id: continue
        item=grouped.setdefault(menu_id,{"menu_id":menu_id,"menu_name":snapshot_name,"menu_role":None,"menu_canonical_name":None,"menu_active":False,"recipes":[],"history":[]})
        item["history"].append({"meal_service_menu_id":service_menu_id,"date":service_date.isoformat(),"meal_type":meal_type,"actual_count":actual_count,"quantity_total":total_quantity,"quantity_per_100":per_100,"unit":unit})
        if not item["menu_name"]: item["menu_name"]=snapshot_name
    current_menu_ids=[menu_id for menu_id in grouped if menu_id is not None]
    current_menus={menu.id:menu for menu in db.scalars(select(Menu).where(Menu.id.in_(current_menu_ids))).all()} if current_menu_ids else {}
    for menu_id, item in grouped.items():
        current_menu=current_menus.get(menu_id)
        if current_menu:
            item["menu_name"]=current_menu.name;item["menu_role"]=current_menu.role;item["menu_canonical_name"]=current_menu.canonical_name;item["menu_active"]=current_menu.active
    items=[]
    for item in grouped.values():
        if q.strip() and q.strip().lower() not in item["menu_name"].lower(): continue
        values=[row for row in item["recipes"] if row["quantity_per_100"] is not None]
        units={row["unit"] or "" for row in values}
        summary={"min":None,"max":None,"unit":next(iter(units)) if len(units)==1 else None,"mixed_units":len(units)>1}
        if values and len(units)==1:
            quantities=[row["quantity_per_100"] for row in values]
            summary["min"]=min(quantities);summary["max"]=max(quantities)
        latest=item["history"][0] if item["history"] else None
        item.update({"current_recipe_count":len(item["recipes"]),"current_quantity_summary":summary,"historical_usage_count":len({row["meal_service_menu_id"] for row in item["history"]}),"last_used":{"date":latest["date"],"meal_type":latest["meal_type"],"actual_count":latest["actual_count"]} if latest else None,"has_current_usage":bool(item["recipes"]),"has_historical_usage":bool(item["history"]),"recipes":None,"history":None})
        items.append(item)
    items.sort(key=lambda item:(item["last_used"] is not None, item["last_used"]["date"] if item["last_used"] else "", item["menu_name"]), reverse=True)
    total=len(items);return {"items":items[offset:offset+limit],"offset":offset,"limit":limit,"total":total,"has_more":offset+limit<total}


@router.get("/ingredients/{ingredient_id}/menus/{menu_id}/usage-detail")
def ingredient_menu_usage_detail(
    ingredient_id: int,
    menu_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not db.get(Ingredient, ingredient_id): raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
    menu=db.get(Menu, menu_id)
    current=db.execute(select(Recipe.id, Recipe.name, Recipe.version, Recipe.is_default, Recipe.active, RecipeIngredient.quantity_per_100, RecipeIngredient.unit, RecipeIngredient.is_primary).join(RecipeIngredient, RecipeIngredient.recipe_id==Recipe.id).where(Recipe.menu_id==menu_id, RecipeIngredient.ingredient_id==ingredient_id)).all()
    history_stmt=select(MealServiceMenu.id, MealService.service_date, MealService.meal_type, MealService.planned_count, MealServiceMenu.recipe_name_snapshot, MealServiceMenu.recipe_version_snapshot, MealServiceMenuIngredient.ingredient_name_snapshot, MealServiceMenuIngredient.quantity_total, MealServiceMenuIngredient.quantity_per_100, MealServiceMenuIngredient.unit).join(MealServiceMenu, MealServiceMenu.id==MealServiceMenuIngredient.meal_service_menu_id).join(MealService, MealService.id==MealServiceMenu.meal_service_id).where(MealServiceMenu.menu_id==menu_id, MealServiceMenuIngredient.ingredient_id==ingredient_id).order_by(MealService.service_date.desc(), MealService.meal_type.desc())
    total=db.scalar(select(func.count()).select_from(history_stmt.order_by(None).subquery())) or 0
    history=db.execute(history_stmt.offset(offset).limit(limit)).all()
    return {"menu":{"menu_id":menu_id,"name":menu.name if menu else None,"role":menu.role if menu else None,"active":menu.active if menu else False},"recipes":[{"recipe_id":r[0],"name":r[1],"version":r[2],"is_default":r[3],"active":r[4],"quantity_per_100":r[5],"unit":r[6],"is_primary":r[7]} for r in current],"history":[{"meal_service_menu_id":r[0],"date":r[1].isoformat(),"meal_type":r[2],"planned_count":r[3],"recipe_name_snapshot":r[4],"recipe_version_snapshot":r[5],"ingredient_name_snapshot":r[6],"quantity_total":r[7],"quantity_per_100":r[8],"unit":r[9]} for r in history],"offset":offset,"limit":limit,"total":total,"has_more":offset+len(history)<total}


@router.get("/ingredients/{ingredient_id}")
def get_ingredient(ingredient_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(Ingredient, ingredient_id)
    if not row:
        raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
    result = ingredient_payload(row)
    result["aliases"] = [{"id": alias.id, "alias": alias.alias} for alias in row.aliases]
    return result


@router.post("/ingredients")
def create_ingredient(body: IngredientBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = body.name.strip()
    if db.scalar(select(Ingredient).where(Ingredient.name == name)):
        raise HTTPException(status_code=409, detail="같은 이름의 재료가 있습니다.")
    row = Ingredient(**body.model_dump())
    row.name = name
    db.add(row)
    db.commit()
    return ingredient_payload(row)


@router.put("/ingredients/{ingredient_id}")
def update_ingredient(ingredient_id: int, body: IngredientBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(Ingredient, ingredient_id)
    if not row:
        raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
    name = body.name.strip()
    if db.scalar(select(Ingredient).where(Ingredient.name == name, Ingredient.id != ingredient_id)):
        raise HTTPException(status_code=409, detail="같은 이름의 재료가 있습니다.")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.name = name
    db.commit()
    return ingredient_payload(row)


@router.delete("/ingredients/{ingredient_id}")
def archive_ingredient(ingredient_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(Ingredient, ingredient_id)
    if not row:
        raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
    row.active = False
    db.commit()
    return {"ok": True, "archived": True}


@router.post("/ingredients/{ingredient_id}/aliases")
def add_alias(ingredient_id: int, body: AliasBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ingredient = db.get(Ingredient, ingredient_id)
    if not ingredient:
        raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
    existing = db.scalar(select(IngredientAlias).where(IngredientAlias.alias == body.alias.strip()))
    if existing:
        existing.ingredient_id = ingredient_id
        alias = existing
    else:
        alias = IngredientAlias(alias=body.alias.strip(), ingredient_id=ingredient_id, source="사용자")
        db.add(alias)
    db.commit()
    return {"id": alias.id, "alias": alias.alias}
