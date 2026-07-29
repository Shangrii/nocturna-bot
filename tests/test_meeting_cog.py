"""Focused tests for durable meeting publishing, backfill, and re-publish."""

import sys
import types
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import discord
import pytest

# The production image includes discord-ext-voice-recv; the lightweight test
# environment does not. Supply only the two import-time types used by meeting.py.
voice_recv_stub = types.ModuleType("discord.ext.voice_recv")
voice_recv_stub.AudioSink = object
voice_recv_stub.VoiceRecvClient = type("VoiceRecvClient", (), {})
sys.modules.setdefault("discord.ext.voice_recv", voice_recv_stub)

import config
from cogs import meeting
from cogs.meeting import MeetingCog
from core import db


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _build_cog(monkeypatch, tmp_path, bot=None):
    monkeypatch.setattr(config, "RECORDINGS_DIR", tmp_path)
    monkeypatch.setattr(db, "init_meetings", Mock())
    return MeetingCog(bot or SimpleNamespace())


def _session(*, text_channel=None):
    return SimpleNamespace(
        tema="Planeación",
        voice_channel=SimpleNamespace(name="General", members=[]),
        text_channel=text_channel or SimpleNamespace(id=10, send=AsyncMock()),
        started_at=datetime(2026, 7, 28, 14, 30),
        ended_at=datetime(2026, 7, 28, 15, 0),
        attendees=["Ana", "Luis"],
    )


