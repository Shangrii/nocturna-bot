"""Validated, sqlite-backed config store for the owner settings panel (Fase 01, plan 01-02).

Single source of truth for what is TUNABLE at runtime (STORE-01) and the load-bearing
validation gate every write passes through (STORE-03). Behavior-preserving: every default is
sourced from the EXACT ``.env`` literal ``config.py`` uses today, so seeding is byte-identical
until an owner edits a value.

Pure module — stdlib (``json``, ``re``, ``os``, ``zoneinfo``, ``logging``) plus ``core.db`` and a
read-only import of ``config`` for the ``.env``-sourced default seeds. No discord.py / FastAPI
imports (mirrors ``core/store_sync.py`` / ``core/editors_model.py``).

Public panel-facing API is exactly ``get`` / ``set`` / ``all_for_ui``. ``seed_defaults`` is a
startup-only helper (called once from ``bot.py::main()`` in 01-03), not part of that contract.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core import db

log = logging.getLogger(__name__)


# ── typed rejection (mirrors core/editors_model.py::SlugRejected) ─────────────────
class SettingRejected(ValueError):
    """Raised by ``set()`` when a key is unknown or a value fails its validator.

    ``reason`` is a human-readable string so the (Phase 2) HTTP layer can surface it
    without string-matching the message. Nothing is written when this is raised (STORE-03).
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# ── validators — each returns the coerced value or raises SettingRejected (STORE-03) ──
_SNOWFLAKE_RE = re.compile(r"\d{17,20}")


def _validate_channel_id(value) -> int:
    """A single Discord snowflake (channel/forum ID): 17–20 digits → int."""
    s = str(value).strip()
    if not _SNOWFLAKE_RE.fullmatch(s):
        raise SettingRejected("must be a Discord snowflake ID (17-20 digits)")
    return int(s)


def _validate_channel_id_or_zero(value) -> int:
    """A snowflake OR the unset ``0`` sentinel (FORUM/ENCODING default to "0").

    Preserves current behavior: these two are validated as ints, never rejected when 0.
    Accepts any non-negative integer string (the ``0`` sentinel plus real snowflakes).
    """
    s = str(value).strip()
    if not s.isdigit():
        raise SettingRejected("must be a non-negative integer (0 = unset) or a snowflake ID")
    return int(s)


def _validate_role_id_list(value) -> list[int]:
    """A list of role IDs, or a comma-separated string of them → list[int].

    Mirrors config.py's ``[int(x) for x in getenv(...).split(",") if x.strip()]`` parse:
    each non-empty item must be a positive integer (a Discord role snowflake in production).
    Empty items are ignored. Kept intentionally lenient on ID length — Discord snowflakes are
    17-20 digits, but the validator's job is to guarantee ``list[int]``, not to police ID width
    (a role that Discord invents outside that range must still round-trip).
    """
    items = value if isinstance(value, list) else str(value).split(",")
    out: list[int] = []
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        if not s.isdigit():
            raise SettingRejected(f"invalid role ID in list: {item!r}")
        out.append(int(s))
    return out


def _make_int_range(low: int, high: int) -> Callable[[object], int]:
    """Build an int validator that coerces to int and rejects outside [low, high]."""

    def _validate(value) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise SettingRejected(f"must be an integer between {low} and {high}")
        if n < low or n > high:
            raise SettingRejected(f"must be between {low} and {high} (got {n})")
        return n

    return _validate


def _validate_timezone(value) -> str:
    """A valid IANA timezone name (same exception tuple as bot.py:130)."""
    s = str(value)
    try:
        ZoneInfo(s)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        raise SettingRejected(f"not a valid IANA timezone: {value!r}")
    return s


def _validate_free_string(value) -> str:
    """Any non-empty string. Model names are free strings, NOT an enum (Pitfall 4)."""
    s = str(value)
    if not s.strip():
        raise SettingRejected("must be a non-empty string")
    return s


def _validate_url(value) -> str:
    """A non-empty http:// or https:// URL."""
    s = str(value).strip()
    if not (s.startswith("http://") or s.startswith("https://")):
        raise SettingRejected("must be an http:// or https:// URL")
    return s


