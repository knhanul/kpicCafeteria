from __future__ import annotations

import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..actual_meal_import import MAX_FILE_SIZE, EXPECTED_FILENAME, ActualMealUploadError, apply_actual_meals, preview_actual_meals, sha256_file
from ..config import settings
from ..db import get_db
from ..deps import admin_user, current_user
from ..importer import MigrationImporter
from .admin import create_backup
from ..models import ImportJob, User

router = APIRouter(prefix="/api/setup", tags=["setup"])


class ApplyBody(BaseModel):
    token: str
    mode: str = "replace"


class ActualMealApplyBody(BaseModel):
    token: str


def _save_actual_upload(file: UploadFile, destination: Path) -> None:
    total = 0
    with destination.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise ActualMealUploadError(f"파일 크기는 {MAX_FILE_SIZE // (1024 * 1024)}MB 이하여야 합니다.")
            output.write(chunk)


@router.post("/import/preview")
def preview_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="XLSX 파일만 업로드할 수 있습니다.")
    token = secrets.token_urlsafe(24)
    destination = settings.import_dir / f"{token}.xlsx"
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    importer = MigrationImporter(destination)
    summary, errors = importer.preview()
    job = ImportJob(
        token=token,
        filename=file.filename,
        storage_path=str(destination),
        status="PREVIEWED" if not errors else "INVALID",
        summary=summary,
        errors=errors,
    )
    db.add(job)
    db.commit()
    return {"token": token, "summary": summary, "errors": errors}


@router.post("/import/apply")
def apply_import(
    body: ApplyBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    job = db.scalar(select(ImportJob).where(ImportJob.token == body.token))
    if not job:
        raise HTTPException(status_code=404, detail="업로드 작업을 찾을 수 없습니다.")
    if job.status == "INVALID":
        raise HTTPException(status_code=400, detail="검증에 실패한 파일입니다.")
    try:
        result = MigrationImporter(Path(job.storage_path)).apply(db, mode=body.mode, user_id=user.id)
        job.status = "COMPLETED"
        job.summary = {**(job.summary or {}), "result": result}
        job.completed_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        return {"ok": True, "result": result}
    except Exception as exc:
        db.rollback()
        job = db.scalar(select(ImportJob).where(ImportJob.token == body.token))
        if job:
            job.status = "FAILED"
            job.errors = [*(job.errors or []), {"type": "IMPORT_ERROR", "message": str(exc)}]
            db.commit()
        raise HTTPException(status_code=400, detail=f"이관 실패: {exc}") from exc


@router.post("/actual-meals/preview")
def preview_actual_meals_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="XLSX 파일만 업로드할 수 있습니다.")
    token = secrets.token_urlsafe(24)
    destination = settings.import_dir / f"actual-meals-{token}.xlsx"
    try:
        _save_actual_upload(file, destination)
        result = preview_actual_meals(destination, db)
    except ActualMealUploadError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="XLSX 검증 중 오류가 발생했습니다.") from exc

    summary = {**result["summary"], "file_sha256": sha256_file(destination), "kind": "actual-meals"}
    job = ImportJob(
        token=token,
        filename=file.filename,
        storage_path=str(destination),
        status="ACTUAL_PREVIEWED" if not result["errors"] else "ACTUAL_INVALID",
        summary={**summary, "rows": result["rows"]},
        errors=result["errors"],
    )
    db.add(job)
    db.commit()
    return {"token": token, "filename": file.filename, "summary": summary, "rows": result["rows"], "errors": result["errors"]}


@router.post("/actual-meals/apply")
def apply_actual_meals_upload(
    body: ActualMealApplyBody,
    db: Session = Depends(get_db),
    user: User = Depends(admin_user),
):
    job = db.scalar(select(ImportJob).where(ImportJob.token == body.token))
    if not job or (job.summary or {}).get("kind") != "actual-meals":
        raise HTTPException(status_code=404, detail="식수 업로드 Preview를 찾을 수 없습니다.")
    if job.status != "ACTUAL_PREVIEWED":
        raise HTTPException(status_code=400, detail="오류가 있거나 이미 처리된 Preview입니다.")
    created_at = job.created_at
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at and datetime.now(timezone.utc) - created_at > timedelta(minutes=30):
        raise HTTPException(status_code=400, detail="Preview가 만료되었습니다. 파일을 다시 검증해 주세요.")
    source = Path(job.storage_path)
    if not source.is_file() or sha256_file(source) != (job.summary or {}).get("file_sha256"):
        raise HTTPException(status_code=400, detail="Preview 이후 업로드 파일이 변경되었거나 삭제되었습니다.")
    try:
        create_backup(db, user)
        result = apply_actual_meals(source, db, user.id, (job.summary or {}).get("rows_fingerprint", ""))
        job.status = "ACTUAL_COMPLETED"
        job.summary = {**(job.summary or {}), "result": result}
        job.completed_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        source.unlink(missing_ok=True)
        return {"ok": True, "result": result, "completed_at": job.completed_at.isoformat()}
    except ActualMealUploadError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        job = db.scalar(select(ImportJob).where(ImportJob.token == body.token))
        if job:
            job.status = "ACTUAL_FAILED"
            job.errors = [*(job.errors or []), {"type": "ACTUAL_MEAL_APPLY_ERROR", "message": "DB 반영에 실패했습니다."}]
            db.commit()
        raise HTTPException(status_code=400, detail="식수 정보 DB 반영에 실패했습니다.") from exc


@router.get("/import/jobs")
def import_jobs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    jobs = db.scalars(select(ImportJob).order_by(ImportJob.created_at.desc()).limit(20)).all()
    return [
        {
            "token": job.token,
            "filename": job.filename,
            "status": job.status,
            "summary": job.summary,
            "errors": job.errors,
            "created_at": job.created_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        for job in jobs
    ]
