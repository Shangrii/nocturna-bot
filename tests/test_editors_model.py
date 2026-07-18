"""Unit tests for the editors.json pydantic schema (Fase 10, plan 10-02).

Proves the closed block union, https-only URL validation (D-16), slug normalization
(Pitfall 5), and length caps (V5) BEFORE any FastAPI/OAuth/transport wiring exists
(10-05/10-08/10-09). Every model under test is pure pydantic — no Discord/network/DB/
filesystem dependency, matching the repo's ``core/store_sync.py`` precedent.
"""

import pytest
from pydantic import ValidationError

from core.editors_model import EditorPage, ThemeModel, normalize_slug


def _all_block_types_payload():
    """One instance of each of the 8 locked block types (UI-SPEC Block Inventory).

    Block copy is single-language now (D-13): each block carries one plain string."""
    return [
        {"type": "bio", "text": "Bio"},
        {"type": "heading", "text": "Heading"},
        {"type": "text", "text": "Paragraph"},
        {"type": "links", "items": [{"label": "Twitter", "url": "https://x.com/aria"}]},
        {
            "type": "portfolio",
            "auto": True,
            "extra": [{"image": "/editors/aria/w1.webp", "caption": ""}],
        },
        {"type": "quote", "text": "Quote", "attribution": "Cliente"},
        {"type": "image", "src": "/editors/aria/shot.webp", "alt": "shot"},
        {"type": "divider"},
    ]


def _base_theme(**overrides):
    """A full, valid Midnight-Nocturna theme payload (UI-SPEC Theme Token Contract)."""
    payload = {
        "bg": "#0a0c14",
        "overlay": 40,
        "blur": 0,
        "surface": "rgba(240,234,228,0.06)",
        "accent": "#c0192c",
        "text": "#f0eae4",
        "textMuted": "#9a9198",
        "font": "Inter",
        "btnStyle": "glass",
        "btnShape": "rounded",
        "effects": [],
    }
    payload.update(overrides)
    return payload


def _base_page(**overrides):
    payload = {
        "slug": "aria",
        "discordId": "123456789012345678",
        "published": True,
        "name": "Aria",
        "avatar": "/editors/aria/avatar.webp",
        "lang": "es",
        "tagline": "Editora de texturas",
        "badges": ["Outfits", "Textures"],
        "socials": [{"label": "Twitter", "url": "https://x.com/aria"}],
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
    blocks = [{"type": "portfolio", "auto": False, "extra": [{"image": bad_url, "caption": ""}]}]
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


# ── block copy is a single string (D-13); a legacy {es,en} dict is collapsed ───────
def test_block_text_plain_string_passes_through():
    page = EditorPage.model_validate(_base_page(blocks=[{"type": "bio", "text": "Hola"}]))
    assert page.blocks[0].text == "Hola"


def test_block_text_legacy_dict_collapses_prefers_es():
    """A save from a pre-migration admin app may still send {es,en}; it is collapsed
    (prefer es, then en) rather than rejected with a 422 during the deploy window."""
    page = EditorPage.model_validate(
        _base_page(blocks=[{"type": "bio", "text": {"es": "Hola", "en": "Hello"}}])
    )
    assert page.blocks[0].text == "Hola"


def test_block_text_legacy_dict_falls_back_to_en_when_es_empty():
    page = EditorPage.model_validate(
        _base_page(blocks=[{"type": "quote", "text": {"es": "", "en": "Hello"}}])
    )
    assert page.blocks[0].text == "Hello"


def test_portfolio_extra_caption_legacy_dict_collapses():
    blocks = [
        {
            "type": "portfolio",
            "auto": False,
            "extra": [{"image": "/editors/aria/w1.webp", "caption": {"es": "Pie", "en": "Cap"}}],
        }
    ]
    page = EditorPage.model_validate(_base_page(blocks=blocks))
    assert page.blocks[0].extra[0].caption == "Pie"


# ── string length caps enforced (V5) ──────────────────────────────────────────────
def test_string_length_cap_enforced_on_tagline():
    payload = _base_page(tagline="x" * 5000)
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
    blocks = [{"type": "bio", "text": "x" * 10000}]
    payload = _base_page(blocks=blocks)
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


# ── no raw HTML anywhere — every block text field is a plain str ──────────────────
def test_no_raw_html_field_block_text_is_plain_str():
    page = EditorPage.model_validate(_base_page())
    assert isinstance(page.blocks[0].text, str)  # bio
    assert isinstance(page.blocks[5].text, str)  # quote


def test_editor_page_rejects_unknown_top_level_field():
    """Closed schema: a stray top-level key (e.g. a client trying to smuggle extra state)
    is rejected rather than silently ignored."""
    payload = _base_page()
    payload["isAdmin"] = True
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


# ══════════════════════════════════════════════════════════════════════════════════
# ThemeModel — the theme-injection mitigation (10.1-09, T-10.1-09-01)
# ══════════════════════════════════════════════════════════════════════════════════


# ── a full Midnight-Nocturna theme parses ─────────────────────────────────────────
def test_theme_full_midnight_nocturna_parses():
    theme = ThemeModel.model_validate(_base_theme())
    assert theme.bg == "#0a0c14"
    assert theme.accent == "#c0192c"
    assert theme.font == "Inter"
    assert theme.btnStyle == "glass"
    assert theme.btnShape == "rounded"
    assert theme.overlay == 40
    assert theme.blur == 0
    assert theme.effects == []


# ── hex-color fields: non-hex values rejected ─────────────────────────────────────
@pytest.mark.parametrize("bad_accent", ["red", "#gggggg", "url(x)", "#12", "rgb(1,2)", "#fff;color:red"])
def test_theme_rejects_non_hex_accent(bad_accent):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(accent=bad_accent))


