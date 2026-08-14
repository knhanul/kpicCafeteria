from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from app.hwpx_engine import REQUIRED_PLACEHOLDERS, HwpxTemplateEngine, render_document, validate_template


@dataclass
class PreviewStub:
    document_type: str
    payload: dict


def build_hwpx(placeholders: list[str], *, section_count: int = 1) -> bytes:
    placeholder_text = " ".join(f"{{{{{placeholder}}}}}" for placeholder in placeholders)
    body = f"{placeholder_text} " + ("x" * 1600)
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
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/vnd.hancom.hwpx")
        archive.writestr("version.xml", version_xml)
        archive.writestr("META-INF/container.xml", container_xml)
        archive.writestr("Contents/content.hpf", content_hpf)
        archive.writestr("Contents/header.xml", header_xml)
        archive.writestr("Contents/section0.xml", section_xml)
        for index in range(1, section_count):
            archive.writestr(f"Contents/section{index}.xml", section_xml)
    return buf.getvalue()


def section_text(hwpx_bytes: bytes, name: str = "Contents/section0.xml") -> str:
    with zipfile.ZipFile(io.BytesIO(hwpx_bytes)) as archive:
        root = ET.fromstring(archive.read(name))
    return "".join(node.text or "" for node in root.iter() if node.tag.split("}")[-1] == "t")


def test_validate_template_accepts_meal_plan_tokens(tmp_path):
    template = build_hwpx(sorted(REQUIRED_PLACEHOLDERS["MEAL_PLAN"]))
    path = tmp_path / "ignored.hwpx"
    path.write_bytes(template)
    try:
        result = validate_template(path, "MEAL_PLAN")
        assert result["sections"] == 1
        assert "W1_D1_DATE" in result["placeholders"]
    finally:
        path.unlink(missing_ok=True)


def test_render_meal_plan_produces_valid_hwpx_round_trip(tmp_path):
    template_path = tmp_path / "meal-plan.hwpx"
    template_path.write_bytes(build_hwpx(sorted(REQUIRED_PLACEHOLDERS["MEAL_PLAN"])))

    preview = PreviewStub(
        "MEAL_PLAN",
        {
            "title": "식단표",
            "weeks": [
                {
                    "start": "2026-08-17",
                    "end": "2026-08-21",
                    "days": [
                        {
                            "date": "2026-08-17",
                            "date_label": "08.17",
                            "weekday": "월요일",
                            "services": {
                                "LUNCH": {
                                    "meal_type": "LUNCH",
                                    "meal_name": "중식",
                                    "planned_count": 400,
                                    "service_time": "11:40",
                                    "concept_title": "여름 보양식",
                                    "menus": ["현미밥", "육개장", "제육볶음"],
                                },
                                "DINNER": {
                                    "meal_type": "DINNER",
                                    "meal_name": "석식",
                                    "planned_count": 120,
                                    "service_time": "17:30",
                                    "concept_title": None,
                                    "menus": ["비빔밥"],
                                },
                            },
                        }
                    ]
                    + [
                        {
                            "date": f"2026-08-{18 + offset:02d}",
                            "date_label": f"08.{18 + offset:02d}",
                            "weekday": ["화요일", "수요일", "목요일", "금요일"][offset],
                            "services": {},
                        }
                        for offset in range(4)
                    ],
                }
            ],
        },
    )

    output = render_document(template_path, preview)
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        assert archive.testzip() is None
        assert "Contents/content.hpf" in archive.namelist()
        assert "{{" not in archive.read("Contents/section0.xml").decode("utf-8", errors="ignore")
    text = section_text(output)
    assert "여름 보양식" in text
    assert "현미밥" in text
    assert "08.17" in text


