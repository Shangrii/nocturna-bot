import json
import sqlite3
from datetime import datetime, timezone

import config

# ── Conexión ──────────────────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # CONC-01: WAL journal mode lets the bot read while the panel writes the same file
    # without "database is locked". WAL is persistent per-database, so this self-heals on
    # whichever process opens the file first; the pragma is non-transactional and applies
    # immediately (the `with conn:` idiom is unaffected). Requires a LOCAL filesystem —
    # WAL does not work over a network share (both processes here run on the same host).
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forum_posts (
                thread_id  INTEGER PRIMARY KEY,
                title      TEXT    NOT NULL,
                author_id  INTEGER NOT NULL,
                avatars    TEXT    NOT NULL DEFAULT '',
                image_url  TEXT    DEFAULT '',
                source_url TEXT    DEFAULT '',
                created_at TEXT    NOT NULL
            )
        """)
        for col, default in [("image_url", "''"), ("source_url", "''")]:
            try:
                conn.execute(f"ALTER TABLE forum_posts ADD COLUMN {col} TEXT DEFAULT {default}")
            except sqlite3.OperationalError:
                pass  # Ya existe
        
        conn.execute("CREATE INDEX IF NOT EXISTS idx_avatars    ON forum_posts(avatars)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON forum_posts(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source_url ON forum_posts(source_url)")


# ── Config store (Fase 01: panel de settings) ─────────────────────────────────
def init_settings():
    """Create the key/value ``settings`` table if it doesn't exist (STORE-02).

    Mirrors ``init_gallery_state`` in shape: a single ``CREATE TABLE IF NOT EXISTS``
    inside ``with _get_conn() as conn:``. Deliberately NOT folded into ``init_db()``
    (locked CONTEXT decision) and holds NO seeding logic — the defaults are seeded by
    ``core/settings.py::seed_defaults()`` at startup. Idempotent: calling it twice is a
    no-op. ``key`` is the tunable's name; ``value`` is the JSON-encoded stored value.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


# ── Galería (Fase 5): cursor de backfill ──────────────────────────────────────
def init_gallery_state():
    """Create the 1-row backfill-cursor table for the gallery cog (D-20).

    The cog's ``__init__`` calls this so the table exists before startup backfill.
    This plan (05-03) only creates the table; the cursor read/write helpers land in
    05-04. ``CHECK (id = 1)`` keeps it a single-row store — one cursor for the one
    photos channel — following the repo's ``CREATE TABLE IF NOT EXISTS`` idiom.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gallery_state (
                id                        INTEGER PRIMARY KEY CHECK (id = 1),
                last_processed_message_id INTEGER
            )
        """)


def get_cursor() -> int | None:
    """Return the persisted last-processed-message-id for the gallery backfill (D-20).

    ``None`` when the cursor has never been set (fresh db / first run) — the caller then
    scans the channel from the beginning. Reads the single ``id = 1`` ``gallery_state`` row.
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT last_processed_message_id FROM gallery_state WHERE id = 1"
        ).fetchone()
    return row["last_processed_message_id"] if row else None


def set_cursor(message_id: int):
    """Advance the gallery backfill cursor to ``message_id`` (D-20 / T-05-17).

    ``INSERT OR REPLACE`` keeps the single ``id = 1`` row so a restart only ever scans
    history *after* the last message the bot processed, never the whole channel again.
    """
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO gallery_state (id, last_processed_message_id) VALUES (1, ?)",
            (message_id,),
        )


# NOTE (Fase 7 / WR-03): the reviews backfill deliberately has NO cursor. Approvals and
# removals are reaction events on EXISTING messages, so a creation-ordered cursor would
# skip staff ✅/🌙 added during downtime to already-scanned messages. The reviews channel
# is low volume — the cog re-scans the full history on every startup instead.


# ── CRUD ──────────────────────────────────────────────────────────────────────
def save_post(thread_id: int, title: str, author_id: int, avatars: list[str],
              image_url: str = "", source_url: str = ""):
    avatars_str = ",".join(a.lower() for a in avatars)
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO forum_posts
                (thread_id, title, author_id, avatars, image_url, source_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (thread_id, title, author_id, avatars_str, image_url, source_url,
              datetime.now(timezone.utc).isoformat()))


def delete_post(thread_id: int):
    with _get_conn() as conn:
        conn.execute("DELETE FROM forum_posts WHERE thread_id = ?", (thread_id,))


def search_posts(avatar: str) -> list[sqlite3.Row]:
    needle = avatar.lower().strip()
    with _get_conn() as conn:
        return conn.execute("""
            SELECT thread_id, title, author_id, avatars, image_url FROM forum_posts
            WHERE (',' || avatars || ',') LIKE ('%,' || ? || ',%')
            ORDER BY created_at DESC
        """, (needle,)).fetchall()


def get_known_avatars() -> set[str]:
    """Devuelve todos los nombres de avatar únicos almacenados en la DB (en minúsculas)."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT avatars FROM forum_posts").fetchall()
    names: set[str] = set()
    for row in rows:
        for a in row["avatars"].split(","):
            a = a.strip()
            if a and a != "general":
                names.add(a)
    return names