def test_theme_accepts_hex_short_and_alpha_forms():
    assert ThemeModel.model_validate(_base_theme(accent="#abc")).accent == "#abc"
    assert ThemeModel.model_validate(_base_theme(accent="#aabbccdd")).accent == "#aabbccdd"


# ── btnStyle / btnShape are closed enums ──────────────────────────────────────────
@pytest.mark.parametrize("bad_style", ["ghost", "solid", "", "GLASS"])
def test_theme_rejects_unknown_btn_style(bad_style):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(btnStyle=bad_style))


@pytest.mark.parametrize("bad_shape", ["round", "square", "", "PILL"])
def test_theme_rejects_unknown_btn_shape(bad_shape):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(btnShape=bad_shape))


# ── overlay 0..100, blur 0..20 numeric bounds ─────────────────────────────────────
@pytest.mark.parametrize("bad_overlay", [-1, 101, 1000])
def test_theme_rejects_overlay_out_of_range(bad_overlay):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(overlay=bad_overlay))


@pytest.mark.parametrize("bad_blur", [-1, 21, 100])
def test_theme_rejects_blur_out_of_range(bad_blur):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(blur=bad_blur))


def test_theme_accepts_overlay_and_blur_bounds():
    low = ThemeModel.model_validate(_base_theme(overlay=0, blur=0))
    assert low.overlay == 0 and low.blur == 0
    high = ThemeModel.model_validate(_base_theme(overlay=100, blur=20))
    assert high.overlay == 100 and high.blur == 20


# ── font constrained to the 14 curated families ──────────────────────────────────
def test_theme_rejects_unknown_font():
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(font="Comic Sans MS"))


@pytest.mark.parametrize(
    "font", ["Inter", "Space Grotesk", "UnifrakturMaguntia", "Press Start 2P", "Rajdhani"]
)
def test_theme_accepts_curated_fonts(font):
    assert ThemeModel.model_validate(_base_theme(font=font)).font == font


# ── effects: only Effects-Catalog keys allowed ───────────────────────────────────
def test_theme_rejects_unknown_effect_key():
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(effects=["glass", "explode"]))


def test_theme_accepts_known_effect_keys():
    theme = ThemeModel.model_validate(_base_theme(effects=["glass", "glow", "typewriter"]))
    assert "glow" in theme.effects


# ── bgMedia / audio pass the is_safe_image_ref scheme guard ───────────────────────
@pytest.mark.parametrize(
    "bad_ref", ["javascript:alert(1)", "data:text/html,x", "http://x.com/v.mp4", "../../secret.mp4"]
)
def test_theme_rejects_dangerous_bg_media(bad_ref):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(bgMedia=bad_ref))


@pytest.mark.parametrize("bad_ref", ["javascript:alert(1)", "data:audio/x,x", "http://x.com/a.mp3"])
def test_theme_rejects_dangerous_audio(bad_ref):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(audio=bad_ref))


def test_theme_accepts_relative_and_https_media():
    t1 = ThemeModel.model_validate(_base_theme(bgMedia="/editors/aria/bg.mp4"))
    assert t1.bgMedia == "/editors/aria/bg.mp4"
    t2 = ThemeModel.model_validate(_base_theme(audio="https://cdn.example.com/a.mp3"))
    assert t2.audio == "https://cdn.example.com/a.mp3"


