from __future__ import annotations

from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"


def test_new_template_action_resets_selected_template():
    source = APP_JS.read_text(encoding="utf-8")
    view = source.split("async function renderHwpxTemplatesView(root){", 1)[1].split(
        "async function renderHwpxTemplatePanel(){", 1
    )[0]

    assert 'id="new-hwpx-template"' in view
    assert "state.masterDataSelectionId=null;" in view
    assert "btn.classList.remove('active')" in view
    assert "renderHwpxTemplatePanel();" in view


def test_stale_template_detail_request_cannot_replace_new_form():
    source = APP_JS.read_text(encoding="utf-8")
    panel = source.split("async function renderHwpxTemplatePanel(){", 1)[1].split(
        "function renderHwpxTemplateForm(panel,data){", 1
    )[0]

    assert "const requestId=++state.hwpxTemplatePanelRequestId;" in panel
    assert "requestId!==state.hwpxTemplatePanelRequestId" in panel
    assert "id!==state.masterDataSelectionId" in panel


def test_document_type_is_selectable_only_for_new_templates():
    source = APP_JS.read_text(encoding="utf-8")
    form = source.split("function renderHwpxTemplateForm(panel,data){", 1)[1].split(
        "async function renderMealServiceDefaultsView(root){", 1
    )[0]

    assert '<select id="md-doc-type" ${isNew?\'\':\'disabled\'}>' in form
