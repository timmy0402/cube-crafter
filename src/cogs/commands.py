import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import base64
from PIL import Image, ImageEnhance
import io
import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import RubiksBot

from views.algorithms import AlgorithmsView
from views.timer import TimerView
from azure.storage.blob import BlobServiceClient
from stats import get_user_pbs, calculate_wca_avg, recalculate_user_pbs
import os
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

PUZZLE_CHOICES = [
    app_commands.Choice(name="2x2", value="2x2"),
    app_commands.Choice(name="3x3", value="3x3"),
    app_commands.Choice(name="4x4", value="4x4"),
    app_commands.Choice(name="5x5", value="5x5"),
    app_commands.Choice(name="6x6", value="6x6"),
    app_commands.Choice(name="7x7", value="7x7"),
    app_commands.Choice(name="pyraminx", value="PYRA"),
    app_commands.Choice(name="square1", value="SQ1"),
    app_commands.Choice(name="megaminx", value="MEGA"),
    app_commands.Choice(name="skewb", value="SKEWB"),
    app_commands.Choice(name="clock", value="CLOCK"),
]

SCRAMBLE_API_CHOICES = [                                                                                                                                                                                                                                                                            
    app_commands.Choice(name="2x2", value="TWO"),                                                                                                                                                                                                                                                 
    app_commands.Choice(name="3x3", value="THREE"),                                                                                                                                                                                                                                               
    app_commands.Choice(name="4x4", value="FOUR"),                                                                                                                                                                                                                                                  
    app_commands.Choice(name="5x5", value="FIVE"),                                                                                                                                                                                                                                                  
    app_commands.Choice(name="6x6", value="SIX"),                                                                                                                                                                                                                                                   
    app_commands.Choice(name="7x7", value="SEVEN"),                                                                                                                                                                                                                                                 
    app_commands.Choice(name="pyraminx", value="PYRA"),                                                                                                                                                                                                                                             
    app_commands.Choice(name="square1", value="SQ1"),                                                                                                                                                                                                                                        
    app_commands.Choice(name="megaminx", value="MEGA"),                                                                                                                                                                                                                                      
    app_commands.Choice(name="skewb", value="SKEWB"),                                                                                                                                                                                                                                        
    app_commands.Choice(name="clock", value="CLOCK"),                                                                                                                                                                                                                                        
]        

# Subset for /sessions: NxN only — other puzzles produce scrambles too long
# to fit multiple in a single Discord message.
SCRAMBLE_API_NXN_CHOICES = [
    app_commands.Choice(name="2x2", value="TWO"),
    app_commands.Choice(name="3x3", value="THREE"),
    app_commands.Choice(name="4x4", value="FOUR"),
    app_commands.Choice(name="5x5", value="FIVE"),
    app_commands.Choice(name="6x6", value="SIX"),
    app_commands.Choice(name="7x7", value="SEVEN"),
]

# Per-puzzle scramble count caps for /sessions. Larger cubes have longer
# scramble strings, so fewer fit inside Discord's 2000-char message limit.
SESSIONS_MAX_COUNT = {
    "TWO": 10,
    "THREE": 10,
    "FOUR": 10,
    "FIVE": 7,
    "SIX": 6,
    "SEVEN": 5,
}
SESSIONS_ABS_MAX = max(SESSIONS_MAX_COUNT.values())


