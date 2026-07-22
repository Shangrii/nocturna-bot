"""Connection-level sqlite hardening contract (INFRA-02)."""

import config
import core.db as db


def _use_tmp_db(monkeypatch, tmp_path, name="db_hardening.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


def test_busy_timeout_pragma_active(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    with db._get_conn() as conn:
        value = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert value == 8000
