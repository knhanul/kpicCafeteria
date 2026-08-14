from __future__ import annotations

import copy
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from zipfile import BadZipFile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from .models import DocumentPreview

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

PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
MIN_HWPX_SIZE = 1024
REQUIRED_PACKAGE_FILES = {"mimetype", "Contents/content.hpf", "Contents/header.xml", "version.xml", "META-INF/container.xml"}
REQUIRED_PLACEHOLDERS = {
    "PRESERVATION_RECORD": {
        "PERIOD_TITLE",
        "B1_DATE_LABEL",
        "B1_SAMPLE_DATETIME",
        "B1_MANAGER",
        "B1_MENU_LIST",
        "B1_FREEZER_TEMP",
        "B1_DISCARD_DATETIME",
        "B1_COLLECTOR",
        "B1_COLLECTION_TIME",
        "B2_DATE_LABEL",
        "B2_SAMPLE_DATETIME",
        "B2_MANAGER",
        "B2_MENU_LIST",
        "B2_FREEZER_TEMP",
        "B2_DISCARD_DATETIME",
        "B2_COLLECTOR",
        "B2_COLLECTION_TIME",
        "B3_DATE_LABEL",
        "B3_SAMPLE_DATETIME",
        "B3_MANAGER",
        "B3_MENU_LIST",
        "B3_FREEZER_TEMP",
        "B3_DISCARD_DATETIME",
        "B3_COLLECTOR",
        "B3_COLLECTION_TIME",
    },
    "COOKING_INSTRUCTION": {
        "DATE_LABEL",
        "LUNCH_MENU_1",
        "LUNCH_MENU_2",
        "LUNCH_MENU_3",
        "LUNCH_MENU_4",
        "LUNCH_MENU_5",
        "LUNCH_MENU_6",
        "LUNCH_MENU_7",
        "LUNCH_INGREDIENTS_1",
        "LUNCH_INGREDIENTS_2",
        "LUNCH_INGREDIENTS_3",
        "LUNCH_INGREDIENTS_4",
        "LUNCH_INGREDIENTS_5",
        "LUNCH_INGREDIENTS_6",
        "LUNCH_INGREDIENTS_7",
        "DINNER_MENU_1",
        "DINNER_MENU_2",
        "DINNER_MENU_3",
        "DINNER_MENU_4",
        "DINNER_MENU_5",
        "DINNER_MENU_6",
        "DINNER_MENU_7",
        "DINNER_INGREDIENTS_1",
        "DINNER_INGREDIENTS_2",
        "DINNER_INGREDIENTS_3",
        "DINNER_INGREDIENTS_4",
        "DINNER_INGREDIENTS_5",
        "DINNER_INGREDIENTS_6",
        "DINNER_INGREDIENTS_7",
    },
    "MEAL_PLAN": {
        "PERIOD_TITLE",
        "W1_WEEK_LABEL",
        "W1_D1_DATE",
        "W1_D1_LUNCH_MENU",
        "W1_D1_DINNER_MENU",
        "W1_D2_DATE",
        "W1_D2_LUNCH_MENU",
        "W1_D2_DINNER_MENU",
        "W1_D3_DATE",
        "W1_D3_LUNCH_MENU",
        "W1_D3_DINNER_MENU",
        "W1_D4_DATE",
        "W1_D4_LUNCH_MENU",
        "W1_D4_DINNER_MENU",
        "W1_D5_DATE",
        "W1_D5_LUNCH_MENU",
        "W1_D5_DINNER_MENU",
        "W2_WEEK_LABEL",
        "W2_D1_DATE",
        "W2_D1_LUNCH_MENU",
        "W2_D1_DINNER_MENU",
        "W2_D2_DATE",
        "W2_D2_LUNCH_MENU",
        "W2_D2_DINNER_MENU",
        "W2_D3_DATE",
        "W2_D3_LUNCH_MENU",
        "W2_D3_DINNER_MENU",
        "W2_D4_DATE",
        "W2_D4_LUNCH_MENU",
        "W2_D4_DINNER_MENU",
        "W2_D5_DATE",
        "W2_D5_LUNCH_MENU",
        "W2_D5_DINNER_MENU",
    },
}
WEEKDAY_LABELS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
REPEAT_PAGE_START = "CAFETERIA_REPEAT_PAGE_START"
REPEAT_PAGE_END = "CAFETERIA_REPEAT_PAGE_END"

_DEFAULT_TEMPLATE_PAGE_CONFIG = {
    "식단표_반복페이지템플릿.hwpx": {
        "out": "식단표_반복페이지템플릿.hwpx",
        "type": "meal-plan",
        "capacity": "2-weeks",
        "unit": "2주",
        "local_slots": "W1,W2",
        "page_rule": "ceil(week_count/2)",
        "sha256": "68a9bd53f7fcddf377581143f236082886a8bf39394e7f70af89b162ae66de2a",
        "size": 46767,
    },
    "조리지시서_반복페이지템플릿.hwpx": {
        "out": "조리지시서_반복페이지템플릿.hwpx",
        "type": "cooking-instruction",
        "capacity": "1-day-2-meals",
        "unit": "1일(중식+석식)",
        "local_slots": "LUNCH,DINNER",
        "page_rule": "selected_day_count",
        "sha256": "228083c1aac1b15fae5ccafda2c57e4ab92148c4631806b0895330067262492e",
        "size": 31979,
    },
    "보존식기록지_반복페이지템플릿.hwpx": {
        "out": "보존식기록지_반복페이지템플릿.hwpx",
        "type": "preserved-food",
        "capacity": "3-meals",
        "unit": "3식",
        "local_slots": "B1,B2,B3",
        "page_rule": "ceil(meal_count/3)",
        "sha256": "004e003365a2a7020c5a629cffc6caf56b184b93a16be3608ddcd5edaec4143c",
        "size": 35495,
    },
}
_DOCUMENT_TYPE_TO_TEMPLATE_TYPE = {
    "MEAL_PLAN": "meal-plan",
    "COOKING_INSTRUCTION": "cooking-instruction",
    "PRESERVATION_RECORD": "preserved-food",
}
_CAPACITY_TO_COUNT = {
    "2-weeks": 2,
    "1-day-2-meals": 1,
    "3-meals": 3,
}