def count_avatars() -> dict[str, int]:
    """Devuelve {nombre: cantidad_de_posts} para cada avatar en la DB."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT avatars FROM forum_posts").fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        for a in row["avatars"].split(","):
            a = a.strip()
            if a:
                counts[a] = counts.get(a, 0) + 1
    return counts


def rename_avatar(old: str, new: str) -> int:
    """Renombra un avatar en todas las entradas. Devuelve cuántas filas cambió."""
    old_lower = old.lower().strip()
    new_lower = new.lower().strip()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT thread_id, avatars FROM forum_posts WHERE (',' || avatars || ',') LIKE ('%,' || ? || ',%')",
            (old_lower,)
        ).fetchall()
        count = 0
        for row in rows:
            parts = [a.strip() for a in row["avatars"].split(",") if a.strip()]
            updated = [new_lower if a == old_lower else a for a in parts]
            conn.execute(
                "UPDATE forum_posts SET avatars = ? WHERE thread_id = ?",
                (",".join(updated), row["thread_id"])
            )
            count += 1
    return count


def find_duplicate_url(source_url: str, exclude_thread: int = 0) -> sqlite3.Row | None:
    """Busca si ya existe un post con la misma source_url. Devuelve la fila o None."""
    if not source_url:
        return None
    with _get_conn() as conn:
        return conn.execute(
            "SELECT thread_id, title, author_id FROM forum_posts "
            "WHERE source_url = ? AND thread_id != ?",
            (source_url, exclude_thread)
        ).fetchone()


def get_posts_without_url() -> list[sqlite3.Row]:
    """Devuelve los posts que no tienen source_url."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT thread_id, title FROM forum_posts WHERE source_url = '' OR source_url IS NULL"
        ).fetchall()


