from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..document_service import create_preview, render_pdf, render_preview_html, resolve_services
from ..document_hwpx import generate_hwpx_bytes, generate_pdf_bytes
from ..hwpx_service import HwpxTemplateError, active_template
from ..models import DocumentPreview, MealService, User

router = APIRouter(tags=["documents"])
VALID_TYPES = {"MEAL_PLAN", "COOKING_INSTRUCTION", "PRESERVATION_RECORD"}


class PreviewBody(BaseModel):
    document_type: str
    service_ids: list[int] | None = None
    start_date: date | None = None
    end_date: date | None = None


class ExportBody(BaseModel):
    service_ids: list[int] | None = None
    start_date: date | None = None
    end_date: date | None = None


class PreviewRangeBody(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _validate_range(self):
        if self.end_date < self.start_date:
            raise ValueError("종료일은 시작일보다 빠를 수 없습니다.")
        return self


def get_preview_or_404(db: Session, token: str, user_id: int | None = None) -> DocumentPreview:
    preview = db.get(DocumentPreview, token)
    if not preview:
        raise HTTPException(status_code=404, detail="미리보기를 찾을 수 없습니다.")
    if preview.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="미리보기가 만료되었습니다.")
    if user_id and preview.user_id not in {None, user_id}:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    return preview


