"""Unit tests for the editors.json pydantic schema (Fase 10, plan 10-02).

Proves the closed block union, https-only URL validation (D-16), slug normalization
(Pitfall 5), and length caps (V5) BEFORE any FastAPI/OAuth/transport wiring exists
(10-05/10-08/10-09). Every model under test is pure pydantic — no Discord/network/DB/
filesystem dependency, matching the repo's ``core/store_sync.py`` precedent.
"""

import pytest
from pydantic import ValidationError

from core.editors_model import EditorPage, Locale, normalize_slug


def _all_block_types_payload():
    """One instance of each of the 8 locked block types (UI-SPEC Block Inventory)."""
    return [
        {"type": "bio", "text": {"es": "Bio es", "en": "Bio en"}},
        {"type": "heading", "text": {"es": "Titulo", "en": "Heading"}},
        {"type": "text", "text": {"es": "Parrafo", "en": "Paragraph"}},
        {"type": "links", "items": [{"label": "Twitter", "url": "https://x.com/aria"}]},
        {
            "type": "portfolio",
            "auto": True,
            "extra": [{"image": "/editors/aria/w1.webp", "caption": {"es": "", "en": ""}}],
        },
        {"type": "quote", "text": {"es": "Cita", "en": "Quote"}, "attribution": "Cliente"},
        {"type": "image", "src": "/editors/aria/shot.webp", "alt": "shot"},
        {"type": "divider"},
    ]


def _base_page(**overrides):
    payload = {
        "slug": "aria",
        "discordId": "123456789012345678",
        "published": True,
        "name": "Aria",
        "avatar": "/editors/aria/avatar.webp",
        "tagline": {"es": "Editora", "en": "Editor"},
        "links": [{"label": "Twitter", "url": "https://x.com/aria"}],
        "blocks": _all_block_types_payload(),
    }
    payload.update(overrides)
    return payload


# ── a valid EditorPage with all 8 block types parses ─────────────────────────────
def test_valid_editor_page_all_block_types_parses():
    page = EditorPage.model_validate(_base_page())
    assert len(page.blocks) == 8
    assert page.blocks[0].type == "bio"
    assert page.blocks[-1].type == "divider"
    assert page.slug == "aria"
    assert page.discordId == "123456789012345678"


# ── an unknown block `type` is rejected (closed union) ────────────────────────────
def test_unknown_block_type_rejected():
    payload = _base_page(blocks=[{"type": "carousel", "items": []}])
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


# ── link/portfolio-extra/image URLs: non-https / dangerous schemes rejected (D-16) ─
@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "http://x.com", "data:text/html,x"])
def test_link_url_rejects_non_https(bad_url):
    payload = _base_page(links=[{"label": "Bad", "url": bad_url}])
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "http://x.com", "data:text/html,x"])
def test_links_block_item_url_rejects_non_https(bad_url):
    blocks = [{"type": "links", "items": [{"label": "Bad", "url": bad_url}]}]
    payload = _base_page(blocks=blocks)
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "http://x.com", "data:text/html,x"])
def test_portfolio_extra_image_rejects_dangerous_scheme(bad_url):
    blocks = [{"type": "portfolio", "auto": False, "extra": [{"image": bad_url, "caption": {}}]}]
    payload = _base_page(blocks=blocks)
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "http://x.com", "data:text/html,x"])
def test_image_block_src_rejects_dangerous_scheme(bad_url):
    blocks = [{"type": "image", "src": bad_url, "alt": "x"}]
    payload = _base_page(blocks=blocks)
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


def test_image_block_src_allows_relative_path():
    """Avatar/image/portfolio-extra fields are normally site-relative paths (10-01 schema),
    never user-typed URLs — the guard must not reject the legitimate stored form."""
    blocks = [{"type": "image", "src": "/editors/aria/ok.webp", "alt": "x"}]
    page = EditorPage.model_validate(_base_page(blocks=blocks))
    assert page.blocks[0].src == "/editors/aria/ok.webp"


def test_avatar_allows_relative_path_and_empty_string():
    page = EditorPage.model_validate(_base_page(avatar="/editors/aria/avatar.webp"))
    assert page.avatar == "/editors/aria/avatar.webp"
    page2 = EditorPage.model_validate(_base_page(avatar=""))
    assert page2.avatar == ""


def test_image_field_rejects_path_traversal():
    """Defense-in-depth (Rule 2): a relative image path must not carry `../` either."""
    blocks = [{"type": "image", "src": "../../etc/passwd", "alt": "x"}]
    payload = _base_page(blocks=blocks)
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


# ── normalize_slug ─────────────────────────────────────────────────────────────────
def test_normalize_slug_basic():
    assert normalize_slug("Aria X!") == "aria-x"


def test_normalize_slug_strips_traversal_chars_to_charset():
    result = normalize_slug("../etc")
    assert result == "etc"
    assert __import__("re").fullmatch(r"[a-z0-9-]+", result)


def test_normalize_slug_pure_traversal_raises():
    with pytest.raises(ValueError):
        normalize_slug("../..")


def test_normalize_slug_all_punctuation_raises():
    with pytest.raises(ValueError):
        normalize_slug("!!!")


def test_normalize_slug_empty_string_raises():
    with pytest.raises(ValueError):
        normalize_slug("")


# ── block text field is a {es,en} dict; missing locale defaults to "" not None ────
def test_locale_missing_key_defaults_to_empty_string_not_none():
    loc = Locale.model_validate({"es": "hola"})
    assert loc.es == "hola"
    assert loc.en == ""
    assert loc.en is not None


def test_locale_both_keys_present():
    loc = Locale.model_validate({"es": "hola", "en": "hello"})
    assert loc.es == "hola"
    assert loc.en == "hello"


# ── string length caps enforced (V5) ──────────────────────────────────────────────
def test_string_length_cap_enforced_on_tagline():
    payload = _base_page(tagline={"es": "x" * 5000, "en": ""})
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


def test_string_length_cap_enforced_on_name():
    payload = _base_page(name="x" * 500)
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


def test_string_length_cap_enforced_on_link_label():
    payload = _base_page(links=[{"label": "x" * 500, "url": "https://x.com"}])
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


def test_string_length_cap_enforced_on_block_text():
    blocks = [{"type": "bio", "text": {"es": "x" * 10000, "en": ""}}]
    payload = _base_page(blocks=blocks)
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


# ── no raw HTML anywhere — every text field is a plain str ───────────────────────
def test_no_raw_html_field_all_locale_fields_are_plain_str():
    assert Locale.model_fields["es"].annotation is str
    assert Locale.model_fields["en"].annotation is str


def test_editor_page_rejects_unknown_top_level_field():
    """Closed schema: a stray top-level key (e.g. a client trying to smuggle extra state)
    is rejected rather than silently ignored."""
    payload = _base_page()
    payload["isAdmin"] = True
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)
