from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import admin_user, current_user
from ..models import AuditLog, User
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/users", tags=["users"])

_MIN_PASSWORD_LEN = 8


def _validate_password(password: str, username: str) -> None:
    if len(password) < _MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"비밀번호는 최소 {_MIN_PASSWORD_LEN}자 이상이어야 합니다.")
    if password == username:
        raise HTTPException(status_code=400, detail="사용자 ID와 동일한 비밀번호는 사용할 수 없습니다.")


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "active": user.active,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "password_changed_at": user.password_changed_at.isoformat() if user.password_changed_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _log_audit(db: Session, actor: User, action: str, entity_type: str, entity_id: int, detail: dict | None = None) -> None:
    db.add(AuditLog(
        user_id=actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        detail=detail or {},
    ))


def _active_admin_count(db: Session, exclude_id: int | None = None) -> int:
    stmt = select(func.count(User.id)).where(User.role == "admin", User.active.is_(True))
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt) or 0


# ---------- List ----------

@router.get("")
def list_users(
    q: str = Query("", description="search username or display_name"),
    db: Session = Depends(get_db),
    _: User = Depends(admin_user),
):
    stmt = select(User).order_by(User.id)
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.username.ilike(term), User.display_name.ilike(term)))
    rows = db.scalars(stmt).all()
    return {"items": [_user_payload(u) for u in rows]}


# ---------- Create ----------

class CreateUserBody(BaseModel):
    username: str
    display_name: str
    role: str
    password: str
    password_confirm: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("admin", "user"):
            raise ValueError("권한은 관리자 또는 일반사용자만 선택할 수 있습니다.")
        return v


@router.post("")
def create_user(
    body: CreateUserBody,
    db: Session = Depends(get_db),
    actor: User = Depends(admin_user),
):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="사용자 ID를 입력해 주세요.")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=400, detail="이미 사용 중인 사용자 ID입니다.")
    if body.password != body.password_confirm:
        raise HTTPException(status_code=400, detail="비밀번호 확인이 일치하지 않습니다.")
    _validate_password(body.password, username)

    user = User(
        username=username,
        display_name=body.display_name.strip() or username,
        role=body.role,
        password_hash=hash_password(body.password),
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    _log_audit(db, actor, "user.create", "user", user.id, {"username": user.username, "role": user.role})
    db.commit()
    return _user_payload(user)


# ---------- Update ----------

class UpdateUserBody(BaseModel):
    display_name: str | None = None
    role: str | None = None
    active: bool | None = None


@router.put("/{user_id}")
def update_user(
    user_id: int,
    body: UpdateUserBody,
    db: Session = Depends(get_db),
    actor: User = Depends(admin_user),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    # Prevent self-deactivation
    if body.active is False and actor.id == user_id:
        raise HTTPException(status_code=400, detail="본인 계정은 사용중지할 수 없습니다.")

    # Prevent removing last active admin role
    if body.role is not None and body.role != "admin" and user.role == "admin" and user.active:
        if _active_admin_count(db, exclude_id=user_id) == 0:
            raise HTTPException(status_code=400, detail="시스템에는 최소 1명의 관리자가 필요합니다.")

    # Prevent deactivating last active admin
    if body.active is False and user.role == "admin" and user.active:
        if _active_admin_count(db, exclude_id=user_id) == 0:
            raise HTTPException(status_code=400, detail="시스템에는 최소 1명의 관리자가 필요합니다.")

    changes: dict = {}
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or user.display_name
        changes["display_name"] = user.display_name
    if body.role is not None and body.role != user.role:
        user.role = body.role
        changes["role"] = body.role
    if body.active is not None and body.active != user.active:
        user.active = body.active
        changes["active"] = body.active

    if changes:
        user.updated_at = datetime.now(timezone.utc)
        _log_audit(db, actor, "user.update", "user", user.id, changes)

    db.commit()
    return _user_payload(user)


# ---------- Reset password ----------

class ResetPasswordBody(BaseModel):
    password: str
    password_confirm: str


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    body: ResetPasswordBody,
    db: Session = Depends(get_db),
    actor: User = Depends(admin_user),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if body.password != body.password_confirm:
        raise HTTPException(status_code=400, detail="비밀번호 확인이 일치하지 않습니다.")
    _validate_password(body.password, user.username)

    user.password_hash = hash_password(body.password)
    user.must_change_password = True
    user.password_changed_at = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)
    _log_audit(db, actor, "user.reset_password", "user", user.id, {})
    db.commit()
    return {"ok": True}
