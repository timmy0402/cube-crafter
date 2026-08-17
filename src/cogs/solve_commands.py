import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import RubiksBot

from views.timer import TimerView
from stats import get_user_pbs, calculate_wca_avg, recalculate_user_pbs
from cogs._constants import PUZZLE_CHOICES
from cogs._helpers import log_command_usage, get_db_user_id

logger = logging.getLogger(__name__)


class SolveCommands(commands.Cog):
    """
    Discord Cog containing solve-tracking commands: /stopwatch, /time,
    /personal_bests, /delete_time, /adjust_time.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="stopwatch", description="Time your own solve with an interactive timer")
    @app_commands.describe(arg="Optional: Choose your Puzzle: 3x3, 4x4, etc.")
    @app_commands.choices(arg=PUZZLE_CHOICES)
    async def stopwatch(self, interaction: discord.Interaction, arg: str = None) -> None:
        """
        Launches an interactive stopwatch for the user to time their solves.
        """
        user_id = interaction.user.id
        user = await self.bot.fetch_user(user_id)
        if arg == None:
            puzzle = "3x3"
        else:
            puzzle = arg

        await interaction.response.defer()
        await log_command_usage(self.bot.db_manager, "stopwatch")

        try:
            view = TimerView(
                timeout=360,
                user_id=user_id,
                userName=user.name,
                puzzle=puzzle,
                db_manager=self.bot.db_manager,
            )
            await interaction.followup.send(
                "Click **Start** to begin timing. Click **Stop** when finished.", view=view
            )

            message = await interaction.original_response()
            view.message = message

            await view.wait()
            await view.disable_all_items()
        except Exception as e:
            logger.error(f"Stopwatch error: {e}")
            await interaction.followup.send(
                "An error occurred with the timer. Please try again."
            )

    @app_commands.command(name="time", description="Display your recent solve times and averages")
    @app_commands.describe(puzzle="Optional: Filter by puzzle type (3x3, 4x4, etc.)")
    @app_commands.choices(puzzle=PUZZLE_CHOICES)
    async def time(self, interaction: discord.Interaction, puzzle: str = "3x3") -> None:
        """
        Fetches the last 15 solves from the database and calculates Ao5/Ao12.
        """
        await interaction.response.defer(thinking=True)
        await log_command_usage(self.bot.db_manager, "time")

        try:
            user_id = interaction.user.id
            user = await self.bot.fetch_user(user_id)

            db_id = await get_db_user_id(self.bot.db_manager, user_id)

            if not db_id:
                await interaction.followup.send("You haven't recorded any solves yet!")
                return

            rows = await self.bot.db_manager.fetchall(
                "SELECT TOP 15 TimeID, SolveTime, SolveStatus FROM SolveTimes WHERE UserID=? AND PuzzleType=? ORDER BY TimeID DESC",
                (db_id, puzzle),
            )

            if not rows:
                await interaction.followup.send(f"No solve history found for **{puzzle}**.")
                return


            raw_times = []
            formatted_times_list = []

            for row in rows:
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

            ao5 = calculate_wca_avg(raw_times, 5)
            ao12 = calculate_wca_avg(raw_times, 12)

            # Build Response Embed
            embed = discord.Embed(
                title=f"{user.name}'s {puzzle} Solve Times",
                description=f"Showing your 15 most recent solves for **{puzzle}**.",
                color=discord.Color.blue(),
            )

            ids_str = "\n".join([str(row[0]) for row in rows])
            times_str = "\n".join(formatted_times_list)

            embed.add_field(name="ID", value=ids_str, inline=True)
            embed.add_field(name="Time", value=times_str, inline=True)
            embed.add_field(name="Stats", value=(
                f"**Ao5:** {ao5:.02f}s\n" if ao5 else "**Ao5:** N/A\n"
            ) + (
                f"**Ao12:** {ao12:.02f}s" if ao12 else "**Ao12:** N/A"
            ), inline=True)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Time command error: {e}")
            await interaction.followup.send("Database connection error. Please try again later.")

    @app_commands.command(name="personal_bests", description="View your personal best times for each puzzle")
    @app_commands.describe(puzzle="Optional: Filter by puzzle type (3x3, 4x4, etc.)")
    @app_commands.choices(puzzle=PUZZLE_CHOICES)
    async def personal_bests(self, interaction: discord.Interaction, puzzle: str = "3x3") -> None:
        """
        Fetches the user's personal best single, Ao5, and Ao12 for the specified puzzle.
        """
        await interaction.response.defer(thinking=True)
        await log_command_usage(self.bot.db_manager, "personal_bests")

        try:
            user_id = interaction.user.id
            user = await self.bot.fetch_user(user_id)

            db_id = await get_db_user_id(self.bot.db_manager, user_id)

            if not db_id:
                await interaction.followup.send("You haven't recorded any solves yet!")
                return

            pb_data = await get_user_pbs(self.bot.db_manager, db_id, puzzle)

            if pb_data["BestSingle"] is None and pb_data["BestAo5"] is None and pb_data["BestAo12"] is None:
                await interaction.followup.send(f"No personal bests found for **{puzzle}**.")
                return

            embed = discord.Embed(
                title=f"{user.name}'s Personal Bests for {puzzle}",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Best Single", value=f"{pb_data['BestSingle']:.02f}s" if pb_data['BestSingle'] else "N/A", inline=False)
            embed.add_field(name="Best Ao5", value=f"{pb_data['BestAo5']:.02f}s" if pb_data['BestAo5'] else "N/A", inline=False)
            embed.add_field(name="Best Ao12", value=f"{pb_data['BestAo12']:.02f}s" if pb_data['BestAo12'] else "N/A", inline=False)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Personal bests error: {e}")
            await interaction.followup.send("Database connection error. Please try again later.")

    @app_commands.command(name="delete_time", description="Delete a specific solve time by ID")
    @app_commands.describe(timeid="The ID of the time to delete (found in /time)")
    async def deleteTime(self, interaction: discord.Interaction, timeid: str) -> None:
        """
        Deletes a specific solve time from the user's history.
        """
        await interaction.response.defer(thinking=True)
        await log_command_usage(self.bot.db_manager, "delete_time")

        try:
            user_id = interaction.user.id
            db_id = await get_db_user_id(self.bot.db_manager, user_id)

            if not db_id:
                await interaction.followup.send("History not found.")
                return

            # Security check: Ensure the time belongs to the user.
            # PuzzleType is needed for the post-delete PB recalculation.
            owner_row = await self.bot.db_manager.fetchone(
                "SELECT UserID, PuzzleType FROM SolveTimes WHERE TimeID = ?", (timeid,)
            )

            if not owner_row:
                await interaction.followup.send("Time ID not found.")
                return

            if owner_row[0] != db_id:
                await interaction.followup.send("You cannot delete someone else's time!")
                return

            puzzle_type = owner_row[1]

            await self.bot.db_manager.execute(
                "DELETE FROM SolveTimes WHERE TimeID = ?", (timeid,)
            )

            # Recalculate PBs in case the deleted row was a best.
            await recalculate_user_pbs(self.bot.db_manager, db_id, puzzle_type)

            await interaction.followup.send(f"Successfully deleted record `{timeid}`.")

        except Exception as e:
            logger.error(f"Delete time error: {e}")
            await interaction.followup.send("Error processing deletion.")

    @app_commands.command(name="adjust_time", description="Adjust a specific solve time by ID")
    @app_commands.describe(timeid="The ID of the time to adjust (found in /time)", operation="Choose either +2 seconds or DNF")
    @app_commands.choices(
        operation=[
            app_commands.Choice(name="+2 seconds", value="plus2"),
            app_commands.Choice(name="DNF", value="dnf"),
        ]
    )
    async def adjust_time(self, interaction: discord.Interaction, timeid: str, operation: str) -> None:
        """Adjusts a specific solve time by either adding 2 seconds or marking it as DNF.
        Args:
          timeid (str): The ID of the time to adjust (found in /time).
          operation (str): The type of adjustment to make ("plus2" or "dnf").
        """
        await interaction.response.defer(thinking=True)
        await log_command_usage(self.bot.db_manager, "adjust_time")
        try:
            user_id = interaction.user.id
            db_id = await get_db_user_id(self.bot.db_manager, user_id)
            if not db_id:
                await interaction.followup.send("History not found.")
                return
        except Exception as e:
            logger.error(f"Adjust time error (fetching user): {e}")
            await interaction.followup.send("Database connection error. Please try again later.")
            return

        try:
            result = await self.bot.db_manager.fetchone(
                "SELECT SolveTime, PuzzleType, SolveStatus FROM SolveTimes WHERE TIMEID = ? AND UserID = ?",
                (timeid, db_id),
            )
            if not result:
                await interaction.followup.send("Time not found or inaccessible.")
                return

            original_time = result[0]
            puzzle_type = result[1]
            curr_status = result[2]

            new_time = original_time

            # Perform adjustment
            if operation == "plus2":
                if curr_status == "+2":
                    await interaction.followup.send("Invalid operation, can't not do another +2")
                    return
                # A DNF already discards the result, so a +2 on top is meaningless —
                # and allowing it would let plus2/dnf be alternated to stack penalties.
                if curr_status == "DNF":
                    await interaction.followup.send(
                        "This solve is a DNF, so a +2 can't be added to it."
                    )
                    return
                new_time = original_time + 2  # Add 2 seconds
                status = '+2'
            elif operation == "dnf":
                status = 'DNF'
            else:
                await interaction.followup.send("Invalid operation.")
                return

            await self.bot.db_manager.execute(
                "UPDATE SolveTimes SET SolveTime = ?, SolveStatus = ? WHERE TIMEID = ?",
                (new_time, status, timeid),
            )

            await recalculate_user_pbs(self.bot.db_manager, db_id, puzzle_type)

            msg = f"Successfully adjusted time `{timeid}`: "
            if operation == "plus2":
                msg += f"{original_time:.2f}s -> {new_time:.2f}s (+2)"
            else:
                msg += f"Marked as DNF"

            await interaction.followup.send(msg)

        except Exception as e:
            logger.error(f"Adjust time error: {e}")
            await interaction.followup.send("Error processing adjustment.")
