from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    if settings.desktop_mode:
        user = db.scalar(select(User).where(User.username == settings.desktop_username, User.active.is_(True)))
        if not user:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PC 사용자를 초기화하지 못했습니다.")
        return user
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")
    user = db.get(User, int(user_id))
    if not user or not user.active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다.")
    return user