def update_source_url(thread_id: int, source_url: str):
    """Actualiza solo la source_url de un post."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE forum_posts SET source_url = ? WHERE thread_id = ?",
            (source_url, thread_id)
        )


def delete_avatar(name: str) -> int:
    """Elimina un avatar de todas las entradas. Borra la entrada si queda sin avatares."""
    target = name.lower().strip()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT thread_id, avatars FROM forum_posts WHERE (',' || avatars || ',') LIKE ('%,' || ? || ',%')",
            (target,)
        ).fetchall()
        count = 0
        for row in rows:
            parts = [a.strip() for a in row["avatars"].split(",") if a.strip() and a.strip() != target]
            if parts:
                conn.execute(
                    "UPDATE forum_posts SET avatars = ? WHERE thread_id = ?",
                    (",".join(parts), row["thread_id"])
                )
            else:
                conn.execute("DELETE FROM forum_posts WHERE thread_id = ?", (row["thread_id"],))
            count += 1
    return count


# ── Recordatorios (Fase 8: cog de recordatorios programados) ──────────────────
# El cog crea/edita/borra recordatorios semanales/mensuales/únicos; el scheduler lee
# las filas "vencidas" por next_fire_utc (el cursor ISO 8601 UTC) y recalcula la
# próxima. Todas las sentencias usan placeholders `?` — nunca SQL con f-strings:
# name/message son texto de staff persistido tal cual (T-08-03). El cog llama a
# init_reminders() en su __init__ (mismo patrón que init_gallery_state), NO init_db().

# Columnas que update_reminder puede modificar. Lista blanca explícita para que una
# clave inesperada en **fields no pueda inyectar un nombre de columna en el SQL (T-08-03).
_REMINDER_UPDATABLE = (
    "name", "frequency", "weekday", "day_of_month", "run_date", "hour", "minute",
    "channel_id", "message", "mentions", "reactions", "next_fire_utc",
)


def init_reminders():
    """Crea la tabla de recordatorios si no existe (idiom CREATE TABLE IF NOT EXISTS).

    El cog la llama en su ``__init__`` para que exista antes de programar. ``id`` es
    AUTOINCREMENT; ``frequency`` es 'weekly'|'monthly'|'oneoff'; weekday/day_of_month/
    run_date son nullable (solo aplica el campo de la frecuencia); ``next_fire_utc`` es
    el cursor ISO 8601 UTC que usa el scheduler.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                frequency     TEXT    NOT NULL,        -- 'weekly' | 'monthly' | 'oneoff'
                weekday       INTEGER,                 -- 0-6 (weekly)
                day_of_month  INTEGER,                 -- 1-31 (monthly)
                run_date      TEXT,                    -- 'YYYY-MM-DD' (oneoff)
                hour          INTEGER NOT NULL,
                minute        INTEGER NOT NULL,
                channel_id    INTEGER NOT NULL,
                message       TEXT    NOT NULL,
                mentions      TEXT    DEFAULT '',       -- e.g. '<@&123>'
                reactions     TEXT    DEFAULT '',       -- e.g. '✅ ❌'
                next_fire_utc TEXT    NOT NULL,         -- ISO 8601 UTC (el cursor del scheduler)
                created_by    INTEGER NOT NULL,
                created_at    TEXT    NOT NULL
            )
        """)


def add_reminder(name: str, frequency: str, hour: int, minute: int, channel_id: int,
                 message: str, created_by: int, weekday: int | None = None,
                 day_of_month: int | None = None, run_date: str | None = None,
                 mentions: str = "", reactions: str = "",
                 next_fire_utc: str = "") -> int:
    """Inserta un recordatorio y devuelve el id nuevo (``lastrowid``).

    ``created_at`` se sella con ``datetime.now(timezone.utc).isoformat()`` (mismo idiom
    que save_post). Todos los valores van por placeholders `?` (T-08-03).
    """
    with _get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO reminders
                (name, frequency, weekday, day_of_month, run_date, hour, minute,
                 channel_id, message, mentions, reactions, next_fire_utc,
                 created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, frequency, weekday, day_of_month, run_date, hour, minute,
              channel_id, message, mentions, reactions, next_fire_utc,
              created_by, datetime.now(timezone.utc).isoformat()))
        return cur.lastrowid


def list_reminders() -> list[sqlite3.Row]:
    """Devuelve todos los recordatorios ordenados por próxima ejecución."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders ORDER BY next_fire_utc"
        ).fetchall()


def get_reminder(reminder_id: int) -> sqlite3.Row | None:
    """Devuelve el recordatorio con ese id, o None si no existe."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()


def update_reminder(reminder_id: int, **fields):
    """Actualiza SOLO las columnas pasadas en ``**fields`` para ese recordatorio.

    Las claves se filtran contra ``_REMINDER_UPDATABLE`` (lista blanca) antes de armar
    el ``SET col = ?, ...``, así una clave inesperada nunca inyecta un nombre de columna
    (T-08-03). No hace nada si no queda ninguna columna válida.
    """
    cols = [(k, v) for k, v in fields.items() if k in _REMINDER_UPDATABLE]
    if not cols:
        return
    set_clause = ", ".join(k + " = ?" for k, _ in cols)
    values = [v for _, v in cols]
    values.append(reminder_id)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET " + set_clause + " WHERE id = ?", values
        )


def delete_reminder(reminder_id: int):
    """Elimina el recordatorio con ese id."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))


def due_reminders(now_utc_iso: str) -> list[sqlite3.Row]:
    """Devuelve los recordatorios vencidos (next_fire_utc <= ahora), en orden de disparo."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE next_fire_utc <= ? ORDER BY next_fire_utc",
            (now_utc_iso,)
        ).fetchall()


def set_next_fire(reminder_id: int, next_fire_utc_iso: str):
    """Avanza el cursor next_fire_utc de un recordatorio a la próxima ejecución."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET next_fire_utc = ? WHERE id = ?",
            (next_fire_utc_iso, reminder_id)
        )


