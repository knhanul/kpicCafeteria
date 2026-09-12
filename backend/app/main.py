from __future__ import annotations

from datetime import time
from pathlib import Path
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import Base, SessionLocal, engine
from .desktop_schema import ensure_desktop_schema_version
from .models import MealTypeSetting, User
from .routers import admin, auth, documents, master, master_data, orders, setup, statistics, stats, templates, users, weather, workspace
from .security import hash_password
from .schema_upgrade import upgrade_existing_schema

BASE_DIR = Path(__file__).parent
app = FastAPI(title=settings.app_name, docs_url="/api/docs", redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
views = Jinja2Templates(directory=str(BASE_DIR / "templates"))

if not settings.desktop_mode:
    app.include_router(auth.router)
    app.include_router(users.router)
app.include_router(setup.router)
app.include_router(master.router)
app.include_router(workspace.router)
app.include_router(stats.router)
app.include_router(statistics.router)
app.include_router(templates.router)
app.include_router(master_data.router)
app.include_router(documents.router)
app.include_router(admin.router)
app.include_router(orders.router)
app.include_router(weather.router)


@app.on_event("startup")
def startup() -> None:
    upgrade_existing_schema(engine)
    Base.metadata.create_all(engine)
    if settings.desktop_mode:
        ensure_desktop_schema_version(engine)
    with SessionLocal() as db:
        username = settings.desktop_username if settings.desktop_mode else settings.admin_username
        display_name = settings.desktop_display_name if settings.desktop_mode else settings.admin_display_name
        password = secrets.token_urlsafe(32) if settings.desktop_mode else settings.admin_password
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    display_name=display_name,
                    role="admin",
                )
            )
        elif settings.desktop_mode:
            user.active = True
            user.role = "admin"
            user.display_name = display_name
        elif not user.role or user.role == "user":
            user.role = "admin"
        defaults = [
            ("LUNCH", "중식", 400, time(11, 40), 1),
            ("DINNER", "석식", 100, time(17, 30), 2),
        ]
        for code, name, count, svc_time, sort_order in defaults:
            existing = db.scalar(select(MealTypeSetting).where(MealTypeSetting.code == code))
            if not existing:
                db.add(MealTypeSetting(
                    code=code, name=name, default_planned_count=count,
                    default_service_time=svc_time, sort_order=sort_order, active=True,
                ))
            elif existing.default_service_time is None:
                existing.default_service_time = svc_time
        db.commit()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if settings.desktop_mode or request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    return views.TemplateResponse(request=request, name="login.html", context={"app_name": settings.app_name})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user_id = request.session.get("user_id") if not settings.desktop_mode else None
    if not settings.desktop_mode and not user_id:
        return RedirectResponse("/login", status_code=302)
    db = SessionLocal()
    try:
        if settings.desktop_mode:
            user = db.scalar(select(User).where(User.username == settings.desktop_username, User.active.is_(True)))
        else:
            user = db.get(User, int(user_id))
        if not user or not user.active:
            if not settings.desktop_mode:
                request.session.clear()
                return RedirectResponse("/login", status_code=302)
            return HTMLResponse("PC 사용자 초기화에 실패했습니다.", status_code=503)
        return views.TemplateResponse(
            request=request,
            name="app.html",
            context={
                "app_name": settings.app_name,
                "display_name": user.display_name,
                "role": user.role,
                "must_change_password": False if settings.desktop_mode else user.must_change_password,
                "desktop_mode": settings.desktop_mode,
            },
        )
    finally:
        db.close()
