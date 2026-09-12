from __future__ import annotations

import csv
import io
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import admin_user
from ..models import ImportJob, User, WeatherHistory, WeatherUploadHistory
from ..weather_import import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    WeatherImportError,
    apply_weather_file,
    parse_weather_file,
    sha256_file,
)

router = APIRouter(prefix="/api/weather", tags=["weather"])


class WeatherApplyBody(BaseModel):
    token: str


def _save_upload(file: UploadFile, destination: Path) -> None:
    total = 0
    with destination.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise WeatherImportError(f"파일 크기는 {MAX_FILE_SIZE // (1024 * 1024)}MB 이하여야 합니다.")
            output.write(chunk)


def _cleanup_expired_previews(db: Session) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    jobs = db.scalars(select(ImportJob).where(ImportJob.status == "WEATHER_PREVIEWED", ImportJob.created_at < cutoff)).all()
    for job in jobs:
        Path(job.storage_path).unlink(missing_ok=True)
        job.status = "WEATHER_EXPIRED"
    if jobs:
        db.commit()


@router.post("/preview")
def preview_weather(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    _cleanup_expired_previews(db)
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="XLSX, XLS, CSV 파일만 업로드할 수 있습니다.")
    token = secrets.token_urlsafe(24)
    destination = settings.import_dir / f"weather-{token}{suffix}"
    try:
        _save_upload(file, destination)
        parsed = parse_weather_file(destination, db)
    except WeatherImportError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="날씨자료 분석 중 오류가 발생했습니다.") from exc
    summary = {
        **parsed["summary"],
        "kind": "weather",
        "file_sha256": sha256_file(destination),
    }
    job = ImportJob(
        token=token,
        filename=filename,
        storage_path=str(destination),
        status="WEATHER_PREVIEWED",
        summary=summary,
        errors=parsed["errors"][:1000],
    )
    db.add(job)
    db.commit()
    return {
        "token": token,
        "filename": filename,
        "summary": summary,
        "preview_rows": parsed["rows"][:20],
        "errors": parsed["errors"][:200],
    }


def _record_failed_upload(db: Session, job: ImportJob, user_id: int, message: str) -> None:
    summary = job.summary or {}
    db.add(WeatherUploadHistory(
        original_filename=job.filename,
        checksum_sha256=summary.get("file_sha256", ""),
        date_from=date.fromisoformat(summary["date_from"]) if summary.get("date_from") else None,
        date_to=date.fromisoformat(summary["date_to"]) if summary.get("date_to") else None,
        stations=summary.get("stations", []),
        total_rows=summary.get("total_rows", 0),
        valid_rows=summary.get("valid_rows", 0),
        skipped_rows=summary.get("skipped_rows", 0),
        error_rows=summary.get("error_rows", 0),
        status="FAILED",
        errors=[{"row": "", "message": message}],
        uploaded_by=user_id,
        completed_at=datetime.now(timezone.utc),
    ))
    job.status = "WEATHER_FAILED"
    db.commit()


