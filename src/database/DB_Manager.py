import asyncio
import aioodbc
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages the async connection pool for the Azure SQL Database.
    Handles pool lifecycle, reconnection logic, and keep-alive ticks.
    """

    def __init__(self, dsn: str) -> None:
        """
        Initialize the manager with a DSN; the pool is created lazily by connect().

        Input:
            dsn (str): ODBC connection string used by aioodbc.create_pool.
        Output:
            None
        """
        self._dsn = dsn
        self._pool: aioodbc.Pool | None = None

    async def connect(self) -> None:
        """
        Create the aioodbc connection pool with retry/backoff.

        No-op if a pool already exists (prevents leaking pools when called
        from both on_ready/setup_hook and the keep-alive recovery path).

        Input:
            None
        Output:
            None
        Raises:
            RuntimeError: when all retry attempts have been exhausted.
        """
        # Guard against double-init from concurrent call sites (on_ready
        # re-fires on resume, keep_alive calls us on recovery).
        if self._pool is not None:
            return

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self._pool = await aioodbc.create_pool(
                    dsn=self._dsn, minsize=2, maxsize=10
                )
                logger.info("DB connected successfully")
                return
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    logger.info("Waiting for 5 seconds before retrying...")
                    await asyncio.sleep(5)
        raise RuntimeError("Unable to connect to DB after 3 attempts")

    async def close(self) -> None:
        """
        Close the connection pool and release all underlying connections.

        Input:
            None
        Output:
            None
        """
        if self._pool:
            try:
                self._pool.close()
                await self._pool.wait_closed()
                logger.info("DB connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")
            finally:
                self._pool = None

    async def fetchone(self, query: str, params: tuple = ()) -> tuple | None:
        """
        Run a SELECT and return a single row, or None if no row matched.

        Input:
            query (str): Parameterized SQL statement.
            params (tuple): Positional bind parameters for the statement.
        Output:
            tuple | None: The first row, or None.
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> list[tuple]:
        """
        Run a SELECT and return all matching rows.

        Input:
            query (str): Parameterized SQL statement.
            params (tuple): Positional bind parameters for the statement.
        Output:
            list[tuple]: Every row returned by the query (empty list if none).
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                return await cur.fetchall()

    async def execute(self, query: str, params: tuple = ()) -> None:
        """
        Run an INSERT/UPDATE/DELETE and commit on success.

        Input:
            query (str): Parameterized SQL statement.
            params (tuple): Positional bind parameters for the statement.
        Output:
            None
        """
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                await cur.commit()

    async def keep_alive(self) -> None:
        """
        Run a lightweight SELECT 1 to keep an idle Azure SQL connection warm.

        Reconnects automatically if the pool is missing or the probe fails.

        Input:
            None
        Output:
            None
        """
        if not self._pool:
            logger.warning("No active pool found. Attempting to reconnect.")
            await self.connect()
        try:
            await self.fetchone("SELECT 1")
            logger.debug("Keep-alive query executed successfully.")
        except Exception as e:
            logger.error(f"Error during keep-alive query: {e}")
            # Reconnect if the connection was lost. Drop the stale pool first
            # so the connect() guard doesn't short-circuit.
            await self.close()
            await self.connect()
