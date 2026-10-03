from __future__ import annotations

from datetime import date, datetime, timedelta

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, create_database_engine
from app.models import MealActual, MealPeriodWeather, MealService, User, WeatherHistory, WeatherHourly, WeatherUploadHistory
from app.weather_import import WeatherImportError, apply_weather_file, parse_weather_file, sha256_file


def make_db(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'weather.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id=1, username="admin", password_hash="unused", display_name="관리자", role="admin"))
        db.commit()
    return engine


def make_xlsx(path, headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "기상자료"
    sheet.append(["기상청 자료"])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_xlsx_header_mapping_and_normalization(tmp_path):
    path = tmp_path / "weather.xlsx"
    make_xlsx(path, ["일시", "지점", "지점명", "평균기온(℃)", "일강수량(mm)"], [
        [date(2025, 1, 1), 108, "서울", "-1.2℃", "0mm"],
        ["2025/01/02", 108, "서울", 0.8, "-"],
    ])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        result = parse_weather_file(path, db)
    assert result["summary"]["valid_rows"] == 2
    assert result["summary"]["date_from"] == "2025-01-01"
    assert result["summary"]["mapped_headers"]["avg_temp"] == "평균기온(℃)"
    assert result["rows"][0]["avg_temp"] == -1.2
    assert result["rows"][0]["precipitation"] == 0
    assert result["rows"][1]["precipitation"] is None


def test_csv_supports_name_only_multiple_stations_and_missing_optional_columns(tmp_path):
    path = tmp_path / "weather.csv"
    path.write_text("관측일자,관측지점명,평균상대습도\n2025.01.01,서울,55%\n2025.01.01,수원,60\n", encoding="cp949")
    engine = make_db(tmp_path)
    with Session(engine) as db:
        result = parse_weather_file(path, db)
    assert result["summary"]["valid_rows"] == 2
    assert len(result["summary"]["stations"]) == 2
    assert all(row["station_id"].startswith("NAME:") for row in result["rows"])
    assert all(row["avg_temp"] is None for row in result["rows"])


def test_invalid_date_is_error_and_invalid_number_becomes_null_warning(tmp_path):
    path = tmp_path / "weather.xlsx"
    make_xlsx(path, ["날짜", "지점코드", "지점명", "평균기온"], [
        ["2025-02-30", "108", "서울", 1.5],
        ["2025-02-28", "108", "서울", "abc"],
    ])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        result = parse_weather_file(path, db)
    assert result["summary"]["error_rows"] == 1
    assert result["summary"]["valid_rows"] == 1
    assert result["summary"]["warning_fields"] == 1
    assert result["rows"][1]["avg_temp"] is None


def test_missing_required_headers_stops_preview(tmp_path):
    path = tmp_path / "weather.xlsx"
    make_xlsx(path, ["평균기온", "강수량"], [[1.2, 0]])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        try:
            parse_weather_file(path, db)
        except WeatherImportError as exc:
            assert "헤더" in str(exc)
        else:
            raise AssertionError("required header validation did not fail")


def test_apply_upserts_and_reupload_is_idempotent(tmp_path):
    path = tmp_path / "weather.xlsx"
    make_xlsx(path, ["날짜", "지점", "지점명", "평균기온", "최고기온"], [["2025-01-01", 108, "서울", 1.2, 5.0]])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        batch, first = apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        assert batch.status == "COMPLETED"
        assert first["inserted_rows"] == 1
        second_preview = parse_weather_file(path, db)
        _, second = apply_weather_file(path, db, path.name, sha256_file(path), 1, second_preview["summary"]["rows_fingerprint"])
        db.commit()
        assert second["skipped_rows"] == 1
        assert db.query(WeatherHistory).count() == 1
        assert db.query(WeatherUploadHistory).count() == 2


def test_apply_updates_existing_and_preserves_meal_actuals(tmp_path):
    path = tmp_path / "weather.xlsx"
    make_xlsx(path, ["날짜", "지점", "평균기온"], [["2025-01-01", 108, 3.5]])
    engine = make_db(tmp_path)
    with Session(engine) as db:
        service = MealService(service_date=date(2025, 1, 1), meal_type="LUNCH", planned_count=400)
        db.add(service)
        db.flush()
        db.add_all([MealActual(meal_service_id=service.id, actual_count=390), WeatherHistory(observation_date=date(2025, 1, 1), station_id="108", avg_temp=1.0)])
        db.commit()
        preview = parse_weather_file(path, db)
        assert preview["summary"]["updated_rows"] == 1
        apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        assert db.scalar(select(WeatherHistory.avg_temp)) == 3.5
        assert db.scalar(select(MealActual.actual_count)) == 390


def test_large_xlsx_preview(tmp_path):
    path = tmp_path / "weather.xlsx"
    start = date(2020, 1, 1)
    rows = [[start + timedelta(days=index), 108, float(index % 30)] for index in range(2000)]
    make_xlsx(path, ["관측일", "관측지점번호", "평균기온(°C)"], rows)
    engine = make_db(tmp_path)
    with Session(engine) as db:
        result = parse_weather_file(path, db)
    assert result["summary"]["total_rows"] == 2000
    assert result["summary"]["valid_rows"] == 2000


def test_hourly_csv_is_stored_raw_and_builds_meal_period_weather(tmp_path):
    path = tmp_path / "weather-hourly.csv"
    path.write_text(
        "observation_datetime,station_id,station_name,temperature,precipitation,humidity,wind_speed,source_kind\n"
        "2026-09-17 11:00,156,관악,20,0.5,70,2,OFFICIAL\n"
        "2026-09-17 12:00,156,관악,22,1.0,74,4,OFFICIAL\n"
        "2026-09-17 17:00,156,관악,24,,60,3,OFFICIAL\n"
        "2026-09-17 18:00,156,관악,26,0,64,5,OFFICIAL\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        assert preview["summary"]["data_granularity"] == "hourly"
        assert preview["summary"]["valid_rows"] == 4
        apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        assert db.query(WeatherHourly).count() == 4
        lunch = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.meal_type == "LUNCH"))
        dinner = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.meal_type == "DINNER"))
    assert lunch.avg_temp == 21
    assert lunch.min_temp == 20
    assert lunch.max_temp == 22
    assert lunch.precipitation == 1.5
    assert lunch.avg_humidity == 72
    assert lunch.avg_wind_speed == 3
    assert lunch.sample_count == 2
    assert dinner.avg_temp == 25
    assert dinner.precipitation == 0
    assert dinner.avg_humidity == 62
    assert dinner.avg_wind_speed == 4
    assert dinner.sample_count == 2


