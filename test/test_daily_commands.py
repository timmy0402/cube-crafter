import pytest

from cogs.daily_commands import DailyCommands
from conftest import FakeDatabase, FakeFollowup, FakeResponse


class Interaction:
    def __init__(self):
        self.user = type("User", (), {"id": 10})()
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class Bot:
    def __init__(self, db):
        self.db_manager = db

    async def fetch_user(self, user_id):
        return type("User", (), {"name": "Ada"})()


@pytest.mark.asyncio
async def test_daily_rejects_a_second_attempt_for_the_same_day(monkeypatch):
    interaction = Interaction()
    db = FakeDatabase(one=[(12.34, "Completed")])
    cog = DailyCommands(Bot(db))

    async def no_log(*args):
        pass

    async def db_user(*args):
        return 1

    monkeypatch.setattr("cogs.daily_commands.log_command_usage", no_log)
    monkeypatch.setattr("cogs.daily_commands.get_db_user_id", db_user)
    await DailyCommands.daily.callback(cog, interaction)
    assert "already did your daily" in interaction.followup.calls[0][0][0]
