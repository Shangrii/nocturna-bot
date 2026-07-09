import sqlite3
from datetime import datetime, timezone

import config

# ── Conexión ──────────────────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
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
