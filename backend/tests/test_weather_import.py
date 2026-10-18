from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
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
        "observation_datetime,station_id,station_name,temperature,precipitation,humidity,wind_speed,snow_depth,source_kind\n"
        "2026-09-17 11:00,156,관악,20,0.5,70,2,0,OFFICIAL\n"
        "2026-09-17 12:00,156,관악,22,1.0,74,4,1.5,OFFICIAL\n"
        "2026-09-17 17:00,156,관악,24,,60,3,,OFFICIAL\n"
        "2026-09-17 18:00,156,관악,26,0,64,5,0,OFFICIAL\n",
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
    assert lunch.snow_depth == 1.5
    assert lunch.avg_humidity == 72
    assert lunch.avg_wind_speed == 3
    assert lunch.sample_count == 2
    assert dinner.avg_temp == 25
    assert dinner.precipitation == 0
    assert dinner.snow_depth == 0
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


def test_asos_keeps_workday_hours_and_does_not_fill_blanks(tmp_path):
    path = tmp_path / "asos.csv"
    path.write_text(
        "일시,지점,지점명,기온(°C),강수량(mm),적설(cm),3시간신적설(cm),기온 QC플래그,강수량 QC플래그\n"
        "2026-04-13 07:00,156,광주,1,9,0,0,0,0\n"
        "2026-04-13 08:00,156,광주,-1.5,,, ,0,\n"
        "2026-04-13 10:00,156,광주,2,0.2,0,0,0,0\n"
        "2026-04-13 11:00,156,광주,3,0.4,1,0,0,0\n"
        "2026-04-13 12:00,156,광주,4,1.5,2,0.3,0,0\n"
        "2026-04-13 18:00,156,광주,6,0,0,0,0,0\n"
        "2026-04-13 19:00,156,광주,7,8,0,0,0,0\n"
        "2026-04-13 13:00,156,광주,-3,1,0,0,0,1\n"
        "2026-04-13 14:00,156,광주,5,0,0,0,9,0\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        assert preview["summary"]["outside_hour_rows"] == 2
        assert preview["summary"]["valid_rows"] == 7
        assert preview["summary"]["file_format"] == "asos_hourly"
        assert preview["summary"]["precip_interval"] == "unconfirmed"
        kept = {row["observation_datetime"]: row for row in preview["rows"] if not row["error"]}
        assert "2026-04-13T07:00" not in kept and "2026-04-13T19:00" not in kept
        assert kept["2026-04-13T08:00"]["temperature"] == -1.5
        assert kept["2026-04-13T08:00"]["precipitation"] is None
        assert kept["2026-04-13T08:00"]["snow_depth"] is None
        assert kept["2026-04-13T13:00"]["precipitation"] is None
        assert kept["2026-04-13T13:00"]["precip_state"] == "error"
        assert kept["2026-04-13T14:00"]["temperature"] is None
        assert kept["2026-04-13T12:00"]["raw_payload"]["지점명"] == "광주"
        apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        assert db.query(WeatherHourly).count() == 7
        lunch = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.meal_type == "LUNCH"))
        dinner = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.meal_type == "DINNER"))
        assert lunch.avg_temp == 3.5 and lunch.temp_complete is True
        assert lunch.precipitation is None and lunch.precip_state == "unavailable"
        assert lunch.snow_depth == 2 and lunch.snow_state == "ok"
        assert lunch.snow_new_3h == 0.3
        assert dinner.precipitation is None
        assert dinner.temp_complete is False
        assert db.query(WeatherHistory).count() == 0
        again = parse_weather_file(path, db)
        assert again["summary"]["skipped_rows"] == 7


def test_asos_one_hour_precip_uses_end_hour_and_pre_window(tmp_path):
    path = tmp_path / "asos-1h.csv"
    path.write_text(
        "일시,지점,지점명,기온(°C),1시간강수량(mm),적설(cm)\n"
        "2026-04-13 10:00,156,광주,2,0.2,0\n"
        "2026-04-13 11:00,156,광주,3,0.4,1\n"
        "2026-04-13 12:00,156,광주,4,1.5,2\n"
        "2026-04-13 16:00,156,광주,5,0,0\n"
        "2026-04-13 17:00,156,광주,6,0,0\n"
        "2026-04-13 18:00,156,광주,7,0,0\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        assert preview["summary"]["precip_interval"] == "1h"
        apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        lunch = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.meal_type == "LUNCH"))
        dinner = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.meal_type == "DINNER"))
    assert lunch.precipitation == 1.5 and lunch.precip_method == "1h_end"
    assert lunch.pre_precip == pytest.approx(0.6) and lunch.pre_precip_state == "ok"
    assert lunch.snow_depth == 2
    assert dinner.precipitation == 0 and dinner.pre_precip == 0
    assert dinner.temp_complete is True


