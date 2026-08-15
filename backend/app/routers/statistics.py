from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..dashboard_service import operations_dashboard
from ..db import get_db
from ..deps import current_user
from ..ingredient_statistics import ingredient_detail, ingredient_statistics
from ..menu_statistics import menu_detail, menu_statistics
from ..models import User
from ..operations_statistics import operations_statistics
from ..statistics_service import meal_statistics, meal_trend

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


def _resolved_range(start_date: date, end_date: date) -> tuple[date, date]:
    if start_date > end_date:
        return end_date, start_date
    return start_date, end_date


@router.get("/dashboard")
def dashboard(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return operations_dashboard(db, start, end, meal_type)


@router.get("/ingredients/{ingredient_id}")
def ingredients_detail(
    ingredient_id: int,
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    result = ingredient_detail(db, ingredient_id, start, end, meal_type)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="재료를 찾을 수 없습니다.")
    return result


@router.get("/ingredients")
def ingredients(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    unused_days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return ingredient_statistics(db, start, end, meal_type, unused_days)


@router.get("/menus/{menu_id}")
def menus_detail(
    menu_id: int,
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    result = menu_detail(db, menu_id, start, end, meal_type)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")
    return result


@router.get("/menus")
def menus(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    unused_days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return menu_statistics(db, start, end, meal_type, unused_days)


@router.get("/operations")
def operations(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return operations_statistics(db, start, end, meal_type)


@router.get("/meals")
def meals(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return meal_statistics(db, start, end, meal_type)


@router.get("/meals/trend")
def meals_trend(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return meal_trend(db, start, end, meal_type)
