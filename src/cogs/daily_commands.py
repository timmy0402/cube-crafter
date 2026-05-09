import discord
from discord.ext import commands
from discord import app_commands
import datetime
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import RubiksBot

from views.timer import TimerView
from views.reminder import RemindMeView
from cogs._helpers import log_command_usage, get_db_user_id, process_scramble_image

logger = logging.getLogger(__name__)


class DailyCommands(commands.Cog):
    """
    Discord Cog containing the daily challenge commands: /daily, /leaderboard.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="daily", description="Start your daily scramble section")
    async def daily(self, interaction: discord.Interaction) -> None:
        """
        Begin users daily sessions with timer and auto record to DailySolves table
        """
        await interaction.response.defer(ephemeral=True)
        log_command_usage(self.bot.db_manager, "daily")
        # Fetch Daily Scramble
        curr_date = datetime.datetime.now(datetime.timezone.utc).date()
        # Check if user already did their daily
        try:
            user_id = interaction.user.id
            user = await self.bot.fetch_user(user_id)

            db_id = get_db_user_id(self.bot.db_manager, user_id)

            self.bot.db_manager.cursor.execute(
                "SELECT SolveTime, SolveStatus FROM DailySolves WHERE UserID=? AND SolveDate=?", (db_id,curr_date)
            )
            result = self.bot.db_manager.cursor.fetchone()
            if result:
                await interaction.followup.send(f"You already did your daily, your time is {result[0]} ({result[1]}). Come back tommorrow please ☺️")
                return
        except Exception as e:
            logger.error(f"Getting userid error: {e}")
            await interaction.followup.send("Error getting your User profile")
            return
        # fetching daily scramble
        try:
            self.bot.db_manager.cursor.execute(
                "SELECT ScrambleText, ImageString, PuzzleType FROM DailyScramble WHERE ScrambleDate = ?", (curr_date)
            )
            response = self.bot.db_manager.cursor.fetchone()
            if not response:
                await interaction.followup.send("Daily scramble not generated yet. Come back latter")
                return
        except Exception as e:
            logger.error(f"Fetching daily scramble error: {e}")
            await interaction.followup.send("Error getting daily scramble")
            return

        scramble_string = response[0]
        svg_string = response[1]
        puzzle = response[2]

        new_png_buffer = process_scramble_image(svg_string)

        # Create Discord file and embed
        file = discord.File(fp=new_png_buffer, filename="daily_rubiks_cube.png")
        embed = discord.Embed(
            title=f"Your {puzzle} Scramble", description=scramble_string, color=0x0099FF
        )
        embed.set_image(url="attachment://daily_rubiks_cube.png")
        try:
            view = TimerView(
                timeout=360,
                is_daily=True,
                user_id=user_id,
                userName=user.name,
                puzzle=puzzle,
                db_manager=self.bot.db_manager,
            )
            await interaction.followup.send(
                "Click **Start** to begin timing. Click **Stop** when finished.",
                view=view,
                embed=embed,
                file=file,
                ephemeral=True
            )

            message = await interaction.original_response()
            view.message = message

            try:
                await interaction.followup.send(
                    "Want a daily reminder? Click below to set a time and timezone.",
                    view=RemindMeView(self.bot),
                    ephemeral=True,
                )
            except Exception as e:
                logger.warning(f"Failed to send reminder opt-in followup: {e}")

            await view.wait()
            await view.disable_all_items()
        except Exception as e:
            logger.error(f"Stopwatch error: {e}")
            await interaction.followup.send(
                "An error occurred with the timer. Please try again."
            )
        return

    @app_commands.command(name="leaderboard", description="Get daily leaderboard in your server")
    async def leaderboard(self, interaction: discord.Interaction):
        """
        Get daily leaderboard in current server
        """
        await interaction.response.defer(thinking=True)
       # Ensure members are loaded
        if not interaction.guild.chunked:
            await interaction.guild.chunk()

        # List comprehension to get all IDs
        member_ids = [int(member.id) for member in interaction.guild.members]

        if not member_ids:
            await interaction.followup.send("No members found in this server.")
            return

        try:
            placeholders = ",".join("?" * len(member_ids))
            query = f"SELECT UserID, UserName FROM Users WHERE DiscordID IN ({placeholders})"
            self.bot.db_manager.cursor.execute(query, *member_ids)
            results = self.bot.db_manager.cursor.fetchall()

            if not results:
                await interaction.followup.send("No users in this server have registered with the bot.")
                return

            # Initialize a dictionary to map userid to username
            userid_to_username = {}
            user_ids = []

            # Loop through the results and create the mapping
            for row in results:
                user_id, user_name = row
                user_ids.append(user_id)
                userid_to_username[user_id] = user_name

        except Exception as e:
            logger.error(f"Error getting users list from server: {e}")
            await interaction.followup.send("Error getting the list of members in server")
            return

        try:
            if not user_ids:
                await interaction.followup.send("No registered users found.")
                return

            curr_date = datetime.datetime.now(datetime.timezone.utc).date()
            placeholders = ",".join("?" * len(user_ids))
            query = (
                "SELECT UserID, SolveTime, SolveStatus "
                "FROM DailySolves "
                f"WHERE UserID IN ({placeholders}) AND SolveDate = ? "
                "ORDER BY CASE "
                "WHEN SolveStatus = 'Completed' OR SolveStatus = '+2' THEN 0 "
                "WHEN SolveStatus = 'DNF' THEN 1 "
                "ELSE 2 "
                "END, SolveTime ASC;"
            )

            params = list(user_ids)
            params.append(curr_date)

            self.bot.db_manager.cursor.execute(query, *params)
            results = self.bot.db_manager.cursor.fetchall()

            if not results:
                await interaction.followup.send("No daily solves found for today.")
                return

            name_str = "\n".join([str(userid_to_username[row[0]]) for row in results])

            raw_times = []
            formatted_times_list = []

            for row in results:
                t_val = float(row[1])
                status = row[2] if row[2] else ""

                # For calculation
                if status == 'DNF':
                    raw_times.append(float('inf'))
                else:
                    raw_times.append(t_val)

                # For display
                display_str = f"{t_val:.02f}s"
                if status == 'DNF':
                    display_str += " (DNF)"
                elif status == '+2':
                    display_str += " (+2)"
                formatted_times_list.append(display_str)

            times_str = "\n".join(formatted_times_list)

            embed = discord.Embed(
                title=f"{interaction.guild.name}'s Daily Leaderboard",
                description="Today's solve time leaderboard of the server",
                color=discord.Color.blue(),
            )

            embed.add_field(name="Name", value=name_str, inline=True)
            embed.add_field(name="Time", value=times_str, inline=True)

            await interaction.followup.send(embed=embed)
            return

        except Exception as e:
            logger.error(f"Error fetching leaderboard: {e}")
            await interaction.followup.send("Error fetching leaderboard data.")
            return