def _validate_lang(value) -> str:
    """A lowercase 2-letter language code (keeps "es"/"en" valid, no closed enum)."""
    s = str(value).strip().lower()
    if not re.fullmatch(r"[a-z]{2}", s):
        raise SettingRejected("must be a lowercase 2-letter language code (e.g. 'es', 'en')")
    return s


# ── .env-sourced default seeds (byte-identical to config.py's current literals) ───
def _env_role_ids(name: str) -> list[int]:
    """Same parse config.py uses for a comma-separated role-id env var → list[int]."""
    return [int(x) for x in os.getenv(name, "").split(",") if x.strip()]


# ── schema descriptor ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Setting:
    key: str
    group: str          # owning feature (grouping for the panel)
    type_tag: str       # snowflake | role_list | int_range | timezone | free_string | url | lang
    default: object     # the .env/default seed value (already coerced)
    validate: Callable[[object], object]
    fallback_key: str | None = None   # empty-list → resolve this key instead (CONF-03)
    hint: str = ""      # optional rendering hint for the panel


# ── the 19 safe tunables, grouped exactly as CONTEXT.md's "Safe tunables in scope" ──
_SCHEMA: dict[str, _Setting] = {
    # ── Galería ──
    "PHOTO_CHANNEL_ID": _Setting(
        "PHOTO_CHANNEL_ID", "gallery", "snowflake",
        int(os.getenv("PHOTO_CHANNEL_ID", "1416329356426481717")),
        _validate_channel_id,
    ),
    "GALLERY_STAFF_ROLE_IDS": _Setting(
        "GALLERY_STAFF_ROLE_IDS", "gallery", "role_list",
        _env_role_ids("GALLERY_STAFF_ROLE_IDS"),
        _validate_role_id_list,
    ),
    # ── Reseñas ──
    "REVIEWS_CHANNEL_ID": _Setting(
        "REVIEWS_CHANNEL_ID", "reviews", "snowflake",
        int(os.getenv("REVIEWS_CHANNEL_ID", "1453534905706221600")),
        _validate_channel_id,
    ),
    "REVIEWS_STAFF_ROLE_IDS": _Setting(
        "REVIEWS_STAFF_ROLE_IDS", "reviews", "role_list",
        _env_role_ids("REVIEWS_STAFF_ROLE_IDS"),
        _validate_role_id_list,
        fallback_key="GALLERY_STAFF_ROLE_IDS",
    ),
    # ── Recordatorios ──
    "REMINDERS_TZ": _Setting(
        "REMINDERS_TZ", "reminders", "timezone",
        os.getenv("REMINDERS_TZ", "America/Mexico_City"),
        _validate_timezone,
    ),
    "REMINDERS_STAFF_ROLE_IDS": _Setting(
        "REMINDERS_STAFF_ROLE_IDS", "reminders", "role_list",
        _env_role_ids("REMINDERS_STAFF_ROLE_IDS"),
        _validate_role_id_list,
        fallback_key="GALLERY_STAFF_ROLE_IDS",
    ),
    "REMINDERS_CATCHUP_GRACE_HOURS": _Setting(
        "REMINDERS_CATCHUP_GRACE_HOURS", "reminders", "int_range",
        int(os.getenv("REMINDERS_CATCHUP_GRACE_HOURS", "6")),
        _make_int_range(1, 168),
    ),
    # ── Jinxxy / tienda ──
    "JINXXY_ANNOUNCE_CHANNEL_ID": _Setting(
        "JINXXY_ANNOUNCE_CHANNEL_ID", "jinxxy", "snowflake",
        int(os.getenv("JINXXY_ANNOUNCE_CHANNEL_ID", "1525202600738295818")),
        _validate_channel_id,
    ),
    "JINXXY_POLL_HOURS": _Setting(
        "JINXXY_POLL_HOURS", "jinxxy", "int_range",
        int(os.getenv("JINXXY_POLL_HOURS", "6")),
        _make_int_range(1, 168),
    ),
    "JINXXY_STAFF_ROLE_IDS": _Setting(
        "JINXXY_STAFF_ROLE_IDS", "jinxxy", "role_list",
        _env_role_ids("JINXXY_STAFF_ROLE_IDS"),
        _validate_role_id_list,
        fallback_key="GALLERY_STAFF_ROLE_IDS",
    ),
    "JINXXY_STORE_URL": _Setting(
        "JINXXY_STORE_URL", "jinxxy", "url",
        os.getenv("JINXXY_STORE_URL", "https://nocturna-avatars.site/en/store"),
        _validate_url,
    ),
    "WEBSITE_BASE_URL": _Setting(
        "WEBSITE_BASE_URL", "jinxxy", "url",
        os.getenv("WEBSITE_BASE_URL", "https://nocturna-avatars.site"),
        _validate_url,
    ),
    # ── Reuniones ──
    "MEETINGS_FORUM_ID": _Setting(
        "MEETINGS_FORUM_ID", "meetings", "snowflake",
        int(os.getenv("MEETINGS_FORUM_ID", "1517386124044013588")),
        _validate_channel_id,
    ),
    "MEETING_LANG": _Setting(
        "MEETING_LANG", "meetings", "lang",
        os.getenv("MEETING_LANG", "es"),
        _validate_lang,
    ),
    "WHISPER_PROMPT": _Setting(
        "WHISPER_PROMPT", "meetings", "free_string",
        os.getenv("WHISPER_PROMPT", "Reunión en español del equipo Nocturna. Bot: CachoraBot."),
        _validate_free_string,
    ),
    "WHISPER_MODEL": _Setting(
        "WHISPER_MODEL", "meetings", "free_string",
        os.getenv("WHISPER_MODEL", "large-v3-turbo"),
        _validate_free_string,
        hint="the model must already be available on the host (faster-whisper)",
    ),
    "OLLAMA_MODEL": _Setting(
        "OLLAMA_MODEL", "meetings", "free_string",
        os.getenv("OLLAMA_MODEL", "phi4"),
        _validate_free_string,
        hint="the model must already be pulled on the host (ollama)",
    ),
    # ── Foro / encoding ──
    "FORUM_CHANNEL_ID": _Setting(
        "FORUM_CHANNEL_ID", "forum", "snowflake",
        int(os.getenv("FORUM_CHANNEL_ID", "0")),
        _validate_channel_id_or_zero,
    ),
    "ENCODING_CHANNEL_ID": _Setting(
        "ENCODING_CHANNEL_ID", "forum", "snowflake",
        int(os.getenv("ENCODING_CHANNEL_ID", "0")),
        _validate_channel_id_or_zero,
    ),
}