@router.post("/api/documents/preview")
def preview_document(
    body: PreviewBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if body.document_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 문서 유형입니다.")
    services = resolve_services(db, body.service_ids, body.start_date, body.end_date)
    if not services:
        raise HTTPException(status_code=400, detail="출력할 배식이 없습니다.")
    preview = create_preview(db, body.document_type, services, user.id)
    return {
        "token": preview.token,
        "html_url": f"/preview/{preview.token}",
        "pdf_url": f"/api/documents/{preview.token}/pdf",
        "hwpx_url": f"/api/documents/{preview.token}/hwpx",
    }


@router.post("/api/documents/meal-plan/preview")
def preview_meal_plan_pdf(
    body: PreviewRangeBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _preview_pdf_by_type("MEAL_PLAN", body, db, user)


@router.post("/api/documents/cooking-instruction/preview")
def preview_cooking_instruction_pdf(
    body: PreviewRangeBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _preview_pdf_by_type("COOKING_INSTRUCTION", body, db, user)


@router.post("/api/documents/preserved-food/preview")
def preview_preserved_food_pdf(
    body: PreviewRangeBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _preview_pdf_by_type("PRESERVATION_RECORD", body, db, user)


@router.post("/api/documents/preservation-record/preview")
def preview_preservation_record_pdf(
    body: PreviewRangeBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _preview_pdf_by_type("PRESERVATION_RECORD", body, db, user)


@router.get("/preview/{token}", response_class=HTMLResponse)
def preview_page(token: str, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return HTMLResponse("<script>location.href='/login'</script>", status_code=401)
    preview = get_preview_or_404(db, token, int(user_id))
    return HTMLResponse(render_preview_html(preview, toolbar=True))


@router.get("/api/documents/{token}/pdf")
def download_pdf(
    token: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    preview = get_preview_or_404(db, token, user.id)
    try:
        content, filename = render_pdf(db, preview)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF 생성에 실패했습니다: {exc}") from exc
    _mark_output(db, preview)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/api/documents/{token}/hwpx")
def download_hwpx(
    token: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    preview = get_preview_or_404(db, token, user.id)
    template = active_template(db, preview.document_type)
    if not template:
        raise HTTPException(
            status_code=409,
            detail="활성 HWPX 템플릿이 없습니다. HWPX 문서 메뉴에서 템플릿을 등록해 주세요.",
        )
    try:
        services = resolve_services(db, preview.service_ids)
        if not services:
            raise HTTPException(status_code=400, detail="출력할 배식이 없습니다.")
        content, filename = generate_hwpx_bytes(
            preview.document_type,
            services,
            template.storage_path,
        )
    except HwpxTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"HWPX 생성에 실패했습니다: {exc}") from exc
    _mark_output(db, preview)
    return Response(
        content,
        media_type="application/vnd.hancom.hwpx",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def _preview_pdf_by_type(document_type: str, body: PreviewRangeBody, db: Session, _user: User):
    template = active_template(db, document_type)
    if not template:
        raise HTTPException(
            status_code=409,
            detail="활성 HWPX 템플릿이 없습니다. HWPX 문서 메뉴에서 템플릿을 등록해 주세요.",
        )
    services = resolve_services(db, start_date=body.start_date, end_date=body.end_date)
    if not services:
        raise HTTPException(status_code=400, detail="출력할 배식이 없습니다.")
    try:
        content, filename = generate_pdf_bytes(
            document_type,
            services,
            template.storage_path,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    except HwpxTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF 생성에 실패했습니다: {exc}") from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(filename, inline=True)},
    )


@router.post("/api/documents/meal-plan/hwpx")
def download_meal_plan_hwpx(
    body: ExportBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _download_hwpx_by_type("MEAL_PLAN", body, db, user)


@router.post("/api/documents/cooking-instruction/hwpx")
def download_cooking_instruction_hwpx(
    body: ExportBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _download_hwpx_by_type("COOKING_INSTRUCTION", body, db, user)


@router.post("/api/documents/preserved-food/hwpx")
def download_preserved_food_hwpx(
    body: ExportBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _download_hwpx_by_type("PRESERVATION_RECORD", body, db, user)


@router.post("/api/documents/preservation-record/hwpx")
def download_preservation_record_hwpx(
    body: ExportBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return _download_hwpx_by_type("PRESERVATION_RECORD", body, db, user)


def _mark_output(db: Session, preview: DocumentPreview) -> None:
    now = datetime.now(timezone.utc)
    if preview.document_type == "COOKING_INSTRUCTION":
        for service_id in preview.service_ids:
            service = db.get(MealService, service_id)
            if service:
                service.cooking_output_at = now
    elif preview.document_type == "MEAL_PLAN":
        for service_id in preview.service_ids:
            service = db.get(MealService, service_id)
            if service:
                service.meal_plan_output_at = now
    db.commit()


def _download_hwpx_by_type(document_type: str, body: ExportBody, db: Session, user: User):
    template = active_template(db, document_type)
    if not template:
        raise HTTPException(
            status_code=409,
            detail="활성 HWPX 템플릿이 없습니다. HWPX 문서 메뉴에서 템플릿을 등록해 주세요.",
        )
    services = resolve_services(db, body.service_ids, body.start_date, body.end_date)
    if not services:
        raise HTTPException(status_code=400, detail="출력할 배식이 없습니다.")
    try:
        content, filename = generate_hwpx_bytes(document_type, services, template.storage_path, start_date=body.start_date, end_date=body.end_date)
    except HwpxTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"HWPX 생성에 실패했습니다: {exc}") from exc
    _mark_output_services(db, document_type, services)
    return Response(
        content,
        media_type="application/vnd.hancom.hwpx",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def _mark_output_services(db: Session, document_type: str, services: list[MealService]) -> None:
    now = datetime.now(timezone.utc)
    if document_type == "COOKING_INSTRUCTION":
        for service in services:
            service.cooking_output_at = now
    elif document_type == "MEAL_PLAN":
        for service in services:
            service.meal_plan_output_at = now
    db.commit()


def _filename(document_type: str, extension: str) -> str:
    names = {
        "MEAL_PLAN": "식단표",
        "COOKING_INSTRUCTION": "조리지시서",
        "PRESERVATION_RECORD": "보존식기록지",
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{names.get(document_type, '문서')}_{stamp}.{extension}"


def _content_disposition(filename: str, *, inline: bool = False) -> str:
    disposition = "inline" if inline else "attachment"
    return f"{disposition}; filename*=UTF-8''{quote(filename)}"
