from __future__ import annotations

import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator
from zipfile import ZipFile

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
M = f"{{{MAIN_NS}}}"
RID = f"{{{REL_NS}}}id"


def excel_serial_to_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        serial = float(value)
    except (TypeError, ValueError):
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    pass
        return None
    # Excel's 1900 date system, including its historical leap-year compatibility.
    return date(1899, 12, 30) + timedelta(days=int(serial))


def excel_column_index(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference)
    if not letters:
        return 0
    result = 0
    for char in letters.group(1):
        result = result * 26 + (ord(char) - 64)
    return result - 1


@dataclass(slots=True)
class SheetInfo:
    name: str
    target: str


class SimpleXlsxReader:
    """Read the migration workbook with only the Python standard library.

    It intentionally supports values, strings and dates used by the supplied workbook.
    Formulas and presentation formatting are not needed for migration.
    """

    def __init__(self, source: str | Path):
        self.source = Path(source)
        self._local_copy: Path | None = None
        self._zip: ZipFile | None = None
        self.shared_strings: list[str] = []
        self.sheets: dict[str, SheetInfo] = {}

    def __enter__(self) -> "SimpleXlsxReader":
        # Mounted volumes on Windows can be slow for repeated random ZIP reads.
        # A local temporary copy makes import predictable inside Docker.
        temp_dir = Path(tempfile.mkdtemp(prefix="cafeteria-xlsx-"))
        self._local_copy = temp_dir / self.source.name
        shutil.copy2(self.source, self._local_copy)
        self._zip = ZipFile(self._local_copy)
        self._load_metadata()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._zip:
            self._zip.close()
        if self._local_copy:
            shutil.rmtree(self._local_copy.parent, ignore_errors=True)

    @property
    def archive(self) -> ZipFile:
        if not self._zip:
            raise RuntimeError("SimpleXlsxReader must be used as a context manager")
        return self._zip

    def _load_metadata(self) -> None:
        names = set(self.archive.namelist())
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(self.archive.read("xl/sharedStrings.xml"))
            self.shared_strings = [
                "".join(node.text or "" for node in item.findall(f".//{M}t"))
                for item in root.findall(f"{M}si")
            ]

        workbook = ET.fromstring(self.archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(self.archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {node.attrib["Id"]: node.attrib["Target"] for node in relationships}
        sheets_node = workbook.find(f"{M}sheets")
        if sheets_node is None:
            return
        for sheet in sheets_node:
            target = rel_map[sheet.attrib[RID]].lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            self.sheets[sheet.attrib["name"]] = SheetInfo(sheet.attrib["name"], target)

    def sheet_rows(self, sheet_name: str) -> Iterator[dict[str, object]]:
        info = self.sheets.get(sheet_name)
        if not info:
            raise KeyError(f"워크북에 '{sheet_name}' 시트가 없습니다.")
        headers: list[str] = []
        with self.archive.open(info.target) as stream:
            for _, elem in ET.iterparse(stream, events=("end",)):
                if elem.tag != f"{M}row":
                    continue
                row_values: dict[int, object] = {}
                for cell in elem.findall(f"{M}c"):
                    reference = cell.attrib.get("r", "A1")
                    index = excel_column_index(reference)
                    row_values[index] = self._cell_value(cell)
                max_index = max(row_values.keys(), default=-1)
                values = [row_values.get(i, "") for i in range(max_index + 1)]
                if not headers:
                    headers = [str(value).strip() for value in values]
                else:
                    record = {
                        header: values[index] if index < len(values) else ""
                        for index, header in enumerate(headers)
                        if header
                    }
                    if any(value not in (None, "") for value in record.values()):
                        yield record
                elem.clear()

    def read_sheet(self, sheet_name: str) -> list[dict[str, object]]:
        return list(self.sheet_rows(sheet_name))

    def _cell_value(self, cell: ET.Element) -> object:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(node.text or "" for node in cell.findall(f".//{M}t"))
        value_node = cell.find(f"{M}v")
        if value_node is None or value_node.text is None:
            return ""
        raw = value_node.text
        if cell_type == "s":
            try:
                return self.shared_strings[int(raw)]
            except (ValueError, IndexError):
                return raw
        if cell_type in {"str", "e"}:
            return raw
        if cell_type == "b":
            return raw == "1"
        try:
            number = float(raw)
            return int(number) if number.is_integer() else number
        except ValueError:
            return raw
