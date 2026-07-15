"""Pydantic schema + validation for editor profile pages (Fase 10, plan 10-02).

Mirrors the canonical ``editors.json`` entry shape locked in 10-01's ``<interfaces>``
block: a CLOSED union of block models keyed on ``type`` (no raw-HTML field exists
anywhere — D-02 safety), an https-only URL guard on every link field (D-16, V5), a
site-relative-path-or-https guard on image-like fields (avatar/image/portfolio-extra —
these are normally paths the admin app writes after a Pillow re-encode, never a
user-typed URL, but a crafted payload must still never smuggle a dangerous scheme into
an ``<img src>``), and a slug normalizer that restricts the charset to ``[a-z0-9-]``
before it can ever enter a filesystem/commit path (Pitfall 5).

This is the server-side validation gate every save in 10-09 passes through before any
commit. Pure module: no Discord/network/DB/filesystem import, matching the
``core/store_sync.py`` precedent (import-safe, stdlib + pydantic only).
"""

import re
from typing import Annotated, Literal, Union
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── length caps (V5 — reject an oversized payload before it can reach a commit) ────
_SLUG_MAX = 64
_NAME_MAX = 100
_LABEL_MAX = 100
_TEXT_MAX = 4000
_ATTRIBUTION_MAX = 200
_ALT_MAX = 300
_PATH_MAX = 500
_URL_MAX = 2048
_TAGLINE_MAX = 300
_COLOR_MAX = 64
_FONT_MAX = 64


# ── theme allowlists (10.1-09 — the theme-injection mitigation, T-10.1-09-01) ──────
# The 14 curated font families (UI-SPEC Curated Font Palette, D-03). Only the editor's
# chosen family loads on their page; a value outside this set is rejected outright so a
# crafted `--theme-font` value can never smuggle an arbitrary string into a `@font-face`
# or CSS `font-family` declaration downstream.
CURATED_FONTS = frozenset(
    {
        "Inter",
        "Space Grotesk",
        "Sora",
        "Playfair Display",
        "Fraunces",
        "Bebas Neue",
        "UnifrakturMaguntia",
        "Pirata One",
        "Caveat",
        "Permanent Marker",
        "Press Start 2P",
        "VT323",
        "Orbitron",
        "Rajdhani",
    }
)

# The opt-in per-editor effect keys (UI-SPEC Effects Catalog, D-04). Each maps to a
# reduced-motion-safe front-end effect; an unknown key is rejected so `theme.effects`
# can only ever carry a value the render layer (plan 06's effects.ts) knows how to gate.
KNOWN_EFFECTS = frozenset(
    {
        "glass",       # glassmorphism cards
        "glow",        # avatar glow / ring
        "hover",       # link-button hover animation
        "gradient",    # animated username gradient
        "typewriter",  # typewriter tagline
        "tilt",        # tilt-on-hover
        "particles",   # particle / snow overlay
        "presence",    # live Discord presence (Lanyard)
        "audio",       # background audio
    }
)

# The curated, team-defined specialty badge keys (UI-SPEC SpecialtyBadges, D-07).
# Editors pick FROM this set — no free-form text — so a badge value can never carry
# arbitrary markup; the front-end maps each key to a localized label + glyph.
SPECIALTY_BADGES = frozenset(
    {
        "Outfits",
        "Accessories",
        "Dances",
        "Textures",
        "Blender",
        "Modeling3D",
    }
)

# A hex color: #rgb, #rrggbb, or #rrggbbaa (case-insensitive). ``fullmatch`` (no anchors)
# is used so an embedded newline/`;` — e.g. ``#fff;color:red`` — can never slip through.
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")

# A strict, numeric-only rgb()/rgba() form for the glass surface + optional media tint.
# Channels are 1–3 digits, alpha is 0 | 1 | 0?.d+ — no way to break out of a CSS value.
_RGB_COLOR_RE = re.compile(
    r"rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)"
)


def _is_hex_color(value: str) -> bool:
    """True iff ``value`` is a strict hex color (#rgb / #rrggbb / #rrggbbaa)."""
    return bool(_HEX_COLOR_RE.fullmatch(str(value)))


def _is_color_or_alpha(value: str) -> bool:
    """True iff ``value`` is a hex color OR a strict rgb()/rgba() value.

    Used for the surface (glass alpha fill) and optional media tint, which legitimately
    need an alpha channel; both regexes are numeric-only so no CSS breakout is possible.
    """
    s = str(value)
    return bool(_HEX_COLOR_RE.fullmatch(s) or _RGB_COLOR_RE.fullmatch(s))


def is_https_url(url: str) -> bool:
    """True iff ``url`` parses with an ``https`` scheme and a network location (D-16/V5).

    Mirrors ``core/store_sync.py::is_https_url`` — rejects ``http://``, ``javascript:``,
    ``data:``, ``vbscript:`` and any malformed/relative input. No domain allowlist: D-16
    says editors may link to any ``https://`` URL.
    """
    try:
        parts = urlparse(str(url))
    except (ValueError, TypeError):
        return False
    return parts.scheme == "https" and bool(parts.netloc)


