from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app import meal_count_analysis as analysis
from app.db import Base, create_database_engine
from app.models import (
    Ingredient,
    MealActual,
    MealPeriodWeather,
    MealService,
    MealServiceMenu,
    MealServiceMenuIngredient,
    Menu,
    Recipe,
)
from app.routers import analysis as analysis_router

MONDAY = date(2026, 3, 2)  # a Monday


@pytest.fixture()
def engine(tmp_path):
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'analysis.db').as_posix()}")
    Base.metadata.create_all(engine)
    return engine


class Builder:
    def __init__(self, db: Session):
        self.db = db
        self.menus: dict[str, Menu] = {}
        self.ingredients: dict[str, Ingredient] = {}

    def menu(self, name: str, group: str | None = None) -> Menu:
        if name not in self.menus:
            menu = Menu(name=name, canonical_name=group or name)
            self.db.add(menu)
            self.db.flush()
            self.menus[name] = menu
        return self.menus[name]

    def ingredient(self, name: str) -> Ingredient:
        if name not in self.ingredients:
            item = Ingredient(name=name)
            self.db.add(item)
            self.db.flush()
            self.ingredients[name] = item
        return self.ingredients[name]

    def meal(self, day: date, actual: int | None, meal_type: str = "LUNCH", menus=(("밥", None, ()),), weather=None):
        service = MealService(service_date=day, meal_type=meal_type, planned_count=400)
        self.db.add(service)
        self.db.flush()
        for order, (name, group, ingredients) in enumerate(menus, start=1):
            menu = self.menu(name, group)
            item = MealServiceMenu(meal_service_id=service.id, menu_id=menu.id, sort_order=order, menu_name_snapshot=name)
            self.db.add(item)
            self.db.flush()
            for index, ingredient_name in enumerate(ingredients, start=1):
                ingredient = self.ingredient(ingredient_name)
                self.db.add(MealServiceMenuIngredient(
                    meal_service_menu_id=item.id, ingredient_id=ingredient.id, sort_order=index,
                    ingredient_name_snapshot=ingredient_name, quantity_total=1.5, unit="kg",
                ))
        if actual is not None:
            self.db.add(MealActual(meal_service_id=service.id, actual_count=actual))
        if weather is not None:
            temp, rain = weather
            self.db.add(MealPeriodWeather(
                observation_date=day, station_id="156", station_name="광주", meal_type=meal_type,
                avg_temp=temp, precipitation=rain, sample_count=2,
            ))
        self.db.flush()
        return service


def test_usual_count_uses_all_weekdays_in_previous_364_days_and_excludes_self(engine):
    target = MONDAY + timedelta(weeks=60)
    with Session(engine) as db:
        b = Builder(db)
        b.meal(target - timedelta(days=365), 900)  # one day older than the 364-day window: ignored
        b.meal(target - timedelta(days=364), 300)  # first day of the window: included
        b.meal(target - timedelta(days=100), 350)  # another weekday: included (weekday is not used)
        b.meal(target - timedelta(weeks=1), 400)
        b.meal(target - timedelta(days=1), 450)  # Sunday right before: included
        b.meal(target, 500)  # the day itself: never part of its own usual count
        b.meal(target - timedelta(weeks=2), 80, meal_type="DINNER")  # other meal type: ignored
        db.commit()
        result = analysis.daily(db, "LUNCH", target, target)
        dinner_usual = analysis.usual_counts(analysis._counted_meals(db, "DINNER", target - timedelta(days=400), target), [target])[target]
    point = result["points"][0]
    assert point["actual"] == 500
    assert point["usual"] == 375  # (300 + 350 + 400 + 450) / 4
    assert point["usual_days"] == 4
    assert point["diff"] == 125
    assert point["diff_text"] == "125명 많음"
    assert point["sentence"].startswith(f"{target.month}/{target.day}(월) 중식")
    assert "실제 500명 · 평소 375명 · 125명 많음" in point["sentence"]
    assert dinner_usual == (80, 1)


def test_usual_count_rounds_half_up():
    history = [analysis.MealPoint(1, MONDAY, 100), analysis.MealPoint(2, MONDAY + timedelta(days=1), 101)]
    assert analysis.usual_counts(history, [MONDAY + timedelta(days=2)])[MONDAY + timedelta(days=2)] == (101, 2)
    assert analysis.usual_counts(history, [MONDAY])[MONDAY] == (None, 0)


