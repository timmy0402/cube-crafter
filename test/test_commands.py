import pytest

from cogs._constants import SCRAMBLE_API_MAP, SESSIONS_MAX_COUNT
from cogs.meta_commands import MetaCommands
from cogs.reminder_commands import ReminderCommands
from cogs.scramble_commands import ScrambleCommands


class Response:
    def __init__(self):
        self.sent = []
        self.deferred = False

    def is_done(self):
        return False

    async def defer(self, **kwargs):
        self.deferred = True


class Followup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class Interaction:
    def __init__(self):
        self.response = Response()
        self.followup = Followup()
        self.user = type("User", (), {"id": 5})()


class DB:
    async def execute(self, *args):
        pass


class Bot:
    db_manager = DB()


def test_scramble_mapping_and_session_caps_are_complete():
    assert SCRAMBLE_API_MAP["3x3"] == "THREE"
    assert SESSIONS_MAX_COUNT["SEVEN"] == 5
    assert set(SESSIONS_MAX_COUNT) == {"TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN"}


@pytest.mark.asyncio
async def test_sessions_rejects_puzzle_specific_count_before_http_call(monkeypatch):
    interaction = Interaction()
    command = ScrambleCommands(Bot())

    async def no_log(*args):
        pass

    monkeypatch.setattr("cogs.scramble_commands.log_command_usage", no_log)
    await command.sessions.callback(command, interaction, "SEVEN", 6)
    assert interaction.followup.sent
    assert "Maximum is **5**" in interaction.followup.sent[0][0][0]


@pytest.mark.asyncio
async def test_reminder_disable_reports_missing_user(monkeypatch):
    interaction = Interaction()
    command = ReminderCommands(Bot())

    async def no_log(*args):
        pass

    async def missing_user(*args):
        return None

    monkeypatch.setattr("cogs.reminder_commands.log_command_usage", no_log)
    monkeypatch.setattr("cogs.reminder_commands.get_db_user_id", missing_user)
    await ReminderCommands.reminder_disable.callback(command, interaction)
    assert "don't have a reminder" in interaction.followup.sent[0][0][0]


@pytest.mark.asyncio
async def test_meta_invite_builds_application_invite(monkeypatch):
    interaction = Interaction()
    command = MetaCommands(Bot())

    async def no_log(*args):
        pass

    monkeypatch.setattr("cogs.meta_commands.log_command_usage", no_log)
    monkeypatch.setenv("APPLICATION_ID", "123")
    await MetaCommands.invite.callback(command, interaction)
    embed = interaction.followup.sent[0][1]["embed"]
    assert "client_id=123" in embed.description
