import pytest

from cogs.solve_commands import SolveCommands
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
async def test_time_reports_empty_history_for_unknown_user(monkeypatch):
    interaction = Interaction()
    cog = SolveCommands(Bot(FakeDatabase()))

    async def no_log(*args):
        pass

    async def no_user(*args):
        return None

    monkeypatch.setattr("cogs.solve_commands.log_command_usage", no_log)
    monkeypatch.setattr("cogs.solve_commands.get_db_user_id", no_user)
    await SolveCommands.time.callback(cog, interaction, "3x3")
    assert "haven't recorded" in interaction.followup.calls[0][0][0]


@pytest.mark.asyncio
async def test_delete_time_rejects_record_owned_by_another_user(monkeypatch):
    interaction = Interaction()
    db = FakeDatabase(one=[(2, "3x3")])
    cog = SolveCommands(Bot(db))

    async def no_log(*args):
        pass

    async def current_user(*args):
        return 1

    monkeypatch.setattr("cogs.solve_commands.log_command_usage", no_log)
    monkeypatch.setattr("cogs.solve_commands.get_db_user_id", current_user)
    await SolveCommands.deleteTime.callback(cog, interaction, "44")
    assert "cannot delete" in interaction.followup.calls[0][0][0]
    assert not [call for call in db.calls if call[0] == "execute"]