def test_closed_days_without_menu_or_actual_are_left_out(engine):
    target = MONDAY + timedelta(weeks=10)
    with Session(engine) as db:
        b = Builder(db)
        b.meal(target - timedelta(weeks=1), 400)
        b.meal(target - timedelta(weeks=2), None)  # menu but no actual count
        b.meal(target - timedelta(weeks=3), 0)  # recorded 0: not a served meal
        no_menu = MealService(service_date=target - timedelta(weeks=4), meal_type="LUNCH", planned_count=400)
        db.add(no_menu)
        db.flush()
        db.add(MealActual(meal_service_id=no_menu.id, actual_count=1000))  # actual but no menu
        b.meal(target, 420)
        db.commit()
        result = analysis.daily(db, "LUNCH", target - timedelta(weeks=5), target)
    assert [p["date"] for p in result["points"]] == [(target - timedelta(weeks=1)).isoformat(), target.isoformat()]
    first, last = result["points"]
    assert first["usual"] is None and first["diff"] is None
    assert "평소 식수 없음" in first["sentence"]
    assert last["usual"] == 400 and last["usual_days"] == 1 and last["diff"] == 20


def test_lunch_and_dinner_are_always_separate(engine):
    target = MONDAY + timedelta(weeks=3)
    with Session(engine) as db:
        b = Builder(db)
        b.meal(target - timedelta(weeks=1), 400, "LUNCH")
        b.meal(target - timedelta(weeks=1), 70, "DINNER")
        b.meal(target, 380, "LUNCH")
        b.meal(target, 60, "DINNER")
        db.commit()
        lunch = analysis.daily(db, "LUNCH", target, target)["points"][0]
        dinner = analysis.daily(db, "DINNER", target, target)["points"][0]
    assert (lunch["usual"], lunch["diff"], lunch["diff_text"]) == (400, -20, "20명 적음")
    assert (dinner["usual"], dinner["diff"]) == (70, -10)
    with pytest.raises(analysis.AnalysisError):
        with Session(engine) as db:
            analysis.daily(db, "ALL", target, target)


def test_menu_group_uses_canonical_name_and_baseline_from_all_meals(engine):
    with Session(engine) as db:
        b = Builder(db)
        for week in range(4):
            b.meal(MONDAY + timedelta(weeks=week), 400, menus=(("밥", None, ()), ("국", None, ())))
        b.meal(MONDAY + timedelta(weeks=4), 450, menus=(("밥", None, ()), ("갈비찜 - 매운맛", "갈비찜", ())), weather=(30.0, 0.0))
        b.meal(MONDAY + timedelta(weeks=5), 420, menus=(("LA갈비찜", "갈비찜", ()),), weather=(12.0, 3.0))
        db.commit()
        result = analysis.menu_group(db, "LUNCH", MONDAY, MONDAY + timedelta(weeks=6), "갈비찜")
        hot = analysis.menu_group(db, "LUNCH", MONDAY, MONDAY + timedelta(weeks=6), "갈비찜", "hot")
        rain = analysis.menu_group(db, "LUNCH", MONDAY, MONDAY + timedelta(weeks=6), "갈비찜", "rain")
        cold = analysis.menu_group(db, "LUNCH", MONDAY, MONDAY + timedelta(weeks=6), "갈비찜", "cold")
        groups = analysis.search_menu_groups(db, "갈비")
    assert [p["actual"] for p in result["points"]] == [450, 420]
    # baselines are computed from every counted meal, not only the group's own days
    assert result["points"][0]["usual"] == 400
    assert result["points"][1]["usual"] == 410  # (400*4 + 450) / 5
    assert [p["actual"] for p in hot["points"]] == [450]
    assert [p["actual"] for p in rain["points"]] == [420]
    assert cold["points"] == []
    assert result["low_sample_note"] == "2일뿐이라 참고만 하세요."
    assert groups == [{"name": "갈비찜", "served": 2}]


