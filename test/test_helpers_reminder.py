import pytest

from cogs._helpers import get_db_user_id, log_command_usage
from views.reminder import TIME_PATTERN, _save_and_confirm, upsert_reminder


class DB:
    def __init__(self, rows=(), error=None):
        self.rows = list(rows)
        self.calls = []
        self.error = error

    async def fetchone(self, query, params=()):
        if self.error:
            raise self.error
        self.calls.append(("fetchone", query, params))
        return self.rows.pop(0) if self.rows else None

    async def execute(self, query, params=()):
        if self.error:
            raise self.error
        self.calls.append(("execute", query, params))


class Response:
    def __init__(self):
        self.messages = []

    async def send_message(self, message, **kwargs):
        self.messages.append((message, kwargs))


class Interaction:
    def __init__(self, user_id=7, name="Ada"):
        self.user = type("User", (), {"id": user_id, "name": name})()
        self.response = Response()


class Bot:
    def __init__(self, db):
        self.db_manager = db


def test_time_pattern_rejects_invalid_hours_and_accepts_boundaries():
    assert TIME_PATTERN.fullmatch("00:00")
    assert TIME_PATTERN.fullmatch("23:59")
    assert not TIME_PATTERN.fullmatch("24:00")
    assert not TIME_PATTERN.fullmatch("9:00")


@pytest.mark.asyncio
async def test_log_command_usage_is_best_effort_and_user_lookup():
    db = DB(rows=[(42,)])
    await log_command_usage(db, "daily")
    assert await get_db_user_id(db, 9) == 42
    failing = DB(error=RuntimeError("offline"))
    await log_command_usage(failing, "daily")


@pytest.mark.asyncio
async def test_upsert_reminder_creates_user_and_reminder():
    db = DB(rows=[None, (31,), None])
    await upsert_reminder(db, 9, "Ada", "09:30", "UTC")
    assert any("INSERT INTO Users" in call[1] for call in db.calls if call[0] == "execute")
    assert any("INSERT INTO DailyReminders" in call[1] for call in db.calls if call[0] == "execute")


@pytest.mark.asyncio
async def test_upsert_reminder_updates_existing_row():
    db = DB(rows=[(31,), (1,)])
    await upsert_reminder(db, 9, "Ada", "09:30", "UTC")
    assert any("UPDATE DailyReminders" in call[1] for call in db.calls if call[0] == "execute")


@pytest.mark.asyncio
async def test_save_and_confirm_validates_time_timezone_and_db_errors():
    interaction = Interaction()
    await _save_and_confirm(interaction, Bot(DB()), "9:00", "UTC")
    assert "Invalid time" in interaction.response.messages[0][0]

    interaction = Interaction()
    await _save_and_confirm(interaction, Bot(DB()), "09:00", "Not/AZone")
    assert "Unknown IANA timezone" in interaction.response.messages[0][0]

    interaction = Interaction()
    await _save_and_confirm(interaction, Bot(DB(error=RuntimeError("db"))), "09:00", "UTC")
    assert "Couldn't save" in interaction.response.messages[0][0]


@pytest.mark.asyncio
async def test_save_and_confirm_success_replies_ephemerally():
    interaction = Interaction()
    await _save_and_confirm(interaction, Bot(DB(rows=[(2,), None])), "09:00", "UTC")
    message, kwargs = interaction.response.messages[0]
    assert "Reminder set" in message
    assert kwargs["ephemeral"] is True