# ── Tienda (Fase 9: snapshot de sync) ─────────────────────────────────────────
# El cog del sync guarda, por producto, el ÚLTIMO valor sincronizado de cada campo
# propiedad del sync (D-12). Ese snapshot durable permite la comparación de tres vías
# ("Jinxxy cambió" vs "el staff editó") sobreviva reinicios. Se clave por checkout_url
# (la clave de enlace D-13). El cog llama a init_store_state() en su __init__ (mismo
# patrón que init_gallery_state/init_reminders), NO init_db(). Todas las sentencias usan
# placeholders `?`; ningún nombre de columna se interpola desde una variable (T-08-03).


def init_store_state():
    """Crea la tabla de snapshot de la tienda si no existe (CREATE TABLE IF NOT EXISTS).

    Una fila por producto sincronizado con el último valor Jinxxy de cada campo propiedad
    del sync, clave ``checkout_url`` (D-13). ``synced_at`` es ISO 8601 UTC. Idempotente:
    llamarla dos veces no falla. El cog la invoca en su ``__init__``.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_snapshot (
                checkout_url TEXT PRIMARY KEY,   -- clave de enlace (D-13)
                jinxxy_id    TEXT,
                name         TEXT,
                price        TEXT,
                category     TEXT,
                nsfw         INTEGER,
                date         TEXT,
                synced_at    TEXT NOT NULL        -- ISO 8601 UTC del último sync
            )
        """)


def get_store_snapshot() -> dict[str, sqlite3.Row]:
    """Devuelve todas las filas del snapshot, indexadas por ``checkout_url``.

    Para una pasada de merge sobre toda la tienda: el cog compara este snapshot durable
    contra los valores en vivo de Jinxxy y contra el ``store.json`` actual (comparación
    de tres vías, D-12). Devuelve ``{}`` cuando la tabla está vacía.
    """
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM store_snapshot").fetchall()
    return {row["checkout_url"]: row for row in rows}


def upsert_store_snapshot(checkout_url: str, jinxxy_id: str, name: str, price: str,
                          category: str, nsfw: int, date: str):
    """Inserta o reemplaza la fila del snapshot para ``checkout_url``.

    ``INSERT OR REPLACE`` mantiene una sola fila por producto (una segunda llamada sobre
    el mismo ``checkout_url`` reemplaza, no duplica). ``synced_at`` se sella con
    ``datetime.now(timezone.utc).isoformat()`` (mismo idiom que save_post). Todos los
    valores van por placeholders `?` (T-08-03).
    """
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO store_snapshot
                (checkout_url, jinxxy_id, name, price, category, nsfw, date, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (checkout_url, jinxxy_id, name, price, category, nsfw, date,
              datetime.now(timezone.utc).isoformat()))


def delete_store_snapshot(checkout_url: str):
    """Elimina la fila del snapshot de un producto deslistado (baja en la tienda)."""
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM store_snapshot WHERE checkout_url = ?", (checkout_url,)
        )


# ── Contador de vistas (Fase 10.1: view counter self-hosted, D-25) ────────────
# El endpoint público (app/counter_app.py, unidad systemd hermana en cinema) incrementa
# y lee un contador por-slug para las páginas de editor. Se guarda SOLO un HASH de la IP
# del cliente (nunca la IP cruda — privacidad, T-10.1-12-02) en una ventana de dedup corta
# para que un reload/loop no infle el contador (T-10.1-12-01). Todas las sentencias usan
# placeholders `?`; el slug se valida en la capa de la app (`[a-z0-9-]+`) antes de llegar
# aquí (T-10.1-12-03). El app llama a init_view_counts() al arrancar (mismo patrón que
# init_gallery_state/init_store_state), NO init_db().

# Ventana de dedup: un mismo (slug, ip_hash) dentro de esta ventana NO vuelve a incrementar.
_VIEW_DEDUP_WINDOW_SEC = 6 * 3600  # 6h — retención corta del hash de IP


def init_view_counts():
    """Crea las tablas del contador de vistas si no existen (CREATE TABLE IF NOT EXISTS).

    ``view_counts`` guarda el total por ``slug``; ``view_dedup`` guarda solo un HASH de la
    IP (columna ``ip_hash`` — nunca la IP cruda) + un timestamp epoch para la ventana de
    dedup. Idempotente: llamarla dos veces no falla. La app la invoca al arrancar.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS view_counts (
                slug  TEXT    PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS view_dedup (
                slug    TEXT    NOT NULL,
                ip_hash TEXT    NOT NULL,        -- SOLO un hash de la IP, nunca la IP cruda
                ts      INTEGER NOT NULL,        -- epoch UTC del último hit de este par
                PRIMARY KEY (slug, ip_hash)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_view_dedup_ts ON view_dedup(ts)")


def get_view_count(slug: str) -> int:
    """Devuelve el contador de vistas del slug; 0 si el slug es desconocido (nunca falla)."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT count FROM view_counts WHERE slug = ?", (slug,)
        ).fetchone()
    return row["count"] if row else 0


