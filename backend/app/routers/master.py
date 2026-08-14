from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user
from ..models import Ingredient, IngredientAlias, MealServiceMenu, Menu, Recipe, RecipeIngredient, User

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


class AliasBody(BaseModel):
    alias: str


def _menu_query():
    return select(Menu).options(
        selectinload(Menu.recipes).selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient)
    )


def recipe_payload(recipe: Recipe, detail: bool = True) -> dict[str, Any]:
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


@router.get("/menus/{menu_id}")
def get_menu(menu_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    menu = db.scalar(_menu_query().where(Menu.id == menu_id))
    if not menu:
        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    return menu_payload(menu, True)


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
