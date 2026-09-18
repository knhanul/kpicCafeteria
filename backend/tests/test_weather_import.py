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
