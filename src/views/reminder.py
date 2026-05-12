import re
import zoneinfo
import logging
from typing import TYPE_CHECKING

import discord

from database import DatabaseManager

if TYPE_CHECKING:
    from bot import RubiksBot

logger = logging.getLogger(__name__)

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# (display label, IANA value). Kept at 24 entries so we can add an "Other..."
# option without exceeding Discord's 25-option Select limit.
COMMON_TIMEZONES: list[tuple[str, str]] = [
    ("UTC", "UTC"),
    ("America/Los_Angeles (PT)", "America/Los_Angeles"),
    ("America/Denver (MT)", "America/Denver"),
    ("America/Chicago (CT)", "America/Chicago"),
    ("America/New_York (ET)", "America/New_York"),
    ("America/Toronto", "America/Toronto"),
    ("America/Mexico_City", "America/Mexico_City"),
    ("America/Sao_Paulo", "America/Sao_Paulo"),
    ("Europe/London", "Europe/London"),
    ("Europe/Paris", "Europe/Paris"),
    ("Europe/Berlin", "Europe/Berlin"),
    ("Europe/Athens", "Europe/Athens"),
    ("Europe/Moscow", "Europe/Moscow"),
    ("Africa/Cairo", "Africa/Cairo"),
    ("Africa/Johannesburg", "Africa/Johannesburg"),
    ("Asia/Dubai", "Asia/Dubai"),
    ("Asia/Kolkata (IST)", "Asia/Kolkata"),
    ("Asia/Bangkok", "Asia/Bangkok"),
    ("Asia/Singapore", "Asia/Singapore"),
    ("Asia/Shanghai", "Asia/Shanghai"),
    ("Asia/Tokyo (JST)", "Asia/Tokyo"),
    ("Asia/Seoul", "Asia/Seoul"),
    ("Australia/Sydney", "Australia/Sydney"),
    ("Pacific/Auckland", "Pacific/Auckland"),
]
OTHER_TZ_VALUE = "__other__"


async def upsert_reminder(
    db_manager: DatabaseManager,
    discord_id: int,
    user_name: str,
    reminder_time: str,
    timezone: str,
) -> None:
    """
    Inserts or updates the user's reminder settings.

    Ensures the user exists in Users (creates if missing), then UPSERTs the
    DailyReminders row, resetting LastSentDate so a new time can fire today.

    Input:
        db_manager (DatabaseManager): Shared async database manager.
        discord_id (int): Discord user ID.
        user_name (str): Discord username (used only when creating the user row).
        reminder_time (str): Validated 'HH:MM' 24-hour string.
        timezone (str): Validated IANA timezone name.
    Output:
        None
    """
    row = await db_manager.fetchone(
        "SELECT UserID FROM Users WHERE DiscordID=?", (discord_id,)
    )
    db_id = row[0] if row else None
    if not db_id:
        await db_manager.execute(
            "INSERT INTO Users(UserName, DiscordID) VALUES(?, ?)",
            (user_name, discord_id),
        )
        row = await db_manager.fetchone(
            "SELECT UserID FROM Users WHERE DiscordID=?", (discord_id,)
        )
        db_id = row[0] if row else None

    exists = await db_manager.fetchone(
        "SELECT 1 FROM DailyReminders WHERE UserID=?", (db_id,)
    )
    if exists:
        await db_manager.execute(
            "UPDATE DailyReminders SET ReminderTime=?, Timezone=?, IsActive=1, "
            "LastSentDate=NULL, UpdatedAt=GETUTCDATE() WHERE UserID=?",
            (reminder_time, timezone, db_id),
        )
    else:
        await db_manager.execute(
            "INSERT INTO DailyReminders(UserID, ReminderTime, Timezone) "
            "VALUES(?, ?, ?)",
            (db_id, reminder_time, timezone),
        )


