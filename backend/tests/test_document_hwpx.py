from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timezone
from urllib.parse import quote

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.document_hwpx import build_document_dto
from app.hwpx_engine import REQUIRED_PLACEHOLDERS
from app.models import (
    DocumentTemplate,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    PreservationRecord,
    User,
)
from app.routers.documents import (
    ExportBody,
    download_cooking_instruction_hwpx,
    download_hwpx,
    download_meal_plan_hwpx,
    download_preserved_food_hwpx,
)
from app.document_service import create_preview


def make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def make_user(db: Session) -> User:
    user = User(username="tester", password_hash="x", display_name="테스터", active=True)
    db.add(user)
    db.flush()
    return user


def build_hwpx(placeholders: list[str]) -> bytes:
    placeholder_text = " ".join(f"{{{{{placeholder}}}}}" for placeholder in placeholders)
    body = placeholder_text + " " + ("x" * 1700)
    section_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<section xmlns="http://www.hancom.co.kr/hwpml/2011/section">'
        f"<p><run><t>{body}</t></run></p>"
        '</section>'
    )
    content_hpf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.hancom.co.kr/hwpml/2011/package">'
        '<manifest><item id="section0" href="Contents/section0.xml"/></manifest>'
        '<spine><itemref idref="section0"/></spine>'
        '</package>'
    )
    header_xml = '<?xml version="1.0" encoding="UTF-8"?><header xmlns="http://www.hancom.co.kr/hwpml/2011/header"/>'
    version_xml = '<?xml version="1.0" encoding="UTF-8"?><version/>'
    container_xml = '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles><rootfile full-path="Contents/content.hpf"/></rootfiles></container>'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/vnd.hancom.hwpx")
        zf.writestr("version.xml", version_xml)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("Contents/content.hpf", content_hpf)
        zf.writestr("Contents/header.xml", header_xml)
        zf.writestr("Contents/section0.xml", section_xml)
    return buf.getvalue()


def seed_template(db: Session, tmp_path, document_type: str) -> DocumentTemplate:
    path = tmp_path / f"{document_type.lower()}.hwpx"
    path.write_bytes(build_hwpx(sorted(REQUIRED_PLACEHOLDERS[document_type])))
    template = DocumentTemplate(
        document_type=document_type,
        name=f"{document_type} template",
        description=None,
        original_filename=path.name,
        stored_filename=path.name,
        storage_path=str(path),
        file_size=path.stat().st_size,
        checksum_sha256="0" * 64,
        active=True,
        version=1,
        is_valid=True,
        validation_message=None,
        placeholder_summary={"placeholders": sorted(REQUIRED_PLACEHOLDERS[document_type])},
        created_by="tester",
    )
    db.add(template)
    db.commit()
    return template


def add_service(
    db: Session,
    *,
    service_date: date,
    meal_type: str,
    planned_count: int,
    service_time: time | None,
    concept_title: str | None,
    menus: list[dict],
    preservation: dict | None = None,
) -> MealService:
    service = MealService(
        service_date=service_date,
        meal_type=meal_type,
        planned_count=planned_count,
        service_time=service_time,
        concept_title=concept_title,
    )
    db.add(service)
    db.flush()

    for menu_index, menu_data in enumerate(menus, start=1):
        service_menu = MealServiceMenu(
            meal_service_id=service.id,
            sort_order=menu_index,
            menu_name_snapshot=menu_data["name"],
            recipe_name_snapshot=menu_data.get("recipe_name"),
            recipe_version_snapshot=menu_data.get("recipe_version"),
            note=menu_data.get("note"),
        )
        db.add(service_menu)
        db.flush()

        for ingredient_index, ingredient_data in enumerate(menu_data.get("ingredients", []), start=1):
            db.add(
                MealServiceMenuIngredient(
                    meal_service_menu_id=service_menu.id,
                    sort_order=ingredient_index,
                    ingredient_name_snapshot=ingredient_data["name"],
                    quantity_total=ingredient_data.get("quantity"),
                    quantity_per_100=ingredient_data.get("quantity_per_100"),
                    unit=ingredient_data.get("unit"),
                    source_note=ingredient_data.get("remark"),
                )
            )

    if preservation is not None:
        db.add(
            PreservationRecord(
                meal_service_id=service.id,
                collected_at=preservation.get("collected_at"),
                manager_name=preservation.get("manager"),
                freezer_temperature=preservation.get("freezer_temperature"),
                disposal_at=preservation.get("disposal_at"),
                collector_name=preservation.get("collector"),
                collection_time=preservation.get("collection_time"),
                note=preservation.get("note"),
                completed_at=preservation.get("completed_at"),
            )
        )

    db.commit()
    return service


