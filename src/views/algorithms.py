import discord
import json
import os
from azure.storage.blob import BlobServiceClient
from paths import DATA_DIR
import logging

logger = logging.getLogger(__name__)


class AlgorithmsView(discord.ui.View):
    def __init__(
        self,
        *,
        timeout: float | None = 180,
        mode,
        user_id,
        userName,
        initial_group=None,
        blob_service_client=None,
        container=None,
    ) -> None:
        """
        Initialize the AlgorithmsView.

        Args:
            timeout (float | None): The timeout for the view in seconds.
            mode (str): The mode of the view ('oll' or 'pll').
            user_id (int): The ID of the user who initiated the command.
            userName (str): The name of the user.
            initial_group (str, optional): The initial group to display. Defaults to None.
            blob_service_client (BlobServiceClient, optional): The Azure Blob Service Client.
            container (str, optional): The container name.
        """
        super().__init__(timeout=timeout)
        self.mode = mode
        self.user_id = user_id
        self.userName = userName
        self.current_page = 0
        self.algorithms_list = []  # List of tuples (id, alg_string)
        self.current_group = initial_group
        self.blob_service_client = blob_service_client
        self.container = container
        self.images = {}

        self.OLL_GROUPS = {
            "Awkward Shape": ["29", "30", "41", "42"],
            "Big Lightning Bolt": ["39", "40"],
            "C Shape": ["34", "46"],
            "Corners Oriented": ["28", "57"],
            "Cross": ["21", "22", "23", "24", "25", "26", "27"],
            "Dot": ["1", "2", "3", "4", "17", "18", "19", "20"],
            "Fish Shape": ["9", "10", "35", "37"],
            "I Shape": ["51", "52", "55", "56"],
            "P Shape": ["31", "32", "43", "44"],
            "Small L Shape": ["47", "48", "49", "50", "53", "54"],
            "Small Lightning Bolt": ["7", "8", "11", "12"],
            "W Shape": ["36", "38"],
            "T Shape": ["33", "45"],
        }
        self.PLL_GROUPS = {
            "Adjacent Corner Swap": [
                "Aa",
                "Ab",
                "F",
                "Ga",
                "Gb",
                "Gc",
                "Gd",
                "Ja",
                "Jb",
                "Ra",
                "Rb",
                "T",
            ],
            "Diagonal Corner Swap": ["E", "Na", "Nb", "V", "Y"],
            "Edges Only": ["H", "Ua", "Ub", "Z"],
        }

        # Load data
        # Use DATA_DIR from paths.py for absolute path
        json_path = DATA_DIR / "algorithms.json"

        try:
            with open(json_path, "r") as f:
                self.alg_data = json.load(f)
        except FileNotFoundError:
            # Fallback
            logger.error("Could not find algorithms.json")
            self.alg_data = {}
            return

        # Setup Select Menu
        self.setup_select_menu()

        # If an initial group is provided, load it
        if self.current_group:
            self.load_group(self.current_group)

    def setup_select_menu(self) -> None:
        """
        Dynamically sets up the select menu options based on the mode (OLL or PLL).
        """
        options = []
        groups = self.OLL_GROUPS if self.mode == "oll" else self.PLL_GROUPS

        # Sort keys for consistent order
        sorted_groups = sorted(groups.keys())

        for group in sorted_groups:
            options.append(discord.SelectOption(label=group, value=group))

        # Create the Select item
        select = discord.ui.Select(
            placeholder="Choose a group...",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        # Set the callback function for the select menu
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction) -> None:
        """
        Callback for the select menu. Updates the current group and page based on selection.

        Args:
            interaction (discord.Interaction): The interaction object.
        """
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This view is not for you.", ephemeral=True
            )
            return
        # Get the selected group from the interaction data
        selected_group = interaction.data["values"][0]
        # Defer update to allow time for image downloading
        await interaction.response.defer()

        self.load_group(selected_group)
        self.current_group = selected_group

        # Update view
        await self.update_view(interaction)

    def load_group(self, group_name) -> None:
        """
        Loads the algorithms for the specified group into algorithms_list and fetches images.

        Args:
            group_name (str): The name of the group to load.
        """
        groups = self.OLL_GROUPS if self.mode == "oll" else self.PLL_GROUPS
        data_key = self.mode

        if group_name not in groups:
            self.algorithms_list = []
            return

        # Get the algorithm IDs for the selected group
        alg_ids = groups[group_name]
        # Get the full algorithm data
        full_data = self.alg_data.get(data_key, {})

        # Load the algorithms into algorithms_list
        self.algorithms_list = []
        for alg_id in alg_ids:
            alg_str = full_data.get(alg_id, "Not found")
            self.algorithms_list.append((alg_id, alg_str))

        # Download images if client is available
        if self.blob_service_client and self.container:
            import io

            for alg_id, alg_str in self.algorithms_list:
                # Avoid re-downloading if already present
                if alg_id in self.images:
                    continue

                try:
                    blob_name = f"{self.mode}/{alg_id}.png"
                    blob_client = self.blob_service_client.get_blob_client(
                        container=self.container, blob=blob_name
                    )

                    stream = io.BytesIO()
                    blob_client.download_blob().readinto(stream)
                    stream.seek(0)
                    self.add_image(alg_id, stream)
                except Exception as e:
                    logger.error(f"Error loading image for {blob_name}: {e}")

        self.current_page = 0

    async def update_view(self, interaction: discord.Interaction) -> None:
        """
        Updates the view with the current embed and button states.

        Args:
            interaction (discord.Interaction): The interaction object.
        """
        self.update_buttons()
        embed, file = self.get_embed()
        if interaction.response.is_done():
            if file:
                # Need to reset file seek if reusing, but here we create fresh from bytes
                await interaction.edit_original_response(
                    embed=embed, view=self, attachments=[file]
                )
            else:
                await interaction.edit_original_response(
                    embed=embed, view=self, attachments=[]
                )
        else:
            if file:
                await interaction.response.edit_message(
                    embed=embed, view=self, attachments=[file]
                )
            else:
                await interaction.response.edit_message(
                    embed=embed, view=self, attachments=[]
                )

    def add_image(self, alg_id, image_data) -> None:
        """
        Adds an image data (bytes) for a specific algorithm ID.

        Args:
            alg_id (str): The algorithm ID.
            image_data (io.BytesIO): The image data.
        """
        if not hasattr(self, "images"):
            self.images = {}
        self.images[alg_id] = image_data

    def get_embed(self) -> tuple[discord.Embed, discord.File | None]:
        """
        Generates the embed for the current algorithm page.

        Returns:
            tuple: (discord.Embed, discord.File | None)
        """
        if not self.algorithms_list:
            return (
                discord.Embed(
                    title="No algorithms selected",
                    description="Please select a group from the menu.",
                    color=discord.Color.red(),
                ),
                None,
            )

        alg_id, alg_str = self.algorithms_list[self.current_page]
        title_prefix = "OLL" if self.mode == "oll" else "PLL"

        embed = discord.Embed(
            title=f"{title_prefix} Algorithms: {self.current_group}",
            color=(
                discord.Color.yellow() if self.mode == "oll" else discord.Color.green()
            ),
        )
        embed.add_field(name=f"{title_prefix} {alg_id}", value=alg_str, inline=False)
        embed.set_footer(
            text=f"Algorithm {self.current_page + 1}/{len(self.algorithms_list)}"
        )

        file = None
        if hasattr(self, "images") and alg_id in self.images:
            image_stream = self.images[alg_id]
            image_stream.seek(0)
            file = discord.File(fp=image_stream, filename=f"{alg_id}.png")
            embed.set_image(url=f"attachment://{alg_id}.png")

        return embed, file

    def update_buttons(self) -> None:
        """
        Updates the enabled/disabled state of the Back and Next buttons based on current page.
        """
        # Let's dynamically find them to be safe
        back_button = None
        next_button = None
        for x in self.children:
            if isinstance(x, discord.ui.Button):
                if x.label == "Back":
                    back_button = x
                elif x.label == "Next":
                    next_button = x

        if not self.algorithms_list:
            back_button.disabled = True
            next_button.disabled = True
        else:
            back_button.disabled = self.current_page == 0
            next_button.disabled = self.current_page == len(self.algorithms_list) - 1

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        Callback for the Back button. Moves to the previous page.

        Args:
            interaction (discord.Interaction): The interaction object.
            button (discord.ui.Button): The button object.
        """
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This view is not for you.", ephemeral=True
            )
            return

        if self.current_page > 0:
            self.current_page -= 1
            await self.update_view(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        Callback for the Next button. Moves to the next page.

        Args:
            interaction (discord.Interaction): The interaction object.
            button (discord.ui.Button): The button object.
        """
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This view is not for you.", ephemeral=True
            )
            return

        if self.current_page < len(self.algorithms_list) - 1:
            self.current_page += 1
            await self.update_view(interaction)
        else:
            await interaction.response.defer()
