from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.importer import MigrationImporter
from app.models import ImportJob, Ingredient, MealActual, MealService, MealServiceMenu, MealServiceMenuIngredient, Menu, Recipe, RecipeIngredient
from app.routers import setup


def test_replace_import_preserves_existing_actual_count_when_upload_has_no_actual_data(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "01_배식설정"
    sheet.append(["배식유형", "기본계획식수", "기본배식시간", "사용여부", "설명"])
    sheet.append(["중식", 400, "12:00", "Y", ""])
    for name, headers, rows in [
        ("02_메뉴기준정보", ["메뉴ID", "메뉴명", "통계집계메뉴명", "메뉴역할", "사용여부", "검토상태"], [["M001", "밥", "밥", "밥·죽", "Y", "정상"]]),
        ("03_재료기준정보", ["재료ID", "표준재료명", "통계분석군", "기본단위", "kg환산계수", "분석제외", "사용여부", "검토상태"], []),
        ("04_재료별칭_선택", ["원재료별칭", "재료ID", "표준재료명", "출처"], []),
        ("05_메뉴별재료_기준", ["메뉴ID", "메뉴명", "레시피명", "재료ID", "표준재료명", "100인기준수량", "단위", "원본행", "원본비고", "검토상태", "재료순서"], []),
        ("06_식단이력_이관", ["일자", "배식유형", "계획식수", "배식시간", "메뉴순서", "메뉴ID", "메뉴명", "메뉴비고"], [["2025-04-01", "중식", 400, "12:00", 1, "M001", "밥", ""]]),
        ("07_식단재료_이관", ["일자", "배식유형", "메뉴순서", "메뉴ID", "메뉴명", "재료순서", "재료ID", "표준재료명", "원본재료명", "수량", "단위", "원본비고", "원본행"], []),
    ]:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    path = tmp_path / "migration.xlsx"
    workbook.save(path)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = MealService(id=100, service_date=date(2025, 4, 1), meal_type="LUNCH", planned_count=400)
        db.add(service)
        db.flush()
        db.add(MealActual(meal_service_id=service.id, actual_count=367, note="기존 실제 식수"))
        db.commit()

        result = MigrationImporter(path).apply(db, mode="replace")

        imported_service = db.scalar(select(MealService).where(MealService.service_date == date(2025, 4, 1), MealService.meal_type == "LUNCH"))
        assert imported_service is not None
        assert result["actuals_preserved"] == 1
        assert imported_service.actual.actual_count == 367
        assert imported_service.actual.note == "기존 실제 식수"


def test_apply_import_returns_before_background_import_finishes(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'setup.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(ImportJob(token="import-token", filename="upload.xlsx", storage_path=str(tmp_path / "upload.xlsx"), status="PREVIEWED"))
        db.commit()

    def fake_apply(self, db, mode="replace", user_id=None, progress=None):
        return {"menus": 3}

    monkeypatch.setattr(setup, "SessionLocal", sessions)
    monkeypatch.setattr(setup.MigrationImporter, "apply", fake_apply)
    app = FastAPI()
    app.include_router(setup.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[setup.get_db] = override_db
    app.dependency_overrides[setup.current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        response = client.post("/api/setup/import/apply", json={"token": "import-token", "mode": "replace"})
        assert response.json()["status"] == "PROCESSING"
        status = client.get("/api/setup/import/jobs/import-token")

    assert status.json()["status"] == "COMPLETED"
    assert status.json()["result"] == {"menus": 3}


def test_repository_migration_workbook_previews_and_applies_in_isolated_db():
    workbook = next((Path(__file__).resolve().parents[2] / "data" / "source").glob("*.xlsx"))
    importer = MigrationImporter(workbook)
    summary, errors = importer.preview()
    assert summary["ready"] is True
    assert errors == []

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = importer.apply(db, mode="merge")
        assert result["menus"] > 0
        assert result["ingredients"] > 0
        assert result["recipe_rows"] > 0
        assert result["meal_history_rows"] > 0
        assert db.scalar(select(func.count()).select_from(Menu)) > 0
        assert db.scalar(select(func.count()).select_from(Ingredient)) > 0
        assert db.scalar(select(func.count()).select_from(Recipe)) > 0
        assert db.scalar(select(func.count()).select_from(RecipeIngredient)) > 0
        assert db.scalar(select(func.count()).select_from(MealService)) > 0
        assert db.scalar(select(func.count()).select_from(MealServiceMenu)) > 0
        assert db.scalar(select(func.count()).select_from(MealServiceMenuIngredient)) > 0


def _setup_client(tmp_path, monkeypatch, status, fake_apply):
    engine = create_engine(f"sqlite:///{(tmp_path / 'setup.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(ImportJob(token="import-token", filename="upload.xlsx", storage_path=str(tmp_path / "upload.xlsx"), status=status))
        db.commit()
    monkeypatch.setattr(setup, "SessionLocal", sessions)
    monkeypatch.setattr(setup.MigrationImporter, "apply", fake_apply)
    app = FastAPI()
    app.include_router(setup.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[setup.get_db] = override_db
    app.dependency_overrides[setup.current_user] = lambda: SimpleNamespace(id=1)
    return TestClient(app)


def test_apply_import_rejects_second_apply_with_409(tmp_path, monkeypatch):
    calls = []

    def fake_apply(self, db, mode="replace", user_id=None, progress=None):
        calls.append(mode)
        return {"menus": 1}

    with _setup_client(tmp_path, monkeypatch, "PREVIEWED", fake_apply) as client:
        first = client.post("/api/setup/import/apply", json={"token": "import-token", "mode": "replace"})
        assert first.status_code == 200
        second = client.post("/api/setup/import/apply", json={"token": "import-token", "mode": "replace"})
        assert second.status_code == 409
    assert calls == ["replace"]


def test_background_import_failure_marks_failed_and_allows_retry(tmp_path, monkeypatch):
    attempts = []

    def fake_apply(self, db, mode="replace", user_id=None, progress=None):
        attempts.append(mode)
        if len(attempts) == 1:
            raise ValueError("boom")
        return {"menus": 2}

    with _setup_client(tmp_path, monkeypatch, "PREVIEWED", fake_apply) as client:
        assert client.post("/api/setup/import/apply", json={"token": "import-token", "mode": "replace"}).status_code == 200
        failed = client.get("/api/setup/import/jobs/import-token").json()
        assert failed["status"] == "FAILED"
        assert any("boom" in error["message"] for error in failed["errors"])
        assert client.post("/api/setup/import/apply", json={"token": "import-token", "mode": "replace"}).status_code == 200
        done = client.get("/api/setup/import/jobs/import-token").json()
    assert done["status"] == "COMPLETED"
    assert done["result"] == {"menus": 2}


def test_import_reports_stage_progress_for_the_ui(tmp_path, monkeypatch):
    seen = []

    def fake_apply(self, db, mode="replace", user_id=None, progress=None):
        progress(40, "메뉴별 레시피를 반영하고 있습니다.")
        seen.append(dict(setup.IMPORT_PROGRESS["import-token"]))
        return {"menus": 1}

    with _setup_client(tmp_path, monkeypatch, "PREVIEWED", fake_apply) as client:
        client.post("/api/setup/import/apply", json={"token": "import-token", "mode": "replace"})
        status = client.get("/api/setup/import/jobs/import-token").json()
    assert seen == [{"percent": 40, "message": "메뉴별 레시피를 반영하고 있습니다."}]
    assert status["status"] == "COMPLETED" and status["progress"] is None
    assert "import-token" not in setup.IMPORT_PROGRESS


def test_real_importer_progress_is_increasing_and_ends_at_100():
    workbook = next((Path(__file__).resolve().parents[2] / "data" / "source").glob("*.xlsx"))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    steps = []
    with Session(engine) as db:
        MigrationImporter(workbook).apply(db, mode="replace", progress=lambda percent, message: steps.append(percent))
    assert steps == sorted(steps)
    assert steps[0] < 10 and steps[-1] == 100
