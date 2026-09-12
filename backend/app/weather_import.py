from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import WeatherHistory, WeatherUploadHistory

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_UNCOMPRESSED_SIZE = 100 * 1024 * 1024
MAX_ROWS = 100_000
PREVIEW_TTL = timedelta(minutes=30)
NULL_MARKERS = {"", "-", "--", "n/a", "na", "null"}
WEATHER_FIELDS = (
    "avg_temp", "min_temp", "max_temp", "precipitation",
    "avg_humidity", "snow_depth", "sunshine_hours",
)
HEADER_ALIASES = {
    "observation_date": {"일시", "날짜", "관측일", "관측일자", "관측일시"},
    "station_id": {"지점", "지점번호", "지점코드", "관측지점번호", "관측지점코드"},
    "station_name": {"지점명", "관측지점명", "관측소명"},
    "avg_temp": {"평균기온", "일평균기온"},
    "min_temp": {"최저기온", "일최저기온"},
    "max_temp": {"최고기온", "일최고기온"},
    "precipitation": {"일강수량", "강수량", "일강수"},
    "avg_humidity": {"평균습도", "평균상대습도", "일평균상대습도"},
    "snow_depth": {"적설", "최심적설", "일최심적설", "최심신적설"},
    "sunshine_hours": {"일조시간", "합계일조시간", "일조"},
}


class WeatherImportError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower().replace("\n", "").replace("\r", "")
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", "", text)
    text = text.replace("℃", "").replace("°c", "").replace("°", "")
    return re.sub(r"[\s_./-]+", "", text)


NORMALIZED_ALIASES = {
    field: {normalize_header(alias) for alias in aliases}
    for field, aliases in HEADER_ALIASES.items()
}


def map_headers(headers: list[Any]) -> tuple[dict[str, int], list[str]]:
    mapping: dict[str, int] = {}
    unknown: list[str] = []
    for index, raw in enumerate(headers):
        header = str(raw or "").strip()
        normalized = normalize_header(raw)
        if not normalized:
            continue
        matched = [field for field, aliases in NORMALIZED_ALIASES.items() if normalized in aliases]
        if not matched:
            unknown.append(header)
            continue
        field = matched[0]
        if field in mapping:
            raise WeatherImportError(f"'{field}'에 매핑되는 헤더가 여러 개입니다.")
        mapping[field] = index
    if "observation_date" not in mapping:
        raise WeatherImportError("관측일자 헤더를 인식하지 못했습니다.")
    if "station_id" not in mapping and "station_name" not in mapping:
        raise WeatherImportError("관측지점 번호 또는 관측지점명 헤더를 인식하지 못했습니다.")
    return mapping, unknown


def validate_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise WeatherImportError("XLSX, XLS, CSV 파일만 업로드할 수 있습니다.")
    if path.stat().st_size > MAX_FILE_SIZE:
        raise WeatherImportError(f"파일 크기는 {MAX_FILE_SIZE // (1024 * 1024)}MB 이하여야 합니다.")
    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise WeatherImportError("유효한 XLSX 파일이 아닙니다.")
                if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_SIZE:
                    raise WeatherImportError("압축 해제 크기가 제한을 초과합니다.")
                if archive.testzip():
                    raise WeatherImportError("손상된 XLSX 파일입니다.")
        except zipfile.BadZipFile as exc:
            raise WeatherImportError("유효한 XLSX 파일이 아닙니다.") from exc
    elif suffix == ".xls":
        if path.read_bytes()[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
            raise WeatherImportError("유효한 XLS 파일이 아닙니다.")
    else:
        sample = path.read_bytes()[:4096]
        if b"\x00" in sample:
            raise WeatherImportError("유효한 CSV 텍스트 파일이 아닙니다.")


def _decode_csv(path: Path) -> str:
    content = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise WeatherImportError("CSV 인코딩은 UTF-8 또는 CP949여야 합니다.")


@contextmanager
def tabular_rows(path: Path) -> Iterator[Iterator[tuple[str, int, list[Any]]]]:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise WeatherImportError("XLSX 파일을 읽을 수 없습니다.") from exc
        try:
            def iterator() -> Iterator[tuple[str, int, list[Any]]]:
                for sheet in workbook.worksheets:
                    for row_number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
                        yield sheet.title, row_number, list(values)
            yield iterator()
        finally:
            workbook.close()
        return
    if suffix == ".xls":
        try:
            import xlrd
            workbook = xlrd.open_workbook(path, on_demand=True)
        except Exception as exc:
            raise WeatherImportError("XLS 파일을 읽을 수 없습니다.") from exc
        try:
            def iterator() -> Iterator[tuple[str, int, list[Any]]]:
                for sheet in workbook.sheets():
                    for row_index in range(sheet.nrows):
                        values: list[Any] = []
                        for cell in sheet.row(row_index):
                            value = cell.value
                            if cell.ctype == xlrd.XL_CELL_DATE:
                                value = xlrd.xldate_as_datetime(value, workbook.datemode)
                            values.append(value)
                        yield sheet.name, row_index + 1, values
            yield iterator()
        finally:
            workbook.release_resources()
        return
    text = _decode_csv(path)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    yield (("CSV", number, row) for number, row in enumerate(csv.reader(text.splitlines(), dialect), start=1))


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)) or float(value) != int(value):
            return None
        try:
            return date(1899, 12, 30) + timedelta(days=int(value))
        except OverflowError:
            return None
    text = str(value).strip()
    if " " in text:
        text = text.split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_number(value: Any) -> tuple[float | None, str | None]:
    if value is None or str(value).strip().lower() in NULL_MARKERS:
        return None, None
    if isinstance(value, bool):
        return None, f'값 "{value}"을 숫자로 변환할 수 없습니다.'
    if isinstance(value, (int, float)):
        number = float(value)
        return (number, None) if math.isfinite(number) else (None, f'값 "{value}"을 숫자로 변환할 수 없습니다.')
    text = str(value).strip().replace(",", "")
    match = re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:℃|°c|c|mm|cm|%|시간|hr|h)?", text, re.IGNORECASE)
    if not match:
        return None, f'값 "{value}"을 숫자로 변환할 수 없습니다.'
    return float(match.group(1)), None