def test_render_cooking_instruction_clones_sections_and_keeps_valid_zip(tmp_path):
    template_path = tmp_path / "cooking.hwpx"
    template_path.write_bytes(build_hwpx(sorted(REQUIRED_PLACEHOLDERS["COOKING_INSTRUCTION"])))

    preview = PreviewStub(
        "COOKING_INSTRUCTION",
        {
            "title": "조리지시서",
            "days": [
                {
                    "date": "2026-08-17",
                    "date_label": "2026년 08월 17일",
                    "weekday": "월요일",
                    "services": [
                        {
                            "meal_type": "LUNCH",
                            "meal_name": "중식",
                            "menus": [
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
                        },
                        {
                            "meal_type": "DINNER",
                            "meal_name": "석식",
                            "menus": [
                                {
                                    "name": "미역국",
                                    "ingredients": [{"name": "미역", "quantity": 1.2, "unit": "kg"}],
                                    "instruction": "끓인다.",
                                    "note": "",
                                }
                            ],
                        },
                    ],
                },
                {
                    "date": "2026-08-18",
                    "date_label": "2026년 08월 18일",
                    "weekday": "화요일",
                    "services": [],
                },
            ],
        },
    )

    output = render_document(template_path, preview)
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        assert archive.testzip() is None
        assert {name for name in archive.namelist() if name.startswith("Contents/section")} >= {
            "Contents/section0.xml",
            "Contents/section1.xml",
        }
        assert "{{" not in archive.read("Contents/section0.xml").decode("utf-8", errors="ignore")
        assert "{{" not in archive.read("Contents/section1.xml").decode("utf-8", errors="ignore")
    text = section_text(output)
    assert "제육볶음" in text
    assert "돼지고기" in text
    assert "미역국" in text


def test_render_preservation_record_expands_sections_and_remains_reopenable(tmp_path):
    template_path = tmp_path / "preserved.hwpx"
    template_path.write_bytes(build_hwpx(sorted(REQUIRED_PLACEHOLDERS["PRESERVATION_RECORD"])))

    preview = PreviewStub(
        "PRESERVATION_RECORD",
        {
            "title": "보존식 기록지",
            "records": [
                {
                    "date_label": "2026년 08월 17일",
                    "weekday": "월요일",
                    "meal_name": "중식",
                    "collection_hour": "13",
                    "collection_minute": "20",
                    "manager_name": "홍길동",
                    "menu_items": ["불고기", "김치"],
                    "freezer_temperature": "-18",
                    "disposal_date": "2026년 08월 18일",
                    "collector_name": "김수거",
                    "collection_time": "13:20",
                },
                {
                    "date_label": "2026년 08월 17일",
                    "weekday": "월요일",
                    "meal_name": "석식",
                    "collection_hour": "17",
                    "collection_minute": "40",
                    "manager_name": "이관리",
                    "menu_items": ["된장국"],
                    "freezer_temperature": "-18",
                    "disposal_date": "2026년 08월 18일",
                    "collector_name": "박수거",
                    "collection_time": "17:40",
                },
                {
                    "date_label": "2026년 08월 18일",
                    "weekday": "화요일",
                    "meal_name": "중식",
                    "collection_hour": "13",
                    "collection_minute": "10",
                    "manager_name": "최관리",
                    "menu_items": ["카레"],
                    "freezer_temperature": "-18",
                    "disposal_date": "2026년 08월 19일",
                    "collector_name": "정수거",
                    "collection_time": "13:10",
                },
                {
                    "date_label": "2026년 08월 18일",
                    "weekday": "화요일",
                    "meal_name": "석식",
                    "collection_hour": "17",
                    "collection_minute": "50",
                    "manager_name": "한관리",
                    "menu_items": ["라면"],
                    "freezer_temperature": "-18",
                    "disposal_date": "2026년 08월 19일",
                    "collector_name": "오수거",
                    "collection_time": "17:50",
                },
            ],
        },
    )

    output = render_document(template_path, preview)
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        assert archive.testzip() is None
        assert "Contents/section1.xml" in archive.namelist()
        assert "{{" not in archive.read("Contents/section0.xml").decode("utf-8", errors="ignore")
        assert "{{" not in archive.read("Contents/section1.xml").decode("utf-8", errors="ignore")
    text = section_text(output)
    assert "불고기" in text
    assert "13" in text
    assert "김수거" in text
