from __future__ import annotations

import hashlib
import shutil
from datetime import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..hwpx_service import HwpxTemplateError, validate_hwpx
from ..models import DocumentTemplate, MealTypeSetting, User

router = APIRouter(prefix="/api/master-data", tags=["master-data"])

VALID_TYPES = {"MEAL_PLAN", "COOKING_INSTRUCTION", "PRESERVATION_RECORD"}
TYPE_LABELS = {
    "MEAL_PLAN": "식단표",
    "COOKING_INSTRUCTION": "조리지시서",
    "PRESERVATION_RECORD": "보존식 기록지",
}


# ---------------------------------------------------------------------------
# HWPX document templates
# ---------------------------------------------------------------------------

def _template_payload(row: DocumentTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "document_type": row.document_type,
        "document_type_label": TYPE_LABELS.get(row.document_type, row.document_type),
        "name": row.name,
        "description": row.description or "",
        "original_filename": row.original_filename,
        "stored_filename": row.stored_filename or "",
        "file_size": row.file_size,
        "checksum_sha256": row.checksum_sha256 or "",
        "version": row.version,
        "active": row.active,
        "is_valid": row.is_valid,
        "validation_message": row.validation_message or "",
        "placeholder_summary": row.placeholder_summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_by": row.created_by or "",
    }


@router.get("/document-templates")
def list_templates(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(DocumentTemplate).order_by(DocumentTemplate.document_type, DocumentTemplate.version.desc())
    ).all()
    return [_template_payload(row) for row in rows]


@router.get("/document-templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    return _template_payload(row)


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


@router.post("/document-templates")
def upload_template(
    document_type: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    activate: bool = Form(False),
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

    version = 1 + (
        db.scalar(
            select(func.max(DocumentTemplate.version)).where(DocumentTemplate.document_type == document_type)
        )
        or 0
    )
    temp_id = f"{document_type.lower()}_v{version}_{__import__('secrets').token_hex(5)}"
    stored_filename = f"{temp_id}.hwpx"
    destination = folder / stored_filename

    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    try:
        validation = validate_hwpx(destination, document_type)
    except HwpxTemplateError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_size = destination.stat().st_size
    checksum = _compute_sha256(destination)

    if activate:
        db.execute(
            update(DocumentTemplate)
            .where(DocumentTemplate.document_type == document_type)
            .values(active=False)
        )

    row = DocumentTemplate(
        document_type=document_type,
        name=name.strip(),
        description=description.strip() or None,
        original_filename=file.filename,
        stored_filename=stored_filename,
        storage_path=str(destination),
        file_size=file_size,
        checksum_sha256=checksum,
        active=activate,
        version=version,
        is_valid=True,
        validation_message=None,
        placeholder_summary=validation,
        created_by=user.display_name,
    )
    db.add(row)
    db.commit()
    return _template_payload(row)


@router.put("/document-templates/{template_id}")
def update_template(
    template_id: int,
    name: str = Form(None),
    description: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")

    if name is not None:
        row.name = name.strip()
    if description is not None:
        row.description = description.strip() or None

    if file and file.filename:
        if not file.filename.lower().endswith(".hwpx"):
            raise HTTPException(status_code=400, detail="HWPX 파일만 등록할 수 있습니다.")
        folder = settings.template_dir / row.document_type.lower()
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / (row.stored_filename or f"{row.document_type.lower()}_{row.id}_{row.version}.hwpx")
        with destination.open("wb") as output:
            shutil.copyfileobj(file.file, output)
        try:
            validation = validate_hwpx(destination, row.document_type)
        except HwpxTemplateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.storage_path = str(destination)
        row.file_size = destination.stat().st_size
        row.checksum_sha256 = _compute_sha256(destination)
        row.is_valid = True
        row.validation_message = None
        row.placeholder_summary = validation

    db.commit()
    return _template_payload(row)


@router.post("/document-templates/{template_id}/validate")
def validate_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    path = Path(row.storage_path)
    if not path.exists():
        row.is_valid = False
        row.validation_message = "파일이 존재하지 않습니다."
        db.commit()
        raise HTTPException(status_code=404, detail="템플릿 파일이 존재하지 않습니다.")
    try:
        validation = validate_hwpx(path, row.document_type)
        row.is_valid = True
        row.validation_message = None
        row.placeholder_summary = validation
    except HwpxTemplateError as exc:
        row.is_valid = False
        row.validation_message = str(exc)
    db.commit()
    return _template_payload(row)


@router.post("/document-templates/{template_id}/activate")
def activate_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail="템플릿 파일이 존재하지 않습니다.")
    try:
        validate_hwpx(path, row.document_type)
    except HwpxTemplateError as exc:
        raise HTTPException(status_code=400, detail=f"활성화 실패: {exc}") from exc
    db.execute(
        update(DocumentTemplate)
        .where(DocumentTemplate.document_type == row.document_type)
        .values(active=False)
    )
    row.active = True
    db.commit()
    return _template_payload(row)


@router.post("/document-templates/{template_id}/deactivate")
def deactivate_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    row.active = False
    db.commit()
    return _template_payload(row)


@router.get("/document-templates/{template_id}/download")
def download_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    path = Path(row.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="템플릿 파일이 존재하지 않습니다.")
    return FileResponse(
        path,
        media_type="application/vnd.hancom.hwpx",
        filename=row.original_filename,
    )


@router.delete("/document-templates/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = db.get(DocumentTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="템플릿을 찾을 수 없습니다.")
    if row.active:
        raise HTTPException(status_code=400, detail="활성 템플릿은 삭제할 수 없습니다. 먼저 비활성화해 주세요.")
    path = Path(row.storage_path)
    db.delete(row)
    db.commit()
    path.unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Meal service defaults
# ---------------------------------------------------------------------------

class MealServiceDefaultItem(BaseModel):
    meal_type: str
    default_planned_count: int = Field(ge=0)
    default_service_time: str
    is_active: bool = True

    @model_validator(mode="after")
    def validate_time(self):
        try:
            time.fromisoformat(self.default_service_time)
        except ValueError as exc:
            raise ValueError("배식시간 형식은 HH:MM이어야 합니다.") from exc
        return self


class MealServiceDefaultsBody(BaseModel):
    items: list[MealServiceDefaultItem]


def _meal_type_setting_payload(row: MealTypeSetting) -> dict[str, Any]:
    return {
        "id": row.id,
        "meal_type": row.code,
        "display_name": row.name,
        "default_planned_count": row.default_planned_count,
        "default_service_time": row.default_service_time.strftime("%H:%M") if row.default_service_time else "",
        "sort_order": row.sort_order,
        "is_active": row.active,
    }


@router.get("/meal-service-defaults")
def get_meal_service_defaults(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(MealTypeSetting).order_by(MealTypeSetting.sort_order, MealTypeSetting.id)
    ).all()
    return [_meal_type_setting_payload(row) for row in rows]


@router.put("/meal-service-defaults")
def update_meal_service_defaults(
    body: MealServiceDefaultsBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    for item in body.items:
        row = db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == item.meal_type))
        if not row:
            raise HTTPException(status_code=404, detail=f"배식유형을 찾을 수 없습니다: {item.meal_type}")
        row.default_planned_count = item.default_planned_count
        row.default_service_time = time.fromisoformat(item.default_service_time)
        row.active = item.is_active
    db.commit()
    rows = db.scalars(
        select(MealTypeSetting).order_by(MealTypeSetting.sort_order, MealTypeSetting.id)
    ).all()
    return [_meal_type_setting_payload(row) for row in rows]