def test_reupload_without_a_column_keeps_the_stored_value(tmp_path):
    full = tmp_path / "full.csv"
    full.write_text(
        "일시,지점,기온(°C),강수량(mm)\n2026-04-13 12:00,156,-2.5,1.2\n",
        encoding="utf-8",
    )
    temp_only = tmp_path / "temp.csv"
    temp_only.write_text(
        "일시,지점,기온(°C)\n2026-04-13 12:00,156,-2.5\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        first = parse_weather_file(full, db)
        apply_weather_file(full, db, full.name, sha256_file(full), 1, first["summary"]["rows_fingerprint"])
        db.commit()
        second = parse_weather_file(temp_only, db)
        assert second["summary"]["skipped_rows"] == 1
        apply_weather_file(temp_only, db, temp_only.name, sha256_file(temp_only), 1, second["summary"]["rows_fingerprint"])
        db.commit()
        row = db.scalar(select(WeatherHourly))
    assert row.temperature == -2.5
    assert row.precipitation == 1.2
    assert row.precip_state == "value"


def test_three_hour_precip_is_not_used_as_meal_rain(tmp_path):
    path = tmp_path / "asos-3h.csv"
    path.write_text(
        "일시,지점,기온(°C),3시간강수량(mm)\n"
        "2026-04-13 11:00,156,3,1\n"
        "2026-04-13 12:00,156,4,9\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        assert preview["summary"]["precip_interval"] == "3h"
        assert preview["rows"][1]["precipitation"] == 9
        apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        lunch = db.scalar(select(MealPeriodWeather).where(MealPeriodWeather.meal_type == "LUNCH"))
    assert lunch.precipitation is None
    assert lunch.precip_state == "unavailable"
    assert lunch.precip_method == "3h"


def test_hub_full_layout_uses_seasonal_precip_and_keeps_blanks(tmp_path):
    path = tmp_path / "weather-hourly-108.csv"
    path.write_text(
        "observation_datetime,station_id,station_name,temperature,precipitation,snow_depth,snow_new_3h,phenomenon_code,ta_qcflg,rn_qcflg\n"
        "2026-01-15 7:00,108,서울,-2,,,,,,,,\n"
        "2026-01-15 8:00,108,서울,-1.2,,,,,,,\n"
        "2026-01-15 11:00,108,서울,0.5,0,1.0,0,,,\n"
        "2026-01-15 12:00,108,서울,1.1,,2.0,0.4,,9\n"
        "2026-03-02 11:00,108,서울,5,,,,,,,\n"
        "2026-03-02 12:00,108,서울,6,4.0,,,,,\n"
        "2026-07-15 11:00,108,서울,28,,,,,,,\n"
        "2026-07-15 12:00,108,서울,29,2.0,,,,,\n"
        "2026-07-15 17:00,108,서울,27,,,,,,,\n"
        "2026-07-15 18:00,108,서울,26,0,,,,,\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        assert preview["summary"]["file_format"] == "hub_hourly"
        assert preview["summary"]["precip_interval"] == "seasonal"
        assert preview["summary"]["outside_hour_rows"] == 1
        assert preview["summary"]["precipitation_blank_as_zero"] == 0
        kept = {row["observation_datetime"]: row for row in preview["rows"] if not row["error"]}
        assert "2026-01-15T07:00" not in kept
        assert kept["2026-01-15T08:00"]["temperature"] == -1.2
        assert kept["2026-01-15T08:00"]["precipitation"] is None
        assert kept["2026-01-15T12:00"]["precip_interval"] == "3h"
        assert kept["2026-01-15T12:00"]["precipitation"] is None
        assert kept["2026-01-15T12:00"]["snow_new_3h"] == 0.4
        assert kept["2026-03-02T12:00"]["precip_interval"] == "3h"
        assert kept["2026-03-02T12:00"]["precipitation"] == 4.0
        assert kept["2026-07-15T12:00"]["precip_interval"] == "1h"
        assert kept["2026-07-15T12:00"]["precipitation"] == 2.0
        apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        db.commit()
        meals = {
            (row.observation_date.isoformat(), row.meal_type): row
            for row in db.scalars(select(MealPeriodWeather))
        }
        winter = meals[("2026-01-15", "LUNCH")]
        march = meals[("2026-03-02", "LUNCH")]
        summer = meals[("2026-07-15", "LUNCH")]
        dinner = meals[("2026-07-15", "DINNER")]
        assert winter.precipitation is None and winter.precip_method == "3h"
        assert winter.snow_depth == 2 and winter.snow_new_3h == 0.4
        assert march.precipitation is None and march.precip_method == "3h"
        assert summer.precipitation == 2.0 and summer.precip_method == "1h_end"
        assert summer.avg_temp == 28.5 and summer.temp_complete is True
        assert dinner.precipitation == 0 and dinner.precip_method == "1h_end"
        assert db.query(WeatherHistory).count() == 0


def test_meal_chart_joins_headcount_and_xlsx(tmp_path):
    from app.weather_meal_stats import meal_chart_series

    path = tmp_path / "weather-hourly-108.csv"
    path.write_text(
        "observation_datetime,station_id,station_name,temperature,precipitation,snow_depth,snow_new_3h,phenomenon_code,ta_qcflg,rn_qcflg\n"
        "2026-07-15 11:00,108,서울,28,,,,,,,\n"
        "2026-07-15 12:00,108,서울,30,2.0,,,,,\n"
        "2026-07-16 11:00,108,서울,22,,,,,,,\n"
        "2026-07-16 12:00,108,서울,24,0,,,,,\n",
        encoding="utf-8",
    )
    engine = make_db(tmp_path)
    with Session(engine) as db:
        preview = parse_weather_file(path, db)
        apply_weather_file(path, db, path.name, sha256_file(path), 1, preview["summary"]["rows_fingerprint"])
        service = MealService(service_date=date(2026, 7, 15), meal_type="LUNCH", planned_count=0)
        db.add(service)
        db.flush()
        db.add(MealActual(meal_service_id=service.id, actual_count=412))
        db.commit()
        chart = meal_chart_series(db, "LUNCH", date(2026, 7, 15), date(2026, 7, 16), "108", 800)
    by_date = {point["date"]: point for point in chart["points"]}
    assert by_date["2026-07-15"]["temp"] == 29
    assert by_date["2026-07-15"]["precip"] == 2.0
    assert by_date["2026-07-15"]["headcount"] == 412
    assert by_date["2026-07-16"]["precip"] == 0
    assert by_date["2026-07-16"]["headcount"] is None

