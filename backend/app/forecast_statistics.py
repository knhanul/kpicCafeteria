"""Yearly-average baseline, forecasts, usage index and menu-preference helpers.

Definitions (shared by every statistics screen):
* A day/meal is *closed* (휴무) when it has no actual count (no MealActual row, NULL, or 0).
  Closed days never enter any average.
* 연간 평균 (yearly weekday average) for date d and meal m = mean of valid actual counts of meal m on the
  same weekday within [d-365, d-1]. When fewer than ``MIN_WEEKDAY_SAMPLES`` such records exist, the
  meal's overall 365-day average is used instead (``fallback``).
* Every value for date d only uses data strictly before d, so evaluations are leak-free.
* 중식 and 석식 are always computed separately.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Ingredient, MealActual, MealService, MealServiceMenu, MealServiceMenuIngredient, Menu

YEAR_DAYS = 365
RECENT_DAYS = 28
MIN_WEEKDAY_SAMPLES = 8
MEALS = ("LUNCH", "DINNER")
MEAL_NAMES = {"LUNCH": "중식", "DINNER": "석식"}
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
SHRINK_K = 8
MIN_MENU_SAMPLES = {"LUNCH": 5, "DINNER": 4}
MIN_GROUP_SAMPLES = 10
MIN_INGREDIENT_SAMPLES = 15
SHARP_DROP_INDEX = 85.0  # usage index <= 85 means 15% or more below the yearly average
BIG_MISS_RATE = 0.20
PREFERENCE_THRESHOLD = 5.0  # shrunk lift percent


def _r(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) + 0.0 if value is not None else None  # + 0.0 turns -0.0 into 0.0


def is_valid_actual(value: Any) -> bool:
    return value is not None and value > 0


@dataclass
class Estimate:
    value: float | None
    n: int
    fallback: bool = False


class _Series:
    """Sorted dates with prefix sums so any [start, end) window is O(log n)."""

    def __init__(self, points: list[tuple[date, int]]):
        points.sort()
        self.dates = [p[0] for p in points]
        self.prefix = [0]
        for _, value in points:
            self.prefix.append(self.prefix[-1] + value)

    def window(self, start: date, end: date) -> tuple[int, int]:
        lo, hi = bisect_left(self.dates, start), bisect_left(self.dates, end)
        return self.prefix[hi] - self.prefix[lo], hi - lo


class ActualIndex:
    def __init__(self, records: Iterable[tuple[date, str, Any]]):
        overall: dict[str, list[tuple[date, int]]] = defaultdict(list)
        weekday: dict[tuple[str, int], list[tuple[date, int]]] = defaultdict(list)
        self.actual: dict[tuple[date, str], int] = {}
        self.valid_days: set[date] = set()
        for service_date, meal_type, actual in records:
            if not is_valid_actual(actual):
                continue
            key = (service_date, meal_type)
            if key in self.actual:  # one service per date/meal is enforced by a unique constraint
                continue
            self.actual[key] = int(actual)
            overall[meal_type].append((service_date, int(actual)))
            weekday[(meal_type, service_date.weekday())].append((service_date, int(actual)))
            self.valid_days.add(service_date)
        self._overall = {key: _Series(points) for key, points in overall.items()}
        self._weekday = {key: _Series(points) for key, points in weekday.items()}
        self.first_day = min(self.valid_days) if self.valid_days else None
        self.last_day = max(self.valid_days) if self.valid_days else None

    @staticmethod
    def _mean(series: _Series | None, start: date, end: date) -> Estimate:
        if series is None:
            return Estimate(None, 0)
        total, n = series.window(start, end)
        return Estimate(total / n if n else None, n)

    def yearly_overall(self, day: date, meal: str) -> Estimate:
        return self._mean(self._overall.get(meal), day - timedelta(days=YEAR_DAYS), day)

    def yearly_weekday(self, day: date, meal: str) -> Estimate:
        same = self._mean(self._weekday.get((meal, day.weekday())), day - timedelta(days=YEAR_DAYS), day)
        if same.n >= MIN_WEEKDAY_SAMPLES:
            return same
        overall = self.yearly_overall(day, meal)
        return Estimate(overall.value, overall.n, True)

    def weekday_count(self, day: date, meal: str) -> int:
        return self._mean(self._weekday.get((meal, day.weekday())), day - timedelta(days=YEAR_DAYS), day).n

    def recent_weekday(self, day: date, meal: str) -> Estimate:
        return self._mean(self._weekday.get((meal, day.weekday())), day - timedelta(days=RECENT_DAYS), day)

    def month_average(self, year: int, month: int, meal: str) -> Estimate:
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        return self._mean(self._overall.get(meal), start, end)

    # --- closure (휴무) handling -------------------------------------------------------------
    def is_closed(self, day: date) -> bool | None:
        """Weekday (Mon-Fri) inside the observed period without any actual count. None = unknown."""
        if self.first_day is None or day < self.first_day or day > self.last_day:
            return None
        return day.weekday() < 5 and day not in self.valid_days

    @staticmethod
    def _business_day(day: date, step: int) -> date:
        day += timedelta(days=step)
        while day.weekday() >= 5:
            day += timedelta(days=step)
        return day

    def closure_flags(self, day: date) -> dict[str, bool | None]:
        return {
            "after_closure": self.is_closed(self._business_day(day, -1)),
            "before_closure": self.is_closed(self._business_day(day, 1)),
        }


def baseline_for(index: ActualIndex, day: date, meal: str) -> Estimate:
    return index.yearly_weekday(day, meal)


def history_rows(db: Session, start: date, end: date, meal_code: str | None = None) -> list[dict[str, Any]]:
    """Single query: every service in [start, end] with its actual count."""
    stmt = (
        select(
            MealService.id,
            MealService.service_date,
            MealService.meal_type,
            MealService.planned_count,
            MealService.note.label("service_note"),
            MealActual.actual_count,
            MealActual.note.label("actual_note"),
        )
        .outerjoin(MealActual, MealActual.meal_service_id == MealService.id)
        .where(MealService.service_date.between(start, end))
        .order_by(MealService.service_date, MealService.meal_type, MealService.id)
    )
    if meal_code:
        stmt = stmt.where(MealService.meal_type == meal_code)
    return [dict(row._mapping) for row in db.execute(stmt)]


def attach_baseline(rows: list[dict[str, Any]], index: ActualIndex) -> None:
    """Replace planned_count by the yearly weekday×meal average (original kept as scheduled_planned_count)."""
    for row in rows:
        estimate = baseline_for(index, row["service_date"], row["meal_type"])
        row["scheduled_planned_count"] = row.get("planned_count")
        row["planned_count"] = _r(estimate.value)
        row["baseline_n"] = estimate.n
        row["baseline_fallback"] = estimate.fallback
        row["closed"] = not is_valid_actual(row.get("actual_count"))


# --------------------------------------------------------------------------------------------
# Forecast (예상식수)
# --------------------------------------------------------------------------------------------
METHODS = {
    "yearly_weekday": "연간 요일 평균",
    "yearly_overall": "연간 전체 평균",
    "recent4": "최근 4주 같은 요일",
    "blend": "혼합(연간 50%+최근 50%)",
}


def _estimates(index: ActualIndex, day: date, meal: str) -> dict[str, Estimate]:
    weekday = index.yearly_weekday(day, meal)
    overall = index.yearly_overall(day, meal)
    recent = index.recent_weekday(day, meal)
    if weekday.value is not None and recent.value is not None:
        blend = Estimate(0.5 * weekday.value + 0.5 * recent.value, weekday.n + recent.n)
    else:
        blend = Estimate(weekday.value, weekday.n, True)
    return {"yearly_weekday": weekday, "yearly_overall": overall, "recent4": recent, "blend": blend}


def _metrics(pairs: list[tuple[float, int]]) -> dict[str, Any]:
    if not pairs:
        return {"n": 0, "mae": None, "wape": None, "bias": None, "bias_rate": None, "within_10_rate": None}
    errors = [forecast - actual for forecast, actual in pairs]
    actual_total = sum(actual for _, actual in pairs)
    within10 = sum(abs(error) / actual <= 0.10 for error, (_, actual) in zip(errors, pairs))
    return {
        "n": len(pairs),
        "mae": _r(sum(abs(e) for e in errors) / len(errors)),
        "wape": _r(sum(abs(e) for e in errors) / actual_total * 100) if actual_total else None,
        "bias": _r(sum(errors) / len(errors)),
        "bias_rate": _r(sum(errors) / actual_total * 100) if actual_total else None,
        "within_10_rate": _r(within10 / len(pairs) * 100),
    }


def forecast(
    db: Session,
    as_of: date | None = None,
    days: int = 14,
    eval_start: date | None = None,
    eval_end: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    eval_end = eval_end or (as_of - timedelta(days=1))
    eval_start = eval_start or (eval_end - timedelta(days=YEAR_DAYS - 1))
    forecast_end = as_of + timedelta(days=days - 1)
    history_start = min(eval_start, as_of) - timedelta(days=2 * YEAR_DAYS)
    rows = history_rows(db, history_start, max(forecast_end, eval_end))  # the only DB query
    index = ActualIndex((r["service_date"], r["meal_type"], r["actual_count"]) for r in rows if r["service_date"] < as_of)

    # Leak-free error history per method/meal for every observed day (used for metrics and ±MAE ranges).
    errors: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
    evaluation: dict[str, list[dict[str, Any]]] = {meal: [] for meal in MEALS}
    for (day, meal), actual in sorted(index.actual.items()):
        if meal not in MEALS:
            continue
        estimates = _estimates(index, day, meal)
        for method, estimate in estimates.items():
            if estimate.value is not None:
                errors[(meal, method)].append((day, estimate.value - actual))
        if eval_start <= day <= eval_end:
            evaluation[meal].append({"date": day, "actual": actual, "estimates": estimates})

    def trailing_mae(meal: str, method: str, day: date) -> float | None:
        values = [abs(e) for d, e in errors[(meal, method)] if day - timedelta(days=YEAR_DAYS) <= d < day]
        return sum(values) / len(values) if values else None

    scheduled = {(r["service_date"], r["meal_type"]) for r in rows if as_of <= r["service_date"] <= forecast_end}
    forecast_rows: list[dict[str, Any]] = []
    for offset in range(days):
        day = as_of + timedelta(days=offset)
        item: dict[str, Any] = {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "meals": {}}
        for meal in MEALS:
            is_scheduled = (day, meal) in scheduled
            regular = index.weekday_count(day, meal) >= 4
            if not is_scheduled and not regular:
                item["meals"][meal] = None
                continue
            estimates = _estimates(index, day, meal)
            mae_weekday = trailing_mae(meal, "yearly_weekday", day)
            mae_blend = trailing_mae(meal, "blend", day)
            weekday = estimates["yearly_weekday"].value
            blend = estimates["blend"].value
            item["meals"][meal] = {
                "scheduled": is_scheduled,
                "yearly_weekday": _r(weekday),
                "yearly_weekday_n": estimates["yearly_weekday"].n,
                "fallback": estimates["yearly_weekday"].fallback,
                "yearly_overall": _r(estimates["yearly_overall"].value),
                "recent4": _r(estimates["recent4"].value),
                "recent4_n": estimates["recent4"].n,
                "blend": _r(blend),
                "range_weekday": [_r(weekday - mae_weekday), _r(weekday + mae_weekday)] if weekday is not None and mae_weekday is not None else None,
                "range_blend": [_r(blend - mae_blend), _r(blend + mae_blend)] if blend is not None and mae_blend is not None else None,
                "mae_weekday": _r(mae_weekday),
                "actual": index.actual.get((day, meal)),
            }
        if any(item["meals"].values()):
            forecast_rows.append(item)

    method_metrics: dict[str, dict[str, Any]] = {}
    series: dict[str, list[dict[str, Any]]] = {}
    misses: dict[str, list[dict[str, Any]]] = {}
    for meal in MEALS:
        method_metrics[meal] = {}
        for method in METHODS:
            pairs = [(e["estimates"][method].value, e["actual"]) for e in evaluation[meal] if e["estimates"][method].value is not None]
            method_metrics[meal][method] = {"label": METHODS[method], **_metrics(pairs)}
        series[meal] = [{
            "date": e["date"].isoformat(),
            "actual": e["actual"],
            "yearly_weekday": _r(e["estimates"]["yearly_weekday"].value),
            "fallback": e["estimates"]["yearly_weekday"].fallback,
        } for e in evaluation[meal]]
        meal_misses = []
        for e in evaluation[meal]:
            base = e["estimates"]["yearly_weekday"].value
            if base is None:
                continue
            rate = (e["actual"] - base) / base
            if abs(rate) >= BIG_MISS_RATE:
                meal_misses.append({
                    "date": e["date"].isoformat(), "weekday": WEEKDAYS[e["date"].weekday()],
                    "actual": e["actual"], "yearly_weekday": _r(base), "difference": _r(e["actual"] - base),
                    "difference_rate": _r(rate * 100), **index.closure_flags(e["date"]),
                })
        meal_misses.sort(key=lambda x: -abs(x["difference_rate"]))
        misses[meal] = meal_misses[:20]
    best = {meal: min((m for m in method_metrics[meal] if method_metrics[meal][m]["wape"] is not None),
                      key=lambda m: method_metrics[meal][m]["wape"], default=None) for meal in MEALS}
    return {
        "as_of": as_of.isoformat(),
        "forecast_from": as_of.isoformat(),
        "forecast_to": forecast_end.isoformat(),
        "evaluation_from": eval_start.isoformat(),
        "evaluation_to": eval_end.isoformat(),
        "meal_names": MEAL_NAMES,
        "methods": METHODS,
        "forecast": forecast_rows,
        "metrics": method_metrics,
        "best_method": best,
        "series": series,
        "big_misses": misses,
        "history_actual_count": len(index.actual),
        "definitions": {
            "closed_day": "실제 식수가 없는 날(미입력·0명)은 휴무로 보고 모든 평균에서 제외합니다.",
            "yearly_weekday": f"직전 365일 같은 요일·같은 배식 실제 식수 평균. 표본 {MIN_WEEKDAY_SAMPLES}건 미만이면 해당 배식 365일 전체 평균으로 대체합니다.",
            "leak_free": "모든 예측·평가는 해당 날짜 이전 자료만 사용합니다.",
            "range": "범위 = 예측값 ± 직전 365일 해당 방법의 평균절대오차(MAE)",
            "error": "오차 = 예측 − 실제 (양수는 과대 예측)",
        },
    }


# --------------------------------------------------------------------------------------------
# Usage index (이용지수) — stage 2
# --------------------------------------------------------------------------------------------
def usage_index(index: ActualIndex, rows: list[dict[str, Any]], start: date, end: date, menus_by_service: dict[int, list[str]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for meal in MEALS:
        daily = []
        groups: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row["meal_type"] != meal or not (start <= row["service_date"] <= end) or not is_valid_actual(row["actual_count"]):
                continue
            base = baseline_for(index, row["service_date"], meal)
            if base.value is None or base.value <= 0:
                continue
            value = row["actual_count"] / base.value * 100
            flags = index.closure_flags(row["service_date"])
            daily.append({
                "date": row["service_date"].isoformat(), "weekday": WEEKDAYS[row["service_date"].weekday()],
                "actual": row["actual_count"], "baseline": _r(base.value), "baseline_fallback": base.fallback,
                "index": _r(value), "menus": menus_by_service.get(row["id"], []), **flags,
            })
            if flags["after_closure"]:
                groups["after_closure"].append(value)
            if flags["before_closure"]:
                groups["before_closure"].append(value)
            if flags["after_closure"] is False and flags["before_closure"] is False:
                groups["normal"].append(value)
        months = []
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            this = index.month_average(cursor.year, cursor.month, meal)
            last = index.month_average(cursor.year - 1, cursor.month, meal)
            months.append({
                "month": cursor.strftime("%Y-%m"), "average": _r(this.value), "n": this.n,
                "last_year_average": _r(last.value), "last_year_n": last.n,
                "change_rate": _r((this.value - last.value) / last.value * 100) if this.value and last.value else None,
            })
            cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        labels = {"normal": "일반일", "after_closure": "휴무 다음날", "before_closure": "휴무 전날"}
        closure_effect = [{
            "key": key, "label": label, "n": len(groups[key]),
            "average_index": _r(sum(groups[key]) / len(groups[key])) if groups[key] else None,
        } for key, label in labels.items()]
        values = [d["index"] for d in daily]
        result[meal] = {
            "meal_name": MEAL_NAMES[meal],
            "average_index": _r(sum(values) / len(values)) if values else None,
            "n": len(values),
            "daily": daily,
            "months": months,
            "sharp_drops": sorted([d for d in daily if d["index"] <= SHARP_DROP_INDEX], key=lambda d: d["index"]),
            "closure_effect": closure_effect,
        }
    return {
        "meals": result,
        "definition": "이용지수 = 실제 식수 ÷ 연간 요일·배식 평균 × 100 (100 = 평소 수준)",
        "sharp_drop_threshold": SHARP_DROP_INDEX,
        "closure_definition": "평일 중 실제 식수가 하나도 없는 날을 휴무로 봅니다. 휴무 전날·다음날은 가장 가까운 평일 기준입니다.",
    }


# --------------------------------------------------------------------------------------------
# Menu preference (stage 3)
# --------------------------------------------------------------------------------------------
COOKING_RULES = [
    ("튀김", ["튀김", "까스", "카츠", "커틀릿", "가라아게", "강정", "탕수", "치킨", "프라이", "후라이드", "크로켓", "고로케", "텐더"]),
    ("구이", ["구이", "스테이크", "바비큐", "바베큐", "오븐", "그릴", "숯불"]),
    ("볶음", ["볶음", "잡채", "제육", "닭갈비", "불고기", "주물럭", "두루치기"]),
    ("조림·찜", ["조림", "찜", "갈비찜", "장조림", "수육", "보쌈", "족발"]),
    ("전·부침", ["전", "부침", "지짐", "동그랑땡"]),
    ("국·탕·찌개", ["국", "탕", "찌개", "전골", "개장", "곰탕", "설렁탕"]),
    ("무침·샐러드", ["무침", "샐러드", "겉절이", "냉채", "쌈"]),
    ("면·덮밥·일품", ["덮밥", "볶음밥", "비빔밥", "국수", "우동", "짜장", "짬뽕", "라면", "파스타", "스파게티", "카레", "라이스", "김밥", "버거", "또띠아"]),
]
PROTEIN_RULES = [
    ("돼지고기", ["돼지", "돈육", "돈까스", "돈가스", "제육", "삼겹", "목살", "수육", "보쌈", "족발", "등갈비", "돈", "햄", "소시지", "순대", "탕수육", "바비큐"]),
    ("소고기", ["소고기", "쇠고기", "우육", "한우", "차돌", "양지", "사태", "육전", "떡갈비", "불고기", "장조림", "갈비찜", "육개장", "소불고기"]),
    ("닭·오리", ["닭", "치킨", "계육", "오리", "가라아게", "윙", "봉"]),
    ("수산물", ["생선", "고등어", "삼치", "연어", "동태", "명태", "코다리", "갈치", "조기", "참치", "임연수", "가자미", "꽁치", "오징어", "쭈꾸미", "주꾸미", "낙지", "새우", "해물", "조개", "어묵", "멸치", "쥐어채", "황태", "북어", "게맛살", "맛살", "굴"]),
    ("두부·콩", ["두부", "콩", "유부"]),
    ("달걀", ["계란", "달걀", "에그", "오믈렛", "알찜"]),
]
INGREDIENT_PROTEIN_GROUPS = {"돼지고기": "돼지고기", "소고기": "소고기", "닭·오리": "닭·오리", "수산물": "수산물", "두류·두부": "두부·콩", "두부·콩": "두부·콩", "달걀": "달걀"}


def _match(name: str, rules: list[tuple[str, list[str]]], prefer: str = "last") -> str | None:
    """Keyword rules. Cooking methods sit at the end of Korean dish names (prefer='last'),
    the protein usually comes first (prefer='first'); ties go to the longer keyword."""
    text = re.sub(r"\s+", "", name or "")
    best: tuple[int, int] | None = None
    best_label: str | None = None
    for label, keywords in rules:
        for keyword in keywords:
            position = text.rfind(keyword) if prefer == "last" else text.find(keyword)
            if position < 0:
                continue
            score = (position + len(keyword), len(keyword)) if prefer == "last" else (-position, len(keyword))
            if best is None or score > best:
                best, best_label = score, label
    return best_label


def classify_cooking(name: str) -> str:
    return _match(name, COOKING_RULES) or "기타"


def classify_protein(name: str, ingredient_groups: Iterable[str] = ()) -> str:
    by_name = _match(name, PROTEIN_RULES, prefer="first")
    if by_name:
        return by_name
    groups = set(ingredient_groups)
    for group, mapped in INGREDIENT_PROTEIN_GROUPS.items():
        if group in groups:
            return mapped
    return "기타·채소"


def _shrunk(ratios: list[float], k: int = SHRINK_K) -> tuple[float | None, float | None]:
    if not ratios:
        return None, None
    raw = sum(ratios) / len(ratios)
    return raw * 100, raw * len(ratios) / (len(ratios) + k) * 100


def _preference_bucket(n: int, minimum: int, shrunk_percent: float | None) -> str:
    if n < minimum or shrunk_percent is None:
        return "더 관찰 필요"
    if shrunk_percent >= PREFERENCE_THRESHOLD:
        return "선호"
    if shrunk_percent <= -PREFERENCE_THRESHOLD:
        return "비선호"
    return "보통"


def preference_item(key: str, occurrences: list[dict[str, Any]], minimum: int) -> dict[str, Any]:
    """occurrences: rows with actual_count (>0) and baseline (>0)."""
    ratios = [row["actual_count"] / row["planned_count"] - 1 for row in occurrences]
    people = [row["actual_count"] - row["planned_count"] for row in occurrences]
    raw, shrunk = _shrunk(ratios)
    n = len(occurrences)
    return {
        "key": key,
        "n": n,
        "minimum_sample": minimum,
        "sample_ok": n >= minimum,
        "average_actual": _r(sum(r["actual_count"] for r in occurrences) / n) if n else None,
        "average_baseline": _r(sum(r["planned_count"] for r in occurrences) / n) if n else None,
        "raw_lift_percent": _r(raw),
        "shrunk_lift_percent": _r(shrunk),
        "shrunk_lift_people": _r(sum(people) / n * n / (n + SHRINK_K)) if n else None,
        "bucket": _preference_bucket(n, minimum, shrunk),
    }


def ingredient_groups_by_service(db: Session, service_ids: list[int]) -> dict[int, set[str]]:
    if not service_ids:
        return {}
    stmt = (
        select(MealServiceMenu.meal_service_id, Ingredient.stat_group)
        .join(MealServiceMenuIngredient, MealServiceMenuIngredient.meal_service_menu_id == MealServiceMenu.id)
        .join(Ingredient, Ingredient.id == MealServiceMenuIngredient.ingredient_id)
        .where(MealServiceMenu.meal_service_id.in_(service_ids), Ingredient.analysis_excluded.is_(False))
    )
    result: dict[int, set[str]] = defaultdict(set)
    for service_id, group in db.execute(stmt):
        if group:
            result[service_id].add(group)
    return result


def menu_ingredient_groups(db: Session, service_ids: list[int]) -> dict[tuple[int, str], set[str]]:
    """(service_id, canonical menu name) -> ingredient stat groups of that menu (for protein fallback)."""
    if not service_ids:
        return {}
    stmt = (
        select(MealServiceMenu.meal_service_id, Menu.canonical_name, MealServiceMenu.menu_name_snapshot, Ingredient.stat_group)
        .join(MealServiceMenuIngredient, MealServiceMenuIngredient.meal_service_menu_id == MealServiceMenu.id)
        .join(Ingredient, Ingredient.id == MealServiceMenuIngredient.ingredient_id)
        .outerjoin(Menu, Menu.id == MealServiceMenu.menu_id)
        .where(MealServiceMenu.meal_service_id.in_(service_ids))
    )
    result: dict[tuple[int, str], set[str]] = defaultdict(set)
    for service_id, canonical, snapshot, group in db.execute(stmt):
        name = (canonical or "").strip() or (snapshot or "").strip()
        if group:
            result[(service_id, name)].add(group)
    return result
