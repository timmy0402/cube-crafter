import time
import logging
import discord

from stats import update_user_pbs
from database import DatabaseManager
from stats.personal_best import calculate_wca_avg, update_user_average_best

logger = logging.getLogger(__name__)


class TimerView(discord.ui.View):
    """
    A discord.ui.View that provides an interactive stopwatch for users to time their cube solves.
    """

    def __init__(
        self,
        *,
        timeout: float | None = 180,
        is_daily: bool = False,
        user_id: int,
        userName: str,
        puzzle: str,
        db_manager: DatabaseManager,
    ) -> None:
        """
        Initialize the TimerView.

        Args:
            timeout (float | None): The timeout for the view in seconds.
            user_id (int): The Discord ID of the user who started the timer.
            userName (str): The name of the user.
            puzzle (str): The type of puzzle being timed (e.g., '3x3').
            db_manager: The database manager instance.
        """
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.user_name = userName
        self.puzzle = puzzle
        self.db_manager = db_manager
        self.message = None
        self.is_daily = is_daily
        self.start_time = None
        self.end_time = None
        self.base_time = 0.0
        self.solve_status = "Completed"  # Completed, +2, DNF

        # Check if the user exists in the database, if not create a new entry
        self.db_id = self._get_or_create_user()

    def _get_or_create_user(self) -> int:
        """
        Retrieves the internal UserID from the database, creating a new user record if necessary.

        Returns:
            int: The UserID from the database.
        """
        try:
            # Check for existing user
            self.db_manager.cursor.execute(
                "SELECT UserID FROM Users WHERE DiscordID=?", (self.user_id,)
            )
            db_id = self.db_manager.cursor.fetchval()

            if not db_id:
                # Insert new user if not found
                self.db_manager.cursor.execute(
                    "INSERT INTO Users(UserName, DiscordID) VALUES(?, ?)",
                    (self.user_name, self.user_id),
                )
                self.db_manager.connection.commit()

                # Fetch the newly created UserID
                self.db_manager.cursor.execute(
                    "SELECT UserID FROM Users WHERE DiscordID=?", (self.user_id,)
                )
                db_id = self.db_manager.cursor.fetchval()

            return db_id
        except Exception as e:
            logger.error(f"Error in _get_or_create_user: {e}")
            return None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Ensures that only the user who started the timer can interact with it.

        Args:
            interaction (discord.Interaction): The interaction object.

        Returns:
            bool: True if the user is authorized, False otherwise.
        """
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You cannot interact with this timer.", ephemeral=True
            )
            return False
        return True

    async def disable_all_items(self) -> None:
        """
        Disables all buttons in the view and updates the message if it exists.
        """
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception as e:
                logger.error(f"Error in disable_all_items: {e}")

    async def on_timeout(self) -> None:
        """
        Handles the view timeout by notifying the user and disabling buttons.
        """
        try:
            if self.message:
                # Notify the user about the timeout
                await self.message.channel.send(
                    f"<@{self.user_id}>, your timer session has timed out.",
                    delete_after=10
                )
            await self.disable_all_items()
        except Exception as e:
            logger.error(f"Error handling on_timeout: {e}")

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
    async def start_timer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """
        Starts the timer and updates the UI to show timing is in progress.

        Args:
            interaction (discord.Interaction): The interaction object.
            button (discord.ui.Button): The button that was clicked.
        """
        self.start_time = time.time()

        # Disable the start button once timing begins
        button.disabled = True

        embed = discord.Embed(
            title="Timer Started!",
            description=f"Currently timing your **{self.puzzle}** solve.\nClick **Stop** when you are finished.",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary)
    async def stop_timer(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """
        Stops the timer and transitions to the review phase.
        """
        if self.start_time is None:
            await interaction.response.send_message(
                "You must start the timer first!", ephemeral=True
            )
            return

        self.end_time = time.time()
        self.base_time = round(self.end_time - self.start_time, 2)
        self.solve_status = "Completed"

        # Transition to Review Mode
        self.clear_items()
        
        # Add Review Buttons
        confirm_btn = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.success)
        confirm_btn.callback = self.confirm_callback
        self.add_item(confirm_btn)

        plus2_btn = discord.ui.Button(label="+2", style=discord.ButtonStyle.secondary)
        plus2_btn.callback = self.plus2_callback
        self.add_item(plus2_btn)

        dnf_btn = discord.ui.Button(label="DNF", style=discord.ButtonStyle.danger)
        dnf_btn.callback = self.dnf_callback
        self.add_item(dnf_btn)

        # Daily deletetion not allowed
        if not self.is_daily:
            delete_btn = discord.ui.Button(label="Delete", style=discord.ButtonStyle.danger)
            delete_btn.callback = self.delete_callback
            self.add_item(delete_btn)

        embed = self._get_review_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def _get_review_embed(self) -> discord.Embed:
        """Helper to generate the review embed based on current status."""
        time_display = f"{self.base_time}s"
        
        if self.solve_status == "+2":
            time_display = f"{self.base_time + 2:.2f}s (+2)"
        elif self.solve_status == "DNF":
            time_display = f"DNF ({self.base_time}s)"

        embed = discord.Embed(
            title="Review Result",
            description=f"Time: **{time_display}**\n\nConfirm to save, or adjust status.",
            color=discord.Color.orange()
        )
        return embed

    async def plus2_callback(self, interaction: discord.Interaction) -> None:
        if self.solve_status == "+2":
            self.solve_status = "Completed"
        else:
            self.solve_status = "+2"
        
        await interaction.response.edit_message(embed=self._get_review_embed(), view=self)

    async def dnf_callback(self, interaction: discord.Interaction) -> None:
        if self.solve_status == "DNF":
            self.solve_status = "Completed"
        else:
            self.solve_status = "DNF"
        
        await interaction.response.edit_message(embed=self._get_review_embed(), view=self)

    async def delete_callback(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Solve Discarded",
            description="You deleted this solve.",
            color=discord.Color.red()
        )
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def confirm_callback(self, interaction: discord.Interaction) -> None:
        """
        Saves the result to the database and shows statistics.
        """
        # Calculate final time based on status
        final_time = self.base_time
        if self.solve_status == "+2":
            final_time += 2
        
        # Save the result to the database
        if self.db_id is None:
            logger.error("Cannot save solve time: User database ID is missing.")
            await interaction.response.send_message(
                "An error occurred: Your user record could not be found. Time not saved.",
                ephemeral=True
            )
            return

        try:
            # Save the solve time to the database
            self.db_manager.cursor.execute(
                "INSERT INTO SolveTimes(UserID, SolveTime, PuzzleType, SolveStatus) VALUES(?, ?, ?, ?)",
                (self.db_id, final_time, self.puzzle, self.solve_status),
            )
            self.db_manager.connection.commit()
            
            # Update the user's personal best if this solve is better
            # Note: DNF is handled by passing status-aware time or handling it in update_user_pbs logic
            # Current update_user_pbs assumes float time. DNF usually effectively infinite.
            # We will pass float('inf') for DNF for PB calculation
            calc_time = final_time if self.solve_status != "DNF" else float('inf')
            
            is_new_pb = update_user_pbs(self.db_manager, self.db_id, self.puzzle, calc_time)

            # Fetch last 15 solves for the specific puzzle to calculate averages
            self.db_manager.cursor.execute(
                "SELECT TOP 15 SolveTime, SolveStatus FROM SolveTimes WHERE UserID=? AND PuzzleType=? ORDER BY SolveAt DESC, TimeID DESC",
                (self.db_id, self.puzzle)
            )
            rows = self.db_manager.cursor.fetchall()

            raw_times = []
            for r in rows:
                t = float(r[0])
                s = r[1]
                if s == "DNF":
                    raw_times.append(float('inf'))
                else:
                    raw_times.append(t)

            ao5 = calculate_wca_avg(raw_times, 5)
            ao12 = calculate_wca_avg(raw_times, 12)
            
            is_new_ao5, is_new_ao12 = update_user_average_best(self.db_manager, self.db_id, self.puzzle, ao5, ao12)
            
            # Saving to daily
            if self.is_daily:
                self.db_manager.cursor.execute(
                    "INSERT INTO DailySolves (UserID, SolveTime, SolveStatus)" \
                    "VALUES (?,?,?)",(self.db_id, final_time, self.solve_status)
                )
                self.db_manager.cursor.commit()

        except Exception as e:
            logger.error(f"Error saving solve time to database: {e}")
            await interaction.response.send_message(
                "Failed to save your time to the database.", ephemeral=True
            )
            return
        
        # Prepare the completion embed
        pb_messages = []
        if is_new_pb:
            pb_messages.append("✨ **New Personal Best Single!**")
        if is_new_ao5:
            pb_messages.append("🎉 **New Personal Best Ao5!**")
        if is_new_ao12:
            pb_messages.append("🎊 **New Personal Best Ao12!**")

        time_str = f"{final_time:.2f}s"
        if self.solve_status == "+2":
             time_str += " (+2)"
        elif self.solve_status == "DNF":
             time_str = "DNF"

        description = f"**{self.user_name}'s {self.puzzle}** time is: **{time_str}**\n"
        
        if pb_messages:
            description += "\n" + "\n".join(pb_messages) + "\n"
        else:
            description += "Your record has been saved.\n"

        embed = discord.Embed(
            title="Solve Completed!",
            description=description,
            color=discord.Color.gold() if pb_messages else discord.Color.green(),
        )

        if ao5:
            embed.add_field(name="Current Ao5", value=f"{ao5:.2f}s", inline=True)
        if ao12:
            embed.add_field(name="Current Ao12", value=f"{ao12:.2f}s", inline=True)
        
        embed.set_footer(text=f"Puzzle: {self.puzzle}")

        # Disable all buttons upon completion
        self.clear_items()

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        Cancels the current timer session.

        Args:
            interaction (discord.Interaction): The interaction object.
            button (discord.ui.Button): The button that was clicked.
        """
        embed = discord.Embed(
            title="Timer Cancelled",
            description="The timing session was cancelled by the user.",
            color=discord.Color.red()
        )
        
        # Disable all buttons upon cancellation
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()