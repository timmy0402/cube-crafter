import discord
from discord.ext import commands
from discord import app_commands
import os
import logging
from dotenv import load_dotenv
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import RubiksBot

from views.algorithms import AlgorithmsView
from azure.storage.blob import BlobServiceClient
from cogs._helpers import log_command_usage

load_dotenv()

logger = logging.getLogger(__name__)


class AlgorithmCommands(commands.Cog):
    """
    Discord Cog containing the OLL/PLL algorithm reference commands.
    """

    def __init__(self, bot: "RubiksBot") -> None:
        self.bot = bot
        # Azure Blob credentials
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
        await log_command_usage(self.bot.db_manager, "oll")

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
        await log_command_usage(self.bot.db_manager, "pll")

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
