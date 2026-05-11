import json
import discord
from discord.ext import commands, tasks
from database.DB_Manager import DatabaseManager
from azure.storage.blob import BlobServiceClient
import os
import requests
import logging
import datetime
import asyncio
import itertools
import zoneinfo
import aiohttp

logger = logging.getLogger(__name__)


class RubiksBot(commands.Bot):
    """
    Main Bot class for Cube Crafter.
    Handles initialization, database management, and background tasks.
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        intents.members = True
        intents.guilds = True
        self.status_index = 0
        self.server_count = 0
        self.session = None
        super().__init__(command_prefix="/", intents=intents)

        # Persistent database manager shared across the bot
        self.db_manager = DatabaseManager()


    async def setup_hook(self) -> None:
        """
        Setup hook called before the bot starts.
        Registers cogs, syncs commands, and starts background loops.
        """
        # Add the Cogs
        from cogs.scramble_commands import ScrambleCommands
        from cogs.algorithm_commands import AlgorithmCommands
        from cogs.solve_commands import SolveCommands
        from cogs.daily_commands import DailyCommands
        from cogs.reminder_commands import ReminderCommands
        from cogs.meta_commands import MetaCommands

        for cog_cls in (
            ScrambleCommands,
            AlgorithmCommands,
            SolveCommands,
            DailyCommands,
            ReminderCommands,
            MetaCommands,
        ):
            await self.add_cog(cog_cls(self))
        # set up ClientSessions
        self.session = aiohttp.ClientSession()
        # Sync application commands with Discord
        if os.getenv("ENV", "").upper() == "PROD":
            await self.tree.sync()
            logger.info("Commands synced globally.")
        else:
            guild_id = os.getenv("GUILD_ID")
            if guild_id:
                dev_guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=dev_guild)
                await self.tree.sync(guild=dev_guild)
                logger.info(f"Commands synced with development guild: {guild_id}")
            else:
                logger.warning("GUILD_ID not found in environment. Skipping guild sync.")

        # Start background tasks for database health and stats reporting
        if not self.keep_database_alive.is_running():
            logger.info("Starting keep-alive task...")
            self.keep_database_alive.start()

        if not self.update_topgg.is_running():
            logger.info("Starting updating topgg...")
            self.update_topgg.start()

        if not self.update_discordbotlist.is_running():
            logger.info("Starting updating discordbotlist...")
            self.update_discordbotlist.start()

        if not self.get_servers_count.is_running():
            logger.info("Starting get servers count task...")
            self.get_servers_count.start()

        if not self.daily_scramble_task.is_running():
            logger.info("Starting daily scramble task...")
            self.daily_scramble_task.start()

        if not self.daily_reminder_task.is_running():
            logger.info("Starting daily reminder task...")
            self.daily_reminder_task.start()

    async def on_ready(self) -> None:
        """
        Triggered when the bot is fully connected and ready.
        """
        logger.info(f"We have logged as an {self.user}")
        if not self.rotate_status.is_running():
            logger.info("Starting roatate statuses")
            self.rotate_status.start()
        # Initialize the shared database connection
        try:
            self.db_manager.connect()
            await self.check_and_generate_daily_scramble()
        except Exception as e:
            logger.error(f"Failed to initialize database connection: {e}")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """
        Triggered when joining a server. Sends a welcome embed inviting the
        guild to the support server.

        Input:
            guild (discord.Guild): The guild the bot just joined.
        Output:
            None
        """
        logger.info(f"Joined guild {guild.id} ({guild.name})")
        server_link = "https://discord.com/invite/sq4Qa9vavc"
        embed = discord.Embed(
            title="Welcome to Cube Crafter",
            description=(
                f"Thank you for using Cube Crafter — use /help to learn more "
                f"and join our support [server]({server_link}) if you need more assistance."
            ),
        )
        # finding channel that message can be send
        channel = guild.system_channel
        if channel is None or not channel.permissions_for(guild.me).send_messages:
            channel = next(
                (
                    c
                    for c in guild.text_channels
                    if c.permissions_for(guild.me).send_messages
                    and c.permissions_for(guild.me).embed_links
                ),
                None,
            )
        if channel is None:
            logger.info(f"No writable channel in guild {guild.id}; skipping welcome.")
            return
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logger.info(f"Welcome send forbidden in guild {guild.id}.")
        except discord.HTTPException as e:
            logger.warning(f"Welcome send failed for guild {guild.id}: {e}")


    async def on_disconnect(self) -> None:
        """
        Cleanup logic when the bot disconnects.
        """
        self.db_manager.close()
        await self.session.close()

    @tasks.loop(minutes=5)
    async def keep_database_alive(self) -> None:
        """
        Background task to prevent Azure SQL from going idle.
        """
        logger.debug("Executing keep-alive query...")
        self.db_manager.keep_alive()
    
    @tasks.loop(minutes=15)
    async def rotate_status(self) -> None:
        statuses = [
            discord.Activity(type=discord.ActivityType.watching, name=f"/scramble for {self.server_count} servers"),
            discord.Activity(type=discord.ActivityType.competing, name="Competing in /daily"),
            discord.Activity(type=discord.ActivityType.watching, name="Begging for review on https://top.gg/bot/1197268536918278236")
        ]
        await self.change_presence(activity=statuses[self.status_index % len(statuses)])
        self.status_index = (self.status_index + 1) % len(statuses)

    @rotate_status.before_loop
    async def before_rotate_status(self):
        """
        Wait for full sync
        """
        await self.wait_until_ready()

    @tasks.loop(minutes=60)
    async def get_servers_count(self) -> int:
        """
        Get the current number of servers the bot is in.
        """
        url = "https://discord.com/api/v10/users/@me/guilds?limit=200"

        token = os.getenv("TOKEN")
        
        headers = {
            'Authorization': f'Bot {token}',
        }

        async with self.session.get(url, headers=headers) as response:
            if response.status == 200:
                guilds = await response.json()
                logger.info(f"Retrieved {len(guilds)} guilds from Discord API")
                self.server_count = len(guilds)
            else:
                error_text = await response.text()
                logger.error(f"Failed to get guilds: {response.status} - {error_text}")
        return self.server_count
    
    
    @tasks.loop(minutes=60)
    async def update_topgg(self) -> None:
        """
        Post bot stats to Top.gg (Production only).
        """

        servers = int(self.server_count if self.server_count > 0 else await self.get_servers_count())
        id = os.getenv("APPLICATION_ID")
        token = os.getenv("TOPGG_TOKEN")
        url = f"https://top.gg/api/bots/{id}/stats"
        payload = {"server_count": servers}
        headers = {"Authorization": token}

        try:
            async with self.session.post(url=url, json=payload, headers=headers) as response:
                if response.status == 200:
                    logger.info(f"Posted server count ({servers}) to Top.gg")
                else:
                    logger.error(
                        f"Failed to post to Top.gg: {response.status} - {await response.text()}"
                    )
        except Exception as e:
            logger.error(f"Error posting to Top.gg: {e}")
    @update_topgg.before_loop
    async def before_update_topgg(self):
        await self.wait_until_ready()


    @tasks.loop(minutes=60)
    async def update_discordbotlist(self) -> None:
        """
        Post bot stats to DiscordBotList (Production only).
        """
        servers = self.server_count if self.server_count > 0 else await self.get_servers_count()
        id = os.getenv("APPLICATION_ID")
        token = os.getenv("BOTLIST_TOKEN")
        url = f"https://discordbotlist.com/api/v1/bots/{id}/stats"
        params = {"guilds": servers}
        headers = {"Authorization": token}

        try:
            async with self.session.post(url=url, json=params, headers=headers) as response:
                if response.status == 200:
                    logger.info(f"Posted server count ({servers}) to DBL")
                else:
                    logger.error(
                        f"Failed to post to DBL: {response.status} - {await response.text()}"
                    )
        except Exception as e:
            logger.error(f"Error posting to DBL: {e}")
    @update_discordbotlist.before_loop
    async def before_update_discordbotlist(self):
        await self.wait_until_ready()
    
    async def check_and_generate_daily_scramble(self) -> None:
        """
        Checks if a daily scramble exists for the current UTC date.
        If not, generates one and saves it to the database.
        """
        today = datetime.datetime.now(datetime.timezone.utc).date()
        try:
            # Check if scramble exists
            self.db_manager.cursor.execute(
                "SELECT 1 FROM DailyScramble WHERE ScrambleDate = ?", (today,)
            )
            if self.db_manager.cursor.fetchone():
                logger.info("Daily scramble for today already exists.")
                return

            logger.info("Generating daily scramble...")
            puzzle_api_value = "THREE"
            puzzle_display_name = "3x3"
            
            url = "https://scrambler-api-apim.azure-api.net/scrambler-api/GetScramble"
            params = {"puzzle": puzzle_api_value}

            # Use run_in_executor to avoid blocking the event loop with requests
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, lambda: requests.get(url=url, params=params))

            if response.status_code == 200:
                response_json = response.json()
                scramble_string = response_json["scramble"]
                image_string = response_json["image"]
                
                query = "INSERT INTO DailyScramble (ScrambleText, ScrambleDate, PuzzleType, ImageString) VALUES (?, ?, ?, ?)"
                self.db_manager.cursor.execute(query, (scramble_string, today, puzzle_display_name, image_string))
                self.db_manager.cursor.commit()
                logger.info(f"Daily scramble generated: {scramble_string}")
            else:
                logger.error(f"Failed to generate daily scramble: {response.status_code} - {response.text}")

        except Exception as e:
            logger.error(f"Error checking/generating daily scramble: {e}")

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc))
    async def daily_scramble_task(self) -> None:
        """
        Generates a daily scramble for 3x3 at 00:00 UTC.
        """
        await self.check_and_generate_daily_scramble()

    async def _send_reminder_dm(self, discord_id: int) -> None:
        """
        Sends the daily reminder DM to a user.

        Best-effort: silently swallows Forbidden (DMs blocked) and other HTTP
        errors so the reminder loop keeps moving.

        Input:
            discord_id (int): The Discord user ID to DM.
        Output:
            None
        """
        try:
            user = await self.fetch_user(discord_id)
            await user.send(
                "⏰ Time for your daily Rubik's scramble! "
                "Run `/daily` in any server with the bot. \n Please give us a vote or review on https://top.gg/bot/1197268536918278236"
            )
        except discord.Forbidden:
            logger.info(f"DMs blocked for {discord_id}; skipping reminder.")
        except discord.HTTPException as e:
            logger.warning(f"Reminder DM failed for {discord_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected reminder DM failure for {discord_id}: {e}")

    @tasks.loop(minutes=1)
    async def daily_reminder_task(self) -> None:
        """
        Per-minute loop that sends daily reminder DMs to opted-in users.

        For each active reminder, computes the user's local time, fires a DM
        once their preferred time is reached, and skips if they've already
        completed today's daily. LastSentDate is keyed off the user's local
        date, not UTC, so each user gets exactly one reminder per local day.
        """
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        try:
            self.db_manager.cursor.execute(
                "SELECT r.ReminderID, r.UserID, u.DiscordID, r.ReminderTime, "
                "r.Timezone, r.LastSentDate "
                "FROM DailyReminders r JOIN Users u ON u.UserID = r.UserID "
                "WHERE r.IsActive = 1"
            )
            rows = self.db_manager.cursor.fetchall()
        except Exception as e:
            logger.error(f"Reminder query failed: {e}")
            return

        for reminder_id, db_uid, discord_id, hhmm, tz_name, last_sent in rows:
            try:
                tz = zoneinfo.ZoneInfo(tz_name)
            except zoneinfo.ZoneInfoNotFoundError:
                logger.warning(
                    f"Reminder {reminder_id} has invalid timezone {tz_name}; skipping."
                )
                continue
            # getting local time in the user timezone
            local_now = now_utc.astimezone(tz)
            local_today = local_now.date()
            if last_sent == local_today: # time zone roll back, already sent
                continue

            try:
                target_h, target_m = (int(p) for p in hhmm.split(":"))
            except ValueError:
                logger.warning(
                    f"Reminder {reminder_id} has malformed time {hhmm}; skipping."
                )
                continue

            if (local_now.hour, local_now.minute) < (target_h, target_m): # time already passed
                continue

            # checking if user already solve the daily
            try:
                self.db_manager.cursor.execute(
                    "SELECT 1 FROM DailySolves WHERE UserID=? AND SolveDate=?",
                    (db_uid, local_today),
                )
                already_solved = self.db_manager.cursor.fetchone()
            except Exception as e:
                logger.error(f"DailySolves lookup failed for {db_uid}: {e}")
                continue

            if not already_solved:
                await self._send_reminder_dm(discord_id)
            # set last sent
            try:
                self.db_manager.cursor.execute(
                    "UPDATE DailyReminders SET LastSentDate=?, "
                    "UpdatedAt=GETUTCDATE() WHERE ReminderID=?",
                    (local_today, reminder_id),
                )
                self.db_manager.connection.commit()
            except Exception as e:
                logger.error(
                    f"Failed to mark reminder {reminder_id} as sent: {e}"
                )

    @daily_reminder_task.before_loop
    async def before_daily_reminder_task(self) -> None:
        """
        Wait until the bot is fully connected before starting the reminder loop.
        """
        await self.wait_until_ready()