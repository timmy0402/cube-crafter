import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from database.DB_Manager import DatabaseManager


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    def __await__(self):
        return self.__aenter__().__await__()

    async def __aexit__(self, *args):
        return False


def make_connection(cursor):
    connection = type("Connection", (), {
        "cursor": lambda self: AsyncContext(cursor),
        "closed": False,
        "autocommit": False,
    })()

    async def close():
        connection.closed = True

    connection.close = AsyncMock(side_effect=close)
    return connection


def make_pool(row=(1,), rows=None):
    cursor = type("Cursor", (), {})()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=row)
    cursor.fetchall = AsyncMock(return_value=rows or [row])
    cursor.commit = AsyncMock()
    cursor.rollback = AsyncMock()
    cursor.close = AsyncMock()
    connection = make_connection(cursor)
    pool = type("Pool", (), {})()
    pool.acquire = lambda: AsyncContext(connection)
    pool.close = Mock()
    pool.wait_closed = AsyncMock()
    pool._wakeup = AsyncMock()
    return pool, cursor


@pytest.mark.asyncio
async def test_connect_retries_then_reuses_successful_pool(monkeypatch):
    manager = DatabaseManager("dsn")
    pool, _ = make_pool()
    create_pool = AsyncMock(side_effect=[RuntimeError("down"), pool])
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create_pool)
    monkeypatch.setattr("database.DB_Manager.asyncio.sleep", AsyncMock())

    await manager.connect()
    await manager.connect()
    assert manager._pool is pool
    assert create_pool.await_count == 2


@pytest.mark.asyncio
async def test_connect_raises_after_all_retries(monkeypatch):
    manager = DatabaseManager("dsn")
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", AsyncMock(side_effect=RuntimeError("down")))
    monkeypatch.setattr("database.DB_Manager.asyncio.sleep", AsyncMock())

    with pytest.raises(RuntimeError, match="Unable to connect"):
        await manager.connect()


@pytest.mark.asyncio
async def test_query_helpers_execute_and_commit():
    manager = DatabaseManager("dsn")
    pool, cursor = make_pool(row=(4,), rows=[(1,), (2,)])
    manager._pool = pool

    assert await manager.fetchone("SELECT one", (1,)) == (4,)
    assert await manager.fetchall("SELECT all") == [(1,), (2,)]
    await manager.execute("UPDATE table", (2,))
    assert cursor.execute.await_count == 3
    assert cursor.commit.await_count == 3


@pytest.mark.asyncio
async def test_keep_alive_reconnects_when_probe_fails(monkeypatch):
    manager = DatabaseManager("dsn")
    old_pool, cursor = make_pool()
    cursor.execute.side_effect = RuntimeError("lost")
    new_pool, _ = make_pool()
    manager._pool = old_pool
    create_pool = AsyncMock(return_value=new_pool)
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create_pool)

    await manager.keep_alive()
    old_pool.close.assert_called_once()
    old_pool.wait_closed.assert_awaited_once()
    assert manager._pool is new_pool
    assert await manager.fetchone("SELECT 1") == (1,)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["fetchone", "fetchall", "execute"])
async def test_queries_connect_when_pool_is_missing(monkeypatch, method):
    manager = DatabaseManager("dsn")
    pool, cursor = make_pool()
    create_pool = AsyncMock(return_value=pool)
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create_pool)

    await getattr(manager, method)("query", (42,))

    create_pool.assert_awaited_once()
    cursor.execute.assert_awaited_once_with("query", (42,))


@pytest.mark.asyncio
async def test_concurrent_queries_share_one_pool_creation(monkeypatch):
    manager = DatabaseManager("dsn")
    pool, cursor = make_pool()
    started = asyncio.Event()
    ready = asyncio.Event()

    async def create(**kwargs):
        started.set()
        await ready.wait()
        return pool

    create_pool = AsyncMock(side_effect=create)
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create_pool)
    first = asyncio.create_task(manager.fetchone("first"))
    await asyncio.wait_for(started.wait(), 1)
    second = asyncio.create_task(manager.fetchall("second"))
    await asyncio.sleep(0)
    assert not first.done() and not second.done()
    ready.set()
    await asyncio.wait_for(asyncio.gather(first, second), 1)

    create_pool.assert_awaited_once()
    assert cursor.execute.await_count == 2


@pytest.mark.asyncio
async def test_query_waits_for_recovery_and_uses_replacement_pool(monkeypatch):
    manager = DatabaseManager("dsn")
    old_pool, old_cursor = make_pool()
    old_cursor.execute.side_effect = RuntimeError("lost")
    new_pool, new_cursor = make_pool()
    manager._pool = old_pool
    reconnecting = asyncio.Event()
    ready = asyncio.Event()

    async def create(**kwargs):
        reconnecting.set()
        await ready.wait()
        return new_pool

    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create)
    recovery = asyncio.create_task(manager.keep_alive())
    await asyncio.wait_for(reconnecting.wait(), 1)
    query = asyncio.create_task(manager.fetchall("reminders"))
    await asyncio.sleep(0)
    assert not query.done()
    ready.set()
    await asyncio.wait_for(asyncio.gather(recovery, query), 1)

    old_cursor.execute.assert_awaited_once_with("SELECT 1")
    new_cursor.execute.assert_awaited_once_with("reminders", ())


