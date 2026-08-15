from datetime import datetime, timezone

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..security import verify_password, hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_MIN_PASSWORD_LEN = 8


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    request.session["user_id"] = user.id
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "must_change_password": user.must_change_password,
    }


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"authenticated": False}
    user = db.get(User, int(user_id))
    if not user:
        request.session.clear()
        return {"authenticated": False}
    return {
        "authenticated": True,
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "must_change_password": user.must_change_password,
    }


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str
    new_password_confirm: str


@router.post("/change-password")
def change_password(body: ChangePasswordBody, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    user = db.get(User, int(user_id))
    if not user or not user.active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=400, detail="새 비밀번호 확인이 일치하지 않습니다.")
    if len(body.new_password) < _MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"비밀번호는 최소 {_MIN_PASSWORD_LEN}자 이상이어야 합니다.")
    if body.new_password == user.username:
        raise HTTPException(status_code=400, detail="사용자 ID와 동일한 비밀번호는 사용할 수 없습니다.")

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}