class _Forum:
    def __init__(self, *, created=None, error=None):
        self._created = created
        self._error = error
        self.threads = []

    async def create_thread(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._created


def test_cog_initializes_durable_meeting_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RECORDINGS_DIR", tmp_path)
    init_meetings = Mock()
    monkeypatch.setattr(db, "init_meetings", init_meetings)

    cog = MeetingCog(SimpleNamespace())

    init_meetings.assert_called_once_with()
    assert cog._backfilled is False


@pytest.mark.anyio
async def test_publish_persists_forum_thread_and_starter_message(
    monkeypatch, tmp_path
):
    created = SimpleNamespace(
        thread=SimpleNamespace(id=501, mention="<#501>"),
        message=SimpleNamespace(id=502),
    )
    forum = _Forum(created=created)
    monkeypatch.setattr(meeting.discord, "ForumChannel", _Forum)
    inserted = Mock(return_value=1)
    monkeypatch.setattr(db, "insert_meeting", inserted)
    monkeypatch.setattr(db, "log_activity", Mock())
    bot = SimpleNamespace(get_channel=lambda channel_id: forum)
    cog = _build_cog(monkeypatch, tmp_path, bot)
    session = _session()

    await cog._publish(session, "Resumen", ["Decisión"], "Transcripción")

    assert inserted.call_args.kwargs == {
        "tema": "Planeación",
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat(),
        "attendees": ["Ana", "Luis"],
        "notes": ["Decisión"],
        "transcript": "Transcripción",
        "summary": "Resumen",
        "thread_id": 501,
        "starter_message_id": 502,
    }


@pytest.mark.anyio
async def test_publish_fallback_persists_null_forum_ids_and_sends_embed(
    monkeypatch, tmp_path
):
    response = SimpleNamespace(status=500, reason="Server Error")
    forum = _Forum(error=discord.HTTPException(response, "boom"))
    monkeypatch.setattr(meeting.discord, "ForumChannel", _Forum)
    inserted = Mock(return_value=1)
    monkeypatch.setattr(db, "insert_meeting", inserted)
    text_channel = SimpleNamespace(id=10, send=AsyncMock())
    cog = _build_cog(
        monkeypatch,
        tmp_path,
        SimpleNamespace(get_channel=lambda channel_id: forum),
    )
    session = _session(text_channel=text_channel)

    await cog._publish(session, "Resumen", [], "Transcripción")

    text_channel.send.assert_awaited_once()
    assert inserted.call_args.kwargs["thread_id"] is None
    assert inserted.call_args.kwargs["starter_message_id"] is None


@pytest.mark.anyio
async def test_publish_does_not_fail_when_persistence_fails(monkeypatch, tmp_path):
    created = SimpleNamespace(
        thread=SimpleNamespace(id=501, mention="<#501>"),
        message=SimpleNamespace(id=502),
    )
    forum = _Forum(created=created)
    monkeypatch.setattr(meeting.discord, "ForumChannel", _Forum)
    monkeypatch.setattr(db, "insert_meeting", Mock(side_effect=OSError("disk full")))
    monkeypatch.setattr(db, "log_activity", Mock())
    text_channel = SimpleNamespace(id=501, send=AsyncMock())
    cog = _build_cog(
        monkeypatch,
        tmp_path,
        SimpleNamespace(get_channel=lambda channel_id: forum),
    )

    await cog._publish(
        _session(text_channel=text_channel),
        "Resumen",
        [],
        "Transcripción",
    )

    text_channel.send.assert_not_awaited()


@pytest.mark.anyio
async def test_teardown_snapshots_members_and_speakers_by_name(monkeypatch, tmp_path):
    members = [
        SimpleNamespace(id=1, display_name="Ana", bot=False),
        SimpleNamespace(id=2, display_name="Luis", bot=False),
        SimpleNamespace(id=3, display_name="Bot", bot=True),
    ]
    recorder = SimpleNamespace(
        users={
            1: {"name": "Ana"},
            3: {"name": "Bot"},
            4: {"name": "Mara"},
        },
        cleanup=Mock(),
    )
    vc = SimpleNamespace(stop_listening=Mock(), disconnect=AsyncMock())
    session = SimpleNamespace(
        voice_channel=SimpleNamespace(members=members),
        recorder=recorder,
        vc=vc,
    )
    cog = _build_cog(monkeypatch, tmp_path)

    await cog._teardown(session)

    assert session.attendees == ["Ana", "Luis", "Mara"]
    assert isinstance(session.ended_at, datetime)


class _Thread:
    def __init__(self, *, archived, partial):
        self.id = 901
        self.archived = archived
        self.edit = AsyncMock()
        self._partial = partial

    def get_partial_message(self, message_id):
        self.requested_message_id = message_id
        return self._partial


def _meeting_row(**overrides):
    row = {
        "id": 7,
        "tema": "Planeación",
        "started_at": "2026-07-28T14:30:00",
        "ended_at": "2026-07-28T15:00:00",
        "attendees_json": '["Ana"]',
        "notes_json": '["Decisión"]',
        "transcript": "Original",
        "summary": "Resumen actualizado",
        "thread_id": 901,
        "starter_message_id": 902,
    }
    row.update(overrides)
    return row


@pytest.mark.anyio
async def test_republish_unarchives_edits_stored_message_then_restores(
    monkeypatch, tmp_path
):
    partial = SimpleNamespace(edit=AsyncMock())
    thread = _Thread(archived=True, partial=partial)
    monkeypatch.setattr(meeting.discord, "Thread", _Thread)
    monkeypatch.setattr(db, "get_meeting", Mock(return_value=_meeting_row()))
    log_activity = Mock()
    monkeypatch.setattr(db, "log_activity", log_activity)
    cog = _build_cog(
        monkeypatch,
        tmp_path,
        SimpleNamespace(
            get_channel=lambda channel_id: thread,
            fetch_channel=AsyncMock(),
        ),
    )
    timeline = Mock()
    timeline.attach_mock(thread.edit, "thread_edit")
    timeline.attach_mock(partial.edit, "message_edit")

    result = await cog._republish(7, actor_name="Nocturna")

    assert result == {"ok": True}
    assert thread.requested_message_id == 902
    assert timeline.mock_calls == [
        call.thread_edit(archived=False),
        call.message_edit(embed=partial.edit.call_args.kwargs["embed"]),
        call.thread_edit(archived=True),
    ]
    embed = partial.edit.call_args.kwargs["embed"]
    assert embed.description == "Resumen actualizado"
    assert embed.fields[0].value == "• Decisión"
    log_activity.assert_called_once()
    assert log_activity.call_args.args[0] == "meeting_republished"
    assert "Nocturna" in log_activity.call_args.args[1]


@pytest.mark.anyio
async def test_republish_active_thread_edits_without_archive_changes(
    monkeypatch, tmp_path
):
    partial = SimpleNamespace(edit=AsyncMock())
    thread = _Thread(archived=False, partial=partial)
    monkeypatch.setattr(meeting.discord, "Thread", _Thread)
    monkeypatch.setattr(db, "get_meeting", Mock(return_value=_meeting_row()))
    monkeypatch.setattr(db, "log_activity", Mock())
    cog = _build_cog(
        monkeypatch,
        tmp_path,
        SimpleNamespace(get_channel=lambda channel_id: thread),
    )

    await cog._republish(7, actor_name="Nocturna")

    partial.edit.assert_awaited_once()
    thread.edit.assert_not_awaited()


@pytest.mark.anyio
async def test_republish_uses_the_original_embed_limits(monkeypatch, tmp_path):
    partial = SimpleNamespace(edit=AsyncMock())
    thread = _Thread(archived=False, partial=partial)
    monkeypatch.setattr(meeting.discord, "Thread", _Thread)
    monkeypatch.setattr(
        db,
        "get_meeting",
        Mock(
            return_value=_meeting_row(
                summary="s" * 5000,
                notes_json=f'["{"n" * 1500}"]',
            )
        ),
    )
    monkeypatch.setattr(db, "log_activity", Mock())
    cog = _build_cog(
        monkeypatch,
        tmp_path,
        SimpleNamespace(get_channel=lambda channel_id: thread),
    )

    await cog._republish(7)

    embed = partial.edit.call_args.kwargs["embed"]
    assert len(embed.description) == 4096
    assert len(embed.fields[0].value) == 1024


@pytest.mark.anyio
async def test_republish_rejects_meeting_without_forum_target(monkeypatch, tmp_path):
    monkeypatch.setattr(
        db,
        "get_meeting",
        Mock(return_value=_meeting_row(thread_id=None, starter_message_id=None)),
    )
    cog = _build_cog(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="forum post"):
        await cog._republish(7, actor_name="Nocturna")


class _AsyncItems:
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        self._iterator = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


@pytest.mark.anyio
async def test_backfill_walks_active_and_archived_and_skips_existing(
    monkeypatch, tmp_path
):
    attachment = SimpleNamespace(
        filename="acta_20260728.md",
        read=AsyncMock(return_value="Transcripción histórica".encode()),
    )
    active_starter = SimpleNamespace(
        id=102,
        embeds=[SimpleNamespace(description="Resumen histórico")],
        attachments=[attachment],
    )
    active = SimpleNamespace(
        id=101,
        name="Acta histórica",
        created_at=datetime(2026, 7, 20, 12, 0),
        starter_message=active_starter,
    )
    existing = SimpleNamespace(
        id=201,
        name="Ya importada",
        created_at=datetime(2026, 7, 19, 12, 0),
        starter_message=SimpleNamespace(id=202, embeds=[], attachments=[]),
    )

    class _BackfillForum:
        threads = [active]

        def archived_threads(self, *, limit):
            assert limit is None
            return _AsyncItems([existing])

    forum = _BackfillForum()
    monkeypatch.setattr(meeting.discord, "ForumChannel", _BackfillForum)
    monkeypatch.setattr(
        db,
        "get_meeting_by_thread_id",
        Mock(side_effect=lambda thread_id: {"id": 1} if thread_id == 201 else None),
    )
    inserted = Mock()
    monkeypatch.setattr(db, "insert_meeting", inserted)
    cog = _build_cog(
        monkeypatch,
        tmp_path,
        SimpleNamespace(get_channel=lambda channel_id: forum),
    )

    await cog._backfill_meetings()

    inserted.assert_called_once()
    assert inserted.call_args.kwargs["thread_id"] == 101
    assert inserted.call_args.kwargs["starter_message_id"] == 102
    assert inserted.call_args.kwargs["summary"] == "Resumen histórico"
    assert inserted.call_args.kwargs["transcript"] == "Transcripción histórica"


@pytest.mark.anyio
async def test_on_ready_backfill_runs_only_once_and_swallows_errors(
    monkeypatch, tmp_path
):
    cog = _build_cog(monkeypatch, tmp_path)
    cog._backfill_meetings = AsyncMock(side_effect=RuntimeError("temporary"))

    await cog.on_ready()
    await cog.on_ready()

    cog._backfill_meetings.assert_awaited_once()
