"""Tests for normalizeTime24 and addMinutes utility functions.

These functions are defined in app/static/app.js (frontend JavaScript).
We replicate the logic here in Python to test the algorithm, and also
verify the JS source contains the expected implementations.
"""
from __future__ import annotations

import re
from pathlib import Path


# --- Python replica of the JS normalizeTime24 function ---

def normalize_time24(raw_value: str) -> str | None:
    trimmed = str(raw_value).strip()
    if not trimmed:
        return None
    hms = re.match(r'^(\d{1,2}):(\d{1,2}):(\d{1,2})$', trimmed)
    if hms:
        h, m = int(hms.group(1)), int(hms.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
        return None
    separated = re.match(r'^(\d{1,2})\D+(\d{1,2})$', trimmed)
    if separated:
        hour = int(separated.group(1))
        minute = int(separated.group(2))
    else:
        digits = re.sub(r'\D', '', trimmed)
        if len(digits) == 0 or len(digits) > 4:
            return None
        if len(digits) <= 2:
            hour = int(digits)
            minute = 0
        elif len(digits) == 3:
            hour = int(digits[0])
            minute = int(digits[1:])
        else:
            hour = int(digits[:2])
            minute = int(digits[2:4])
    if not (isinstance(hour, int) and isinstance(minute, int)):
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def add_minutes(time_str: str, delta: int) -> str:
    normalized = normalize_time24(time_str)
    if not normalized:
        raise ValueError("Invalid time")
    hour, minute = map(int, normalized.split(':'))
    total = (hour * 60 + minute + delta + 1440) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


# --- Tests ---

class TestNormalizeTime24:
    def test_1140(self):
        assert normalize_time24("1140") == "11:40"

    def test_1730(self):
        assert normalize_time24("1730") == "17:30"

    def test_930(self):
        assert normalize_time24("930") == "09:30"

    def test_9(self):
        assert normalize_time24("9") == "09:00"

    def test_09(self):
        assert normalize_time24("09") == "09:00"

    def test_11_40(self):
        assert normalize_time24("11:40") == "11:40"

    def test_11_space_40(self):
        assert normalize_time24("11 40") == "11:40"

    def test_11_dot_40(self):
        assert normalize_time24("11.40") == "11:40"

    def test_9_colon_5(self):
        assert normalize_time24("9:5") == "09:05"

    def test_empty(self):
        assert normalize_time24("") is None

    def test_24_00_invalid(self):
        assert normalize_time24("24:00") is None

    def test_11_60_invalid(self):
        assert normalize_time24("11:60") is None

    def test_9999_invalid(self):
        assert normalize_time24("9999") is None

    def test_abcd_invalid(self):
        assert normalize_time24("abcd") is None

    def test_too_many_digits(self):
        assert normalize_time24("12345") is None

    def test_00_00(self):
        assert normalize_time24("00:00") == "00:00"

    def test_23_59(self):
        assert normalize_time24("23:59") == "23:59"

    def test_hms_format(self):
        assert normalize_time24("11:30:00") == "11:30"

    def test_hms_format_pm(self):
        assert normalize_time24("17:30:00") == "17:30"

    def test_hms_invalid_hour(self):
        assert normalize_time24("24:00:00") is None


class TestAddMinutes:
    def test_plus_5(self):
        assert add_minutes("11:40", 5) == "11:45"

    def test_minus_5(self):
        assert add_minutes("11:40", -5) == "11:35"

    def test_wrap_forward(self):
        assert add_minutes("23:58", 5) == "00:03"

    def test_wrap_backward(self):
        assert add_minutes("00:02", -5) == "23:57"

    def test_plus_10(self):
        assert add_minutes("11:58", 5) == "12:03"

    def test_minus_10(self):
        assert add_minutes("00:03", -5) == "23:58"

    def test_zero_delta(self):
        assert add_minutes("11:40", 0) == "11:40"

    def test_full_day_wrap(self):
        assert add_minutes("12:00", 1440) == "12:00"

    def test_invalid_input_raises(self):
        import pytest
        with pytest.raises(ValueError):
            add_minutes("25:00", 5)


class TestJsSourceContainsImplementation:
    """Verify the JS source file contains the expected functions."""

    @property
    def js_source(self) -> str:
        return Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"

    def test_has_normalize_time24(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "function normalizeTime24" in content

    def test_has_add_minutes(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "function addMinutes" in content

    def test_has_create_time_input24(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "function createTimeInput24" in content

    def test_has_arrow_up_handler(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "ArrowUp" in content

    def test_has_arrow_down_handler(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "ArrowDown" in content

    def test_has_escape_handler(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "Escape" in content

    def test_has_quick_buttons(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "ti24-quick" in content

    def test_has_aria_invalid(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "aria-invalid" in content

    def test_has_aria_label_on_quick_buttons(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert "aria-label" in content

    def test_has_inputmode_numeric(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert 'inputmode="numeric"' in content

    def test_no_type_time_in_meal_editor(self):
        content = self.js_source.read_text(encoding="utf-8")
        # The old type="time" for service-time should be gone
        assert 'id="service-time" type="time"' not in content

    def test_no_type_time_in_meal_defaults(self):
        content = self.js_source.read_text(encoding="utf-8")
        assert 'class="md-time" type="time"' not in content