def test_hourly_reupload_is_idempotent(tmp_path):
    path = tmp_path / "weather-hourly.csv"
    path.write_text(
        "observation_datetime,station_id,temperature\n"
        "2026-09-17 11:00,156,20\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        first_preview = parse_weather_file(path, db)
        apply_weather_file(path, db, path.name, sha256_file(path), 1, first_preview["summary"]["rows_fingerprint"])
        db.commit()
        second_preview = parse_weather_file(path, db)
        assert second_preview["summary"]["skipped_rows"] == 1
        apply_weather_file(path, db, path.name, sha256_file(path), 1, second_preview["summary"]["rows_fingerprint"])
        db.commit()
        assert db.query(WeatherHourly).count() == 1
        assert db.query(MealPeriodWeather).count() == 1
        assert db.scalar(select(WeatherHourly.observation_datetime)) == datetime(2026, 9, 17, 11, 0)


# --- weather.nuni.co.kr hourly export (actual file: KMA station 156 광주, 2025-04-01 ~ 2026-09-30) ---
import csv
import gzip
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "weather_nuni_kma156_hourly.csv.gz"


def real_file(tmp_path):
    path = tmp_path / "weather_nuni.csv"
    path.write_bytes(gzip.decompress(FIXTURE.read_bytes()))
    return path


def test_real_weather_nuni_export_preview_dedupes_and_does_not_write(tmp_path):
    path = real_file(tmp_path)
    assert path.read_bytes()[:3] == b"\xef\xbb\xbf"
    engine = make_db(tmp_path)
    with Session(engine) as db:
        summary = parse_weather_file(path, db)["summary"]
        assert db.query(WeatherHourly).count() == 0
        assert db.query(WeatherHistory).count() == 0
        assert db.query(MealPeriodWeather).count() == 0
    assert summary["data_granularity"] == "hourly"
    assert summary["total_rows"] == 25991
    assert summary["duplicate_rows"] == 12839  # "HH:MM" and "HH:MM:SS" rows with identical values
    assert summary["valid_rows"] == 548 * 24
    assert summary["error_rows"] == 0
    assert summary["date_from"] == "2025-04-01" and summary["date_to"] == "2026-09-30"
    assert summary["stations"] == [{"station_id": "156", "station_name": "광주"}]
    assert summary["daily_aggregate_days"] == 548 and summary["partial_days"] == 0
    assert summary["source_note"].startswith("source=KMA")
    assert summary["precipitation_blank_as_zero"] > 10000


def test_real_weather_nuni_export_apply_builds_hourly_meal_and_daily_and_is_idempotent(tmp_path):
    path = real_file(tmp_path)
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        _, result = apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        assert result["inserted_rows"] == 13152 and result["daily_aggregated_days"] == 548
        assert db.query(WeatherHourly).count() == 13152
        assert db.query(MealPeriodWeather).count() == 548 * 2
        assert db.query(WeatherHistory).count() == 548
        day = db.scalar(select(WeatherHistory).where(WeatherHistory.observation_date == date(2025, 4, 2)))
        lunch = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.observation_date == date(2025, 4, 2), MealPeriodWeather.meal_type == "LUNCH"))
        db.expunge(day)
        db.expunge(lunch)
        second = parse_weather_file(path, db)["summary"]
        assert second["skipped_rows"] == 13152 and second["inserted_rows"] == 0 and second["updated_rows"] == 0
        apply_weather_file(path, db, path.name, sha256_file(path), 1, second["rows_fingerprint"])
        db.commit()
        assert db.query(WeatherHourly).count() == 13152
        assert db.query(WeatherHistory).count() == 548
    # independent check against the raw CSV
    lines = path.read_text(encoding="utf-8-sig").splitlines()[1:]
    raw = {}
    for row in csv.DictReader(lines):
        raw[datetime.fromisoformat(row["observation_datetime"]).replace(second=0)] = row
    hours = [row for moment, row in raw.items() if moment.date() == date(2025, 4, 2)]
    temps = [float(row["temperature"]) for row in hours]
    assert len(hours) == 24
    assert day.source == "KMA_HOURLY"
    assert day.min_temp == min(temps) and day.max_temp == max(temps)
    assert day.avg_temp == round(sum(temps) / 24, 1)
    assert day.precipitation == round(sum(float(row["precipitation"] or 0) for row in hours), 1)
    noon = [raw[datetime(2025, 4, 2, hour)] for hour in (11, 12)]
    assert lunch.sample_count == 2
    assert lunch.avg_temp == sum(float(row["temperature"]) for row in noon) / 2


