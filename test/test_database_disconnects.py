import asyncio
from collections import deque
from unittest.mock import AsyncMock

import aioodbc
import pyodbc
import pytest
from aioodbc.connection import Connection

from database.DB_Manager import DatabaseManager, _is_disconnect


class DriverConnection:
    """Simulated ODBC handle used underneath real aioodbc cursors and pools."""

    def __init__(self, *, failure_at=None, error=None, rollback_error=None):
        self.closed = False
        self.autocommit = False
        self.failure_at = failure_at
        self.error = error
        self.rollback_error = rollback_error
        self.calls = []

    def cursor(self):
        if self.failure_at == "cursor":
            raise self.error
        return DriverCursor(self)

    def close(self):
        self.calls.append("connection.close")
        self.closed = True


class DriverCursor:
    def __init__(self, connection):
        self.connection = connection

    def run(self, operation):
        self.connection.calls.append(operation)
        if self.connection.closed:
            raise pyodbc.ProgrammingError("The cursor's connection has been closed.")
        if operation == self.connection.failure_at:
            raise self.connection.error

    def execute(self, *args):
        self.run("execute")

    def fetchone(self):
        self.run("fetchone")
        return (42,)

    def fetchall(self):
        self.run("fetchall")
        return [(42,)]

    def commit(self):
        self.run("commit")

    def rollback(self):
        self.run("rollback")
        if self.connection.rollback_error is not None:
            raise self.connection.rollback_error

    def close(self):
        self.run("cursor.close")


