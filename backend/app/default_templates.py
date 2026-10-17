from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from secrets import token_hex

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .hwpx_service import validate_hwpx
from .models import DocumentTemplate

DEFAULT_TEMPLATE_SPECS = (
    ("MEAL_PLAN", "식단표_템플릿.hwpx", "식단표"),
    ("COOKING_INSTRUCTION", "조리지시서_템플릿.hwpx", "조리지시서"),
    ("PRESERVATION_RECORD", "보존식기록지_템플릿.hwpx", "보존식 기록지"),
)


def default_template_source_dir() -> Path:
    app_file = Path(__file__).resolve()
    candidates = [
        app_file.parents[2] / "docs" / "template",
        app_file.parents[1] / "docs" / "template",
    ]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "docs" / "template")

    expected = {filename for _, filename, _ in DEFAULT_TEMPLATE_SPECS}
    for candidate in candidates:
        if expected.issubset({path.name for path in candidate.glob("*.hwpx")}):
            return candidate
    raise FileNotFoundError(
        "기본 HWPX 템플릿을 찾을 수 없습니다. docs/template 디렉터리에 기본 템플릿 3개가 필요합니다."
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_default_template(
    source: Path,
    template_dir: Path,
    document_type: str,
    checksum: str,
) -> tuple[Path, bool]:
    destination_dir = template_dir / document_type.lower()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"default_{checksum[:16]}.hwpx"
    while destination.exists():
        if _sha256(destination) == checksum:
            return destination, False
        destination = destination_dir / f"default_{checksum[:16]}_{token_hex(4)}.hwpx"
    shutil.copy2(source, destination)
    return destination, True


def ensure_default_templates(
    db: Session,
    template_dir: Path,
    source_dir: Path | None = None,
) -> int:
    """Register bundled base templates without replacing existing user templates."""
    source_dir = source_dir or default_template_source_dir()
    sources = []
    for document_type, filename, label in DEFAULT_TEMPLATE_SPECS:
        source = source_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"기본 HWPX 템플릿이 없습니다: {source}")
        validation = validate_hwpx(source, document_type)
        sources.append((document_type, filename, label, source, validation, _sha256(source)))

    added = 0
    copied_paths: list[Path] = []
    try:
        for document_type, filename, label, source, validation, checksum in sources:
            existing = db.scalar(
                select(DocumentTemplate)
                .where(
                    DocumentTemplate.document_type == document_type,
                    DocumentTemplate.checksum_sha256 == checksum,
                )
                .order_by(DocumentTemplate.version.desc())
            )
            if existing:
                existing_path = Path(existing.storage_path)
                if existing_path.is_file() and _sha256(existing_path) == checksum:
                    continue
                destination, created = _copy_default_template(source, template_dir, document_type, checksum)
                if created:
                    copied_paths.append(destination)
                existing.storage_path = str(destination)
                existing.stored_filename = destination.name
                existing.file_size = destination.stat().st_size
                existing.checksum_sha256 = checksum
                existing.is_valid = True
                existing.validation_message = None
                existing.placeholder_summary = validation
                continue

            has_any_template = db.scalar(
                select(DocumentTemplate.id)
                .where(DocumentTemplate.document_type == document_type)
                .limit(1)
            ) is not None
            version = (
                db.scalar(
                    select(func.max(DocumentTemplate.version)).where(
                        DocumentTemplate.document_type == document_type
                    )
                )
                or 0
            ) + 1
            destination, created = _copy_default_template(source, template_dir, document_type, checksum)
            if created:
                copied_paths.append(destination)
            db.add(
                DocumentTemplate(
                    document_type=document_type,
                    name=f"기본 {label} 템플릿",
                    description="기본 양식입니다. 내려받아 수정한 뒤 새 양식으로 등록하면 기존 버전을 보존합니다.",
                    original_filename=filename,
                    stored_filename=destination.name,
                    storage_path=str(destination),
                    file_size=destination.stat().st_size,
                    checksum_sha256=checksum,
                    active=not has_any_template,
                    version=version,
                    is_valid=True,
                    validation_message=None,
                    placeholder_summary=validation,
                    created_by="system",
                )
            )
            added += 1

        db.commit()
    except Exception:
        db.rollback()
        for path in copied_paths:
            path.unlink(missing_ok=True)
        raise
    return added
