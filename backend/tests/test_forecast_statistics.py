from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.advanced_statistics import menu_metrics, overview
from app.db import Base, create_database_engine
from app.forecast_statistics import (
    ActualIndex,
    classify_cooking,
    classify_protein,
    forecast,
    preference_item,
)
from app.models import Ingredient, MealActual, MealService, MealServiceMenu, MealServiceMenuIngredient, Menu


def make_db(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'forecast.db').as_posix()}")
    Base.metadata.create_all(engine)
    return engine


def add(db, day, meal="LUNCH", actual=100, menu=None):
    service = MealService(service_date=day, meal_type=meal, planned_count=999)
    db.add(service)
    db.flush()
    if actual != "absent":
        db.add(MealActual(meal_service_id=service.id, actual_count=actual))
    if menu is not None:
        db.add(MealServiceMenu(meal_service_id=service.id, menu_id=menu.id, menu_name_snapshot=menu.name, is_representative=True))
    return service


MONDAY = date(2026, 3, 2)


def test_yearly_weekday_average_excludes_closed_days_and_uses_only_the_past():
    records = [(MONDAY - timedelta(days=7 * k), "LUNCH", 100 + k) for k in range(1, 11)]
    records += [(MONDAY - timedelta(days=70 + 7), "LUNCH", 0), (MONDAY - timedelta(days=84), "LUNCH", None)]
    records += [(MONDAY, "LUNCH", 5000), (MONDAY + timedelta(days=7), "LUNCH", 5000)]  # same/future days
    index = ActualIndex(records)
    estimate = index.yearly_weekday(MONDAY, "LUNCH")
    assert estimate.n == 10
    assert estimate.value == sum(100 + k for k in range(1, 11)) / 10
    assert estimate.fallback is False


def test_window_is_365_days():
    index = ActualIndex([(MONDAY - timedelta(days=7 * k), "LUNCH", 100) for k in range(1, 9)] + [(MONDAY - timedelta(days=371), "LUNCH", 1000)])
    assert index.yearly_weekday(MONDAY, "LUNCH").value == 100


def test_fallback_to_meal_overall_average_below_eight_weekday_records():
    records = [(MONDAY - timedelta(days=7 * k), "LUNCH", 200) for k in range(1, 8)]  # 7 Mondays
    records += [(MONDAY - timedelta(days=7 * k - 1), "LUNCH", 100) for k in range(1, 8)]  # 7 Tuesdays
    index = ActualIndex(records)
    estimate = index.yearly_weekday(MONDAY, "LUNCH")
    assert estimate.fallback is True
    assert estimate.value == 150
    records.append((MONDAY - timedelta(days=56), "LUNCH", 200))
    estimate = ActualIndex(records).yearly_weekday(MONDAY, "LUNCH")
    assert estimate.fallback is False and estimate.value == 200


def test_lunch_and_dinner_are_never_mixed():
    records = [(MONDAY - timedelta(days=7 * k), "LUNCH", 400) for k in range(1, 9)]
    records += [(MONDAY - timedelta(days=7 * k), "DINNER", 60) for k in range(1, 9)]
    index = ActualIndex(records)
    assert index.yearly_weekday(MONDAY, "LUNCH").value == 400
    assert index.yearly_weekday(MONDAY, "DINNER").value == 60


def test_forecast_is_leak_free_and_reports_methods_per_meal(tmp_path):
    engine = make_db(tmp_path)
    start = MONDAY - timedelta(days=200)
    with Session(engine) as db:
        for offset in range(200):
            day = start + timedelta(days=offset)
            if day.weekday() < 5:
                add(db, day, "LUNCH", 300 + day.weekday() * 10)
                add(db, day, "DINNER", 50 + day.weekday())
        db.commit()
        eval_start = start + timedelta(days=70)  # after 8 weeks every weekday has >= 8 records
        before = forecast(db, as_of=MONDAY, days=7, eval_start=eval_start)
        # data on/after as_of must not change estimates made as of that date
        for offset in range(0, 30):
            day = MONDAY + timedelta(days=offset)
            if day.weekday() < 5:
                add(db, day, "LUNCH", 9999)
                add(db, day, "DINNER", 9999)
        db.commit()
        after = forecast(db, as_of=MONDAY, days=7, eval_start=eval_start, eval_end=MONDAY - timedelta(days=1))
    strip = lambda rows: [{m: (v and {k: x for k, x in v.items() if k != "scheduled"}) for m, v in row["meals"].items()} for row in rows]
    assert strip(before["forecast"]) == strip(after["forecast"])
    assert before["metrics"] == after["metrics"]
    monday = before["forecast"][0]["meals"]
    assert monday["LUNCH"]["yearly_weekday"] == 300
    assert monday["DINNER"]["yearly_weekday"] == 50
    assert set(before["metrics"]) == {"LUNCH", "DINNER"}
    assert set(before["metrics"]["LUNCH"]) == {"yearly_weekday", "yearly_overall", "recent4", "blend"}
    assert before["metrics"]["LUNCH"]["yearly_weekday"]["wape"] == 0
    assert before["best_method"]["LUNCH"] in before["metrics"]["LUNCH"]
    assert before["forecast"][0]["date"] == MONDAY.isoformat()
    assert all(row["meals"]["LUNCH"] is None for row in before["forecast"] if date.fromisoformat(row["date"]).weekday() >= 5)


