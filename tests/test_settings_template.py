"""Render smoke test for app/templates/settings.html (Fase 02, plan 02-03).

Renders the template through the app's real Jinja2 environment with a payload
built from a real ``settings.all_for_ui()`` call over a tmp DB (mirrors
``tests/test_settings.py``'s ``_use_tmp_db`` isolation) and asserts:

- the 7 typed controls / single-quoted Alpine hydrate / per-field error surface
  markup are all present in the static (pre-hydrate) HTML source, and
- no secret/structural value ever appears in the rendered output (T-02-06).

This is a template-shape test only — no route, no auth, no POST. The route
wiring (``GET``/``POST /admin/settings``) belongs to plan 02-04.
"""

import config
import core.db as db
import core.settings as settings
from app.main import templates


def _use_tmp_db(monkeypatch, tmp_path, name="settings.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


def _render(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    groups = settings.all_for_ui()
    template = templates.env.get_template("settings.html")
    return template.render(groups=groups, asset_v=0)


def test_settings_html_hydrates_via_single_quoted_x_data(monkeypatch, tmp_path):
    html = _render(monkeypatch, tmp_path)
    assert "x-data='settingsApp(" in html


def test_settings_html_save_posts_json_to_admin_settings(monkeypatch, tmp_path):
    html = _render(monkeypatch, tmp_path)
    assert "fetch('/admin/settings'" in html
    assert "Content-Type" in html
    assert "application/json" in html


def test_settings_html_renders_timezone_select_and_int_range_number(monkeypatch, tmp_path):
    html = _render(monkeypatch, tmp_path)
    assert "<select" in html
    assert 'type="number"' in html
    assert 'min="' in html
    assert 'max="' in html


def test_settings_html_has_inline_error_surface(monkeypatch, tmp_path):
    html = _render(monkeypatch, tmp_path)
    assert 'class="field-error"' in html
    assert "field--invalid" in html


def test_settings_html_loads_vendored_alpine_defer_no_sortable(monkeypatch, tmp_path):
    html = _render(monkeypatch, tmp_path)
    assert '<script defer src="/static/alpine.min.js"></script>' in html
    assert "Sortable" not in html


def test_settings_html_never_leaks_secrets(monkeypatch, tmp_path):
    html = _render(monkeypatch, tmp_path)
    for secret in ("BOT_TOKEN", "GITHUB_PAT", "JINXXY_API_KEY", "SESSION_SECRET", "DB_PATH"):
        assert secret not in html
