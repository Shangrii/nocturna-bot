"""Extracted-logic tests for the bot-side action queue dispatcher (INFRA-01)."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import config
from cogs.action_queue_worker import ActionQueueCog
from core import action_queue, db


def _use_tmp_db(monkeypatch, tmp_path, name="action_queue_cog.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


def _build_cog(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_action_queue()
    monkeypatch.setattr(ActionQueueCog._tick, "start", lambda *args, **kwargs: None)
    return ActionQueueCog(SimpleNamespace())


def _advance_past_backoff(action_id):
    due = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE action_queue SET next_attempt_at=? WHERE id=?",
            (due, action_id),
        )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_noop_happy_path_completes_with_echo(monkeypatch, tmp_path):
    cog = _build_cog(monkeypatch, tmp_path)
    action_id = action_queue.enqueue("noop", {"echo": "hi"}, requested_by="manager-1")

    await cog._run_once()

    row = action_queue.get_status(action_id)
    assert row["status"] == "done"
    assert json.loads(row["result_json"]) == {"echo": "hi"}


@pytest.mark.anyio
async def test_noop_force_fail_retries_then_reaches_failed(monkeypatch, tmp_path):
    cog = _build_cog(monkeypatch, tmp_path)
    action_id = action_queue.enqueue(
        "noop", {"force_fail": True}, requested_by="manager-1"
    )

    for expected_attempts in range(1, action_queue._MAX_DISPATCH_ATTEMPTS + 1):
        await cog._run_once()
        row = action_queue.get_status(action_id)
        assert row["attempts"] == expected_attempts
        if expected_attempts < action_queue._MAX_DISPATCH_ATTEMPTS:
            assert row["status"] == "pending"
            _advance_past_backoff(action_id)

    assert row["status"] == "failed"
    assert "forced failure" in row["error"]


@pytest.mark.anyio
async def test_unknown_kind_fails_row_without_escaping_tick(monkeypatch, tmp_path):
    cog = _build_cog(monkeypatch, tmp_path)
    action_id = action_queue.enqueue("bogus_kind", {}, requested_by="manager-1")

    for expected_attempts in range(1, action_queue._MAX_DISPATCH_ATTEMPTS + 1):
        await cog._run_once()
        row = action_queue.get_status(action_id)
        assert row["attempts"] == expected_attempts
        assert "bogus_kind" in row["error"]
        if expected_attempts < action_queue._MAX_DISPATCH_ATTEMPTS:
            _advance_past_backoff(action_id)

    assert row["status"] == "failed"


@pytest.mark.anyio
async def test_empty_queue_tick_is_noop(monkeypatch, tmp_path):
    cog = _build_cog(monkeypatch, tmp_path)

    await cog._run_once()

    with db._get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM action_queue").fetchone()[0]
    assert count == 0