def _station_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _name_station_id(name: str) -> str:
    normalized = re.sub(r"\s+", "", name).lower()
    if len(normalized) <= 64:
        return f"NAME:{normalized}"
    return f"NAME:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    comparable = [{key: value for key, value in row.items() if key not in {"status", "existing"}} for row in rows]
    raw = json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_weather_file(path: Path, db: Session | None = None) -> dict[str, Any]:
    validate_file(path)
    mapping: dict[str, int] | None = None
    mapped_headers: dict[str, str] = {}
    unknown_headers: list[str] = []
    selected_sheet = ""
    header_row = 0
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[tuple[date, str]] = set()
    duplicate_keys: set[tuple[date, str]] = set()
    source_rows = 0

    with tabular_rows(path) as source:
        for sheet_name, row_number, values in source:
            if mapping is None:
                if row_number > 30:
                    continue
                try:
                    candidate, unknown = map_headers(values)
                except WeatherImportError:
                    continue
                mapping, unknown_headers, selected_sheet, header_row = candidate, unknown, sheet_name, row_number
                mapped_headers = {field: str(values[index] or "").strip() for field, index in candidate.items()}
                continue
            if sheet_name != selected_sheet or row_number <= header_row:
                continue
            if not any(value not in (None, "") for value in values):
                continue
            source_rows += 1
            if source_rows > MAX_ROWS:
                raise WeatherImportError(f"최대 {MAX_ROWS:,}행까지 업로드할 수 있습니다.")
            get = lambda field: values[mapping[field]] if field in mapping and mapping[field] < len(values) else None
            observed = _parse_date(get("observation_date"))
            station_name = _station_value(get("station_name"))
            station_id = _station_value(get("station_id"))
            row_errors: list[str] = []
            warnings: list[str] = []
            if observed is None:
                row_errors.append("관측일자를 날짜로 변환할 수 없습니다.")
            if not station_id and not station_name:
                row_errors.append("관측지점 번호와 지점명이 모두 없습니다.")
            if not station_id and station_name:
                station_id = _name_station_id(station_name)
            weather: dict[str, float | None] = {}
            for field in WEATHER_FIELDS:
                value, error = _parse_number(get(field))
                weather[field] = value
                if error:
                    warnings.append(f"{field}: {error} NULL로 처리합니다.")
            if observed and station_id:
                key = (observed, station_id)
                if key in seen:
                    duplicate_keys.add(key)
                seen.add(key)
            row = {
                "source_row": row_number,
                "observation_date": observed.isoformat() if observed else "",
                "station_id": station_id,
                "station_name": station_name,
                **weather,
                "warnings": warnings,
                "error": "; ".join(row_errors),
                "status": "오류" if row_errors else "신규",
            }
            rows.append(row)

    if mapping is None:
        raise WeatherImportError("파일의 처음 30행에서 필요한 헤더를 인식하지 못했습니다.")
    for row in rows:
        if row["observation_date"]:
            key = (date.fromisoformat(row["observation_date"]), row["station_id"])
            if key in duplicate_keys:
                row["error"] = "; ".join(filter(None, [row["error"], "파일 안에서 관측일자와 관측지점이 중복됩니다."]))
                row["status"] = "오류"
    errors = [{"row": row["source_row"], "message": row["error"]} for row in rows if row["error"]]

    valid_rows = [row for row in rows if not row["error"]]
    existing_map: dict[tuple[date, str], WeatherHistory] = {}
    if db is not None and valid_rows:
        dates = [date.fromisoformat(row["observation_date"]) for row in valid_rows]
        station_ids = {row["station_id"] for row in valid_rows}
        existing_rows = db.scalars(
            select(WeatherHistory).where(
                WeatherHistory.observation_date.between(min(dates), max(dates)),
                WeatherHistory.station_id.in_(station_ids),
            )
        ).all()
        existing_map = {(row.observation_date, row.station_id): row for row in existing_rows}
        for row in valid_rows:
            existing = existing_map.get((date.fromisoformat(row["observation_date"]), row["station_id"]))
            row["existing"] = existing.id if existing else None
            if not existing:
                row["status"] = "신규"
            elif any(getattr(existing, field) != row[field] for field in ("station_name", *WEATHER_FIELDS)):
                row["status"] = "수정"
            else:
                row["status"] = "변경 없음"

    valid_dates = [date.fromisoformat(row["observation_date"]) for row in valid_rows]
    stations = sorted({(row["station_id"], row["station_name"]) for row in valid_rows})
    summary = {
        "sheet_name": selected_sheet,
        "header_row": header_row,
        "mapped_headers": mapped_headers,
        "unknown_headers": unknown_headers,
        "total_rows": source_rows,
        "valid_rows": len(valid_rows),
        "inserted_rows": sum(row["status"] == "신규" for row in valid_rows),
        "updated_rows": sum(row["status"] == "수정" for row in valid_rows),
        "skipped_rows": sum(row["status"] == "변경 없음" for row in valid_rows),
        "error_rows": len(errors),
        "warning_fields": sum(len(row["warnings"]) for row in rows),
        "date_from": min(valid_dates).isoformat() if valid_dates else None,
        "date_to": max(valid_dates).isoformat() if valid_dates else None,
        "stations": [{"station_id": station_id, "station_name": name} for station_id, name in stations],
        "rows_fingerprint": _fingerprint(valid_rows),
    }
    return {"summary": summary, "rows": rows, "errors": errors}


