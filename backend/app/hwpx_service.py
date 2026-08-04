from __future__ import annotations

import copy
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DocumentPreview, DocumentTemplate

OPF_NS = "http://www.idpf.org/2007/opf/"
HWPX_NAMESPACES = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": OPF_NS,
    "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
    "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    "epub": "http://www.idpf.org/2007/ops",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}
for _prefix, _uri in HWPX_NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)


class HwpxTemplateError(RuntimeError):
    pass


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def active_template(db: Session, document_type: str) -> DocumentTemplate | None:
    return db.scalar(
        select(DocumentTemplate)
        .where(DocumentTemplate.document_type == document_type, DocumentTemplate.active.is_(True))
        .order_by(DocumentTemplate.version.desc())
    )


MIN_HWPX_SIZE = 1024  # 1KB minimum


def validate_hwpx(path: str | Path, document_type: str | None = None) -> dict[str, Any]:
    path = Path(path)
    file_size = path.stat().st_size
    if file_size < MIN_HWPX_SIZE:
        raise HwpxTemplateError(f"파일이 너무 작습니다 ({file_size}바이트). 정상적인 HWPX 파일이 아닙니다.")

    required = {"mimetype", "Contents/content.hpf", "Contents/header.xml", "version.xml", "META-INF/container.xml"}
    with ZipFile(path) as archive:
        names = set(archive.namelist())

        # ZIP Slip check: no absolute paths or .. traversal
        for name in names:
            if name.startswith("/") or ".." in name:
                raise HwpxTemplateError(f"안전하지 않은 경로가 포함되어 있습니다: {name}")

        missing = sorted(required - names)
        sections = sorted(name for name in names if re.fullmatch(r"Contents/section\d+\.xml", name))
        if not sections:
            missing.append("Contents/section*.xml")
        if missing:
            raise HwpxTemplateError(f"필수 HWPX 파일이 없습니다: {', '.join(missing)}")

        # Parse all required XML files
        for name in ["Contents/content.hpf", "Contents/header.xml", "version.xml", "META-INF/container.xml", *sections]:
            try:
                ET.fromstring(archive.read(name))
            except ET.ParseError as exc:
                raise HwpxTemplateError(f"XML 파싱에 실패했습니다 ({name}): {exc}") from exc

        # Validate manifest/spine references in content.hpf
        content_root = ET.fromstring(archive.read("Contents/content.hpf"))
        manifest = next((elem for elem in content_root.iter() if _local(elem.tag) == "manifest"), None)
        spine = next((elem for elem in content_root.iter() if _local(elem.tag) == "spine"), None)
        if manifest is None:
            raise HwpxTemplateError("content.hpf에 manifest 요소가 없습니다.")
        if spine is None:
            raise HwpxTemplateError("content.hpf에 spine 요소가 없습니다.")
        manifest_ids = {elem.attrib.get("id") for elem in manifest if elem.attrib.get("id")}
        for itemref in spine:
            idref = itemref.attrib.get("idref")
            if idref and idref not in manifest_ids:
                raise HwpxTemplateError(f"spine이 manifest에 없는 항목을 참조합니다: {idref}")

        # Collect all text from sections to find placeholders
        text = "".join(
            "".join(node.text or "" for node in ET.fromstring(archive.read(section)).iter() if _local(node.tag) == "t")
            for section in sections
        )
        placeholders = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text)))
        required_by_type = {
            "PRESERVATION_RECORD": {"R1_DATE", "R1_MENU", "R2_DATE", "R2_MENU", "R3_DATE", "R3_MENU"},
            "COOKING_INSTRUCTION": {"DATE", "LUNCH_BODY", "DINNER_BODY"},
            "MEAL_PLAN": {"D1_DATE", "D1_LUNCH", "D1_DINNER", "D10_DATE", "D10_LUNCH", "D10_DINNER"},
        }
        if document_type:
            missing_placeholders = sorted(required_by_type.get(document_type, set()) - set(placeholders))
            if missing_placeholders:
                raise HwpxTemplateError("필수 플레이스홀더가 없습니다: " + ", ".join(missing_placeholders))
        return {
            "sections": len(sections),
            "files": len(names),
            "placeholders": placeholders,
            "file_size": file_size,
        }


def _paragraphs(root: ET.Element):
    for elem in root.iter():
        if _local(elem.tag) == "p":
            yield elem


def _replace_in_paragraph(paragraph: ET.Element, mapping: dict[str, str]) -> None:
    texts = [elem for elem in paragraph.iter() if _local(elem.tag) == "t"]
    if not texts:
        return
    joined = "".join(elem.text or "" for elem in texts)
    updated = joined
    for key, value in mapping.items():
        updated = updated.replace("{{" + key + "}}", value or "")
    if updated != joined:
        texts[0].text = updated
        for elem in texts[1:]:
            elem.text = ""