async def _save_and_confirm(
    interaction: discord.Interaction,
    bot: "RubiksBot",
    time_str: str,
    timezone: str,
) -> None:
    """
    Validates a time + timezone, persists the reminder, and replies ephemerally.

    Input:
        interaction (discord.Interaction): Modal-submission interaction.
        bot (RubiksBot): Bot instance for DB access.
        time_str (str): Raw HH:MM string from the modal.
        timezone (str): IANA timezone string.
    Output:
        None
    """
    if not TIME_PATTERN.fullmatch(time_str):
        await interaction.response.send_message(
            "Invalid time. Use 24-hour `HH:MM` (e.g. `09:00`).",
            ephemeral=True,
        )
        return

    try:
        zoneinfo.ZoneInfo(timezone)
    except zoneinfo.ZoneInfoNotFoundError:
        await interaction.response.send_message(
            f"Unknown IANA timezone `{timezone}`. Try `America/New_York`, "
            "`Europe/London`, `Asia/Tokyo`, etc.",
            ephemeral=True,
        )
        return

    try:
        await upsert_reminder(
            db_manager=bot.db_manager,
            discord_id=interaction.user.id,
            user_name=interaction.user.name,
            reminder_time=time_str,
            timezone=timezone,
        )
    except Exception as e:
        logger.error(f"Failed to save reminder for {interaction.user.id}: {e}")
        await interaction.response.send_message(
            "Couldn't save your reminder. Please try again later.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"Reminder set for **{time_str}** in **{timezone}**. "
        "I'll DM you each day — make sure your DMs are open.",
        ephemeral=True,
    )


class TimeReminderModal(discord.ui.Modal, title="Daily Reminder"):
    """
    Modal asking only for the reminder time. Used after the user has picked a
    preset timezone from the Select menu.
    """

    time_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Time (24h, HH:MM)",
        placeholder="09:00",
        min_length=4,
        max_length=5,
        required=True,
    )

    def __init__(self, bot: "RubiksBot", timezone: str) -> None:
        """
        Initialize with the timezone picked in the previous step.

        Input:
            bot (RubiksBot): The bot instance.
            timezone (str): IANA timezone the user picked from the Select.
        Output:
            None
        """
        super().__init__()
        self.bot = bot
        self.timezone = timezone

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Saves the reminder using the preset timezone and the submitted time.
        """
        await _save_and_confirm(
            interaction,
            self.bot,
            self.time_input.value.strip(),
            self.timezone,
        )


class ReminderModal(discord.ui.Modal, title="Daily Reminder"):
    """
    Modal asking for both time and a custom IANA timezone. Used when the user
    picks 'Other...' in the Select menu.
    """

    time_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Time (24h, HH:MM)",
        placeholder="09:00",
        min_length=4,
        max_length=5,
        required=True,
    )
    tz_input: discord.ui.TextInput = discord.ui.TextInput(
        label="IANA Timezone",
        placeholder="America/New_York",
        max_length=64,
        required=True,
    )

    def __init__(self, bot: "RubiksBot") -> None:
        """
        Initialize the modal with a reference to the bot for DB access.

        Input:
            bot (RubiksBot): The bot instance.
        Output:
            None
        """
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Validates input and UPSERTs the reminder. Replies ephemerally.
        """
        await _save_and_confirm(
            interaction,
            self.bot,
            self.time_input.value.strip(),
            self.tz_input.value.strip(),
        )


class TimezoneSelect(discord.ui.Select):
    """
    Dropdown listing common IANA timezones plus an 'Other...' fallback that
    opens the free-text modal.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        """
        Initialize the Select with preset timezones.

        Input:
            bot (RubiksBot): The bot instance.
        Output:
            None
        """
        options: list[discord.SelectOption] = [
            discord.SelectOption(label=label, value=value)
            for label, value in COMMON_TIMEZONES
        ]
        options.append(
            discord.SelectOption(
                label="Other (type custom IANA)...",
                value=OTHER_TZ_VALUE,
                description="Use this if your timezone isn't listed",
            )
        )
        super().__init__(
            placeholder="Pick your timezone",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        """
        Routes to the time-only modal for presets, or the full modal for 'Other'.
        """
        choice = self.values[0]
        if choice == OTHER_TZ_VALUE:
            await interaction.response.send_modal(ReminderModal(self.bot))
        else:
            await interaction.response.send_modal(
                TimeReminderModal(self.bot, choice)
            )


class TimezoneSelectView(discord.ui.View):
    """
    Ephemeral view containing the timezone Select. Entry point for the
    reminder-setup flow.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        """
        Initialize the view and attach the timezone Select.

        Input:
            bot (RubiksBot): The bot instance.
        Output:
            None
        """
        super().__init__(timeout=300)
        self.add_item(TimezoneSelect(bot))


class RemindMeView(discord.ui.View):
    """
    Single-button view shown alongside /daily to let users opt in to a daily
    reminder DM.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        """
        Initialize the view with a reference to the bot.

        Input:
            bot (RubiksBot): The bot instance.
        Output:
            None
        """
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.button(
        label="Remind me daily",
        style=discord.ButtonStyle.secondary,
        emoji="⏰",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """
        Opens the timezone Select so the user can pick (or choose 'Other').
        """
        await interaction.response.send_message(
            "Pick your timezone:",
            view=TimezoneSelectView(self.bot),
            ephemeral=True,
        )