@dataclass(frozen=True, slots=True)
class RepeatPageConfig:
    template_type: str
    capacity_token: str
    items_per_page: int
    local_slots: tuple[str, ...]
    page_rule: str
    bind_scope: str = "LOCAL"
    page_break_rule: str = "FIRST_TOP_LEVEL_PARAGRAPH_ON_CLONE"


class HwpxTemplateError(RuntimeError):
    pass


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _is_xml_like(name: str) -> bool:
    lower = name.lower()
    return lower.endswith((".xml", ".hpf", ".rdf"))


def _section_sort_key(name: str) -> tuple[int, str]:
    match = re.fullmatch(r"Contents/section(\d+)\.xml", name)
    return (int(match.group(1)) if match else 10**9, name)


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    mapping: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in list(parent):
            mapping[child] = parent
    return mapping


def _text_nodes(root: ET.Element) -> list[ET.Element]:
    return [node for node in root.iter() if _local(node.tag) == "t"]


def _iter_paragraphs(root: ET.Element) -> list[ET.Element]:
    return [node for node in root.iter() if _local(node.tag) == "p"]


def _normalise_multiline(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Iterable):
        return "\n".join("" if item is None else str(item) for item in value)
    return str(value)


def _parse_xml_with_comments(content: bytes) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.fromstring(content, parser=parser)


def _is_comment_node(node: ET.Element) -> bool:
    return not isinstance(node.tag, str)


def _read_repeat_page_config() -> dict[str, dict[str, Any]]:
    config_path = Path(__file__).resolve().parents[2] / "docs" / "template" / "template-page-config.json"
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULT_TEMPLATE_PAGE_CONFIG


def _build_repeat_config_by_document_type() -> dict[str, RepeatPageConfig]:
    raw = _read_repeat_page_config()
    by_template_type: dict[str, RepeatPageConfig] = {}
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        template_type = str(entry.get("type", "")).strip()
        capacity_token = str(entry.get("capacity", "")).strip()
        if not template_type or capacity_token not in _CAPACITY_TO_COUNT:
            continue
        local_slots_raw = str(entry.get("local_slots", ""))
        local_slots = tuple(slot.strip() for slot in local_slots_raw.split(",") if slot.strip())
        by_template_type[template_type] = RepeatPageConfig(
            template_type=template_type,
            capacity_token=capacity_token,
            items_per_page=_CAPACITY_TO_COUNT[capacity_token],
            local_slots=local_slots,
            page_rule=str(entry.get("page_rule", "")).strip(),
        )

    result: dict[str, RepeatPageConfig] = {}
    for document_type, template_type in _DOCUMENT_TYPE_TO_TEMPLATE_TYPE.items():
        config = by_template_type.get(template_type)
        if config is not None:
            result[document_type] = config
    return result


REPEAT_PAGE_CONFIG_BY_DOCUMENT_TYPE = _build_repeat_config_by_document_type()


def _own_text_nodes(paragraph: ET.Element) -> list[ET.Element]:
    """Collect ``t`` elements that belong directly to *paragraph*.

    ``paragraph.iter()`` recurses into nested ``p`` elements (e.g. table-cell
    paragraphs), which causes the outer section paragraph to absorb and clear
    all table-cell text.  We walk the subtree manually and stop at any nested
    ``p`` so that only the paragraph's own run-level ``t`` nodes are returned.
    """
    result: list[ET.Element] = []

    def _walk(element: ET.Element) -> None:
        for child in element:
            local = _local(child.tag)
            if local == "p":
                continue
            if local == "t":
                result.append(child)
            _walk(child)

    _walk(paragraph)
    return result


def _replace_placeholder_in_paragraph(paragraph: ET.Element, token: str, replacement: str) -> bool:
    texts = _own_text_nodes(paragraph)
    if not texts:
        return False
    joined = "".join(elem.text or "" for elem in texts)
    if token not in joined:
        return False
    updated = joined.replace(token, replacement)
    texts[0].text = updated
    for elem in texts[1:]:
        elem.text = ""
    for child in list(paragraph):
        if _local(child.tag) == "linesegarray":
            paragraph.remove(child)
    return True


def _replace_placeholder_in_root(root: ET.Element, token: str, replacement: str) -> bool:
    changed = False
    for paragraph in _iter_paragraphs(root):
        changed = _replace_placeholder_in_paragraph(paragraph, token, replacement) or changed
    return changed


def _candidate_ancestor(node: ET.Element, parent_map: dict[ET.Element, ET.Element], target_tags: tuple[str, ...]) -> ET.Element | None:
    current = node
    while current in parent_map:
        current = parent_map[current]
        if _local(current.tag) in target_tags:
            return current
    return None


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