def increment_view(slug: str, ip_hash: str) -> int:
    """Incrementa el contador del slug y lo devuelve; no-op dentro de la ventana de dedup.

    Si el mismo ``(slug, ip_hash)`` ya golpeó dentro de ``_VIEW_DEDUP_WINDOW_SEC``, devuelve
    el conteo actual SIN incrementar (un reload no infla el contador, T-10.1-12-01). Solo se
    persiste ``ip_hash`` (un hash de la IP), nunca la IP cruda (T-10.1-12-02). Un ``ip_hash``
    vacío salta el dedup y siempre incrementa (best-effort cuando no hay IP disponible).
    Un slug desconocido se inserta con count 1. Placeholders `?` en todas las sentencias.
    """
    now = int(datetime.now(timezone.utc).timestamp())
    cutoff = now - _VIEW_DEDUP_WINDOW_SEC
    with _get_conn() as conn:
        if ip_hash:
            # Purga las entradas de dedup expiradas (retención corta del hash).
            conn.execute("DELETE FROM view_dedup WHERE ts < ?", (cutoff,))
            recent = conn.execute(
                "SELECT 1 FROM view_dedup WHERE slug = ? AND ip_hash = ? AND ts >= ?",
                (slug, ip_hash, cutoff),
            ).fetchone()
            if recent is not None:
                # Dentro de la ventana → no-op; devuelve el conteo actual sin tocar nada.
                row = conn.execute(
                    "SELECT count FROM view_counts WHERE slug = ?", (slug,)
                ).fetchone()
                return row["count"] if row else 0
            conn.execute(
                "INSERT OR REPLACE INTO view_dedup (slug, ip_hash, ts) VALUES (?, ?, ?)",
                (slug, ip_hash, now),
            )
        conn.execute(
            "INSERT INTO view_counts (slug, count) VALUES (?, 1) "
            "ON CONFLICT(slug) DO UPDATE SET count = count + 1",
            (slug,),
        )
        row = conn.execute(
            "SELECT count FROM view_counts WHERE slug = ?", (slug,)
        ).fetchone()
    return row["count"] if row else 0


# ── Live Discord presence (native integration) ─────────────────────────────────
# The bot process (gateway, GUILD_PRESENCES intent) writes editor member statuses
# here; the editor app (separate process, same sqlite file) serves them read-only at
# /api/presence/<id>. Only editors are ever written (the cog filters on the role), so
# this table is never a general presence-lookup for arbitrary Discord users.
def init_presence():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS presence (
                discord_id TEXT PRIMARY KEY,
                status     TEXT NOT NULL,      -- online | idle | dnd | offline
                updated_at TEXT NOT NULL
            )
        """)


def set_presence(discord_id, status: str):
    """Upsert one editor's live status. Called from the bot's presence cog."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO presence (discord_id, status, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET status = excluded.status, "
            "updated_at = excluded.updated_at",
            (str(discord_id), status, now),
        )