def test_usage_index_heatmap_yoy_sharp_drops_and_closure_effect(tmp_path):
    engine = make_db(tmp_path)
    start = date(2025, 1, 6)
    closed = date(2026, 1, 14)  # Wednesday without actuals
    with Session(engine) as db:
        day = start
        while day <= date(2026, 1, 30):
            if day.weekday() < 5:
                if day == closed:
                    add(db, day, "LUNCH", 0)
                    add(db, day, "DINNER", "absent")
                else:
                    value = 70 if day == date(2026, 1, 15) else 100
                    add(db, day, "LUNCH", value)
                    add(db, day, "DINNER", 50)
            day += timedelta(days=1)
        db.commit()
        result = overview(db, date(2026, 1, 1), date(2026, 1, 30), "lunch")["usage_index"]
    lunch = result["meals"]["LUNCH"]
    assert set(result["meals"]) == {"LUNCH", "DINNER"}
    assert all(item["date"] != closed.isoformat() for item in lunch["daily"])
    drop = lunch["sharp_drops"][0]
    assert drop["date"] == "2026-01-15" and drop["index"] == 70 and drop["after_closure"] is True
    effect = {item["key"]: item for item in lunch["closure_effect"]}
    assert effect["after_closure"]["n"] == 1 and effect["after_closure"]["average_index"] == 70
    assert effect["before_closure"]["n"] == 1 and effect["before_closure"]["average_index"] == 100
    month = lunch["months"][0]
    assert month["month"] == "2026-01" and month["last_year_average"] == 100 and month["last_year_n"] > 0
    assert result["meals"]["DINNER"]["average_index"] == 100


def test_shrunk_lift_buckets():
    rows = [{"actual_count": 120, "planned_count": 100}] * 8
    item = preference_item("A", rows, 5)
    assert item["raw_lift_percent"] == 20
    assert item["shrunk_lift_percent"] == 10  # 20% * 8 / (8 + 8)
    assert item["bucket"] == "선호"
    small = preference_item("B", rows[:4], 5)
    assert small["bucket"] == "더 관찰 필요" and small["shrunk_lift_percent"] == 6.7
    neutral = preference_item("C", [{"actual_count": 104, "planned_count": 100}] * 8, 5)
    assert neutral["bucket"] == "보통"
    low = preference_item("D", [{"actual_count": 80, "planned_count": 100}] * 8, 5)
    assert low["bucket"] == "비선호"


def test_classification_from_menu_names_and_ingredient_groups():
    assert classify_cooking("돈까스") == "튀김"
    assert classify_cooking("제육볶음") == "볶음"
    assert classify_cooking("고등어자반구이") == "구이"
    assert classify_cooking("등갈비찜") == "조림·찜"
    assert classify_cooking("언양식불고기전") == "전·부침"
    assert classify_cooking("김치찌개") == "국·탕·찌개"
    assert classify_protein("오리불고기") == "닭·오리"
    assert classify_protein("파채불고기") == "소고기"
    assert classify_protein("등갈비찜") == "돼지고기"
    assert classify_protein("고등어자반구이") == "수산물"
    assert classify_protein("함박스테이크", ["채소", "돼지고기"]) == "돼지고기"
    assert classify_protein("비빔밥") == "기타·채소"


def test_menu_groups_minimums_observe_bucket_and_ingredient_warning(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        fried = Menu(name="돈까스", canonical_name="돈까스")
        stir = Menu(name="제육볶음", canonical_name="제육볶음")
        pork = Ingredient(name="돼지고기", stat_group="돼지고기", default_unit="kg")
        db.add_all([fried, stir, pork])
        db.flush()
        for k in range(1, 9):
            add(db, MONDAY - timedelta(days=7 * k), "LUNCH", 100)
        for k in range(12):
            service = add(db, MONDAY + timedelta(days=7 * k), "LUNCH", 130, fried)
            link = db.query(MealServiceMenu).filter_by(meal_service_id=service.id).one()
            db.add(MealServiceMenuIngredient(meal_service_menu_id=link.id, ingredient_id=pork.id, ingredient_name_snapshot="돼지고기", quantity_total=1, unit="kg"))
        for k in range(3):
            add(db, MONDAY + timedelta(days=7 * k + 1), "LUNCH", 100, stir)
        db.commit()
        result = menu_metrics(db, MONDAY, MONDAY + timedelta(days=90), "lunch")
    groups = result["groups"]
    assert list(groups) == ["LUNCH"]
    cooking = {item["key"]: item for item in groups["LUNCH"]["cooking"]}
    assert cooking["튀김"]["n"] == 12 and cooking["튀김"]["bucket"] == "선호"
    assert cooking["볶음"]["bucket"] == "더 관찰 필요"
    assert "튀김" in groups["LUNCH"]["buckets"]["cooking"]["선호"]
    protein = {item["key"]: item for item in groups["LUNCH"]["protein"]}
    assert protein["돼지고기"]["n"] == 15
    ingredient = {item["key"]: item for item in groups["LUNCH"]["ingredient"]}
    assert ingredient["돼지고기"]["n"] == 12 and ingredient["돼지고기"]["bucket"] == "더 관찰 필요"  # < 15
    assert "교란" in groups["LUNCH"]["ingredient_warning"]
    by_name = {item["canonical_name"]: item for item in result["items"]}
    assert by_name["돈까스"]["cooking_method"] == "튀김"
    assert by_name["제육볶음"]["preference_bucket"] == "더 관찰 필요"