# ── panel-facing API ──────────────────────────────────────────────────────────────
def get(key: str):
    """Return the stored value for ``key``, or its .env/default seed. NEVER raises (STORE-04).

    Resolution order:
    1. ``SELECT value FROM settings WHERE key=?`` → ``json.loads``. On ANY exception (missing
       table / missing row / corrupt JSON) fall back to the schema default (Pitfall 2).
    2. If the resolved value is an EMPTY list and the descriptor declares a ``fallback_key``,
       return ``get(fallback_key)`` — evaluated fresh every call, never baked in at seed time
       (CONF-03 / Pitfall 5). This composes the staff-role cascade at read time.
    """
    descriptor = _SCHEMA[key]
    default = descriptor.default
    try:
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        value = default if row is None else json.loads(row["value"])
    except Exception as e:  # missing table, corrupt JSON, or any sqlite error → default
        log.warning("settings.get(%r) fell back to default: %s", key, e)
        value = default

    # empty-list → resolve the fallback key fresh (CONF-03); never mutates stored state
    if descriptor.fallback_key and isinstance(value, list) and not value:
        return get(descriptor.fallback_key)
    return value


def set(key: str, value) -> None:
    """Validate ``value`` for ``key`` then persist it. Raises SettingRejected on invalid input;
    writes NOTHING on failure (STORE-03).

    The key is allowlist-checked against ``_SCHEMA`` BEFORE any SQL and passed only as a
    parameterized ``?`` placeholder (never f-string interpolation) — mirrors core/db.py's
    ``_REMINDER_UPDATABLE`` discipline (T-01-02-01). The validator runs before the upsert, so a
    rejected value never reaches the database (T-01-02-02).
    """
    if key not in _SCHEMA:
        raise SettingRejected(f"unknown setting key: {key!r}")
    validated = _SCHEMA[key].validate(value)  # raises SettingRejected on failure, before any SQL
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(validated)),
        )