@dataclass(slots=True)
class HwpxPackage:
    files: dict[str, bytes]
    order: list[str] = field(default_factory=list)
    source_path: Path | None = None
    source_size: int | None = None

    @classmethod
    def load(cls, template_path: str | Path) -> "HwpxPackage":
        path = Path(template_path)
        if not path.exists():
            raise HwpxTemplateError(f"템플릿 파일을 찾을 수 없습니다: {path}")
        file_size = path.stat().st_size
        if file_size < MIN_HWPX_SIZE:
            raise HwpxTemplateError(f"파일이 너무 작습니다 ({file_size}바이트). 정상적인 HWPX 파일이 아닙니다.")
        try:
            with ZipFile(path) as archive:
                order = archive.namelist()
                for name in order:
                    if name.startswith("/") or ".." in name:
                        raise HwpxTemplateError(f"안전하지 않은 경로가 포함되어 있습니다: {name}")
                files = {name: archive.read(name) for name in order}
        except BadZipFile as exc:
            raise HwpxTemplateError(f"정상적인 HWPX ZIP 파일이 아닙니다: {path}") from exc
        return cls(files=files, order=order, source_path=path, source_size=file_size)

    def clone(self) -> "HwpxPackage":
        return HwpxPackage(files=dict(self.files), order=list(self.order), source_path=self.source_path, source_size=self.source_size)

    def section_names(self) -> list[str]:
        return sorted((name for name in self.files if re.fullmatch(r"Contents/section\d+\.xml", name)), key=_section_sort_key)

    def xml_names(self) -> list[str]:
        names = [name for name in self.order if _is_xml_like(name)]
        for name in self.files:
            if _is_xml_like(name) and name not in names:
                names.append(name)
        return names

    def read_xml(self, name: str) -> ET.Element:
        if name not in self.files:
            raise HwpxTemplateError(f"패키지에 파일이 없습니다: {name}")
        return ET.fromstring(self.files[name])

    def write_xml(self, name: str, root: ET.Element) -> None:
        self.files[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        if name not in self.order:
            self.order.append(name)

    def ensureSectionCount(self, section_count: int) -> list[str]:
        if section_count < 1:
            raise HwpxTemplateError("섹션 수는 1개 이상이어야 합니다.")
        sections = self.section_names()
        if not sections:
            raise HwpxTemplateError("HWPX 패키지에 section XML이 없습니다.")
        base_section = sections[0]
        base_xml = self.files[base_section]

        if len(sections) > section_count:
            for name in sections[section_count:]:
                self.files.pop(name, None)
                if name in self.order:
                    self.order.remove(name)
        elif len(sections) < section_count:
            for index in range(len(sections), section_count):
                name = f"Contents/section{index}.xml"
                self.files[name] = base_xml
                if name not in self.order:
                    self.order.append(name)

        self.files["Contents/content.hpf"] = _update_content_hpf(self.files["Contents/content.hpf"], section_count)
        self._update_header_sec_count(section_count)
        self.order = [name for name in self.order if name in self.files]
        for name in self.section_names():
            if name not in self.order:
                self.order.append(name)
        return self.section_names()

    def _update_header_sec_count(self, section_count: int) -> None:
        header_name = "Contents/header.xml"
        if header_name not in self.files:
            return
        root = ET.fromstring(self.files[header_name])
        root.set("secCnt", str(section_count))
        self.files[header_name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def validate(self, *, document_type: str | None = None, required_placeholders: set[str] | None = None, allow_remaining_placeholders: bool = True) -> dict[str, Any]:
        file_size = self.source_size if self.source_size is not None else sum(len(content) for content in self.files.values())
        if file_size < MIN_HWPX_SIZE:
            raise HwpxTemplateError(f"파일이 너무 작습니다 ({file_size}바이트). 정상적인 HWPX 파일이 아닙니다.")

        missing = sorted(REQUIRED_PACKAGE_FILES - set(self.files))
        sections = self.section_names()
        if not sections:
            missing.append("Contents/section*.xml")
        if missing:
            raise HwpxTemplateError(f"필수 HWPX 파일이 없습니다: {', '.join(missing)}")

        for name in self.xml_names():
            try:
                ET.fromstring(self.files[name])
            except ET.ParseError as exc:
                raise HwpxTemplateError(f"XML 파싱에 실패했습니다 ({name}): {exc}") from exc

        content_root = ET.fromstring(self.files["Contents/content.hpf"])
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

        text = "".join("".join(node.text or "" for node in ET.fromstring(self.files[section]).iter() if _local(node.tag) == "t") for section in sections)
        placeholders = sorted(set(PLACEHOLDER_RE.findall(text)))
        if document_type and required_placeholders is None:
            required_placeholders = REQUIRED_PLACEHOLDERS.get(document_type)
        if required_placeholders:
            missing_placeholders = sorted(set(required_placeholders) - set(placeholders))
            if missing_placeholders:
                raise HwpxTemplateError("필수 플레이스홀더가 없습니다: " + ", ".join(missing_placeholders))
        if not allow_remaining_placeholders and placeholders:
            raise HwpxTemplateError("템플릿 플레이스홀더가 남아 있습니다: " + ", ".join(placeholders))

        return {
            "sections": len(sections),
            "files": len(self.files),
            "placeholders": placeholders,
            "file_size": file_size,
        }

    def save(self, output_path: str | Path | None = None) -> bytes:
        output = io.BytesIO()
        names = ["mimetype", *[name for name in self.order if name != "mimetype"]]
        names.extend(name for name in self.files if name not in names)
        with ZipFile(output, "w") as archive:
            if "mimetype" in self.files:
                info = ZipInfo("mimetype")
                info.compress_type = ZIP_STORED
                archive.writestr(info, self.files["mimetype"])
            for name in names:
                if name == "mimetype" or name not in self.files:
                    continue
                archive.writestr(name, self.files[name], compress_type=ZIP_DEFLATED)
        data = output.getvalue()
        with ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip() is not None:
                raise HwpxTemplateError("생성된 HWPX ZIP 패키지가 손상되었습니다.")
            for required_name in REQUIRED_PACKAGE_FILES:
                if required_name not in archive.namelist():
                    raise HwpxTemplateError(f"생성된 HWPX 패키지에 필수 파일이 없습니다: {required_name}")
            for name in self.xml_names():
                ET.fromstring(archive.read(name))
        if output_path is not None:
            Path(output_path).write_bytes(data)
        return data


class HwpxTemplateEngine:
    def __init__(self, package: HwpxPackage):
        self.package = package

    @classmethod
    def loadTemplate(cls, template_path: str | Path) -> "HwpxTemplateEngine":
        engine = cls(HwpxPackage.load(template_path))
        engine.validatePackage(allow_remaining_placeholders=True)
        return engine

    def setField(self, field_name: str, value: Any, *, section_name: str | None = None) -> "HwpxTemplateEngine":
        token = f"{{{{{field_name}}}}}"
        replacement = "" if value is None else str(value)
        target_sections = [section_name] if section_name else self.package.section_names()
        for name in target_sections:
            if name not in self.package.files:
                continue
            root = self.package.read_xml(name)
            if _replace_placeholder_in_root(root, token, replacement):
                self.package.write_xml(name, root)
        return self

    def setMultilineField(self, field_name: str, value: Any, *, section_name: str | None = None) -> "HwpxTemplateEngine":
        if isinstance(value, str):
            text = value
        else:
            text = _normalise_multiline(value)
        return self.setField(field_name, text, section_name=section_name)

    def setFieldInElements(self, roots: list[ET.Element], field_name: str, value: Any) -> "HwpxTemplateEngine":
        token = f"{{{{{field_name}}}}}"
        replacement = "" if value is None else str(value)
        for root in roots:
            _replace_placeholder_in_root(root, token, replacement)
        return self

    def setMultilineFieldInElements(self, roots: list[ET.Element], field_name: str, value: Any) -> "HwpxTemplateEngine":
        text = value if isinstance(value, str) else _normalise_multiline(value)
        return self.setFieldInElements(roots, field_name, text)

    _LEFT_PARA_PR_ID = 100
    _BLUE_CHAR_PR_ID = 100

    def ensureCookingStyles(self) -> tuple[int, int]:
        """Add LEFT-aligned paraPr and blue-colored charPr to header.xml if absent.
        Returns (left_para_pr_id, blue_char_pr_id).
        """
        header_name = "Contents/header.xml"
        if header_name not in self.package.files:
            return (16, 8)
        root = ET.fromstring(self.package.files[header_name])
        left_id = self._LEFT_PARA_PR_ID
        blue_id = self._BLUE_CHAR_PR_ID

        for elem in root.iter():
            local = _local(elem.tag)
            if local == "paraProperties":
                existing = {_local(c.tag) == "paraPr" and c.get("id") for c in elem}
                if str(left_id) not in existing:
                    for child in elem:
                        if _local(child.tag) == "paraPr" and child.get("id") == "16":
                            new_pr = copy.deepcopy(child)
                            new_pr.set("id", str(left_id))
                            for sub in new_pr:
                                if _local(sub.tag) == "align":
                                    sub.set("horizontal", "LEFT")
                            elem.append(new_pr)
                            elem.set("itemCnt", str(int(elem.get("itemCnt", "0")) + 1))
                            break
                break

        for elem in root.iter():
            local = _local(elem.tag)
            if local == "charProperties":
                existing = {_local(c.tag) == "charPr" and c.get("id") for c in elem}
                if str(blue_id) not in existing:
                    for child in elem:
                        if _local(child.tag) == "charPr" and child.get("id") == "8":
                            new_cp = copy.deepcopy(child)
                            new_cp.set("id", str(blue_id))
                            new_cp.set("textColor", "#2E74B5")
                            elem.append(new_cp)
                            elem.set("itemCnt", str(int(elem.get("itemCnt", "0")) + 1))
                            break
                break

        self.package.files[header_name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return left_id, blue_id

    def setMultilineFieldWithNoteColor(
        self, field_name: str, lines: list[str], note_text: str, note_char_pr_id: int, *, section_name: str | None = None
    ) -> "HwpxTemplateEngine":
        """Set a multiline field where note_text gets a separate run with note_char_pr_id."""
        main_text = "\n".join(str(l) for l in lines) if lines else ""
        if not note_text:
            return self.setField(field_name, main_text, section_name=section_name)

        token = f"{{{{{field_name}}}}}"
        HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
        target_sections = [section_name] if section_name else self.package.section_names()

        for name in target_sections:
            if name not in self.package.files:
                continue
            root = self.package.read_xml(name)
            changed = False
            for paragraph in _iter_paragraphs(root):
                texts = _own_text_nodes(paragraph)
                if not texts:
                    continue
                joined = "".join(t.text or "" for t in texts)
                if token not in joined:
                    continue
                texts[0].text = joined.replace(token, main_text)
                for t in texts[1:]:
                    t.text = ""
                parent_run = None
                for child in paragraph:
                    if _local(child.tag) == "run":
                        parent_run = child
                        break
                new_run = ET.Element(f"{{{HP}}}run", {"charPrIDRef": str(note_char_pr_id)})
                new_t = ET.SubElement(new_run, f"{{{HP}}}t")
                new_t.text = "\n" + note_text
                if parent_run is not None:
                    run_index = list(paragraph).index(parent_run)
                    paragraph.insert(run_index + 1, new_run)
                for child in list(paragraph):
                    if _local(child.tag) == "linesegarray":
                        paragraph.remove(child)
                changed = True
            if changed:
                self.package.write_xml(name, root)
        return self

    def applyRepeatPages(
        self,
        pages: list[dict[str, Any]],
        *,
        section_name: str = "Contents/section0.xml",
        apply_page_break_on_clone: bool = True,
    ) -> bool:
        if section_name not in self.package.files:
            return False

        root = _parse_xml_with_comments(self.package.files[section_name])
        children = list(root)
        start_index: int | None = None
        end_index: int | None = None
        for index, child in enumerate(children):
            if not _is_comment_node(child):
                continue
            comment_text = (child.text or "").strip()
            if comment_text.startswith(REPEAT_PAGE_START):
                start_index = index
            elif comment_text.startswith(REPEAT_PAGE_END):
                end_index = index

        if start_index is None or end_index is None:
            return False
        if end_index <= start_index:
            raise HwpxTemplateError("반복 페이지 마커 구간이 올바르지 않습니다.")

        template_block = [copy.deepcopy(node) for node in children[start_index + 1 : end_index]]
        if not template_block:
            raise HwpxTemplateError("반복 페이지 템플릿 블록이 비어 있습니다.")

        for node in children[start_index : end_index + 1]:
            root.remove(node)

        effective_pages = pages or [{}]
        for page_index, fields in enumerate(effective_pages):
            page_nodes = [copy.deepcopy(node) for node in template_block]
            if page_index > 0 and apply_page_break_on_clone:
                self._set_page_break_on_first_top_level_paragraph(page_nodes)
            self._bind_local_fields(page_nodes, fields)
            for node in page_nodes:
                root.append(node)

        self.package.write_xml(section_name, root)
        return True

    def _bind_local_fields(self, roots: list[ET.Element], fields: dict[str, Any]) -> None:
        for field_name, value in fields.items():
            if isinstance(value, list):
                self.setMultilineFieldInElements(roots, field_name, value)
            else:
                self.setFieldInElements(roots, field_name, value)

    def _set_page_break_on_first_top_level_paragraph(self, nodes: list[ET.Element]) -> None:
        for node in nodes:
            if _local(node.tag) == "p":
                node.set("pageBreak", "1")
                return

    def cloneRow(self, marker: str, count: int, *, section_name: str | None = None, occurrence: int = 0) -> "HwpxTemplateEngine":
        return self._clone(marker, count, ("tr",), section_name=section_name, occurrence=occurrence)

    def cloneBlock(self, marker: str, count: int, *, section_name: str | None = None, occurrence: int = 0) -> "HwpxTemplateEngine":
        return self._clone(marker, count, ("tc", "tr", "p"), section_name=section_name, occurrence=occurrence)

    def removeBlock(self, marker: str, *, section_name: str | None = None, occurrence: int = 0) -> "HwpxTemplateEngine":
        return self._remove(marker, ("tc", "tr", "p"), section_name=section_name, occurrence=occurrence)

    def validatePackage(self, *, document_type: str | None = None, required_placeholders: set[str] | None = None, allow_remaining_placeholders: bool = True) -> dict[str, Any]:
        return self.package.validate(
            document_type=document_type,
            required_placeholders=required_placeholders,
            allow_remaining_placeholders=allow_remaining_placeholders,
        )

    def save(self, output_path: str | Path | None = None, *, validate: bool = True) -> bytes:
        if validate:
            self.validatePackage(allow_remaining_placeholders=False)
        return self.package.save(output_path)

    def _clone(self, marker: str, count: int, target_tags: tuple[str, ...], *, section_name: str | None, occurrence: int) -> "HwpxTemplateEngine":
        if count < 1:
            raise HwpxTemplateError("복제 개수는 1개 이상이어야 합니다.")
        if count == 1:
            return self
        token = marker if marker.startswith("{{") else f"{{{{{marker}}}}}"
        sections = [section_name] if section_name else self.package.section_names()
        found = self._find_target(token, sections, target_tags, occurrence=occurrence)
        if found is None:
            raise HwpxTemplateError(f"복제할 블록을 찾을 수 없습니다: {marker}")
        section, root, parent, target = found
        insert_index = list(parent).index(target) + 1
        for _ in range(count - 1):
            parent.insert(insert_index, copy.deepcopy(target))
            insert_index += 1
        self.package.write_xml(section, root)
        return self

    def _remove(self, marker: str, target_tags: tuple[str, ...], *, section_name: str | None, occurrence: int) -> "HwpxTemplateEngine":
        token = marker if marker.startswith("{{") else f"{{{{{marker}}}}}"
        sections = [section_name] if section_name else self.package.section_names()
        found = self._find_target(token, sections, target_tags, occurrence=occurrence)
        if found is None:
            raise HwpxTemplateError(f"삭제할 블록을 찾을 수 없습니다: {marker}")
        section, root, parent, target = found
        parent.remove(target)
        self.package.write_xml(section, root)
        return self

    def _find_target(self, token: str, sections: list[str], target_tags: tuple[str, ...], *, occurrence: int) -> tuple[str, ET.Element, ET.Element, ET.Element] | None:
        seen = 0
        for section_name in sections:
            if section_name not in self.package.files:
                continue
            root = self.package.read_xml(section_name)
            parents = _parent_map(root)
            for node in _text_nodes(root):
                if token not in (node.text or ""):
                    continue
                container = _candidate_ancestor(node, parents, target_tags)
                if container is None:
                    continue
                if seen == occurrence:
                    parent = parents.get(container)
                    if parent is None:
                        return None
                    return section_name, root, parent, container
                seen += 1
        return None


class BaseRenderer:
    def render(self, engine: HwpxTemplateEngine, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class MealPlanRenderer(BaseRenderer):
    _REMOVED_PLACEHOLDER_FIELDS = ["ORIGIN_INFO", "NOTICE", "W1_LUNCH_TIME_INFO", "W2_LUNCH_TIME_INFO", "DINNER_TIME_INFO"]

    def render(self, engine: HwpxTemplateEngine, payload: dict[str, Any]) -> None:
        weeks = payload.get("weeks", []) or []
        repeat_config = REPEAT_PAGE_CONFIG_BY_DOCUMENT_TYPE.get("MEAL_PLAN")
        if repeat_config and engine.applyRepeatPages(self._repeat_pages(payload, repeat_config.items_per_page)):
            return
        if not weeks:
            self._clear(engine)
            return
        period_title = self._period_title(weeks)
        engine.setField("PERIOD_TITLE", period_title)
        self._clear_removed_placeholders(engine)

        for week_index in range(2):
            week = weeks[week_index] if week_index < len(weeks) else {}
            days = week.get("days", []) if isinstance(week, dict) else []
            engine.setField(f"W{week_index + 1}_WEEK_LABEL", week.get("week_label", "") if isinstance(week, dict) else "")
            for day_index in range(5):
                day = days[day_index] if day_index < len(days) else {}
                prefix = f"W{week_index + 1}_D{day_index + 1}"
                engine.setField(f"{prefix}_DATE", day.get("date_label", ""))
                engine.setMultilineField(f"{prefix}_LUNCH_MENU", self._menu_lines(day, "LUNCH"))
                engine.setMultilineField(f"{prefix}_DINNER_MENU", self._menu_lines(day, "DINNER"))

    def _repeat_pages(self, payload: dict[str, Any], weeks_per_page: int) -> list[dict[str, Any]]:
        weeks = payload.get("weeks", []) or []
        pages: list[dict[str, Any]] = []
        chunks = [weeks[index : index + weeks_per_page] for index in range(0, len(weeks), weeks_per_page)] if weeks else [[]]
        for chunk in chunks:
            fields: dict[str, Any] = {
                "PERIOD_TITLE": self._period_title(weeks),
                **{field_name: "" for field_name in self._REMOVED_PLACEHOLDER_FIELDS},
            }
            for week_index in range(2):
                week = chunk[week_index] if week_index < len(chunk) else {}
                days = week.get("days", []) if isinstance(week, dict) else []
                fields[f"W{week_index + 1}_WEEK_LABEL"] = week.get("week_label", "") if isinstance(week, dict) else ""
                for day_index in range(5):
                    day = days[day_index] if day_index < len(days) else {}
                    prefix = f"W{week_index + 1}_D{day_index + 1}"
                    fields[f"{prefix}_DATE"] = day.get("date_label", "")
                    fields[f"{prefix}_LUNCH_MENU"] = self._menu_lines(day, "LUNCH")
                    fields[f"{prefix}_DINNER_MENU"] = self._menu_lines(day, "DINNER")
            pages.append(fields)
        return pages

    def _clear(self, engine: HwpxTemplateEngine) -> None:
        for field_name in ["PERIOD_TITLE"]:
            engine.setField(field_name, "")
        self._clear_removed_placeholders(engine)
        for week_index in range(2):
            engine.setField(f"W{week_index + 1}_WEEK_LABEL", "")
            for day_index in range(5):
                prefix = f"W{week_index + 1}_D{day_index + 1}"
                engine.setField(f"{prefix}_DATE", "")
                engine.setField(f"{prefix}_LUNCH_MENU", "")
                engine.setField(f"{prefix}_DINNER_MENU", "")

    def _clear_removed_placeholders(self, engine: HwpxTemplateEngine) -> None:
        for field_name in self._REMOVED_PLACEHOLDER_FIELDS:
            engine.setField(field_name, "")

    def _period_title(self, weeks: list[dict[str, Any]]) -> str:
        first = self._first_date(weeks, first=True)
        last = self._first_date(weeks, first=False)
        if first and last:
            return self._period_label(first, last)
        return "식단표"

    @staticmethod
    def _week_label(d: Any) -> str:
        """Return 'X월 Y주' for a given date's week (Monday-based).

        Rule: if the 1st of the month falls on Mon-Fri, that week is week 1.
        If the 1st falls on Sat-Sun, the following week is week 1.
        """
        from datetime import date, timedelta

        if not isinstance(d, date):
            return ""
        monday = d - timedelta(days=d.weekday())
        first_of_month = monday.replace(day=1)
        first_weekday = first_of_month.weekday()  # 0=Mon … 6=Sun
        if first_weekday <= 4:  # 1st is Mon-Fri → week containing 1st is week 1
            week1_monday = first_of_month - timedelta(days=first_weekday)
        else:  # 1st is Sat-Sun → next Monday starts week 1
            week1_monday = first_of_month + timedelta(days=7 - first_weekday)
        if monday < week1_monday:
            prev_month_last = first_of_month - timedelta(days=1)
            return MealPlanRenderer._week_label(prev_month_last)
        week_num = (monday - week1_monday).days // 7 + 1
        return f"{monday.month}월 {week_num}주"

    @classmethod
    def _period_label(cls, first: Any, last: Any) -> str:
        left = cls._week_label(first)
        right = cls._week_label(last)
        if left and right:
            if left == right:
                return left
            same_month = left.split("월")[0] == right.split("월")[0]
            if same_month:
                left_week = left.split(" ")[1]
                right_week = right.split(" ")[1]
                return f"{left.split(' ')[0]} {left_week}~{right_week}"
            return f"{left}~{right}"
        if left:
            return left
        if right:
            return right
        return ""

    def _first_date(self, weeks: list[dict[str, Any]], *, first: bool) -> Any:
        ordered = weeks if first else list(reversed(weeks))
        for week in ordered:
            if not isinstance(week, dict):
                continue
            if first and week.get("start"):
                return self._parse_date(week.get("start"))
            if not first and week.get("end"):
                return self._parse_date(week.get("end"))
            days = week.get("days", []) or []
            days_iter = days if first else list(reversed(days))
            for day in days_iter:
                if isinstance(day, dict) and day.get("date"):
                    parsed = self._parse_date(day.get("date"))
                    if parsed:
                        return parsed
        return None

    def _parse_date(self, value: Any) -> Any:
        if not value:
            return None
        try:
            from datetime import date

            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def _menu_lines(self, day: dict[str, Any], meal_type: str) -> str:
        service = self._service_for_meal(day, meal_type)
        menus = service.get("menus", []) if isinstance(service, dict) else []
        if not menus:
            return ""
        lines: list[str] = []
        concept_title = service.get("concept_title") if isinstance(service, dict) else None
        if concept_title:
            lines.append(f"[{concept_title}]")
        for menu in menus:
            if isinstance(menu, dict):
                name = menu.get("name") or menu.get("menu_name") or ""
                lines.append(str(name).strip())
            else:
                lines.append(str(menu).strip())
        return "\n".join(line for line in lines if line)

    def _service_for_meal(self, day: dict[str, Any], meal_type: str) -> dict[str, Any]:
        if not isinstance(day, dict):
            return {}
        services = day.get("services")
        if isinstance(services, dict):
            return services.get(meal_type, {}) or {}
        key = "lunch" if meal_type == "LUNCH" else "dinner"
        nested = day.get(key, {})
        if isinstance(nested, dict):
            return nested
        return {}


class CookingInstructionRenderer(BaseRenderer):
    _left_para_pr_id = 100
    _blue_char_pr_id = 100

    def render(self, engine: HwpxTemplateEngine, payload: dict[str, Any]) -> None:
        days = payload.get("days", []) or []
        period_label = payload.get("period_label", "")
        self._left_para_pr_id, self._blue_char_pr_id = engine.ensureCookingStyles()
        self._apply_ingredients_alignment(engine)
        repeat_config = REPEAT_PAGE_CONFIG_BY_DOCUMENT_TYPE.get("COOKING_INSTRUCTION")
        if repeat_config and engine.applyRepeatPages(self._repeat_pages(days, repeat_config.items_per_page, period_label)):
            return
        engine.setField("PERIOD_TITLE", period_label)
        engine.package.ensureSectionCount(max(1, len(days)))
        for day_index, day in enumerate(days):
            section_name = f"Contents/section{day_index}.xml"
            engine.setField("DATE_LABEL", day.get("date_label", ""), section_name=section_name)
            self._render_meal(engine, day, section_name, "LUNCH")
            self._render_meal(engine, day, section_name, "DINNER")
        if not days:
            engine.setField("DATE_LABEL", "")
            self._clear_meal(engine, None, "LUNCH")
            self._clear_meal(engine, None, "DINNER")

    def _apply_ingredients_alignment(self, engine: HwpxTemplateEngine) -> None:
        for name in engine.package.section_names():
            if name not in engine.package.files:
                continue
            root = engine.package.read_xml(name)
            changed = False
            for paragraph in _iter_paragraphs(root):
                texts = _own_text_nodes(paragraph)
                joined = "".join(t.text or "" for t in texts)
                if "INGREDIENTS" in joined and "{{" in joined:
                    paragraph.set("paraPrIDRef", str(self._left_para_pr_id))
                    changed = True
            if changed:
                engine.package.write_xml(name, root)

    def _repeat_pages(self, days: list[dict[str, Any]], days_per_page: int, period_label: str = "") -> list[dict[str, Any]]:
        chunks = [days[index : index + days_per_page] for index in range(0, len(days), days_per_page)] if days else [[]]
        pages: list[dict[str, Any]] = []
        for chunk in chunks:
            day = chunk[0] if chunk else {}
            fields = {"DATE_LABEL": day.get("date_label", "") if isinstance(day, dict) else "", "PERIOD_TITLE": period_label}
            fields.update(self._meal_fields(day, "LUNCH"))
            fields.update(self._meal_fields(day, "DINNER"))
            pages.append(fields)
        return pages

    def _meal_fields(self, day: dict[str, Any], meal_type: str) -> dict[str, Any]:
        meal = self._meal(day, meal_type)
        menus = meal.get("menus", []) if isinstance(meal, dict) else []
        fields: dict[str, Any] = {f"{meal_type}_TITLE": meal.get("meal_name", "") if isinstance(meal, dict) else ""}
        slots = 7
        for slot in range(1, slots + 1):
            prefix = f"{meal_type}_MENU_{slot}"
            ingredient_prefix = f"{meal_type}_INGREDIENTS_{slot}"
            if slot <= len(menus):
                menu = menus[slot - 1]
                if slot == slots and len(menus) > slots:
                    remaining = menus[slot - 1 :]
                    fields[prefix] = self._menu_name(remaining[0])
                    fields[ingredient_prefix] = [self._menu_block_text(entry) for entry in remaining]
                    break
                fields[prefix] = self._menu_name(menu)
                lines = self._ingredient_lines(menu)
                note = self._note_line(menu)
                if note:
                    lines = lines + [note]
                fields[ingredient_prefix] = lines
            else:
                fields[prefix] = ""
                fields[ingredient_prefix] = ""
        return fields

    def _render_meal(self, engine: HwpxTemplateEngine, day: dict[str, Any], section_name: str, meal_type: str) -> None:
        meal = self._meal(day, meal_type)
        menus = meal.get("menus", []) if isinstance(meal, dict) else []
        slots = 7
        for slot in range(1, slots + 1):
            prefix = f"{meal_type}_MENU_{slot}"
            ingredient_prefix = f"{meal_type}_INGREDIENTS_{slot}"
            if slot <= len(menus):
                menu = menus[slot - 1]
                if slot == slots and len(menus) > slots:
                    remaining = menus[slot - 1 :]
                    engine.setField(prefix, self._menu_name(remaining[0]), section_name=section_name)
                    engine.setMultilineField(ingredient_prefix, [self._menu_block_text(entry) for entry in remaining], section_name=section_name)
                    break
                engine.setField(prefix, self._menu_name(menu), section_name=section_name)
                engine.setMultilineFieldWithNoteColor(ingredient_prefix, self._ingredient_lines(menu), self._note_line(menu), self._blue_char_pr_id, section_name=section_name)
            else:
                engine.setField(prefix, "", section_name=section_name)
                engine.setField(ingredient_prefix, "", section_name=section_name)
        meal_title = meal.get("meal_name", "") if isinstance(meal, dict) else ""
        if meal_title:
            engine.setField(f"{meal_type}_TITLE", meal_title, section_name=section_name)

    def _clear_meal(self, engine: HwpxTemplateEngine, section_name: str | None, meal_type: str) -> None:
        for slot in range(1, 8):
            engine.setField(f"{meal_type}_MENU_{slot}", "", section_name=section_name)
            engine.setField(f"{meal_type}_INGREDIENTS_{slot}", "", section_name=section_name)
        engine.setField(f"{meal_type}_TITLE", "", section_name=section_name)

    def _meal(self, day: dict[str, Any], meal_type: str) -> dict[str, Any]:
        if not isinstance(day, dict):
            return {}
        services = day.get("services")
        if isinstance(services, dict):
            return services.get(meal_type, {}) or {}
        if isinstance(services, list):
            for service in services:
                if isinstance(service, dict) and service.get("meal_type") == meal_type:
                    return service
        key = "lunch" if meal_type == "LUNCH" else "dinner"
        nested = day.get(key, {})
        return nested if isinstance(nested, dict) else {}

    def _menu_name(self, menu: Any) -> str:
        if isinstance(menu, dict):
            return str(menu.get("name") or menu.get("menu_name") or "").strip()
        return str(menu).strip()

    def _ingredient_lines(self, menu: Any) -> list[str]:
        if not isinstance(menu, dict):
            return [str(menu)] if menu else []
        ingredients = menu.get("ingredients", []) or []
        parts: list[str] = []
        for ingredient in ingredients:
            if isinstance(ingredient, dict):
                name = str(ingredient.get("name") or ingredient.get("ingredient_name") or "").strip()
                quantity = ingredient.get("quantity_total")
                if quantity is None:
                    quantity = ingredient.get("quantity")
                unit = ingredient.get("unit") or ""
                if quantity not in {None, ""} and unit:
                    label = f"{name} {quantity}{unit}"
                else:
                    label = name
                parts.append(label)
            else:
                parts.append(str(ingredient))
        lines: list[str] = []
        if parts:
            lines.append(", ".join(parts))
        instruction = menu.get("instruction") or menu.get("cooking_instruction") or ""
        note = menu.get("note") or menu.get("cooking_note") or ""
        if instruction:
            lines.append(str(instruction))
        return lines

    def _note_line(self, menu: Any) -> str:
        if not isinstance(menu, dict):
            return ""
        return str(menu.get("note") or menu.get("cooking_note") or "")

    def _menu_block_text(self, menu: Any) -> str:
        lines = [self._menu_name(menu), *self._ingredient_lines(menu)]
        note = self._note_line(menu)
        if note:
            lines.append(note)
        return "\n".join(line for line in lines if line)


class PreservedFoodRenderer(BaseRenderer):
    def render(self, engine: HwpxTemplateEngine, payload: dict[str, Any]) -> None:
        records = payload.get("records", []) or []
        period_label = payload.get("period_label", "")
        repeat_config = REPEAT_PAGE_CONFIG_BY_DOCUMENT_TYPE.get("PRESERVATION_RECORD")
        if repeat_config and engine.applyRepeatPages(self._repeat_pages(records, repeat_config.items_per_page, period_label)):
            return
        engine.setField("PERIOD_TITLE", period_label)
        section_count = max(1, math.ceil(len(records) / 3))
        engine.package.ensureSectionCount(section_count)
        for section_index in range(section_count):
            section_name = f"Contents/section{section_index}.xml"
            chunk = records[section_index * 3 : section_index * 3 + 3]
            for slot in range(1, 4):
                record = chunk[slot - 1] if slot - 1 < len(chunk) else {}
                prefix = f"B{slot}"
                engine.setField(f"{prefix}_DATE_LABEL", self._record_label(record), section_name=section_name)
                engine.setField(f"{prefix}_SAMPLE_DATETIME", self._sample_datetime(record), section_name=section_name)
                engine.setField(f"{prefix}_MANAGER", self._value(record, "manager", "manager_name"), section_name=section_name)
                engine.setMultilineField(f"{prefix}_MENU_LIST", self._menus(record), section_name=section_name)
                engine.setField(f"{prefix}_FREEZER_TEMP", self._value(record, "freezer_temperature"), section_name=section_name)
                engine.setField(f"{prefix}_DISCARD_DATETIME", self._discard_datetime(record), section_name=section_name)
                engine.setField(f"{prefix}_COLLECTOR", self._value(record, "collector", "collector_name"), section_name=section_name)
                engine.setField(f"{prefix}_COLLECTION_TIME", self._value(record, "collection_time"), section_name=section_name)
        if not records:
            engine.setField("PERIOD_TITLE", "")
            for field_name in [
                "B1_DATE_LABEL", "B1_SAMPLE_DATETIME", "B1_MANAGER", "B1_MENU_LIST", "B1_FREEZER_TEMP", "B1_DISCARD_DATETIME", "B1_COLLECTOR", "B1_COLLECTION_TIME",
                "B2_DATE_LABEL", "B2_SAMPLE_DATETIME", "B2_MANAGER", "B2_MENU_LIST", "B2_FREEZER_TEMP", "B2_DISCARD_DATETIME", "B2_COLLECTOR", "B2_COLLECTION_TIME",
                "B3_DATE_LABEL", "B3_SAMPLE_DATETIME", "B3_MANAGER", "B3_MENU_LIST", "B3_FREEZER_TEMP", "B3_DISCARD_DATETIME", "B3_COLLECTOR", "B3_COLLECTION_TIME",
            ]:
                engine.setField(field_name, "")

    def _repeat_pages(self, records: list[dict[str, Any]], items_per_page: int, period_label: str = "") -> list[dict[str, Any]]:
        chunks = [records[index : index + items_per_page] for index in range(0, len(records), items_per_page)] if records else [[]]
        pages: list[dict[str, Any]] = []
        for chunk in chunks:
            fields: dict[str, Any] = {"PERIOD_TITLE": period_label}
            for slot in range(1, 4):
                record = chunk[slot - 1] if slot - 1 < len(chunk) else {}
                prefix = f"B{slot}"
                fields[f"{prefix}_DATE_LABEL"] = self._record_label(record)
                fields[f"{prefix}_SAMPLE_DATETIME"] = self._sample_datetime(record)
                fields[f"{prefix}_MANAGER"] = self._value(record, "manager", "manager_name")
                fields[f"{prefix}_MENU_LIST"] = self._menus(record)
                fields[f"{prefix}_FREEZER_TEMP"] = self._value(record, "freezer_temperature")
                fields[f"{prefix}_DISCARD_DATETIME"] = self._discard_datetime(record)
                fields[f"{prefix}_COLLECTOR"] = self._value(record, "collector", "collector_name")
                fields[f"{prefix}_COLLECTION_TIME"] = self._value(record, "collection_time")
            pages.append(fields)
        return pages

    def _record_label(self, record: dict[str, Any]) -> str:
        if not isinstance(record, dict):
            return ""
        return str(record.get("date_label") or record.get("weekday") or "")

    def _sample_datetime(self, record: dict[str, Any]) -> str:
        if not isinstance(record, dict):
            return ""
        return str(record.get("sample_datetime") or "")

    def _discard_datetime(self, record: dict[str, Any]) -> str:
        if not isinstance(record, dict):
            return ""
        return str(record.get("discard_datetime") or "")

    def _menus(self, record: dict[str, Any]) -> list[str]:
        if not isinstance(record, dict):
            return []
        menus = record.get("menu_items") or record.get("menus") or []
        if isinstance(menus, list):
            return [str(item).strip() for item in menus if str(item).strip()]
        return [str(menus)] if menus else []

    def _value(self, record: dict[str, Any], *keys: str) -> str:
        if not isinstance(record, dict):
            return ""
        for key in keys:
            value = record.get(key)
            if value not in {None, ""}:
                return str(value)
        return ""


def renderer_for(document_type: str) -> BaseRenderer:
    mapping = {
        "MEAL_PLAN": MealPlanRenderer(),
        "COOKING_INSTRUCTION": CookingInstructionRenderer(),
        "PRESERVATION_RECORD": PreservedFoodRenderer(),
    }
    try:
        return mapping[document_type]
    except KeyError as exc:
        raise HwpxTemplateError(f"지원하지 않는 문서 유형입니다: {document_type}") from exc


def render_document(template_path: str | Path, preview: DocumentPreview) -> bytes:
    engine = HwpxTemplateEngine.loadTemplate(template_path)
    renderer = renderer_for(preview.document_type)
    renderer.render(engine, preview.payload)
    engine.validatePackage(allow_remaining_placeholders=False)
    return engine.save(validate=False)


def validate_template(template_path: str | Path, document_type: str | None = None) -> dict[str, Any]:
    engine = HwpxTemplateEngine.loadTemplate(template_path)
    return engine.validatePackage(document_type=document_type, allow_remaining_placeholders=True)