def section_text(hwpx_bytes: bytes, section_name: str = "Contents/section0.xml") -> str:
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as archive:
        root = ET.fromstring(archive.read(section_name))
    return "".join(node.text or "" for node in root.iter() if node.tag.split("}")[-1] == "t")


def test_preview_token_hwpx_download_uses_real_dto_and_filename(tmp_path):
    db = make_db()
    user = make_user(db)
    seed_template(db, tmp_path, "MEAL_PLAN")

    monday = date(2026, 8, 17)
    tuesday = date(2026, 8, 18)
    lunch = add_service(
        db,
        service_date=monday,
        meal_type="LUNCH",
        planned_count=321,
        service_time=time(11, 40),
        concept_title="여름 보양식",
        menus=[{"name": "현미밥"}, {"name": "육개장"}],
    )
    add_service(
        db,
        service_date=monday,
        meal_type="DINNER",
        planned_count=87,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "비빔밥"}],
    )
    add_service(
        db,
        service_date=tuesday,
        meal_type="LUNCH",
        planned_count=305,
        service_time=time(11, 45),
        concept_title=None,
        menus=[{"name": "카레"}],
    )

    dto = build_document_dto("MEAL_PLAN", [lunch])
    assert dto.period.start_date == monday
    assert dto.period.end_date == monday
    assert dto.weeks[0].days[0].lunch.meal_count == 321
    assert dto.weeks[0].days[0].lunch.menus == ["현미밥", "육개장"]

    preview = create_preview(db, "MEAL_PLAN", db.query(MealService).order_by(MealService.id).all(), user.id)
    response = download_hwpx(preview.token, db, user)

    assert response.media_type == "application/vnd.hancom.hwpx"
    assert quote("식단표_20260817_20260818.hwpx") in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert archive.testzip() is None
        assert "{{" not in archive.read("Contents/section0.xml").decode("utf-8", errors="ignore")
    text = section_text(response.body)
    assert "여름 보양식" in text
    assert "현미밥" in text
    assert "비빔밥" in text
    assert db.get(MealService, lunch.id).meal_plan_output_at is not None


def test_direct_cooking_instruction_hwpx_download_uses_service_counts_and_clones_sections(tmp_path):
    db = make_db()
    user = make_user(db)
    seed_template(db, tmp_path, "COOKING_INSTRUCTION")

    monday = date(2026, 8, 17)
    tuesday = date(2026, 8, 18)
    lunch = add_service(
        db,
        service_date=monday,
        meal_type="LUNCH",
        planned_count=357,
        service_time=time(11, 40),
        concept_title=None,
        menus=[
            {
                "name": "제육볶음",
                "ingredients": [
                    {"name": "돼지고기", "quantity": 18.0, "unit": "kg"},
                    {"name": "양파", "quantity": 2.5, "unit": "kg"},
                ],
                "instruction": "강불에 빠르게 볶는다.",
                "note": "매콤하게",
            }
        ],
    )
    add_service(
        db,
        service_date=monday,
        meal_type="DINNER",
        planned_count=95,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "미역국", "ingredients": [{"name": "미역", "quantity": 1.2, "unit": "kg"}], "instruction": "끓인다.", "note": ""}],
    )
    add_service(
        db,
        service_date=tuesday,
        meal_type="LUNCH",
        planned_count=312,
        service_time=time(11, 50),
        concept_title=None,
        menus=[{"name": "카레", "ingredients": []}],
    )

    dto = build_document_dto("COOKING_INSTRUCTION", db.query(MealService).order_by(MealService.id).all())
    assert dto.days[0].lunch.meal_count == 357
    assert dto.days[0].lunch.menus[0].ingredients[0].name == "돼지고기"

    response = download_cooking_instruction_hwpx(ExportBody(start_date=monday, end_date=tuesday), db, user)

    assert response.media_type == "application/vnd.hancom.hwpx"
    assert quote("조리지시서_20260817_20260818.hwpx") in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert archive.testzip() is None
        assert {name for name in archive.namelist() if name.startswith("Contents/section")} >= {
            "Contents/section0.xml",
            "Contents/section1.xml",
        }
        assert "{{" not in archive.read("Contents/section0.xml").decode("utf-8", errors="ignore")
        assert "{{" not in archive.read("Contents/section1.xml").decode("utf-8", errors="ignore")
    text = section_text(response.body)
    assert "제육볶음" in text
    assert "돼지고기" in text
    assert "미역국" in text
    assert db.get(MealService, lunch.id).cooking_output_at is not None