class RubiksCommands(commands.Cog):
    """
    Discord Cog containing all Rubik's Cube related commands.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        self.bot = bot
        account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
        access_key = os.getenv("AZURE_STORAGE_ACCESS_KEY")
        self.container = os.getenv("AZURE_STORAGE_CONTAINER_NAME")

        # Initialize Azure Blob service client for algorithm images
        if account_url and access_key:
            self.blob_service_client = BlobServiceClient(
                account_url=account_url, credential=access_key
            )
        else:
            self.blob_service_client = None

        super().__init__()

    def _log_command_usage(self, command_name) -> None:
        """
        Logs the usage of a specific command to the database.
        """
        try:
            self.bot.db_manager.cursor.execute(
                "INSERT INTO CommandLog(CommandName) VALUES(?)", (command_name,)
            )
            self.bot.db_manager.cursor.commit()
        except Exception as e:
            logger.error(f"Log usage failed: {e}")

    def _get_db_user_id(self, discord_id: int) -> int | None:
        """
        Fetches the internal database UserID for a given Discord user ID.

        Input: discord_id (int) - The Discord user's ID.
        Output: int | None - The internal UserID, or None if not found.
        """
        self.bot.db_manager.cursor.execute(
            "SELECT UserID FROM Users WHERE DiscordID = ?", (discord_id,)
        )
        return self.bot.db_manager.cursor.fetchval()

    def _process_scramble_image(self, b64_string: str) -> io.BytesIO:
        """
        Decodes a base64-encoded image, resizes it, and enhances contrast.

        Input: b64_string (str) - Base64-encoded image data.
        Output: io.BytesIO - A PNG image buffer ready for Discord upload.
        """
        decoded = base64.b64decode(b64_string)
        png_buffer = io.BytesIO(decoded)
        png_buffer.seek(0)

        with Image.open(png_buffer) as img:
            resized = img.resize((500, 300))
            enhanced = ImageEnhance.Contrast(resized).enhance(2)

            out_buffer = io.BytesIO()
            enhanced.save(out_buffer, format="PNG")
            out_buffer.seek(0)
            return out_buffer

    @app_commands.command(name="sessions", description="Generate multiple scrambles of the same puzzle")
    @app_commands.describe(
        puzzle="Choose the puzzle type (NxN only)",
        count="Number of scrambles (max varies by puzzle: 10 for 2-4x4, 7 for 5x5, 6 for 6x6, 5 for 7x7)",
    )
    @app_commands.choices(puzzle=SCRAMBLE_API_NXN_CHOICES)
    async def sessions(
        self,
        interaction: discord.Interaction,
        puzzle: str,
        count: app_commands.Range[int, 1, SESSIONS_ABS_MAX],
    ) -> None:
        """
        Generates multiple scrambles for the selected puzzle.
        """
        if interaction.response.is_done():
            logger.warning("Interaction already responded to.")
        else:
            await interaction.response.defer()

            # Log command usage
            self._log_command_usage("sessions")

            # Per-puzzle cap: bigger cubes => longer scrambles => fewer fit per message
            max_count = SESSIONS_MAX_COUNT[puzzle]
            if count > max_count:
                await interaction.followup.send(
                    f"Maximum is **{max_count}** scrambles for this puzzle. You requested {count}."
                )
                return

            # Call external Scrambler API
            url = "https://scrambler-api-apim.azure-api.net/scrambler-api/GetRelay"
            params = {"puzzle": puzzle, "count": count}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        await interaction.followup.send("Failed to retrieve scramble. Please try again later.")
                        logger.error(f"Scrambler API error: {response.status} - {await response.text()}")
                        return

                    response_json = await response.json()
            scrambles = "\n\n".join(response_json['scrambles'])
            await interaction.followup.send(scrambles)

    @app_commands.command(name="scramble", description="Generate a Rubik's Cube scramble")
    @app_commands.describe(puzzle="Choose the scramble type")
    @app_commands.choices(
        puzzle=SCRAMBLE_API_CHOICES
    )
    async def scramble(self, interaction: discord.Interaction, puzzle: str) -> None:
        """
        Generates a scramble for the selected puzzle type and displays it with an image.
        """
        if interaction.response.is_done():
            logger.warning("Interaction already responded to.")
        else:
            await interaction.response.defer()

            # Log command usage
            self._log_command_usage("scramble")

            # Call external Scrambler API
            url = "https://scrambler-api-apim.azure-api.net/scrambler-api/GetScramble"
            params = {"puzzle": puzzle}

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        await interaction.followup.send("Failed to retrieve scramble. Please try again later.")
                        logger.error(f"Scrambler API error: {response.status} - {await response.text()}")
                        return

                    response_json = await response.json()

            scramble_string = response_json["scramble"]
            svg_string = response_json["image"]

            new_png_buffer = self._process_scramble_image(svg_string)

            # Create Discord file and embed
            file = discord.File(fp=new_png_buffer, filename="rubiks_cube.png")
            embed = discord.Embed(
                title=f"Your {puzzle} Scramble", description=scramble_string, color=0x0099FF
            )
            embed.set_image(url="attachment://rubiks_cube.png")

            await interaction.followup.send(embed=embed, file=file)

    @app_commands.command(name="oll", description="View all OLL algorithms")
    @app_commands.choices(
        arg=[
            app_commands.Choice(name="Awkward Shape", value="Awkward Shape"),
            app_commands.Choice(name="Big Lightning Bolt", value="Big Lightning Bolt"),
            app_commands.Choice(name="C Shape", value="C Shape"),
            app_commands.Choice(name="Corners Oriented", value="Corners Oriented"),
            app_commands.Choice(name="Cross", value="Cross"),
            app_commands.Choice(name="Dot", value="Dot"),
            app_commands.Choice(name="Fish Shape", value="Fish Shape"),
            app_commands.Choice(name="I Shape", value="I Shape"),
            app_commands.Choice(name="P Shape", value="P Shape"),
            app_commands.Choice(name="Small L Shape", value="Small L Shape"),
            app_commands.Choice(name="Small Lightning Bolt", value="Small Lightning Bolt"),
            app_commands.Choice(name="W Shape", value="W Shape"),
            app_commands.Choice(name="T Shape", value="T Shape"),
        ]
    )
    async def oll(self, interaction: discord.Interaction, arg: str = None) -> None:
        """
        Displays OLL algorithms in an interactive paginated view.
        """
        await interaction.response.defer()
        self._log_command_usage("oll")

        algo_view = AlgorithmsView(
            mode="oll",
            user_id=interaction.user.id,
            userName=interaction.user.name,
            initial_group=arg,
            blob_service_client=self.blob_service_client,
            container=self.container,
        )

        if arg and arg not in algo_view.OLL_GROUPS:
            await interaction.followup.send(f"Unknown OLL group: {arg}")
            return

        algo_view.update_buttons()
        embed, file = algo_view.get_embed()

        if file:
            await interaction.followup.send(embed=embed, view=algo_view, file=file)
        else:
            await interaction.followup.send(embed=embed, view=algo_view)

    @app_commands.command(name="pll", description="View all PLL algorithms")
    @app_commands.describe(arg="Optional: Jump to a specific group")
    @app_commands.choices(
        arg=[
            app_commands.Choice(name="Adjacent Corner Swap", value="Adjacent Corner Swap"),
            app_commands.Choice(name="Diagonal Corner Swap", value="Diagonal Corner Swap"),
            app_commands.Choice(name="Edges Only", value="Edges Only"),
        ]
    )
    async def pll(self, interaction: discord.Interaction, arg: str = None) -> None:
        """
        Displays PLL algorithms in an interactive paginated view.
        """
        await interaction.response.defer()
        self._log_command_usage("pll")

        algo_view = AlgorithmsView(
            mode="pll",
            user_id=interaction.user.id,
            userName=interaction.user.name,
            initial_group=arg,
            blob_service_client=self.blob_service_client,
            container=self.container,
        )

        if arg and arg not in algo_view.PLL_GROUPS:
            await interaction.followup.send(f"Unknown PLL group: {arg}")
            return

        algo_view.update_buttons()
        embed, file = algo_view.get_embed()

        if file:
            await interaction.followup.send(embed=embed, view=algo_view, file=file)
        else:
            await interaction.followup.send(embed=embed, view=algo_view)

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
        self._log_command_usage("stopwatch")
        
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
        self._log_command_usage("time")

        try:
            user_id = interaction.user.id
            user = await self.bot.fetch_user(user_id)

            db_id = self._get_db_user_id(user_id)

            if not db_id:
                await interaction.followup.send("You haven't recorded any solves yet!")
                return

            # Fetch last 15 solves for the specific puzzle
            self.bot.db_manager.cursor.execute(
                "SELECT TOP 15 TimeID, SolveTime, SolveStatus FROM SolveTimes WHERE UserID=? AND PuzzleType=? ORDER BY TimeID DESC",
                (db_id, puzzle)
            )
            rows = self.bot.db_manager.cursor.fetchall()
            
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
        self._log_command_usage("personal_bests")

        try:
            user_id = interaction.user.id
            user = await self.bot.fetch_user(user_id)

            db_id = self._get_db_user_id(user_id)

            if not db_id:
                await interaction.followup.send("You haven't recorded any solves yet!")
                return

            pb_data = get_user_pbs(self.bot.db_manager, db_id, puzzle)

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

    @app_commands.command(name="daily", description="Start your daily scramble section")
    async def daily(self, interaction: discord.Interaction) -> None:
        """
        Begin users daily sessions with timer and auto record to DailySolves table
        """
        await interaction.response.defer(ephemeral=True)
        self._log_command_usage("daily")
        # Fetch Daily Scramble
        curr_date = datetime.datetime.now(datetime.timezone.utc).date()
        # Check if user already did their daily
        try:
            user_id = interaction.user.id
            user = await self.bot.fetch_user(user_id)

            db_id = self._get_db_user_id(user_id)

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

        new_png_buffer = self._process_scramble_image(svg_string)

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


    @app_commands.command(name="delete_time", description="Delete a specific solve time by ID")
    @app_commands.describe(timeid="The ID of the time to delete (found in /time)")
    async def deleteTime(self, interaction: discord.Interaction, timeid: str) -> None:
        """
        Deletes a specific solve time from the user's history.
        """
        await interaction.response.defer(thinking=True)
        self._log_command_usage("delete_time")
        
        try:
            user_id = interaction.user.id
            db_id = self._get_db_user_id(user_id)

            if not db_id:
                await interaction.followup.send("History not found.")
                return

            # Security check: Ensure the time belongs to the user
            self.bot.db_manager.cursor.execute(
                "SELECT UserID FROM SolveTimes WHERE TimeID = ?", (timeid,)
            )
            owner_id = self.bot.db_manager.cursor.fetchval()

            if not owner_id:
                await interaction.followup.send("Time ID not found.")
                return

            if owner_id != db_id:
                await interaction.followup.send("You cannot delete someone else's time!")
                return

            # Perform deletion
            self.bot.db_manager.cursor.execute(
                "DELETE FROM SolveTimes WHERE TimeID = ?", (timeid,)
            )
            self.bot.db_manager.cursor.commit()

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
        self._log_command_usage("adjust_time")
        try:
            user_id = interaction.user.id
            db_id = self._get_db_user_id(user_id)
            if not db_id:
                await interaction.followup.send("History not found.")
                return
        except Exception as e:
            logger.error(f"Adjust time error (fetching user): {e}")
            await interaction.followup.send("Database connection error. Please try again later.")
            return
        
        try:
            # Fetch original time and puzzle type
            self.bot.db_manager.cursor.execute(
                "SELECT SolveTime, PuzzleType, SolveStatus FROM SolveTimes WHERE TIMEID = ? AND UserID = ?", (timeid, db_id)
            )
            result = self.bot.db_manager.cursor.fetchone()
            if not result:
                await interaction.followup.send("Time not found or inaccessible.")
                return
            
            original_time = result[0]
            puzzle_type = result[1]
            curr_status = result[2]
            
            new_time = original_time

            # Perform adjustment
            if operation == "plus2":
                if curr_status == "plus2":
                    await interaction.followup.send("Invalid operation, can't not do another +2")
                    return
                new_time = original_time + 2  # Add 2 seconds 
                status = '+2'
            elif operation == "dnf":
                status = 'DNF'
            else:
                await interaction.followup.send("Invalid operation.")
                return

            self.bot.db_manager.cursor.execute(
                "UPDATE SolveTimes SET SolveTime = ?, SolveStatus = ? WHERE TIMEID = ?", (new_time, status, timeid)
            )
            self.bot.db_manager.cursor.commit()
            
            # Recalculate PBs after adjustment
            recalculate_user_pbs(self.bot.db_manager, db_id, puzzle_type)

            msg = f"Successfully adjusted time `{timeid}`: "
            if operation == "plus2":
                msg += f"{original_time:.2f}s -> {new_time:.2f}s (+2)"
            else:
                msg += f"Marked as DNF"
            
            await interaction.followup.send(msg)

        except Exception as e:
            logger.error(f"Adjust time error: {e}")
            await interaction.followup.send("Error processing adjustment.")

    @app_commands.command(name="help", description="View all available commands")
    async def help(self, interaction: discord.Interaction) -> None:
        """
        Displays a list of all commands and their descriptions.
        """
        await interaction.response.defer()
        self._log_command_usage("help")

        embed = discord.Embed(
            title="Cube Crafter Help", 
            description="Available commands for tracking and improving your solves:", 
            color=discord.Color.blue()
        )
        embed.add_field(name="/scramble", value="Generate a scramble for various puzzles", inline=False)
        embed.add_field(name="/stopwatch", value="Interactive timer to record your solves", inline=False)
        embed.add_field(name="/time", value="View your recent times and WCA averages", inline=False)
        embed.add_field(name="/adjust_time", value="Add 2 seconds penalty or flag as DNF")
        embed.add_field(name="/delete_time", value="Remove an incorrect time record", inline=False)
        embed.add_field(name="/personal_bests", value="View your personal bests for the specified puzzle", inline=False)
        embed.add_field(name="/oll / /pll", value="Reference library for CFOP algorithms", inline=False)
        embed.add_field(name="/daily", value="Start your daily section with timer", inline=False)
        embed.add_field(name="/leaderboard", value="Get your server daily leaderboard", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="invite", description="Get the invite link to add the bot to your server")
    async def invite(self, interaction: discord.Interaction) -> None:
        """
        Provides an invite link for users to add the bot to their own servers.
        """
        await interaction.response.defer()
        self._log_command_usage("invite")

        client_id = os.getenv("APPLICATION_ID")
        invite_url = f"https://discord.com/oauth2/authorize?client_id={client_id}"

        embed = discord.Embed(
            title="Invite Cube Crafter to Your Server!",
            description=f"Click [this link]({invite_url}) to add the bot and start tracking your solves in your own server!",
            color=discord.Color.green()
        )

        await interaction.followup.send(embed=embed)