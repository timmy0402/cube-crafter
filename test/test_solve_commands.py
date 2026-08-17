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


async def _run_adjust(monkeypatch, db, operation, timeid="7"):
    """Invoke /adjust_time against a stubbed database and return the interaction."""
    interaction = Interaction()
    cog = SolveCommands(Bot(db))

    async def no_log(*args):
        pass

    async def current_user(*args):
        return 1

    async def no_recalc(*args):
        pass

    monkeypatch.setattr("cogs.solve_commands.log_command_usage", no_log)
    monkeypatch.setattr("cogs.solve_commands.get_db_user_id", current_user)
    monkeypatch.setattr("cogs.solve_commands.recalculate_user_pbs", no_recalc)
    await SolveCommands.adjust_time.callback(cog, interaction, timeid, operation)
    return interaction


@pytest.mark.asyncio
async def test_adjust_time_refuses_plus2_on_a_dnf(monkeypatch):
    # A DNF already discards the result; stacking a +2 on it used to let
    # plus2/dnf be alternated to add 2 seconds per cycle without limit.
    db = FakeDatabase(one=[(10.0, "3x3", "DNF")])
    interaction = await _run_adjust(monkeypatch, db, "plus2")

    assert "DNF" in interaction.followup.calls[0][0][0]
    assert not [call for call in db.calls if call[0] == "execute"]


@pytest.mark.asyncio
async def test_adjust_time_refuses_a_second_plus2(monkeypatch):
    db = FakeDatabase(one=[(12.0, "3x3", "+2")])
    interaction = await _run_adjust(monkeypatch, db, "plus2")

    assert "+2" in interaction.followup.calls[0][0][0]
    assert not [call for call in db.calls if call[0] == "execute"]


@pytest.mark.asyncio
async def test_adjust_time_applies_plus2_once_to_a_completed_solve(monkeypatch):
    db = FakeDatabase(one=[(10.0, "3x3", "Completed")])
    interaction = await _run_adjust(monkeypatch, db, "plus2")

    writes = [call for call in db.calls if call[0] == "execute"]
    assert len(writes) == 1
    # params are (SolveTime, SolveStatus, TimeID)
    assert writes[0][2][0] == 12.0
    assert writes[0][2][1] == "+2"
    assert "12.00s" in interaction.followup.calls[0][0][0]


@pytest.mark.asyncio
async def test_adjust_time_marks_dnf_without_changing_the_time(monkeypatch):
    db = FakeDatabase(one=[(10.0, "3x3", "Completed")])
    interaction = await _run_adjust(monkeypatch, db, "dnf")

    writes = [call for call in db.calls if call[0] == "execute"]
    assert len(writes) == 1
    assert writes[0][2][0] == 10.0
    assert writes[0][2][1] == "DNF"
    assert "DNF" in interaction.followup.calls[0][0][0]
