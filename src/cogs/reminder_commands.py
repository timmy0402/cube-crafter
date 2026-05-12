import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import RubiksBot

from views.reminder import TimezoneSelectView
from cogs._helpers import log_command_usage, get_db_user_id

logger = logging.getLogger(__name__)


class ReminderCommands(commands.Cog):
    """
    Discord Cog containing the /reminder command group (set/disable/show).
    """

    def __init__(self, bot: "RubiksBot") -> None:
        self.bot = bot
        super().__init__()

    reminder = app_commands.Group(
        name="reminder",
        description="Manage your daily reminder DM",
    )

    @reminder.command(
        name="set",
        description="Set or update your daily reminder time and timezone",
    )
    async def reminder_set(self, interaction: discord.Interaction) -> None:
        """
        Starts the reminder setup flow with a timezone Select. The Select
        callback then opens a time-entry modal (or a custom-tz modal for 'Other').

        Input: interaction (discord.Interaction) - The slash command interaction.
        Output: None
        """
        await log_command_usage(self.bot.db_manager, "reminder_set")
        await interaction.response.send_message(
            "Pick your timezone:",
            view=TimezoneSelectView(self.bot),
            ephemeral=True,
        )

    @reminder.command(
        name="disable",
        description="Turn off your daily reminder",
    )
    async def reminder_disable(self, interaction: discord.Interaction) -> None:
        """
        Marks the user's reminder inactive. No-op if the user has no reminder.

        Input: interaction (discord.Interaction) - The slash command interaction.
        Output: None
        """
        await interaction.response.defer(ephemeral=True)
        await log_command_usage(self.bot.db_manager, "reminder_disable")
        try:
            db_id = await get_db_user_id(self.bot.db_manager, interaction.user.id)
            if db_id is None:
                await interaction.followup.send(
                    "You don't have a reminder set yet. Use `/reminder set` to create one.",
                    ephemeral=True,
                )
                return
            # Pre-check existence so we can return the right message after the UPDATE
            # (the async helper API doesn't expose cursor.rowcount).
            exists = await self.bot.db_manager.fetchone(
                "SELECT 1 FROM DailyReminders WHERE UserID=?", (db_id,)
            )
            if not exists:
                await interaction.followup.send(
                    "You don't have a reminder set yet. Use `/reminder set` to create one.",
                    ephemeral=True,
                )
                return
            await self.bot.db_manager.execute(
                "UPDATE DailyReminders SET IsActive=0, UpdatedAt=GETUTCDATE() "
                "WHERE UserID=?",
                (db_id,),
            )
        except Exception as e:
            logger.error(f"reminder_disable failed for {interaction.user.id}: {e}")
            await interaction.followup.send(
                "Couldn't disable your reminder. Please try again later.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            "Your daily reminder is now off. Use `/reminder set` to turn it back on.",
            ephemeral=True,
        )

    @reminder.command(
        name="show",
        description="Show your current reminder settings",
    )
    async def reminder_show(self, interaction: discord.Interaction) -> None:
        """
        Displays the user's current reminder configuration.

        Input: interaction (discord.Interaction) - The slash command interaction.
        Output: None
        """
        await interaction.response.defer(ephemeral=True)
        await log_command_usage(self.bot.db_manager, "reminder_show")
        try:
            db_id = await get_db_user_id(self.bot.db_manager, interaction.user.id)
            if db_id is None:
                await interaction.followup.send(
                    "No reminder set. Use `/reminder set` to create one.",
                    ephemeral=True,
                )
                return
            row = await self.bot.db_manager.fetchone(
                "SELECT ReminderTime, Timezone, IsActive "
                "FROM DailyReminders WHERE UserID=?",
                (db_id,),
            )
        except Exception as e:
            logger.error(f"reminder_show failed for {interaction.user.id}: {e}")
            await interaction.followup.send(
                "Couldn't fetch your reminder. Please try again later.",
                ephemeral=True,
            )
            return

        if row is None:
            await interaction.followup.send(
                "No reminder set. Use `/reminder set` to create one.",
                ephemeral=True,
            )
            return

        reminder_time, timezone, is_active = row
        status = "On" if is_active else "Off"
        await interaction.followup.send(
            f"**Daily reminder**\n"
            f"Time: `{reminder_time}`\n"
            f"Timezone: `{timezone}`\n"
            f"Status: **{status}**",
            ephemeral=True,
        )