def _replace_xml(xml: bytes, mapping: dict[str, str]) -> bytes:
    root = ET.fromstring(xml)
    for paragraph in _paragraphs(root):
        _replace_in_paragraph(paragraph, mapping)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _page_mappings(preview: DocumentPreview) -> list[dict[str, str]]:
    payload = preview.payload
    if preview.document_type == "PRESERVATION_RECORD":
        records = payload.get("records", [])
        pages = []
        for start in range(0, max(len(records), 1), 3):
            page_records = records[start : start + 3]
            mapping: dict[str, str] = {}
            for slot in range(1, 4):
                record = page_records[slot - 1] if slot - 1 < len(page_records) else {}
                prefix = f"R{slot}_"
                mapping.update(
                    {
                        prefix + "DATE": " ".join(
                            part for part in [record.get("date_label", ""), record.get("weekday", ""), record.get("meal_name", "")] if part
                        ),
                        prefix + "COLLECTION_HOUR": record.get("collection_hour", ""),
                        prefix + "COLLECTION_MINUTE": record.get("collection_minute", ""),
                        prefix + "MANAGER": record.get("manager_name", ""),
                        prefix + "MENU": "\n".join(record.get("menu_items", [])),
                        prefix + "FREEZER_TEMP": record.get("freezer_temperature", ""),
                        prefix + "DISPOSAL_DATE": record.get("disposal_date", ""),
                        prefix + "COLLECTOR": record.get("collector_name", ""),
                        prefix + "COLLECTION_TIME": record.get("collection_time", ""),
                    }
                )
            pages.append(mapping)
        return pages

    if preview.document_type == "COOKING_INSTRUCTION":
        pages = []
        for day in payload.get("days", []):
            mapping = {"DATE": f"{day.get('date_label', '')} {day.get('weekday', '')}"}
            by_type = {service.get("meal_type"): service for service in day.get("services", [])}
            for code, prefix in (("LUNCH", "LUNCH"), ("DINNER", "DINNER")):
                service = by_type.get(code, {})
                lines = []
                for menu in service.get("menus", []):
                    ingredients = ", ".join(
                        f"{item.get('name', '')} {item.get('quantity_total') or ''}{item.get('unit', '')}".strip()
                        for item in menu.get("ingredients", [])
                    )
                    instruction = menu.get("instruction", "")
                    lines.append(f"{menu.get('name', '')}\n{ingredients}\n{instruction}".strip())
                mapping[prefix + "_TITLE"] = service.get("meal_name", "")
                mapping[prefix + "_BODY"] = "\n\n".join(lines)
            pages.append(mapping)
        return pages or [{}]

    # MEAL_PLAN: one section can hold up to ten weekdays through D1..D10 placeholders.
    mapping: dict[str, str] = {}
    days = [day for week in payload.get("weeks", []) for day in week.get("days", [])]
    for index in range(1, 11):
        day = days[index - 1] if index - 1 < len(days) else {}
        mapping[f"D{index}_DATE"] = f"{day.get('date_label', '')} {day.get('weekday', '')}".strip()
        for meal_type, suffix in (("LUNCH", "LUNCH"), ("DINNER", "DINNER")):
            service = day.get("services", {}).get(meal_type, {}) if day else {}
            mapping[f"D{index}_{suffix}"] = "\n".join(service.get("menus", []))
    return [mapping]


def _update_content_hpf(content: bytes, section_count: int) -> bytes:
    root = ET.fromstring(content)
    manifest = next((elem for elem in root.iter() if _local(elem.tag) == "manifest"), None)
    spine = next((elem for elem in root.iter() if _local(elem.tag) == "spine"), None)
    if manifest is None or spine is None:
        raise HwpxTemplateError("content.hpf의 manifest 또는 spine을 찾을 수 없습니다.")

    section_items = [elem for elem in list(manifest) if elem.attrib.get("href", "").startswith("Contents/section")]
    if not section_items:
        raise HwpxTemplateError("content.hpf에 section 항목이 없습니다.")
    prototype = section_items[0]
    for elem in section_items:
        manifest.remove(elem)
    for elem in list(spine):
        if elem.attrib.get("idref", "").startswith("section"):
            spine.remove(elem)

    for index in range(section_count):
        item = copy.deepcopy(prototype)
        item.set("id", f"section{index}")
        item.set("href", f"Contents/section{index}.xml")
        manifest.append(item)
        itemref = ET.Element(f"{{{OPF_NS}}}itemref", {"idref": f"section{index}", "linear": "yes"})
        spine.append(itemref)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render_hwpx(template_path: str | Path, preview: DocumentPreview) -> bytes:
    validate_hwpx(template_path, preview.document_type)
    mappings = _page_mappings(preview)
    with ZipFile(template_path) as source:
        files = {name: source.read(name) for name in source.namelist()}
    section_names = sorted(name for name in files if re.fullmatch(r"Contents/section\d+\.xml", name))
    base_section = files[section_names[0]]
    for name in section_names:
        files.pop(name, None)
    for index, mapping in enumerate(mappings):
        files[f"Contents/section{index}.xml"] = _replace_xml(base_section, mapping)
    files["Contents/content.hpf"] = _update_content_hpf(files["Contents/content.hpf"], len(mappings))

    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        if "mimetype" in files:
            info = ZipInfo("mimetype")
            info.compress_type = ZIP_STORED
            archive.writestr(info, files.pop("mimetype"))
        for name, data in files.items():
            archive.writestr(name, data, compress_type=ZIP_DEFLATED)
    output.seek(0)
    # Validate generated package structurally.
    with ZipFile(output) as archive:
        ET.fromstring(archive.read("Contents/content.hpf"))
        for index in range(len(mappings)):
            ET.fromstring(archive.read(f"Contents/section{index}.xml"))
    return output.getvalue()
