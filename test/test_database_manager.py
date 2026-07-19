from unittest.mock import AsyncMock

import pytest

from database.DB_Manager import DatabaseManager


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


def make_pool(row=(1,), rows=None):
    cursor = type("Cursor", (), {})()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=row)
    cursor.fetchall = AsyncMock(return_value=rows or [row])
    cursor.commit = AsyncMock()
    connection = type("Connection", (), {"cursor": lambda self: AsyncContext(cursor)})()
    pool = type("Pool", (), {})()
    pool.acquire = lambda: AsyncContext(connection)
    pool.close = lambda: None
    pool.wait_closed = AsyncMock()
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
    cursor.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_keep_alive_reconnects_when_probe_fails(monkeypatch):
    manager = DatabaseManager("dsn")
    manager._pool = object()
    manager.fetchone = AsyncMock(side_effect=RuntimeError("lost"))
    manager.close = AsyncMock()
    manager.connect = AsyncMock()

    await manager.keep_alive()
    manager.close.assert_awaited_once()
    manager.connect.assert_awaited_once()