async def make_manager(monkeypatch, *drivers):
    remaining = deque(drivers)

    async def connect(**kwargs):
        connection = Connection(dsn="simulation-only")
        connection._conn = remaining.popleft()
        return connection

    connect_mock = AsyncMock(side_effect=connect)
    monkeypatch.setattr("aioodbc.pool.connect", connect_mock)
    manager = DatabaseManager("simulation-only")
    manager._pool = await aioodbc.create_pool(
        dsn="simulation-only", minsize=0, maxsize=1,
    )
    return manager, connect_mock


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["fetchone", "fetchall"])
@pytest.mark.parametrize("failure_at", ["cursor", "execute", "fetch", "commit", "cursor.close"])
async def test_read_retries_disconnect_on_fresh_connection(monkeypatch, method, failure_at, caplog):
    original = pyodbc.OperationalError("08S01", "sensitive-driver-detail")
    broken = DriverConnection(
        failure_at=method if failure_at == "fetch" else failure_at, error=original,
    )
    healthy = DriverConnection()
    manager, connect = await make_manager(monkeypatch, broken, healthy)
    try:
        result = await getattr(manager, method)("SELECT secret_column", ("secret-param",))

        assert result == ((42,) if method == "fetchone" else [(42,)])
        assert connect.await_count == 2
        assert broken.closed
        assert "rollback" not in broken.calls
        assert healthy.calls.count("execute") == 1
        assert "08S01" in caplog.text
        for secret in ("sensitive-driver-detail", "secret_column", "secret-param"):
            assert secret not in caplog.text
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_read_disconnect_retry_is_bounded_and_preserves_original(monkeypatch):
    first = pyodbc.OperationalError("08S01", "first disconnect")
    second = pyodbc.OperationalError("08S01", "second disconnect")
    drivers = [DriverConnection(failure_at="execute", error=error) for error in (first, second)]
    manager, connect = await make_manager(monkeypatch, *drivers)
    try:
        with pytest.raises(pyodbc.OperationalError) as caught:
            await manager.fetchall("SELECT reminders")

        assert caught.value is second
        assert connect.await_count == 2
        assert all(driver.closed for driver in drivers)
        assert all("rollback" not in driver.calls for driver in drivers)
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("chained", [False, True])
async def test_read_discards_closed_connection_error(monkeypatch, chained):
    error = pyodbc.ProgrammingError("The cursor's connection has been closed.")
    if chained:
        wrapper = RuntimeError("cleanup failed")
        wrapper.__cause__ = error
        error = wrapper
    driver = DriverConnection(failure_at="execute", error=error)
    manager, connect = await make_manager(monkeypatch, driver, DriverConnection())
    try:
        assert await manager.fetchall("SELECT reminders") == [(42,)]
        assert driver.closed
        assert connect.await_count == 2
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rollback_fails", [False, True])
async def test_sql_error_is_not_retried_or_hidden_by_cleanup(monkeypatch, rollback_fails, caplog):
    original = pyodbc.ProgrammingError("42000", "sensitive query error")
    cleanup = pyodbc.OperationalError("08S01", "sensitive rollback error")
    driver = DriverConnection(
        failure_at="execute", error=original,
        rollback_error=cleanup if rollback_fails else None,
    )
    manager, connect = await make_manager(monkeypatch, driver)
    try:
        with pytest.raises(pyodbc.ProgrammingError) as caught:
            await manager.fetchall("SELECT invalid")

        assert caught.value is original
        assert connect.await_count == 1
        assert driver.calls.count("rollback") == 1
        assert driver.closed == rollback_fails
        assert "42000" in caplog.text
        assert "sensitive" not in caplog.text
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", ["execute", "commit"])
async def test_write_disconnect_is_never_replayed(monkeypatch, failure_at):
    original = pyodbc.OperationalError("08S01", "uncertain write outcome")
    driver = DriverConnection(failure_at=failure_at, error=original)
    manager, connect = await make_manager(monkeypatch, driver)
    try:
        with pytest.raises(pyodbc.OperationalError) as caught:
            await manager.execute("INSERT solve", (42,))

        assert caught.value is original
        assert connect.await_count == 1
        assert driver.calls.count("execute") == 1
        assert driver.closed
        assert "rollback" not in driver.calls
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_successful_write_commits_once(monkeypatch):
    driver = DriverConnection()
    manager, _ = await make_manager(monkeypatch, driver)
    try:
        await manager.execute("INSERT solve", (42,))
        assert driver.calls == ["execute", "commit", "cursor.close"]
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting_operation", ["read", "shutdown"])
async def test_disconnect_wakes_waiting_borrower_or_shutdown(monkeypatch, waiting_operation):
    broken = DriverConnection(
        failure_at="execute", error=pyodbc.OperationalError("08S01", "disconnect"),
    )
    manager, _ = await make_manager(monkeypatch, broken, DriverConnection())
    started = asyncio.Event()
    finish = asyncio.Event()
    original_execute = Connection._execute

    async def gated_execute(connection, func, *args, **kwargs):
        if func.__name__ == "execute" and connection._conn is broken:
            started.set()
            await finish.wait()
        return await original_execute(connection, func, *args, **kwargs)

    monkeypatch.setattr(Connection, "_execute", gated_execute)
    query = asyncio.create_task(manager.fetchall("SELECT first"))
    await asyncio.wait_for(started.wait(), 1)
    waiting = asyncio.create_task(
        manager.fetchone("SELECT second") if waiting_operation == "read" else manager.close()
    )
    await asyncio.sleep(0)
    assert not waiting.done()
    finish.set()
    try:
        results = await asyncio.wait_for(
            asyncio.gather(query, waiting, return_exceptions=True), 1,
        )
        if waiting_operation == "read":
            assert results == [[(42,)], (42,)]
        else:
            assert isinstance(results[0], RuntimeError)
            assert str(results[0]) == "Database manager is closed"
            assert results[1] is None
    finally:
        await asyncio.wait_for(manager.close(), 1)


@pytest.mark.asyncio
async def test_cancelled_query_discards_connection_without_retry(monkeypatch):
    driver = DriverConnection()
    manager, connect = await make_manager(monkeypatch, driver)
    started = asyncio.Event()
    original_execute = Connection._execute

    async def blocked_execute(connection, func, *args, **kwargs):
        if func.__name__ == "execute":
            started.set()
            await asyncio.Event().wait()
        return await original_execute(connection, func, *args, **kwargs)

    monkeypatch.setattr(Connection, "_execute", blocked_execute)
    query = asyncio.create_task(manager.fetchall("SELECT reminders"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        query.cancel()
        with pytest.raises(asyncio.CancelledError):
            await query
        assert driver.closed
        assert connect.await_count == 1
        assert "rollback" not in driver.calls
    finally:
        await manager.close()


@pytest.mark.parametrize("state", ["08003", "08006", "08S01"])
def test_disconnect_detection_checks_chained_exception(state):
    original = pyodbc.OperationalError(state, "connection failure")
    wrapper = RuntimeError("cleanup failed")
    wrapper.__context__ = original
    assert _is_disconnect(wrapper)


@pytest.mark.parametrize("state", ["42000", "23000", "HYT00", "HY000"])
def test_unrelated_database_errors_are_not_disconnects(state):
    assert not _is_disconnect(pyodbc.OperationalError(state, "other failure"))