def get_presence(discord_id) -> sqlite3.Row | None:
    """Read one editor's stored status (None if we've never seen them)."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT discord_id, status, updated_at FROM presence WHERE discord_id = ?",
            (str(discord_id),),
        ).fetchone()


# ── Overview data plumbing (Fase 3, SHELL-02) ──────────────────────────────────
# Three concerns feeding the dashboard's Overview page: bot_heartbeat (bot liveness/
# uptime/member-count/loaded-cogs), jinxxy_sync_status (last store-sync outcome, reused
# by Phase 8's manual-sync display per D-10), and activity_log (append-only, bounded
# recent-events feed). The bot process is the ONLY writer of these three tables (T-03-08);
# the app process only ever SELECTs. Both processes call the matching init_*() defensively
# (dual-process init idiom, Pitfall 6) so the app never 500s reading an empty/missing
# table before the bot has run at least once.


def init_heartbeat():
    """Create the single-row ``bot_heartbeat`` table if it doesn't exist (D-09).

    ``CHECK (id = 1)`` keeps it a single global row (one bot process, one heartbeat) —
    same idiom as ``gallery_state``. ``loaded_cogs`` is stored as a JSON-encoded list.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_heartbeat (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                last_beat_utc      TEXT NOT NULL,
                latency_ms         REAL,
                started_at_utc     TEXT NOT NULL,
                guild_member_count INTEGER,
                loaded_cogs        TEXT  -- JSON list
            )
        """)


def set_heartbeat(latency_ms, started_at_utc: str, guild_member_count, loaded_cogs):
    """Upsert the single ``bot_heartbeat`` row (called by ``cogs/heartbeat.py`` every ~45s).

    ``last_beat_utc`` is stamped fresh on every call — Overview treats the bot as Online
    iff this timestamp is recent (staleness threshold computed app-side, Plan 07).
    """
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO bot_heartbeat
                (id, last_beat_utc, latency_ms, started_at_utc, guild_member_count, loaded_cogs)
            VALUES (1, ?, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), latency_ms, started_at_utc,
              guild_member_count, json.dumps(loaded_cogs)))


def get_heartbeat() -> sqlite3.Row | None:
    """Read the single ``bot_heartbeat`` row (None if the bot has never beaten)."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT last_beat_utc, latency_ms, started_at_utc, guild_member_count, "
            "loaded_cogs FROM bot_heartbeat WHERE id = 1"
        ).fetchone()


def init_jinxxy_sync_status():
    """Create the single-row ``jinxxy_sync_status`` table if it doesn't exist (D-10).

    Deliberately its OWN table (not folded into ``bot_heartbeat``) — one-table-per-concern
    idiom, and Phase 8's manual-sync status display reuses this exact record.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jinxxy_sync_status (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                last_run_utc   TEXT,
                ok             INTEGER,
                product_count  INTEGER,
                error          TEXT
            )
        """)


def set_jinxxy_sync_status(ok: bool, product_count: int | None, error: str | None):
    """Upsert the single ``jinxxy_sync_status`` row (called at the end of ``_run_sync``).

    Stamps ``last_run_utc`` fresh on every call — covers both the scheduled poll and the
    manual ``/tienda sync`` command, since both funnel through ``_run_sync`` (D-10).
    """
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO jinxxy_sync_status
                (id, last_run_utc, ok, product_count, error)
            VALUES (1, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), 1 if ok else 0, product_count, error))


def get_jinxxy_sync_status() -> sqlite3.Row | None:
    """Read the single ``jinxxy_sync_status`` row (None if no sync has ever run)."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT last_run_utc, ok, product_count, error FROM jinxxy_sync_status WHERE id = 1"
        ).fetchone()


def init_activity_log():
    """Create the append-only ``activity_log`` table if it doesn't exist (D-11).

    ``id`` is AUTOINCREMENT so recency is orderable without a separate index.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def log_activity(event_type: str, message: str, keep_last: int = 500):
    """Append one activity row, then purge to the last ``keep_last`` rows (T-03-07).

    Purge-on-write bounds growth the same way ``increment_view``'s dedup-cutoff idiom
    does — every write self-limits the table instead of relying on a separate cron/sweep.
    """
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO activity_log (event_type, message, created_at) VALUES (?, ?, ?)",
            (event_type, message, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("""
            DELETE FROM activity_log WHERE id NOT IN (
                SELECT id FROM activity_log ORDER BY id DESC LIMIT ?
            )
        """, (keep_last,))


def get_recent_activity(limit: int = 10) -> list[sqlite3.Row]:
    """Return the ``limit`` most recent activity rows, newest first."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT event_type, message, created_at FROM activity_log "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def init_discord_names():
    """Create the bot-pushed Discord channel/role name cache if absent."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS discord_names (
                id        TEXT PRIMARY KEY,
                kind      TEXT NOT NULL,
                name      TEXT NOT NULL,
                subtype   TEXT,
                color     TEXT,
                synced_at TEXT NOT NULL
            )
        """)


def replace_discord_names(rows: list[tuple]):
    """Atomically replace the complete cached channel/role snapshot."""
    synced_at = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute("DELETE FROM discord_names")
        conn.executemany(
            "INSERT INTO discord_names (id, kind, name, subtype, color, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(str(i), kind, name, subtype, color, synced_at)
             for i, kind, name, subtype, color in rows],
        )


def get_discord_names() -> list[sqlite3.Row]:
    """Return the cached Discord names, or an empty list before the first push."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT id, kind, name, subtype, color, synced_at FROM discord_names"
        ).fetchall()