@pytest.mark.asyncio
async def test_failed_reconnection_allows_later_recovery(monkeypatch):
    manager = DatabaseManager("dsn")
    old_pool, cursor = make_pool()
    cursor.execute.side_effect = RuntimeError("lost")
    new_pool, _ = make_pool()
    manager._pool = old_pool
    create_pool = AsyncMock(side_effect=[RuntimeError("down")] * 3 + [new_pool])
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create_pool)
    monkeypatch.setattr("database.DB_Manager.asyncio.sleep", AsyncMock())

    with pytest.raises(RuntimeError, match="Unable to connect"):
        await manager.keep_alive()
    assert manager._pool is None

    await manager.keep_alive()
    assert await manager.fetchone("SELECT 1") == (1,)
    assert create_pool.await_count == 4


@pytest.mark.asyncio
async def test_unavailable_query_reports_connection_failure(monkeypatch):
    manager = DatabaseManager("dsn")
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", AsyncMock(side_effect=RuntimeError("down")))
    monkeypatch.setattr("database.DB_Manager.asyncio.sleep", AsyncMock())

    with pytest.raises(RuntimeError, match="Unable to connect"):
        await manager.fetchall("reminders")


@pytest.mark.asyncio
async def test_cancelled_connect_releases_lock_for_next_attempt(monkeypatch):
    manager = DatabaseManager("dsn")
    pool, _ = make_pool()
    create_pool = AsyncMock(side_effect=[asyncio.CancelledError(), pool])
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create_pool)

    with pytest.raises(asyncio.CancelledError):
        await manager.connect()
    await asyncio.wait_for(manager.connect(), 1)
    assert manager._pool is pool
    assert create_pool.await_count == 2


@pytest.mark.asyncio
async def test_close_prevents_queries_from_reopening_pool(monkeypatch):
    manager = DatabaseManager("dsn")
    pool, _ = make_pool()
    manager._pool = pool
    create_pool = AsyncMock()
    monkeypatch.setattr("database.DB_Manager.aioodbc.create_pool", create_pool)

    await manager.close()
    await manager.close()
    for operation in (manager.connect, manager.keep_alive, lambda: manager.fetchall("reminders")):
        with pytest.raises(RuntimeError, match="closed"):
            await operation()
    pool.close.assert_called_once()
    create_pool.assert_not_called()


@pytest.mark.asyncio
async def test_failed_write_is_not_replayed(monkeypatch):
    manager = DatabaseManager("dsn")
    pool, cursor = make_pool()
    manager._pool = pool
    cursor.commit.side_effect = RuntimeError("connection lost during commit")

    with pytest.raises(RuntimeError, match="connection lost"):
        await manager.execute("INSERT solve", (42,))
    cursor.execute.assert_awaited_once_with("INSERT solve", (42,))
    cursor.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_queries_can_run_concurrently():
    manager = DatabaseManager("dsn")
    pool, cursor = make_pool()
    manager._pool = pool
    both_started = asyncio.Event()
    calls = 0

    async def execute(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            both_started.set()
        await both_started.wait()

    cursor.execute.side_effect = execute
    await asyncio.wait_for(asyncio.gather(
        manager.fetchone("first"), manager.fetchone("second"),
    ), 1)


@pytest.mark.asyncio
async def test_close_drains_borrowed_connection_without_deadlock():
    manager = DatabaseManager("dsn")
    pool, cursor = make_pool()
    manager._pool = pool
    started = asyncio.Event()
    finish_query = asyncio.Event()
    released = asyncio.Event()
    closing = asyncio.Event()
    connection = make_connection(cursor)

    class BorrowedConnection(AsyncContext):
        async def __aexit__(self, *args):
            released.set()
            return False

    async def execute(*args):
        started.set()
        await finish_query.wait()

    async def wait_closed():
        closing.set()
        await released.wait()

    pool.acquire = lambda: BorrowedConnection(connection)
    pool.wait_closed.side_effect = wait_closed
    cursor.execute.side_effect = execute
    query = asyncio.create_task(manager.fetchone("work"))
    await asyncio.wait_for(started.wait(), 1)
    close = asyncio.create_task(manager.close())
    await asyncio.wait_for(closing.wait(), 1)
    assert not close.done()
    finish_query.set()
    await asyncio.wait_for(asyncio.gather(query, close), 1)
    assert manager._pool is None