@router.post("/apply")
def apply_weather(
    body: WeatherApplyBody,
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    job = db.scalar(select(ImportJob).where(ImportJob.token == body.token))
    if not job or (job.summary or {}).get("kind") != "weather":
        raise HTTPException(status_code=404, detail="날씨자료 Preview를 찾을 수 없습니다.")
    if job.status != "WEATHER_PREVIEWED":
        raise HTTPException(status_code=400, detail="이미 처리되었거나 사용할 수 없는 Preview입니다.")
    created_at = job.created_at.replace(tzinfo=timezone.utc) if job.created_at.tzinfo is None else job.created_at
    if datetime.now(timezone.utc) - created_at > timedelta(minutes=30):
        raise HTTPException(status_code=400, detail="Preview가 만료되었습니다. 파일을 다시 분석해 주세요.")
    source = Path(job.storage_path)
    checksum = (job.summary or {}).get("file_sha256", "")
    if not source.is_file() or sha256_file(source) != checksum:
        raise HTTPException(status_code=400, detail="Preview 이후 업로드 파일이 변경되었거나 삭제되었습니다.")
    if not (job.summary or {}).get("valid_rows"):
        raise HTTPException(status_code=400, detail="반영 가능한 정상 데이터가 없습니다.")
    try:
        batch, result = apply_weather_file(
            source,
            db,
            job.filename,
            checksum,
            user.id,
            (job.summary or {}).get("rows_fingerprint", ""),
        )
        job.status = "WEATHER_COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        job.summary = {**(job.summary or {}), "result": result, "batch_id": batch.id}
        db.commit()
        source.unlink(missing_ok=True)
        return {"ok": True, "batch_id": batch.id, "result": result, "completed_at": job.completed_at.isoformat()}
    except WeatherImportError as exc:
        db.rollback()
        job = db.scalar(select(ImportJob).where(ImportJob.token == body.token))
        if job:
            _record_failed_upload(db, job, user.id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        job = db.scalar(select(ImportJob).where(ImportJob.token == body.token))
        if job:
            _record_failed_upload(db, job, user.id, "날씨자료 DB 반영에 실패했습니다.")
        raise HTTPException(status_code=400, detail="날씨자료 DB 반영에 실패했습니다.") from exc


@router.get("/records")
def weather_records(
    start_date: date | None = None,
    end_date: date | None = None,
    station: str = Query("", max_length=120),
    min_temp: float | None = None,
    max_temp: float | None = None,
    precipitation: str = Query("all", pattern="^(all|yes|no)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    filters = []
    if start_date:
        filters.append(WeatherHistory.observation_date >= start_date)
    if end_date:
        filters.append(WeatherHistory.observation_date <= end_date)
    if station.strip():
        term = f"%{station.strip()}%"
        filters.append(or_(WeatherHistory.station_id.ilike(term), WeatherHistory.station_name.ilike(term)))
    if min_temp is not None:
        filters.append(WeatherHistory.avg_temp >= min_temp)
    if max_temp is not None:
        filters.append(WeatherHistory.avg_temp <= max_temp)
    if precipitation == "yes":
        filters.append(WeatherHistory.precipitation > 0)
    elif precipitation == "no":
        filters.append(WeatherHistory.precipitation == 0)
    total = db.scalar(select(func.count()).select_from(WeatherHistory).where(*filters)) or 0
    rows = db.scalars(
        select(WeatherHistory)
        .where(*filters)
        .order_by(WeatherHistory.observation_date.desc(), WeatherHistory.station_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [{
            "id": row.id,
            "observation_date": row.observation_date.isoformat(),
            "station_id": row.station_id,
            "station_name": row.station_name or "",
            "avg_temp": row.avg_temp,
            "min_temp": row.min_temp,
            "max_temp": row.max_temp,
            "precipitation": row.precipitation,
            "avg_humidity": row.avg_humidity,
            "snow_depth": row.snow_depth,
            "sunshine_hours": row.sunshine_hours,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        } for row in rows],
    }


@router.get("/uploads")
def weather_uploads(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    total = db.scalar(select(func.count()).select_from(WeatherUploadHistory)) or 0
    rows = db.scalars(
        select(WeatherUploadHistory)
        .order_by(WeatherUploadHistory.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "items": [{
            "id": row.id,
            "original_filename": row.original_filename,
            "date_from": row.date_from.isoformat() if row.date_from else None,
            "date_to": row.date_to.isoformat() if row.date_to else None,
            "stations": row.stations or [],
            "total_rows": row.total_rows,
            "inserted_rows": row.inserted_rows,
            "updated_rows": row.updated_rows,
            "skipped_rows": row.skipped_rows,
            "error_rows": row.error_rows,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        } for row in rows],
    }


@router.get("/uploads/{upload_id}/errors.csv")
def weather_upload_errors(
    upload_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    upload = db.get(WeatherUploadHistory, upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="업로드 이력을 찾을 수 없습니다.")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["행", "오류 내용"])
    for error in upload.errors or []:
        writer.writerow([error.get("row", ""), error.get("message", "")])
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="weather-upload-{upload_id}-errors.csv"'},
    )
