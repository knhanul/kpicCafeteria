from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..advanced_statistics import (
    StationSelectionError,
    data_quality,
    drilldown,
    export_xlsx,
    menu_metrics,
    menu_weather_metrics,
    overview,
    plan_vs_actual,
    station_list,
    weather_metrics,
)
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


def _station_error(exc: StationSelectionError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/advanced/stations")
def advanced_stations(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if start_date and end_date:
        start_date, end_date = _resolved_range(start_date, end_date)
    return station_list(db, start_date, end_date)


@router.get("/advanced/overview")
def advanced_overview(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return overview(db, start, end, meal_type)


@router.get("/advanced/plan-vs-actual")
def advanced_plan_vs_actual(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    station_id: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    try:
        return plan_vs_actual(db, start, end, meal_type, station_id)
    except StationSelectionError as exc:
        raise _station_error(exc) from exc


@router.get("/advanced/menus")
def advanced_menus(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    return menu_metrics(db, start, end, meal_type)


@router.get("/advanced/weather")
def advanced_weather(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    station_id: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    try:
        return weather_metrics(db, start, end, meal_type, station_id)
    except StationSelectionError as exc:
        raise _station_error(exc) from exc


@router.get("/advanced/menu-weather")
def advanced_menu_weather(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    station_id: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    try:
        return menu_weather_metrics(db, start, end, meal_type, station_id)
    except StationSelectionError as exc:
        raise _station_error(exc) from exc


@router.get("/advanced/data-quality")
def advanced_data_quality(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    station_id: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    try:
        return data_quality(db, start, end, meal_type, station_id)
    except StationSelectionError as exc:
        raise _station_error(exc) from exc


@router.get("/advanced/drilldown")
def advanced_drilldown(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    station_id: str | None = Query(None, max_length=80),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    rain: str = Query("all", pattern="^(all|missing|dry|rain)$"),
    menu: str | None = Query(None, max_length=200),
    temp_bucket: str | None = Query(None, pattern="^(<0|0~4\\.9|5~9\\.9|10~14\\.9|15~19\\.9|20~24\\.9|25~29\\.9|>=30)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    try:
        return drilldown(db, start, end, meal_type, station_id, page, page_size, rain, menu, temp_bucket)
    except StationSelectionError as exc:
        raise _station_error(exc) from exc


@router.get("/advanced/export.xlsx")
def advanced_export(
    start_date: date,
    end_date: date,
    meal_type: str = Query("all", pattern="^(all|lunch|dinner)$"),
    station_id: str | None = Query(None, max_length=80),
    rain: str = Query("all", pattern="^(all|missing|dry|rain)$"),
    menu: str | None = Query(None, max_length=200),
    temp_bucket: str | None = Query(None, pattern="^(<0|0~4\\.9|5~9\\.9|10~14\\.9|15~19\\.9|20~24\\.9|25~29\\.9|>=30)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    start, end = _resolved_range(start_date, end_date)
    try:
        content = export_xlsx(db, start, end, meal_type, station_id, rain, menu, temp_bucket)
    except StationSelectionError as exc:
        raise _station_error(exc) from exc
    filename = f"cafeteria-statistics-{start.isoformat()}-{end.isoformat()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
