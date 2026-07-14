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


class EditorPage(BaseModel):
    """The canonical ``editors.json`` array entry (D-18), mirroring 10-01's ``<interfaces>``
    schema verbatim. ``discordId`` is the TRUE 1:1 key (D-08) — callers must resolve the
    editable entry from the server session, never from a request body (Pitfall 1); this
    model only validates shape, it does not enforce ownership."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(max_length=_SLUG_MAX)
    discordId: str
    published: bool = False
    name: str = Field(max_length=_NAME_MAX)
    avatar: str = Field(default="", max_length=_PATH_MAX)
    tagline: Locale = Field(default_factory=Locale)
    links: list[LinkItem] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)

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