def test_ingredient_filter_only_counts_meals_with_that_ingredient(engine):
    with Session(engine) as db:
        b = Builder(db)
        b.meal(MONDAY, 400, menus=(("된장국", None, ("두부", "된장")),))
        b.meal(MONDAY + timedelta(weeks=1), 410, menus=(("미역국", None, ("미역",)),))
        b.meal(MONDAY + timedelta(weeks=2), 430, menus=(("마파두부", None, ("두부",)),), weather=(-2.0, 0.0))
        db.commit()
        tofu = b.ingredients["두부"].id
        result = analysis.ingredient(db, "LUNCH", MONDAY, MONDAY + timedelta(weeks=3), tofu)
        cold = analysis.ingredient(db, "LUNCH", MONDAY, MONDAY + timedelta(weeks=3), tofu, "cold")
        found = analysis.search_ingredients(db, "두")
    assert [p["actual"] for p in result["points"]] == [400, 430]
    assert result["points"][1]["usual"] == 405
    assert [p["actual"] for p in cold["points"]] == [430]
    assert found[0]["name"] == "두부" and found[0]["served"] == 2


def test_weather_bands_rain_and_temperature_boundaries(engine):
    with Session(engine) as db:
        b = Builder(db)
        b.meal(MONDAY - timedelta(weeks=1), 400)  # gives every Monday below a usual count
        cases = [(-0.1, 0.0, 380), (0.0, 0.0, 390), (10.0, 2.5, 360), (20.0, 0.0, 420), (28.0, 0.0, 440), (27.9, 1.0, 350)]
        for week, (temp, rain, actual) in enumerate(cases):
            b.meal(MONDAY + timedelta(weeks=week), actual, weather=(temp, rain))
        b.meal(MONDAY + timedelta(weeks=10), 999)  # no weather: left out of weather bands
        db.commit()
        result = analysis.weather_bands(db, "LUNCH", MONDAY, MONDAY + timedelta(weeks=11))
    rain = {band["key"]: band for band in result["rain"]}
    temp = {band["key"]: band for band in result["temperature"]}
    assert rain["rain"]["days"] == 2 and rain["dry"]["days"] == 4
    assert rain["rain"]["avg_actual"] == 355
    assert {k: v["days"] for k, v in temp.items()} == {"below0": 1, "0to10": 1, "10to20": 1, "20to28": 2, "28plus": 1}
    assert temp["below0"]["low_sample_note"] == "1일뿐이라 참고만 하세요."
    assert result["days"] == 6
    band = temp["20to28"]
    assert band["avg_actual"] == round((420 + 350) / 2)
    assert band["avg_diff"] == round(sum(p["diff"] for p in band["points"]) / 2)
    assert result["weather_window"] == "11:00~12:00"


def test_weather_text_uses_serving_window():
    assert analysis.weather_text("11:00~12:00", 3.0, 22.0) == "11:00~12:00 · 비 3mm · 22℃"
    assert analysis.weather_text("17:00~18:00", 0.0, -1.5) == "17:00~18:00 · 비 안 옴 · -1.5℃"
    assert analysis.weather_window_label("DINNER") == "17:00~18:00"


def test_date_detail_lists_menus_in_order_with_main_recipe_and_highlight(engine):
    target = MONDAY + timedelta(weeks=1)
    with Session(engine) as db:
        b = Builder(db)
        b.meal(MONDAY, 400)
        service = b.meal(target, 450, menus=(("쌀밥", None, ("쌀",)), ("제육볶음", None, ("돼지고기", "양파")), ("김치", None, ())), weather=(18.0, 0.0))
        items = sorted(service.menus, key=lambda m: m.sort_order)
        items[1].is_representative = True
        recipe = Recipe(menu_id=items[1].menu_id, name="제육볶음 - 고추장형")
        db.add(recipe)
        db.flush()
        items[1].recipe_id = recipe.id
        items[0].recipe_name_snapshot = "쌀밥 기본"
        db.commit()
        pork = b.ingredients["돼지고기"].id
        detail = analysis.date_detail(db, "LUNCH", target, pork)
    assert [m["name"] for m in detail["menus"]] == ["쌀밥", "제육볶음", "김치"]
    assert [m["is_main"] for m in detail["menus"]] == [False, True, False]
    assert detail["menus"][0]["recipe_name"] == "쌀밥 기본"
    assert detail["menus"][1]["recipe_name"] == "제육볶음 - 고추장형"
    assert [m["has_ingredient"] for m in detail["menus"]] == [False, True, False]
    assert [i["highlight"] for i in detail["menus"][1]["ingredients"]] == [True, False]
    assert (detail["actual"], detail["usual"], detail["diff"]) == (450, 400, 50)
    assert detail["weather"]["text"] == "11:00~12:00 · 비 안 옴 · 18℃"


