from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..stats_service import dashboard_statistics, week_statistics

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/week")
def week(week_start: date, db: Session = Depends(get_db), user: User = Depends(current_user)):
    monday = week_start.fromordinal(week_start.toordinal() - week_start.weekday())
    return week_statistics(db, monday)


@router.get("/dashboard")
def dashboard(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    today = date.today()
    resolved_end = end_date or today
    resolved_start = start_date or (resolved_end - timedelta(days=27))
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start
    return dashboard_statistics(db, resolved_start, resolved_end)
