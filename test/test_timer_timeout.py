import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from views.timer import TimerView


def make_view(*, ephemeral=False):
    view = TimerView(
        user_id=3, userName="Ada", puzzle="3x3", is_daily=ephemeral,
        db_manager=object(),
    )
    view.message = SimpleNamespace(
        id=30,
        guild=SimpleNamespace(id=10),
        channel=SimpleNamespace(id=20, send=AsyncMock()),
        flags=discord.MessageFlags(ephemeral=ephemeral),
        edit=AsyncMock(),
    )
    return view


@pytest.mark.asyncio
@pytest.mark.parametrize("ephemeral", [False, True])
async def test_timeout_updates_original_message_without_channel_notification(ephemeral):
    view = make_view(ephemeral=ephemeral)

    async def edit_message(**kwargs):
        # Controls must be disabled even before the network call completes.
        assert all(item.disabled for item in kwargs["view"].children)
        assert view.is_finished()

    view.message.edit.side_effect = edit_message

    await view.on_timeout()

    view.message.edit.assert_awaited_once_with(
        content="Your timer session has timed out.", view=view,
    )
    view.message.channel.send.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type,status,code,level",
    [
        (discord.Forbidden, 403, 50001, logging.WARNING),
        (discord.NotFound, 404, 10008, logging.WARNING),
        (discord.NotFound, 404, 10015, logging.WARNING),
        (discord.HTTPException, 500, 0, logging.ERROR),
    ],
)
async def test_timeout_handles_unavailable_message_and_http_errors(
    exception_type, status, code, level, caplog,
):
    view = make_view(ephemeral=True)
    view.message.edit.side_effect = exception_type(
        SimpleNamespace(status=status, reason="Test failure"),
        {"code": code, "message": "Test failure"},
    )

    await view.on_timeout()

    assert view.is_finished()
    assert all(item.disabled for item in view.children)
    view.message.edit.assert_awaited_once()
    view.message.channel.send.assert_not_called()
    record = caplog.records[-1]
    assert record.levelno == level
    for field in ("guild_id=10", "channel_id=20", "message_id=30", f"code={code}"):
        assert field in record.getMessage()


@pytest.mark.asyncio
async def test_timeout_without_message_still_disables_controls():
    view = make_view()
    view.message = None

    await view.on_timeout()

    assert view.is_finished()
    assert all(item.disabled for item in view.children)


@pytest.mark.asyncio
async def test_timeout_in_dm_without_guild():
    view = make_view()
    view.message.guild = None

    await view.on_timeout()

    view.message.edit.assert_awaited_once()
    view.message.channel.send.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "delete_callback"])
async def test_terminal_actions_stop_view_and_update_controls(action):
    view = make_view()
    interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))

    if action == "cancel":
        await view.cancel.callback(interaction)
    else:
        await view.delete_callback(interaction)

    assert view.is_finished()
    assert all(item.disabled for item in view.children)
    interaction.response.edit_message.assert_awaited_once()
    view.message.edit.assert_not_called()