def apply_weather_file(path: Path, db: Session, filename: str, checksum: str, user_id: int, expected_fingerprint: str) -> tuple[WeatherUploadHistory, dict[str, int]]:
    parsed = parse_weather_file(path, db)
    if parsed["summary"]["rows_fingerprint"] != expected_fingerprint:
        raise WeatherImportError("Preview 이후 파일 또는 기존 날씨자료가 변경되었습니다. 다시 분석해 주세요.")
    summary = parsed["summary"]
    batch = WeatherUploadHistory(
        original_filename=filename,
        checksum_sha256=checksum,
        date_from=date.fromisoformat(summary["date_from"]) if summary["date_from"] else None,
        date_to=date.fromisoformat(summary["date_to"]) if summary["date_to"] else None,
        stations=summary["stations"],
        total_rows=summary["total_rows"],
        valid_rows=summary["valid_rows"],
        inserted_rows=summary["inserted_rows"],
        updated_rows=summary["updated_rows"],
        skipped_rows=summary["skipped_rows"],
        error_rows=summary["error_rows"],
        status="PROCESSING",
        errors=parsed["errors"][:1000],
        uploaded_by=user_id,
    )
    db.add(batch)
    db.flush()
    now = datetime.now(timezone.utc)
    changed = [row for row in parsed["rows"] if row["status"] in {"신규", "수정"}]
    if changed:
        values = [{
            "observation_date": date.fromisoformat(row["observation_date"]),
            "station_id": row["station_id"],
            "station_name": row["station_name"] or None,
            **{field: row[field] for field in WEATHER_FIELDS},
            "source": "KMA_FILE",
            "upload_batch_id": batch.id,
            "created_at": now,
            "updated_at": now,
        } for row in changed]
        insert = pg_insert(WeatherHistory) if db.bind and db.bind.dialect.name == "postgresql" else sqlite_insert(WeatherHistory)
        for start in range(0, len(values), 1000):
            statement = insert.values(values[start:start + 1000])
            statement = statement.on_conflict_do_update(
                index_elements=[WeatherHistory.observation_date, WeatherHistory.station_id],
                set_={
                    "station_name": statement.excluded.station_name,
                    **{field: getattr(statement.excluded, field) for field in WEATHER_FIELDS},
                    "source": statement.excluded.source,
                    "upload_batch_id": statement.excluded.upload_batch_id,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            db.execute(statement)
    batch.status = "COMPLETED_WITH_ERRORS" if summary["error_rows"] else "COMPLETED"
    batch.completed_at = now
    result = {
        "total_rows": summary["total_rows"],
        "inserted_rows": summary["inserted_rows"],
        "updated_rows": summary["updated_rows"],
        "skipped_rows": summary["skipped_rows"],
        "error_rows": summary["error_rows"],
    }
    return batch, result