# ── surface / tint accept hex OR a strict rgb()/rgba() form ───────────────────────
def test_theme_surface_accepts_rgba_and_tint_hex():
    t = ThemeModel.model_validate(_base_theme(surface="rgba(240,234,228,0.06)", tint="#112233"))
    assert t.surface.startswith("rgba(")
    assert t.tint == "#112233"


@pytest.mark.parametrize("bad_surface", ["url(x)", "rgba(1,2,3,4,5)", "expression(alert(1))", "red"])
def test_theme_rejects_dangerous_surface(bad_surface):
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(surface=bad_surface))


# ── ThemeModel is a closed schema ─────────────────────────────────────────────────
def test_theme_rejects_extra_field():
    with pytest.raises(ValidationError):
        ThemeModel.model_validate(_base_theme(evil="1"))


# ══════════════════════════════════════════════════════════════════════════════════
# EditorPage — lang / single-string tagline / badges / socials / theme (10.1-09)
# ══════════════════════════════════════════════════════════════════════════════════


# ── default theme = Midnight Nocturna when omitted (D-26 clean cutover) ───────────
def test_editor_page_defaults_theme_to_midnight_nocturna():
    payload = _base_page()
    payload.pop("theme", None)  # old entry carries no theme object
    page = EditorPage.model_validate(payload)
    assert page.theme.bg == "#0a0c14"
    assert page.theme.accent == "#c0192c"
    assert page.theme.font == "Inter"
    assert page.theme.btnStyle == "glass"
    assert page.theme.btnShape == "rounded"
    assert page.theme.overlay == 40


def test_editor_page_accepts_full_theme():
    page = EditorPage.model_validate(_base_page(theme=_base_theme(accent="#ff00aa", font="Orbitron")))
    assert page.theme.accent == "#ff00aa"
    assert page.theme.font == "Orbitron"


def test_editor_page_rejects_invalid_nested_theme():
    with pytest.raises(ValidationError):
        EditorPage.model_validate(_base_page(theme=_base_theme(accent="javascript:alert(1)")))


# ── lang single-language field (D-13) ─────────────────────────────────────────────
@pytest.mark.parametrize("lang", ["es", "en"])
def test_editor_page_accepts_valid_lang(lang):
    page = EditorPage.model_validate(_base_page(lang=lang))
    assert page.lang == lang


@pytest.mark.parametrize("bad_lang", ["fr", "EN", "", "es-ES"])
def test_editor_page_rejects_unknown_lang(bad_lang):
    with pytest.raises(ValidationError):
        EditorPage.model_validate(_base_page(lang=bad_lang))


def test_editor_page_requires_lang():
    payload = _base_page()
    payload.pop("lang")
    with pytest.raises(ValidationError):
        EditorPage.model_validate(payload)


# ── tagline is now a single string (D-13), not a {es,en} dict ─────────────────────
def test_editor_page_tagline_is_single_string():
    page = EditorPage.model_validate(_base_page(tagline="Editora de texturas"))
    assert page.tagline == "Editora de texturas"
    assert isinstance(page.tagline, str)


def test_editor_page_rejects_dict_tagline():
    with pytest.raises(ValidationError):
        EditorPage.model_validate(_base_page(tagline={"es": "x", "en": "y"}))


# ── badges from the curated team-defined set (D-07) ───────────────────────────────
def test_editor_page_accepts_known_badges():
    page = EditorPage.model_validate(_base_page(badges=["Outfits", "Textures", "Blender"]))
    assert "Outfits" in page.badges


def test_editor_page_rejects_unknown_badge():
    with pytest.raises(ValidationError):
        EditorPage.model_validate(_base_page(badges=["Outfits", "Hacking"]))


# ── socials are https-only LinkItems (D-09/D-16) ──────────────────────────────────
def test_editor_page_accepts_https_socials():
    page = EditorPage.model_validate(
        _base_page(socials=[{"label": "TikTok", "url": "https://tiktok.com/@a"}])
    )
    assert page.socials[0].url == "https://tiktok.com/@a"


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "http://x.com", "data:text/html,x"])
def test_editor_page_rejects_non_https_social(bad_url):
    with pytest.raises(ValidationError):
        EditorPage.model_validate(_base_page(socials=[{"label": "Bad", "url": bad_url}]))


# ── optional view count ───────────────────────────────────────────────────────────
def test_editor_page_accepts_optional_views():
    page = EditorPage.model_validate(_base_page(views=1234))
    assert page.views == 1234


def test_editor_page_defaults_views_to_none():
    page = EditorPage.model_validate(_base_page())
    assert page.views is None
