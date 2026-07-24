"""Extracted-logic tests for the bot-side action queue dispatcher (INFRA-01)."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

import config
from cogs import action_queue_worker
from cogs.action_queue_worker import ActionQueueCog
from core import action_queue, db


def _use_tmp_db(monkeypatch, tmp_path, name="action_queue_cog.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


def _build_cog(monkeypatch, tmp_path, bot=None):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_action_queue()
    monkeypatch.setattr(ActionQueueCog._tick, "start", lambda *args, **kwargs: None)
    return ActionQueueCog(bot or SimpleNamespace())


def _advance_past_backoff(action_id):
    due = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE action_queue SET next_attempt_at=? WHERE id=?",
            (due, action_id),
        )


_DISPATCH_CASES = (
    pytest.param(
        "gallery_publish",
        "GalleryCog",
        "_publish",
        "gallery_is_published",
        "PHOTO_CHANNEL_ID",
        True,
        id="gallery_publish",
    ),
    pytest.param(
        "gallery_remove",
        "GalleryCog",
        "_unpublish",
        "gallery_is_published",
        "PHOTO_CHANNEL_ID",
        False,
        id="gallery_remove",
    ),
    pytest.param(
        "review_publish",
        "ReviewsCog",
        "_publish",
        "reviews_is_published",
        "REVIEWS_CHANNEL_ID",
        True,
        id="review_publish",
    ),
    pytest.param(
        "review_remove",
        "ReviewsCog",
        "_unpublish",
        "reviews_is_published",
        "REVIEWS_CHANNEL_ID",
        False,
        id="review_remove",
    ),
)


def _build_dispatch_cog(
    monkeypatch,
    tmp_path,
    *,
    cog_name,
    method_name,
    state_helper,
    channel_setting,
    initial_state,
    target_state,
    transition,
):
    monkeypatch.setattr(config, "PHOTO_CHANNEL_ID", 111, raising=False)
    monkeypatch.setattr(config, "REVIEWS_CHANNEL_ID", 222, raising=False)
    monkeypatch.setattr(
        action_queue_worker,
        state_helper,
        lambda message: message.published,
    )

    message = SimpleNamespace(id=123, published=initial_state)

    async def apply_transition(dispatched_message):
        dispatched_message.published = target_state

    action_method = AsyncMock(
        side_effect=apply_transition if transition else None
    )
    business_cog = SimpleNamespace(**{method_name: action_method})
    channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
    expected_channel_id = getattr(config, channel_setting)
    bot = SimpleNamespace(
        get_channel=lambda channel_id: (
            channel if channel_id == expected_channel_id else None
        ),
        fetch_channel=AsyncMock(return_value=channel),
        get_cog=lambda name: business_cog if name == cog_name else None,
    )
    return _build_cog(monkeypatch, tmp_path, bot), action_method, channel


async def _run_through_retry_budget(cog, action_id):
    for expected_attempts in range(1, action_queue._MAX_DISPATCH_ATTEMPTS + 1):
        await cog._run_once()
        row = action_queue.get_status(action_id)
        assert row["attempts"] == expected_attempts
        if expected_attempts < action_queue._MAX_DISPATCH_ATTEMPTS:
            assert row["status"] == "pending"
            _advance_past_backoff(action_id)
    return row


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


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "kind",
        "cog_name",
        "method_name",
        "state_helper",
        "channel_setting",
        "target_state",
    ),
    _DISPATCH_CASES,
)
async def test_dispatch_fresh_success(
    monkeypatch,
    tmp_path,
    kind,
    cog_name,
    method_name,
    state_helper,
    channel_setting,
    target_state,
):
    cog, action_method, channel = _build_dispatch_cog(
        monkeypatch,
        tmp_path,
        cog_name=cog_name,
        method_name=method_name,
        state_helper=state_helper,
        channel_setting=channel_setting,
        initial_state=not target_state,
        target_state=target_state,
        transition=True,
    )
    action_id = action_queue.enqueue(
        kind,
        {"message_id": 123},
        requested_by="manager-1",
    )

    await cog._run_once()

    row = action_queue.get_status(action_id)
    assert row["status"] == "done"
    assert json.loads(row["result_json"]) == {"already": False}
    action_method.assert_awaited_once()
    assert channel.fetch_message.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "kind",
        "cog_name",
        "method_name",
        "state_helper",
        "channel_setting",
        "target_state",
    ),
    _DISPATCH_CASES,
)
async def test_dispatch_moot_success(
    monkeypatch,
    tmp_path,
    kind,
    cog_name,
    method_name,
    state_helper,
    channel_setting,
    target_state,
):
    cog, action_method, channel = _build_dispatch_cog(
        monkeypatch,
        tmp_path,
        cog_name=cog_name,
        method_name=method_name,
        state_helper=state_helper,
        channel_setting=channel_setting,
        initial_state=target_state,
        target_state=target_state,
        transition=False,
    )
    action_id = action_queue.enqueue(
        kind,
        {"message_id": 123},
        requested_by="manager-1",
    )

    await cog._run_once()

    row = action_queue.get_status(action_id)
    assert row["status"] == "done"
    assert json.loads(row["result_json"]) == {"already": True}
    action_method.assert_awaited_once()
    assert channel.fetch_message.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "kind",
        "cog_name",
        "method_name",
        "state_helper",
        "channel_setting",
        "target_state",
    ),
    _DISPATCH_CASES,
)
async def test_dispatch_genuine_failure_reaches_failed(
    monkeypatch,
    tmp_path,
    kind,
    cog_name,
    method_name,
    state_helper,
    channel_setting,
    target_state,
):
    cog, action_method, _ = _build_dispatch_cog(
        monkeypatch,
        tmp_path,
        cog_name=cog_name,
        method_name=method_name,
        state_helper=state_helper,
        channel_setting=channel_setting,
        initial_state=not target_state,
        target_state=target_state,
        transition=False,
    )
    action_id = action_queue.enqueue(
        kind,
        {"message_id": 123},
        requested_by="manager-1",
    )

    row = await _run_through_retry_budget(cog, action_id)

    assert row["status"] == "failed"
    assert "did not complete" in row["error"]
    assert action_method.await_count == action_queue._MAX_DISPATCH_ATTEMPTS


@pytest.mark.anyio
async def test_gallery_publish_deleted_message_reaches_failed(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(config, "PHOTO_CHANNEL_ID", 111, raising=False)
    not_found = discord.NotFound(
        SimpleNamespace(status=404, reason="Not Found"),
        "Unknown Message",
    )
    channel = SimpleNamespace(
        fetch_message=AsyncMock(side_effect=not_found)
    )
    bot = SimpleNamespace(
        get_channel=lambda channel_id: channel,
        fetch_channel=AsyncMock(return_value=channel),
        get_cog=lambda name: SimpleNamespace(_publish=AsyncMock()),
    )
    cog = _build_cog(monkeypatch, tmp_path, bot)
    action_id = action_queue.enqueue(
        "gallery_publish",
        {"message_id": 123},
        requested_by="manager-1",
    )

    row = await _run_through_retry_budget(cog, action_id)

    assert row["status"] == "failed"
    assert "message no longer exists" in row["error"]