def test_analysis_api_and_excel_export(engine):
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        b = Builder(db)
        b.meal(MONDAY, 400, menus=(("갈비찜", None, ("소갈비",)),), weather=(5.0, 1.0))
        b.meal(MONDAY + timedelta(weeks=1), 420, menus=(("갈비찜", None, ("소갈비",)),), weather=(5.0, 0.0))
        db.commit()
        ingredient_id = b.ingredients["소갈비"].id
    app = FastAPI()
    app.include_router(analysis_router.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[analysis_router.get_db] = override_db
    app.dependency_overrides[analysis_router.current_user] = lambda: SimpleNamespace(id=1)
    params = {"start": MONDAY.isoformat(), "end": (MONDAY + timedelta(weeks=2)).isoformat(), "meal_type": "LUNCH"}
    with TestClient(app) as client:
        daily = client.get("/api/analysis/daily", params=params)
        assert daily.status_code == 200 and len(daily.json()["points"]) == 2
        assert client.get("/api/analysis/menu-group", params={**params, "name": "갈비찜", "weather": "rain"}).json()["days"] == 1
        assert client.get("/api/analysis/ingredient", params={**params, "ingredient_id": ingredient_id}).json()["days"] == 2
        assert client.get("/api/analysis/weather", params=params).json()["days"] == 1
        assert client.get("/api/analysis/date-detail", params={"date": MONDAY.isoformat(), "meal_type": "LUNCH"}).json()["menus"][0]["name"] == "갈비찜"
        assert client.get("/api/analysis/daily", params={**params, "meal_type": "BOTH"}).status_code == 400
        assert client.get("/api/analysis/menu-group", params={**params, "name": "갈비찜", "weather": "windy"}).status_code == 400
        for tab, extra in (("daily", {}), ("menu", {"name": "갈비찜"}), ("ingredient", {"ingredient_id": ingredient_id}), ("weather", {})):
            response = client.get("/api/analysis/export.xlsx", params={**params, "tab": tab, **extra})
            assert response.status_code == 200
            assert response.content[:2] == b"PK"


def _popular_fixture(db):
    """Usual count is 400 for every ranked day (one prior meal of 400, then each day adds its own)."""
    b = Builder(db)
    day = MONDAY
    b.meal(day - timedelta(days=1), 400)
    plan = [
        # (menu name, 통계집계명, actual)
        ("갈비찜 - 매운맛", "갈비찜", 440), ("LA갈비찜", "갈비찜", 430), ("갈비찜 - 매운맛", "갈비찜", 450),
        ("짜장면", "짜장면", 380), ("짜장면", "짜장면", 370),
        ("카레", "카레", 410),
    ]
    services = []
    for index, (name, group, actual) in enumerate(plan):
        services.append(b.meal(day + timedelta(days=index), actual, menus=(("밥", None, ()), (name, group, ()))))
    db.commit()
    return b, services


def test_popular_menus_rank_by_average_difference_with_min_count(engine):
    with Session(engine) as db:
        _popular_fixture(db)
        start, end = MONDAY, MONDAY + timedelta(days=10)
        top = analysis.popular_menus(db, "LUNCH", start, end, basis="group", order="top", limit=10, min_days=2)
        bottom = analysis.popular_menus(db, "LUNCH", start, end, basis="group", order="bottom", limit=10, min_days=2)
        by_name = analysis.popular_menus(db, "LUNCH", start, end, basis="name", order="top", limit=10, min_days=2)
        one = analysis.popular_menus(db, "LUNCH", start, end, basis="group", order="top", limit=10, min_days=1)
        default = analysis.popular_menus(db, "LUNCH", start, end, basis="group")
    names = [row["name"] for row in top["items"]]
    assert names[0] == "갈비찜" and "카레" not in names  # 카레 served once: below the minimum
    assert top["excluded_too_few"] == 1
    assert names.index("갈비찜") < names.index("짜장면")
    assert bottom["items"][0]["name"] == "짜장면"
    galbi = top["items"][0]
    assert galbi["rank"] == 1 and galbi["days"] == 3
    assert galbi["avg_diff"] == round(sum(p - u for p, u in zip([440, 430, 450], [400, 420, 423])) / 3)
    # by exact menu name, "갈비찜 - 매운맛"(2 days) and "LA갈비찜"(1 day) are separate menus
    assert [r["name"] for r in by_name["items"]][:1] == ["갈비찜 - 매운맛"]
    assert "LA갈비찜" not in [r["name"] for r in by_name["items"]]
    assert "카레" in [r["name"] for r in one["items"]]
    assert default["min_days"] == 1 and [r["name"] for r in default["items"]] == [r["name"] for r in one["items"]]
    assert default["basis_name"] == "대표 메뉴명"
    assert "밥" in [r["name"] for r in one["items"]]  # every menu counts unless main-only is chosen


def test_popular_menus_main_only_and_validation(engine):
    with Session(engine) as db:
        _b, services = _popular_fixture(db)
        for service in services:
            for item in service.menus:
                item.is_representative = item.menu_name_snapshot != "밥"
        db.commit()
        result = analysis.popular_menus(db, "LUNCH", MONDAY, MONDAY + timedelta(days=10), basis="group", min_days=1, main_only=True)
        assert "밥" not in [r["name"] for r in result["items"]]
        assert result["main_only"] is True
        for kwargs in ({"order": "middle"}, {"limit": 15}, {"min_days": 0}, {"basis": "x"}):
            with pytest.raises(analysis.AnalysisError):
                analysis.popular_menus(db, "LUNCH", MONDAY, MONDAY + timedelta(days=10), **kwargs)


def test_menu_compare_name_vs_group_and_multiple_series(engine):
    with Session(engine) as db:
        _popular_fixture(db)
        start, end = MONDAY, MONDAY + timedelta(days=10)
        group = analysis.menu_compare(db, "LUNCH", start, end, "group", ["갈비찜", "짜장면", "갈비찜"])
        name = analysis.menu_compare(db, "LUNCH", start, end, "name", ["LA갈비찜", "갈비찜"])
        found = analysis.search_menus(db, "name", "갈비")
        with pytest.raises(analysis.AnalysisError):
            analysis.menu_compare(db, "LUNCH", start, end, "group", [f"메뉴{i}" for i in range(6)])
        with pytest.raises(analysis.AnalysisError):
            analysis.menu_compare(db, "LUNCH", start, end, "group", [])
    assert group["mode_name"] == "대표 메뉴명"
    assert [i["name"] for i in group["items"]] == ["갈비찜", "짜장면"]  # duplicates removed, order kept
    assert [i["days"] for i in group["items"]] == [3, 2]
    assert group["items"][0]["points"][0]["actual"] == 440
    assert len(group["usual_line"]) == 5 and group["dates"] == sorted(group["dates"])
    # exact menu name: "갈비찜" is only a 대표 메뉴명, not a menu name
    assert [i["days"] for i in name["items"]] == [1, 0]
    assert {f["name"] for f in found} == {"갈비찜 - 매운맛", "LA갈비찜"}


def test_menu_compare_weather_filter_and_api(engine):
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        b = Builder(db)
        b.meal(MONDAY, 400, menus=(("냉면", None, ()),), weather=(30.0, 0.0))
        b.meal(MONDAY + timedelta(days=1), 380, menus=(("냉면", None, ()),), weather=(20.0, 0.0))
        b.meal(MONDAY + timedelta(days=2), 390, menus=(("국밥", None, ()),), weather=(31.0, 0.0))
        db.commit()
        hot = analysis.menu_compare(db, "LUNCH", MONDAY, MONDAY + timedelta(days=5), "name", ["냉면", "국밥"], "hot")
    assert [i["days"] for i in hot["items"]] == [1, 1]
    app = FastAPI()
    app.include_router(analysis_router.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[analysis_router.get_db] = override_db
    app.dependency_overrides[analysis_router.current_user] = lambda: SimpleNamespace(id=1)
    params = {"start": MONDAY.isoformat(), "end": (MONDAY + timedelta(days=5)).isoformat(), "meal_type": "LUNCH"}
    with TestClient(app) as client:
        response = client.get("/api/analysis/menus", params=[*params.items(), ("mode", "name"), ("names", "냉면"), ("names", "국밥")])
        assert [i["days"] for i in response.json()["items"]] == [2, 1]
        popular = client.get("/api/analysis/popular-menus", params={**params, "basis": "name", "min_days": 1, "order": "bottom"})
        assert popular.status_code == 200 and popular.json()["items"]
        assert client.get("/api/analysis/menus/search", params={"mode": "name", "q": "냉"}).json()["items"][0]["name"] == "냉면"
        assert client.get("/api/analysis/popular-menus", params={**params, "limit": 7}).status_code == 400
        for tab, extra in (("menus", [("mode", "name"), ("names", "냉면"), ("names", "국밥")]), ("popular", [("basis", "name"), ("min_days", "1")])):
            response = client.get("/api/analysis/export.xlsx", params=[*params.items(), ("tab", tab), *extra])
            assert response.status_code == 200 and response.content[:2] == b"PK"


def _ingredient_fixture(db):
    """돼지고기 앞다리/삼겹살 share the 통계집계명 '돼지고기'; 맛소금 is in '양념' but marked 통계 분석 제외."""
    b = Builder(db)
    b.meal(MONDAY - timedelta(days=1), 400)
    plan = [
        (440, ("돼지고기 앞다리", "맛소금"), (30.0, 0.0)),
        (430, ("삼겹살",), (20.0, 2.0)),
        (380, ("두부", "맛소금"), (21.0, 0.0)),
        (420, ("돼지고기 앞다리", "두부"), (29.0, 0.0)),
    ]
    for index, (actual, ingredients, weather) in enumerate(plan):
        b.meal(MONDAY + timedelta(days=index), actual, menus=(("밥", None, ()), (f"반찬{index}", None, ingredients)), weather=weather)
    groups = {"돼지고기 앞다리": "돼지고기", "삼겹살": "돼지고기", "두부": "콩류", "맛소금": "양념"}
    for name, group in groups.items():
        b.ingredients[name].stat_group = group
    b.ingredients["맛소금"].analysis_excluded = True
    db.commit()
    return b


def test_ingredient_compare_name_vs_group_and_excluded_flag(engine):
    with Session(engine) as db:
        b = _ingredient_fixture(db)
        start, end = MONDAY, MONDAY + timedelta(days=10)
        by_name = analysis.ingredient_compare(db, "LUNCH", start, end, "name", ["돼지고기 앞다리", "두부", "삼겹살", "두부"])
        by_group = analysis.ingredient_compare(db, "LUNCH", start, end, "group", ["돼지고기", "콩류", "양념"])
        hot = analysis.ingredient_compare(db, "LUNCH", start, end, "group", ["돼지고기"], "hot")
        name_salt = analysis.ingredient_compare(db, "LUNCH", start, end, "name", ["맛소금"])
        groups = analysis.search_ingredient_keys(db, "group", "")
        names = analysis.search_ingredient_keys(db, "name", "돼지")
        pork_ids = analysis.ingredient_ids_for(db, "group", ["돼지고기"])
        salt_ids = analysis.ingredient_ids_for(db, "group", ["양념"])
        with pytest.raises(analysis.AnalysisError):
            analysis.ingredient_compare(db, "LUNCH", start, end, "group", [])
        with pytest.raises(analysis.AnalysisError):
            analysis.ingredient_compare(db, "LUNCH", start, end, "group", [f"군{i}" for i in range(6)])
        with pytest.raises(analysis.AnalysisError):
            analysis.ingredient_compare(db, "LUNCH", start, end, "stat", ["돼지고기"])
        expected_pork_ids = {b.ingredients["돼지고기 앞다리"].id, b.ingredients["삼겹살"].id}
    assert [i["name"] for i in by_name["items"]] == ["돼지고기 앞다리", "두부", "삼겹살"]
    assert [i["days"] for i in by_name["items"]] == [2, 2, 1]
    assert by_name["mode_name"] == "재료 이름"
    # 통계집계명: both pork ingredients count as one series; the excluded 양념 ingredient yields nothing
    assert [i["days"] for i in by_group["items"]] == [3, 2, 0]
    assert [p["actual"] for p in by_group["items"][0]["points"]] == [440, 430, 420]
    assert by_group["mode_name"] == "통계집계명(분석군)"
    assert len(by_group["usual_line"]) == 4 and by_group["dates"] == sorted(by_group["dates"])
    assert by_group["usual_line"][1]["usual"] == 420  # (400 + 440) / 2: the shared baseline of that day
    assert [p["actual"] for p in hot["items"][0]["points"]] == [440, 420]
    assert name_salt["items"][0]["days"] == 2  # picked by exact name, the ingredient is still shown
    assert {g["name"] for g in groups} == {"돼지고기", "콩류"}
    assert next(g for g in groups if g["name"] == "돼지고기")["served"] == 3
    assert [n["name"] for n in names] == ["돼지고기 앞다리"]
    assert pork_ids == expected_pork_ids and salt_ids == set()


def test_ingredient_compare_api_detail_highlight_and_excel(engine):
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        _ingredient_fixture(db)
    app = FastAPI()
    app.include_router(analysis_router.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[analysis_router.get_db] = override_db
    app.dependency_overrides[analysis_router.current_user] = lambda: SimpleNamespace(id=1)
    params = [("start", MONDAY.isoformat()), ("end", (MONDAY + timedelta(days=10)).isoformat()), ("meal_type", "LUNCH")]
    with TestClient(app) as client:
        response = client.get("/api/analysis/ingredients", params=[*params, ("mode", "group"), ("names", "돼지고기"), ("names", "콩류")])
        assert response.status_code == 200
        assert [i["days"] for i in response.json()["items"]] == [3, 2]
        assert client.get("/api/analysis/ingredients", params=[*params, ("mode", "x"), ("names", "돼지고기")]).status_code == 400
        found = client.get("/api/analysis/ingredient-keys/search", params={"mode": "group", "q": "돼"}).json()["items"]
        assert found == [{"name": "돼지고기", "served": 3}]
        detail = client.get("/api/analysis/date-detail", params=[
            ("date", (MONDAY + timedelta(days=3)).isoformat()), ("meal_type", "LUNCH"),
            ("ing_mode", "name"), ("ing_names", "돼지고기 앞다리"), ("ing_names", "두부"),
        ]).json()
        assert [m["has_ingredient"] for m in detail["menus"]] == [False, True]
        assert [i["highlight"] for i in detail["menus"][1]["ingredients"]] == [True, True]
        excel = client.get("/api/analysis/export.xlsx", params=[*params, ("tab", "ingredients"), ("mode", "group"), ("names", "돼지고기"), ("names", "콩류")])
        assert excel.status_code == 200 and excel.content[:2] == b"PK"
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(excel.content))
    assert wb.sheetnames == ["재료별식수", "재료별 요약"]
    assert wb["재료별식수"].max_row == 1 + 3 + 2
    assert [row[0].value for row in wb["재료별 요약"].iter_rows(min_row=2)] == ["돼지고기", "콩류"]


def _scope_fixture(db):
    """Roles come from the menu master (Menu.role). 비빔밥 is a 밥·죽 menu that is the day's main menu."""
    b = Builder(db)
    b.meal(MONDAY - timedelta(days=1), 400)
    roles = {"제육볶음": "주찬", "비빔밥": "밥·죽", "계란말이": "부찬", "배추김치": "김치·절임", "미역국": "국·탕"}
    plan = [
        (440, ("제육볶음", "계란말이", "배추김치"), "제육볶음"),
        (430, ("제육볶음", "계란말이", "배추김치", "미역국"), "제육볶음"),
        (380, ("비빔밥", "계란말이", "배추김치"), "비빔밥"),
        (420, ("제육볶음", "배추김치"), "배추김치"),  # odd data: main flag on a side dish
    ]
    for index, (actual, names, main) in enumerate(plan):
        service = b.meal(MONDAY + timedelta(days=index), actual, menus=tuple((name, None, ()) for name in names))
        for item in service.menus:
            item.is_representative = item.menu_name_snapshot == main
    for name, role in roles.items():
        b.menus[name].role = role
    db.commit()
    return b


def test_popular_scope_main_dish_main_menu_with_side_and_all(engine):
    with Session(engine) as db:
        _scope_fixture(db)
        start, end = MONDAY, MONDAY + timedelta(days=10)
        run = lambda scope, **kw: analysis.popular_menus(db, "LUNCH", start, end, basis="name", limit=10, min_days=1, scope=scope, **kw)
        main_dish, main_menu, with_side, every = run("main_dish"), run("main_menu"), run("with_side"), run("all")
        legacy = analysis.popular_menus(db, "LUNCH", start, end, basis="name", limit=10, min_days=1, main_only=True)
        default_main = analysis.popular_menus(db, "LUNCH", start, end, basis="name", scope="main_menu")
        default_dinner = analysis.popular_menus(db, "DINNER", start, end, basis="name", scope="main_menu")
        default_dish = analysis.popular_menus(db, "LUNCH", start, end, basis="name", scope="main_dish")
        empty = analysis.popular_menus(db, "LUNCH", start, end, basis="name", scope="main_dish", min_days=4)
        with pytest.raises(analysis.AnalysisError):
            run("side_only")
    names = lambda r: {i["name"] for i in r["items"]}
    assert names(main_dish) == {"제육볶음"}
    assert {i["name"]: i["days"] for i in main_dish["items"]} == {"제육볶음": 3}
    # 메인 메뉴만 follows the per-day flag: 제육볶음 only 2 days as main, plus 비빔밥 and the flagged 배추김치
    assert {i["name"]: i["days"] for i in main_menu["items"]} == {"제육볶음": 2, "비빔밥": 1, "배추김치": 1}
    assert names(with_side) == {"제육볶음", "계란말이"}
    assert names(every) == {"제육볶음", "계란말이", "배추김치", "미역국", "비빔밥"}
    assert names(legacy) == names(main_menu) and legacy["scope"] == "main_menu"
    assert (default_main["min_days"], default_dinner["min_days"], default_dish["min_days"]) == (1, 1, 1)
    assert main_dish["scope_name"] == "주찬만" and main_menu["main_only"] is True
    # empty result still tells the largest count found, for the "가장 많이 나온 메뉴도 N번" message
    assert empty["items"] == [] and empty["max_days"] == 3 and empty["excluded_too_few"] == 1


def test_menu_search_and_compare_respect_scope(engine):
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        _scope_fixture(db)
        start, end = MONDAY, MONDAY + timedelta(days=10)
        dish = analysis.search_menus(db, "name", "", scope="main_dish")
        side = analysis.search_menus(db, "group", "", scope="with_side")
        group_all = analysis.search_menus(db, "group", "")
        compare_main = analysis.menu_compare(db, "LUNCH", start, end, "name", ["제육볶음", "배추김치"], scope="main_menu")
        compare_all = analysis.menu_compare(db, "LUNCH", start, end, "name", ["제육볶음", "배추김치"])
    assert [i["name"] for i in dish] == ["제육볶음"]
    assert {i["name"] for i in side} == {"제육볶음", "계란말이"}
    assert len(group_all) == 6
    assert [i["days"] for i in compare_main["items"]] == [2, 1]
    assert [i["days"] for i in compare_all["items"]] == [3, 4]
    app = FastAPI()
    app.include_router(analysis_router.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[analysis_router.get_db] = override_db
    app.dependency_overrides[analysis_router.current_user] = lambda: SimpleNamespace(id=1)
    params = [("start", MONDAY.isoformat()), ("end", (MONDAY + timedelta(days=10)).isoformat()), ("meal_type", "LUNCH")]
    with TestClient(app) as client:
        popular = client.get("/api/analysis/popular-menus", params=[*params, ("scope", "with_side"), ("min_days", "1")]).json()
        assert {i["name"] for i in popular["items"]} == {"제육볶음", "계란말이"}
        assert client.get("/api/analysis/popular-menus", params=[*params, ("scope", "x")]).status_code == 400
        found = client.get("/api/analysis/menus/search", params={"mode": "name", "scope": "main_dish"}).json()["items"]
        assert [i["name"] for i in found] == ["제육볶음"]
        menus = client.get("/api/analysis/menus", params=[*params, ("mode", "name"), ("names", "제육볶음"), ("scope", "main_menu")]).json()
        assert menus["items"][0]["days"] == 2 and menus["scope_name"] == "메인 메뉴만"
        excel = client.get("/api/analysis/export.xlsx", params=[*params, ("tab", "popular"), ("scope", "main_dish"), ("min_days", "1")])
        assert excel.status_code == 200 and excel.content[:2] == b"PK"
        earliest = client.get("/api/analysis/earliest-date", params={"meal_type": "LUNCH"}).json()
        assert earliest["date"] == (MONDAY - timedelta(days=1)).isoformat()


def test_earliest_counted_date(engine):
    with Session(engine) as db:
        # When empty, returns None
        assert analysis.earliest_counted_date(db) is None

        # Add service without actual
        s1 = MealService(service_date=date(2024, 1, 1), meal_type="LUNCH", planned_count=100)
        db.add(s1)
        db.commit()
        # Fallback to service date if no actual
        assert analysis.earliest_counted_date(db) == date(2024, 1, 1)

        # Add service with actual
        s2 = MealService(service_date=date(2024, 2, 1), meal_type="DINNER", planned_count=100)
        db.add(s2)
        db.flush()
        db.add(MealActual(meal_service_id=s2.id, actual_count=80))
        db.commit()

        # Since s2 has actual_count > 0, it is prioritized
        assert analysis.earliest_counted_date(db) == date(2024, 2, 1)
        assert analysis.earliest_counted_date(db, "DINNER") == date(2024, 2, 1)
        # LUNCH has no actual, so it falls back to s2 date
        assert analysis.earliest_counted_date(db, "LUNCH") == date(2024, 2, 1)