HOURLY_SAMPLE = (
    "# source=KMA timezone=Asia/Seoul station=156\n"
    "observation_datetime,station_id,station_name,temperature,precipitation,humidity,wind_speed,source_kind\n"
    "2026-09-17 11:00:00,156,광주,20,,70,2,OFFICIAL\n"
    "2026-09-17 11:00,156,광주,20,,70,2,OFFICIAL\n"
    "2026-09-17 12:00:00,156,광주,22,1.5,74,4,OFFICIAL\n"
)


def test_hourly_export_encodings_utf8_bom_and_cp949(tmp_path):
    for encoding in ("utf-8", "utf-8-sig", "cp949"):
        path = tmp_path / f"hourly-{encoding}.csv"
        path.write_text(HOURLY_SAMPLE, encoding=encoding)
        result = parse_weather_file(path)
        summary = result["summary"]
        assert summary["valid_rows"] == 2, encoding
        assert summary["duplicate_rows"] == 1
        assert summary["stations"] == [{"station_id": "156", "station_name": "광주"}]
        assert result["rows"][0]["precipitation"] == 0.0  # blank = no rain
        assert result["rows"][1]["precipitation"] == 1.5


def test_conflicting_hourly_duplicates_are_still_errors(tmp_path):
    path = tmp_path / "conflict.csv"
    path.write_text(HOURLY_SAMPLE + "2026-09-17 12:00,156,광주,25,1.5,74,4,OFFICIAL\n", encoding="utf-8")
    summary = parse_weather_file(path)["summary"]
    assert summary["error_rows"] == 2
    assert summary["valid_rows"] == 1


def test_hourly_daily_aggregate_skips_partial_days_and_keeps_official_daily(tmp_path):
    lines = ["observation_datetime,station_id,station_name,temperature,precipitation,humidity"]
    for hour in range(24):
        lines.append(f"2026-09-01 {hour:02d}:00,156,광주,{10 + hour},,50")
        lines.append(f"2026-09-02 {hour:02d}:00,156,광주,{10 + hour},1,50")
    for hour in range(10):
        lines.append(f"2026-09-03 {hour:02d}:00,156,광주,{10 + hour},,50")
    path = tmp_path / "agg.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine = make_db(tmp_path)
    with Session(engine) as db:
        db.add(WeatherHistory(observation_date=date(2026, 9, 2), station_id="156", station_name="광주", avg_temp=99, source="KMA_FILE"))
        db.commit()
        preview = parse_weather_file(path, db)
        assert preview["summary"]["daily_aggregate_days"] == 2 and preview["summary"]["partial_days"] == 1
        _, result = apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        rows = {row.observation_date: row for row in db.scalars(select(WeatherHistory))}
    assert result["daily_aggregated_days"] == 1
    assert set(rows) == {date(2026, 9, 1), date(2026, 9, 2)}
    assert rows[date(2026, 9, 1)].avg_temp == 21.5 and rows[date(2026, 9, 1)].precipitation == 0
    assert rows[date(2026, 9, 1)].source == "KMA_HOURLY"
    assert rows[date(2026, 9, 2)].avg_temp == 99 and rows[date(2026, 9, 2)].source == "KMA_FILE"