def test_direct_preserved_food_hwpx_download_keeps_blank_db_fields_empty(tmp_path):
    db = make_db()
    user = make_user(db)
    seed_template(db, tmp_path, "PRESERVATION_RECORD")

    monday = date(2026, 8, 17)
    tuesday = date(2026, 8, 18)
    add_service(
        db,
        service_date=monday,
        meal_type="LUNCH",
        planned_count=410,
        service_time=time(11, 40),
        concept_title=None,
        menus=[{"name": "불고기"}],
        preservation={
            "collected_at": datetime(2026, 8, 17, 13, 20, tzinfo=timezone.utc),
            "manager": "홍길동",
            "freezer_temperature": "-18",
            "disposal_at": datetime(2026, 8, 18, 13, 20, tzinfo=timezone.utc),
            "collector": "김수거",
            "collection_time": "13:20",
        },
    )
    add_service(
        db,
        service_date=monday,
        meal_type="DINNER",
        planned_count=120,
        service_time=time(17, 30),
        concept_title=None,
        menus=[{"name": "된장국"}],
        preservation=None,
    )
    add_service(
        db,
        service_date=tuesday,
        meal_type="LUNCH",
        planned_count=380,
        service_time=time(11, 50),
        concept_title=None,
        menus=[{"name": "카레"}],
        preservation={
            "collected_at": datetime(2026, 8, 18, 13, 10, tzinfo=timezone.utc),
            "manager": None,
            "freezer_temperature": None,
            "disposal_at": None,
            "collector": None,
            "collection_time": None,
        },
    )
    add_service(
        db,
        service_date=tuesday,
        meal_type="DINNER",
        planned_count=140,
        service_time=time(17, 50),
        concept_title=None,
        menus=[{"name": "라면"}],
        preservation={
            "collected_at": datetime(2026, 8, 18, 17, 50, tzinfo=timezone.utc),
            "manager": "한관리",
            "freezer_temperature": "-18",
            "disposal_at": datetime(2026, 8, 19, 17, 50, tzinfo=timezone.utc),
            "collector": "오수거",
            "collection_time": "17:50",
        },
    )

    dto = build_document_dto("PRESERVATION_RECORD", db.query(MealService).order_by(MealService.id).all())
    assert len(dto.records) == 4
    assert dto.records[1].manager is None
    assert dto.records[1].collection_time is None

    response = download_preserved_food_hwpx(ExportBody(start_date=monday, end_date=tuesday), db, user)

    assert response.media_type == "application/vnd.hancom.hwpx"
    assert quote("보존식기록지_20260817_20260818.hwpx") in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert archive.testzip() is None
        assert {name for name in archive.namelist() if name.startswith("Contents/section")} >= {
            "Contents/section0.xml",
            "Contents/section1.xml",
        }
        assert "{{" not in archive.read("Contents/section0.xml").decode("utf-8", errors="ignore")
        assert "{{" not in archive.read("Contents/section1.xml").decode("utf-8", errors="ignore")
    text = section_text(response.body)
    assert "불고기" in text
    assert "홍길동" in text
    assert "김수거" in text
    assert "라면" in section_text(response.body, "Contents/section1.xml")
