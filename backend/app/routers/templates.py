from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..hwpx_service import HwpxTemplateError, validate_hwpx
from ..models import DocumentTemplate, User

router = APIRouter(prefix="/api/templates", tags=["templates"])
VALID_TYPES = {"MEAL_PLAN", "COOKING_INSTRUCTION", "PRESERVATION_RECORD"}


@router.get("")
def list_templates(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(DocumentTemplate).order_by(DocumentTemplate.document_type, DocumentTemplate.version.desc())).all()
    return [
        {
            "id": row.id,
            "document_type": row.document_type,
            "name": row.name,
            "original_filename": row.original_filename,
            "active": row.active,
            "version": row.version,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("")
def upload_template(
    document_type: str = Form(...),
    name: str = Form(...),
    activate: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if document_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 문서 유형입니다.")
    if not file.filename or not file.filename.lower().endswith(".hwpx"):
        raise HTTPException(status_code=400, detail="HWPX 파일만 등록할 수 있습니다.")
    folder = settings.template_dir / document_type.lower()
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{secrets.token_hex(10)}.hwpx"
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    try:
        validation = validate_hwpx(destination, document_type)
    except HwpxTemplateError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    version = 1 + max(
        [row.version for row in db.scalars(select(DocumentTemplate).where(DocumentTemplate.document_type == document_type)).all()],
        default=0,
    )
    if activate:
        db.execute(
            update(DocumentTemplate)
            .where(DocumentTemplate.document_type == document_type)
            .values(active=False)
        )
    row = DocumentTemplate(
        document_type=document_type,
        name=name.strip(),
        original_filename=file.filename,
        storage_path=str(destination),
        active=activate,
        version=version,
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "version": row.version, "active": row.active, "validation": validation}


@router.post("/{template_id}/activate")
def activate_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    db.execute(update(DocumentTemplate).where(DocumentTemplate.document_type == row.document_type).values(active=False))
    row.active = True
    db.commit()
    return {"ok": True}


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    path = Path(row.storage_path)
    db.delete(row)
    db.commit()
    path.unlink(missing_ok=True)
    return {"ok": True}
