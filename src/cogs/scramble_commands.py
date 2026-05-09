import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import RubiksBot

from cogs._constants import (
    SCRAMBLE_API_CHOICES,
    SCRAMBLE_API_NXN_CHOICES,
    SESSIONS_ABS_MAX,
    SESSIONS_MAX_COUNT,
)
from cogs._helpers import log_command_usage, process_scramble_image

logger = logging.getLogger(__name__)


class ScrambleCommands(commands.Cog):
    """
    Discord Cog containing scramble-generation commands (/scramble, /sessions).
    """

    def __init__(self, bot: "RubiksBot") -> None:
        self.bot = bot
        super().__init__()

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
            log_command_usage(self.bot.db_manager, "sessions")

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
            log_command_usage(self.bot.db_manager, "scramble")

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

            new_png_buffer = process_scramble_image(svg_string)

            # Create Discord file and embed
            file = discord.File(fp=new_png_buffer, filename="rubiks_cube.png")
            embed = discord.Embed(
                title=f"Your {puzzle} Scramble", description=scramble_string, color=0x0099FF
            )
            embed.set_image(url="attachment://rubiks_cube.png")

            await interaction.followup.send(embed=embed, file=file)
