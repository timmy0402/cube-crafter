import asyncio
from unittest.mock import AsyncMock

import pytest

from bot import RubiksBot
from conftest import FakeDatabase


@pytest.mark.asyncio
async def test_keep_alive_loop_survives_failure_and_recovers(caplog):
    recovered = asyncio.Event()
    calls = 0

    async def keep_alive():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Unable to connect to DB after 3 attempts")
        recovered.set()

    db = type("Database", (), {})()
    db.keep_alive = keep_alive
    db.close = AsyncMock()
    bot = RubiksBot(db)
    bot.wait_until_ready = AsyncMock()
    bot.keep_database_alive.change_interval(seconds=0.01)
    try:
        bot.keep_database_alive.start()
        await asyncio.wait_for(recovered.wait(), 2)
        assert bot.keep_database_alive.is_running()
        assert not bot.keep_database_alive.failed()
        assert "will retry next cycle" in caplog.text
    finally:
        await bot.close()
    db.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_cancels_database_work_before_closing_pool():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def keep_alive():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def close_database():
        assert cancelled.is_set()

    db = type("Database", (), {})()
    db.keep_alive = keep_alive
    db.close = AsyncMock(side_effect=close_database)
    bot = RubiksBot(db)
    bot.wait_until_ready = AsyncMock()
    bot.keep_database_alive.start()
    try:
        await asyncio.wait_for(started.wait(), 1)
    finally:
        await asyncio.wait_for(bot.close(), 1)
    assert not bot.keep_database_alive.is_running()
    assert not bot.keep_database_alive.failed()
    db.close.assert_awaited_once()


class DailyBot:
    def __init__(self, db):
        self.db_manager = db
        self.sent = []

    async def _send_reminder_dm(self, discord_id):
        self.sent.append(discord_id)


@pytest.mark.asyncio
async def test_daily_reminder_sends_and_marks_after_due_time():
    db = FakeDatabase(all_rows=[[(1, 7, 99, "00:00", "UTC", None)]], one=[None])
    bot = DailyBot(db)

    await RubiksBot.daily_reminder_task.coro(bot)

    assert bot.sent == [99]
    assert any(call[0] == "execute" and "LastSentDate" in call[1] for call in db.calls)


@pytest.mark.asyncio
async def test_daily_reminder_skips_sent_invalid_and_completed_users():
    import datetime

    today = datetime.datetime.now(datetime.timezone.utc).date()
    db = FakeDatabase(
        all_rows=[[
            (1, 7, 99, "00:00", "UTC", today),
            (2, 8, 98, "not-time", "UTC", None),
            (3, 9, 97, "00:00", "Not/AZone", None),
            (4, 10, 96, "00:00", "UTC", None),
        ]],
        one=[(1,)],
    )
    bot = DailyBot(db)

    await RubiksBot.daily_reminder_task.coro(bot)

    assert bot.sent == []
    marked = [call for call in db.calls if call[0] == "execute"]
    assert len(marked) == 1
    assert marked[0][2][1] == 4


@pytest.mark.asyncio
async def test_daily_scramble_generation_inserts_successful_api_response(monkeypatch):
    db = FakeDatabase(one=[None])
    bot = type("Bot", (), {"db_manager": db})()
    response = type("Response", (), {
        "status_code": 200,
        "json": lambda self: {"scramble": "R U", "image": "image"},
    })()
    monkeypatch.setattr("bot.requests.get", lambda **kwargs: response)

    await RubiksBot.check_and_generate_daily_scramble(bot)

    assert any(call[0] == "execute" and "INSERT INTO DailyScramble" in call[1] for call in db.calls)


@pytest.mark.asyncio
async def test_daily_scramble_generation_skips_existing_record(monkeypatch):
    db = FakeDatabase(one=[(1,)])
    bot = type("Bot", (), {"db_manager": db})()
    request = AsyncMock()
    monkeypatch.setattr("bot.requests.get", request)

    await RubiksBot.check_and_generate_daily_scramble(bot)

    request.assert_not_called()
