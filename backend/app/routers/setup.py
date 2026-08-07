from __future__ import annotations

import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..importer import MigrationImporter
from ..models import ImportJob, User

router = APIRouter(prefix="/api/setup", tags=["setup"])


class ApplyBody(BaseModel):
    token: str
    mode: str = "replace"


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
