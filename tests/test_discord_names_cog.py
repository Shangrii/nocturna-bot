from types import SimpleNamespace

import discord
import pytest

from cogs.discord_names import _map_channel_kind, _role_hex, _snapshot_rows


@pytest.mark.parametrize(
    ("channel_type", "expected"),
    [
        (discord.ChannelType.text, "text"),
        (discord.ChannelType.forum, "forum"),
        (discord.ChannelType.voice, "voice"),
        (discord.ChannelType.news, "text"),
        (discord.ChannelType.stage_voice, "voice"),
        (discord.ChannelType.category, "other"),
    ],
)
def test_map_channel_kind(channel_type, expected):
    assert _map_channel_kind(channel_type) == expected


def test_role_hex_returns_none_for_default_colour():
    assert _role_hex(discord.Colour(0)) is None


def test_role_hex_returns_lowercase_six_digit_hex():
    assert _role_hex(discord.Colour(0x5865F2)) == "#5865f2"


def test_snapshot_rows_skips_everyone_role():
    everyone = SimpleNamespace(
        id=1,
        name="@everyone",
        colour=discord.Colour(0),
        is_default=lambda: True,
    )
    staff = SimpleNamespace(
        id=2,
        name="Staff",
        colour=discord.Colour(0x5865F2),
        is_default=lambda: False,
    )
    guild = SimpleNamespace(channels=[], roles=[everyone, staff])

    assert _snapshot_rows(guild) == [
        (2, "role", "Staff", None, "#5865f2"),
    ]
