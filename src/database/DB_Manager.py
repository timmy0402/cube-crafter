import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import aioodbc
import pyodbc

logger = logging.getLogger(__name__)


def _error_chain(error: BaseException) -> list[BaseException]:
    """Include errors hidden by driver cleanup, without looping on cycles."""
    chain = []
    seen = set()
    while error is not None and id(error) not in seen:
        chain.append(error)
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return chain


def _sqlstate(error: BaseException) -> str | None:
    """Extract a valid ODBC error code for classification and safe logging."""
    if isinstance(error, pyodbc.Error) and error.args:
        state = error.args[0]
        if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state):
            return state
    return None


def _is_disconnect(error: BaseException) -> bool:
    """Identify connection failures, including those hidden by cleanup errors."""
    for cause in _error_chain(error):
        state = _sqlstate(cause)
        if state is not None and state.startswith("08"):
            return True
        if isinstance(cause, pyodbc.ProgrammingError) and cause.args and cause.args[0] in (
            "The cursor's connection has been closed.",
            "Attempt to use a closed connection.",
        ):
            return True
        if state == "HY000" and len(cause.args) > 1:
            if str(cause.args[1]).startswith("[HY000] server closed the connection unexpectedly"):
                return True
    return False


def _error_summary(error: BaseException) -> str:
    """Log types and SQLSTATEs only; driver messages may contain secrets."""
    return " -> ".join(
        f"{type(cause).__name__}(sqlstate={_sqlstate(cause) or 'unknown'})"
        for cause in _error_chain(error)
    )


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
        self._pool_lock = asyncio.Lock()
        self._closed = False

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
            RuntimeError: when retries are exhausted or the manager is closed.
        """
        async with self._pool_lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        """Create a pool while holding the lifecycle lock."""
        if self._closed:
            raise RuntimeError("Database manager is closed")
        if self._pool is not None:
            return

        logger.info("Connecting database pool")
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self._pool = await aioodbc.create_pool(
                    dsn=self._dsn, minsize=2, maxsize=10
                )
                logger.info("DB connected successfully")
                return
            except Exception as e:
                logger.warning(
                    "Connection attempt %s failed (%s)", attempt + 1, type(e).__name__
                )
                if attempt < max_attempts - 1:
                    logger.info("Waiting for 5 seconds before retrying...")
                    await asyncio.sleep(5)
        logger.error("Database connection retries exhausted; pool remains unavailable")
        raise RuntimeError("Unable to connect to DB after 3 attempts")

    async def close(self) -> None:
        """
        Permanently close the manager and release all underlying connections.

        Input:
            None
        Output:
            None
        """
        async with self._pool_lock:
            self._closed = True
            await self._close_pool_locked()

    async def _close_pool_locked(self) -> None:
        """Drain the pool while preventing new borrowers."""
        if self._pool is not None:
            try:
                self._pool.close()
                await self._pool.wait_closed()
                logger.info("DB connection closed")
            except Exception as e:
                logger.error("Error closing database connection: %s", _error_summary(e))
            finally:
                self._pool = None

    @asynccontextmanager
    async def _borrow(self, pool: aioodbc.Pool) -> AsyncIterator[aioodbc.Connection]:
        """Borrow a connection and wake waiting tasks if it closes during use."""
        connection = None
        try:
            async with pool.acquire() as connection:
                yield connection
        finally:
            if connection is not None and connection.closed:
                # aioodbc 0.5.0 release() does not notify waiters when a closed
                # connection is removed. Wake borrowers and wait_closed() after
                # release so a disconnect cannot strand them indefinitely.
                await pool._wakeup()

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aioodbc.Connection]:
        """Wait for recovery, then borrow a connection without serializing queries."""
        async with AsyncExitStack() as stack:
            async with self._pool_lock:
                await self._connect_locked()
                connection = await stack.enter_async_context(self._borrow(self._pool))
            # Release outside the lock so recovery can drain active queries.
            yield connection

    async def _discard_connection(self, conn: aioodbc.Connection) -> None:
        """Close a failed connection before it is returned to the pool."""
        if not conn.closed:
            try:
                await conn.close()
            except Exception as error:
                logger.error("Database connection close failed: %s", _error_summary(error))

    @asynccontextmanager
    async def _cursor(self, conn: aioodbc.Connection) -> AsyncIterator[aioodbc.Cursor]:
        """Commit successful work and clean up failures without hiding the original error."""
        cursor = None
        try:
            # Manage cleanup ourselves: aioodbc's context manager rolls back even
            # when its error handling has already closed the connection.
            cursor = await conn.cursor()
            yield cursor
            if not conn.autocommit:
                await cursor.commit()
        except BaseException as error:
            if _is_disconnect(error) or isinstance(error, asyncio.CancelledError):
                await self._discard_connection(conn)
            elif not conn.closed and cursor is not None:
                try:
                    await cursor.rollback()
                    await cursor.close()
                except Exception as cleanup_error:
                    logger.warning(
                        "Database cursor cleanup failed: %s; preserving original %s",
                        _error_summary(cleanup_error), _error_summary(error),
                    )
                    await self._discard_connection(conn)
            raise
        else:
            try:
                await cursor.close()
            except Exception:
                await self._discard_connection(conn)
                raise

    async def _read(self, operation: str, query: str, params: tuple):
        """Retry a disconnected read once using another pooled connection."""
        for attempt in range(3):
            try:
                async with self._connection() as conn:
                    async with self._cursor(conn) as cur:
                        await cur.execute(query, params)
                        return await getattr(cur, operation)()
            except Exception as error:
                retry = attempt == 0 and _is_disconnect(error)
                logger.log(
                    logging.WARNING if retry else logging.ERROR,
                    "Database %s failed: %s; retry=%s",
                    operation, _error_summary(error), retry,
                )
                if not retry:
                    raise

    async def fetchone(self, query: str, params: tuple = ()) -> tuple | None:
        """
        Run a SELECT and return a single row, or None if no row matched.

        Input:
            query (str): Parameterized SQL statement.
            params (tuple): Positional bind parameters for the statement.
        Output:
            tuple | None: The first row, or None.
        """
        return await self._read("fetchone", query, params)

    async def fetchall(self, query: str, params: tuple = ()) -> list[tuple]:
        """
        Run a SELECT and return all matching rows.

        Input:
            query (str): Parameterized SQL statement.
            params (tuple): Positional bind parameters for the statement.
        Output:
            list[tuple]: Every row returned by the query (empty list if none).
        """
        return await self._read("fetchall", query, params)

    async def execute(self, query: str, params: tuple = ()) -> None:
        """
        Run an INSERT/UPDATE/DELETE and commit on success.

        Input:
            query (str): Parameterized SQL statement.
            params (tuple): Positional bind parameters for the statement.
        Output:
            None
        """
        try:
            async with self._connection() as conn:
                async with self._cursor(conn) as cur:
                    await cur.execute(query, params)
        except Exception as error:
            # A lost commit response leaves the outcome unknown. Never replay it.
            logger.error("Database execute failed: %s; retry=False", _error_summary(error))
            raise

    async def keep_alive(self) -> None:
        """
        Run a lightweight SELECT 1 to keep an idle Azure SQL connection warm.

        Reconnects automatically if the pool is missing or the probe fails.

        Input:
            None
        Output:
            None
        """
        async with self._pool_lock:
            await self._connect_locked()
            try:
                async with self._borrow(self._pool) as conn:
                    async with self._cursor(conn) as cur:
                        await cur.execute("SELECT 1")
                        await cur.fetchone()
                logger.debug("Keep-alive query executed successfully.")
            except Exception as e:
                logger.warning(
                    "Database recovery started after keep-alive failure (%s)",
                    _error_summary(e),
                )
                await self._close_pool_locked()
                await self._connect_locked()
                logger.info("Database recovery completed")
