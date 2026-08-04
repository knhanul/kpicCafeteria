from __future__ import annotations

from datetime import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import Base, SessionLocal, engine
from .models import MealTypeSetting, User
from .routers import auth, documents, master, master_data, setup, stats, templates, workspace
from .security import hash_password
from .schema_upgrade import upgrade_existing_schema

BASE_DIR = Path(__file__).parent
app = FastAPI(title=settings.app_name, docs_url="/api/docs", redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
views = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(auth.router)
app.include_router(setup.router)
app.include_router(master.router)
app.include_router(workspace.router)
app.include_router(stats.router)
app.include_router(templates.router)
app.include_router(master_data.router)
app.include_router(documents.router)


@app.on_event("startup")
def startup() -> None:
    upgrade_existing_schema(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if not user:
            db.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    display_name=settings.admin_display_name,
                )
            )
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
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    return views.TemplateResponse(request=request, name="login.html", context={"app_name": settings.app_name})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=302)
    return views.TemplateResponse(
        request=request,
        name="app.html",
        context={"app_name": settings.app_name, "display_name": settings.admin_display_name},
    )