def is_safe_image_ref(value: str) -> bool:
    """True iff ``value`` is a safe image reference for an ``avatar``/``src``/``image`` field.

    Per 10-01's locked schema these fields are normally SITE-RELATIVE paths (e.g.
    ``/editors/aria/avatar.webp``) committed by the admin app after a Pillow re-encode —
    never a user-typed absolute URL. This guard allows an empty string (unset) or any
    scheme-less relative path with no ``..`` traversal segment, and separately allows an
    ``https://`` URL; it rejects any other explicit scheme (``javascript:``, ``data:``,
    ``vbscript:``, ``http:``, …) so a crafted payload can never smuggle a dangerous URI
    into an image field (defense-in-depth alongside D-16's stricter https-only guard on
    actual link URLs).
    """
    if value == "":
        return True
    try:
        parts = urlparse(str(value))
    except (ValueError, TypeError):
        return False
    if parts.scheme == "":
        return ".." not in value
    return parts.scheme == "https" and bool(parts.netloc)


def normalize_slug(raw: str) -> str:
    """Normalize ``raw`` to a URL-safe slug: lowercase, ``[a-z0-9-]`` only, no traversal.

    Lowercases, replaces every run of non-``[a-z0-9]`` characters with a single ``-``,
    strips leading/trailing ``-``, and raises ``ValueError`` if the result is empty
    (Pitfall 5 — a slug must never carry ``../`` or any other traversal-capable
    character into a filesystem/commit path; a purely-punctuation input like ``"../.."``
    or ``"!!!"`` collapses to nothing and is rejected outright).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(raw).strip().lower()).strip("-")
    if not slug:
        raise ValueError("slug normalizes to an empty string")
    return slug


class Locale(BaseModel):
    """A bilingual ``{es, en}`` string pair. A missing locale defaults to ``""`` (not
    ``None``) — matches the site's render-as-written convention (gallery captions /
    reviews are shown verbatim, empty locale renders as nothing rather than crashing)."""

    model_config = ConfigDict(extra="forbid")

    es: str = Field(default="", max_length=_TEXT_MAX)
    en: str = Field(default="", max_length=_TEXT_MAX)


class LinkItem(BaseModel):
    """A custom ``(label, url)`` link — top-level ``links[]`` and the ``links`` block's
    ``items[]`` both use this shape. ``url`` must be ``https://`` only (D-16)."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=_LABEL_MAX)
    url: str = Field(max_length=_URL_MAX)

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        if not is_https_url(v):
            raise ValueError("url must be an https:// URL (D-16)")
        return v


class PortfolioExtraItem(BaseModel):
    """A hand-added portfolio item (alongside the auto-pulled credited work, D-03)."""

    model_config = ConfigDict(extra="forbid")

    image: str = Field(max_length=_PATH_MAX)
    caption: Locale = Field(default_factory=Locale)

    @field_validator("image")
    @classmethod
    def _safe_image(cls, v: str) -> str:
        if not is_safe_image_ref(v):
            raise ValueError("image must be a site-relative path or an https:// URL")
        return v


# ── the closed block union (D-02) — UI-SPEC Block Inventory, exactly 8 types ──────
class BioBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["bio"]
    text: Locale


class HeadingBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["heading"]
    text: Locale


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"]
    text: Locale


class LinksBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["links"]
    items: list[LinkItem] = Field(default_factory=list)


class PortfolioBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["portfolio"]
    auto: bool = True
    extra: list[PortfolioExtraItem] = Field(default_factory=list)


class QuoteBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["quote"]
    text: Locale
    attribution: str | None = Field(default=None, max_length=_ATTRIBUTION_MAX)


class ImageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image"]
    src: str = Field(max_length=_PATH_MAX)
    alt: str = Field(default="", max_length=_ALT_MAX)

    @field_validator("src")
    @classmethod
    def _safe_src(cls, v: str) -> str:
        if not is_safe_image_ref(v):
            raise ValueError("src must be a site-relative path or an https:// URL")
        return v


class DividerBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["divider"]


Block = Annotated[
    Union[
        BioBlock,
        HeadingBlock,
        TextBlock,
        LinksBlock,
        PortfolioBlock,
        QuoteBlock,
        ImageBlock,
        DividerBlock,
    ],
    Field(discriminator="type"),
]


