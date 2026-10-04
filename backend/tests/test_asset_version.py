from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_templates_load_static_assets_with_version_query():
    app_html = (APP / "templates" / "app.html").read_text(encoding="utf-8")
    login_html = (APP / "templates" / "login.html").read_text(encoding="utf-8")
    assert '/static/app.js?v={{ asset_version }}' in app_html
    assert '/static/app.css?v={{ asset_version }}' in app_html
    assert '/static/app.css?v={{ asset_version }}' in login_html


def test_main_passes_asset_version_and_no_cache_to_pages():
    source = (APP / "main.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert source.count('"asset_version": ASSET_VERSION') == 2
    assert source.count("headers=NO_CACHE_HEADERS") == 2
    assert 'NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}' in source
