import discord
from discord.ext import commands
from discord import app_commands
import os
import logging
from dotenv import load_dotenv
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import RubiksBot

from cogs._helpers import log_command_usage

load_dotenv()

logger = logging.getLogger(__name__)


class MetaCommands(commands.Cog):
    """
    Discord Cog containing meta commands: /help, /invite.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="help", description="View all available commands")
    async def help(self, interaction: discord.Interaction) -> None:
        """
        Displays a list of all commands and their descriptions.
        """
        await interaction.response.defer()
        await log_command_usage(self.bot.db_manager, "help")

        embed = discord.Embed(
            title="Cube Crafter Help",
            description="Available commands for tracking and improving your solves:",
            color=discord.Color.blue()
        )
        embed.add_field(name="/scramble", value="Generate a scramble for various puzzles", inline=False)
        embed.add_field(name="/sessions", value="Generate multiple scrambles of the same puzzles", inline=False)
        embed.add_field(name="/stopwatch", value="Interactive timer to record your solves", inline=False)
        embed.add_field(name="/time", value="View your recent times and WCA averages", inline=False)
        embed.add_field(name="/adjust_time", value="Add 2 seconds penalty or flag as DNF")
        embed.add_field(name="/delete_time", value="Remove an incorrect time record", inline=False)
        embed.add_field(name="/personal_bests", value="View your personal bests for the specified puzzle", inline=False)
        embed.add_field(name="/oll / /pll", value="Reference library for CFOP algorithms", inline=False)
        embed.add_field(name="/daily", value="Start your daily section with timer", inline=False)
        embed.add_field(name="/leaderboard", value="Get your server daily leaderboard", inline=False)
        embed.add_field(name="/reminder set / disable / show", value="Opt in to a daily reminder DM at your chosen time + timezone", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="invite", description="Get the invite link to add the bot to your server")
    async def invite(self, interaction: discord.Interaction) -> None:
        """
        Provides an invite link for users to add the bot to their own servers.
        """
        await interaction.response.defer()
        await log_command_usage(self.bot.db_manager, "invite")

        client_id = os.getenv("APPLICATION_ID")
        invite_url = f"https://discord.com/oauth2/authorize?client_id={client_id}"

        embed = discord.Embed(
            title="Invite Cube Crafter to Your Server!",
            description=f"Click [this link]({invite_url}) to add the bot and start tracking your solves in your own server!",
            color=discord.Color.green()
        )

        await interaction.followup.send(embed=embed)