class ThemeModel(BaseModel):
    """The per-editor theme (UI-SPEC Theme Token Contract, D-01/D-02) — this is the
    LOAD-BEARING theme-injection gate (T-10.1-09-01). Every field is constrained so an
    editor-controlled theme value can never smuggle a dangerous string into the CSS custom
    properties or ``<img/video/audio src>`` the website emits (plans 02/06):

    - color fields are strict hex (or numeric rgb()/rgba() for the alpha surface/tint),
    - ``btnStyle``/``btnShape`` are closed enums,
    - ``overlay``/``blur`` are integers clamped to their legibility ranges,
    - ``font`` must be one of the 14 curated families,
    - ``effects`` may only contain known Effects-Catalog keys,
    - ``bgMedia``/``audio`` pass the existing ``is_safe_image_ref`` scheme guard.

    Defaults are the "Midnight Nocturna" preset (D-26) so an old ``editors.json`` entry
    with no ``theme`` object still validates and renders instantly on cutover.
    """

    model_config = ConfigDict(extra="forbid")

    bg: str = Field(default="#0a0c14", max_length=_COLOR_MAX)
    bgMedia: str | None = Field(default=None, max_length=_PATH_MAX)
    overlay: int = Field(default=40, ge=0, le=100)
    blur: int = Field(default=0, ge=0, le=20)
    tint: str | None = Field(default=None, max_length=_COLOR_MAX)
    surface: str = Field(default="rgba(240,234,228,0.06)", max_length=_COLOR_MAX)
    accent: str = Field(default="#c0192c", max_length=_COLOR_MAX)
    text: str = Field(default="#f0eae4", max_length=_COLOR_MAX)
    textMuted: str = Field(default="#9a9198", max_length=_COLOR_MAX)
    font: str = Field(default="Inter", max_length=_FONT_MAX)
    btnStyle: Literal["filled", "outline", "glass"] = "glass"
    btnShape: Literal["sharp", "rounded", "pill"] = "rounded"
    effects: list[str] = Field(default_factory=list)
    audio: str | None = Field(default=None, max_length=_PATH_MAX)
    preset: str | None = Field(default=None, max_length=_FONT_MAX)

    @field_validator("bg", "accent", "text", "textMuted")
    @classmethod
    def _hex_only(cls, v: str) -> str:
        if not _is_hex_color(v):
            raise ValueError("color must be a hex value (#rgb / #rrggbb / #rrggbbaa)")
        return v

    @field_validator("surface", "tint")
    @classmethod
    def _color_or_alpha(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _is_color_or_alpha(v):
            raise ValueError("must be a hex color or a strict rgb()/rgba() value")
        return v

    @field_validator("font")
    @classmethod
    def _font_curated(cls, v: str) -> str:
        if v not in CURATED_FONTS:
            raise ValueError("font must be one of the 14 curated families (D-03)")
        return v

    @field_validator("effects")
    @classmethod
    def _effects_known(cls, v: list[str]) -> list[str]:
        for effect in v:
            if effect not in KNOWN_EFFECTS:
                raise ValueError(f"unknown effect key: {effect!r}")
        return v

    @field_validator("bgMedia", "audio")
    @classmethod
    def _safe_media(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not is_safe_image_ref(v):
            raise ValueError("media ref must be a site-relative path or an https:// URL")
        return v


class EditorPage(BaseModel):
    """The canonical ``editors.json`` array entry (D-18), mirroring 10-01's ``<interfaces>``
    schema verbatim. ``discordId`` is the TRUE 1:1 key (D-08) — callers must resolve the
    editable entry from the server session, never from a request body (Pitfall 1); this
    model only validates shape, it does not enforce ownership.

    Extended in 10.1-09: single-language ``lang``/``tagline`` (D-13), curated ``badges``
    (D-07), https-only ``socials`` (D-09), a per-editor ``theme`` (defaults to Midnight
    Nocturna so an old entry still validates, D-26), and an optional ``views`` count."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(max_length=_SLUG_MAX)
    discordId: str
    published: bool = False
    name: str = Field(max_length=_NAME_MAX)
    avatar: str = Field(default="", max_length=_PATH_MAX)
    lang: Literal["es", "en"]
    tagline: str = Field(default="", max_length=_TEXT_MAX)
    badges: list[str] = Field(default_factory=list)
    socials: list[LinkItem] = Field(default_factory=list)
    links: list[LinkItem] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    theme: ThemeModel = Field(default_factory=ThemeModel)
    views: int | None = Field(default=None, ge=0)

    @field_validator("slug")
    @classmethod
    def _slug_charset(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", v):
            raise ValueError("slug must match [a-z0-9-]+ (run normalize_slug first)")
        return v

    @field_validator("avatar")
    @classmethod
    def _safe_avatar(cls, v: str) -> str:
        if not is_safe_image_ref(v):
            raise ValueError("avatar must be a site-relative path or an https:// URL")
        return v

    @field_validator("badges")
    @classmethod
    def _badges_curated(cls, v: list[str]) -> list[str]:
        for badge in v:
            if badge not in SPECIALTY_BADGES:
                raise ValueError(f"unknown specialty badge: {badge!r} (D-07 curated set)")
        return v
