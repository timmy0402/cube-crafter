import pytest

from stats.personal_best import (
    get_user_pbs,
    recalculate_user_pbs,
    update_user_average_best,
    update_user_pbs,
)


class FakeDB:
    def __init__(self, *, one=None, all_rows=None):
        self.one = list(one or [])
        self.all_rows = all_rows or []
        self.executed = []

    async def fetchone(self, query, params=()):
        return self.one.pop(0) if self.one else None

    async def fetchall(self, query, params=()):
        return self.all_rows

    async def execute(self, query, params=()):
        self.executed.append((query, params))


@pytest.mark.asyncio
async def test_update_user_pbs_inserts_first_finite_time():
    db = FakeDB(one=[None])
    assert await update_user_pbs(db, 4, "3x3", 8.25) is True
    assert "INSERT INTO UserStats" in db.executed[0][0]
    assert db.executed[0][1] == (4, "3x3", 8.25)


@pytest.mark.asyncio
async def test_update_user_pbs_updates_only_when_faster_and_ignores_dnf():
    db = FakeDB(one=[(10.0,), (10.0,)])
    assert await update_user_pbs(db, 4, "3x3", 12.0) is False
    assert db.executed == []
    assert await update_user_pbs(db, 4, "3x3", float("inf")) is False
    assert db.executed == []


@pytest.mark.asyncio
async def test_update_user_average_best_handles_missing_row_and_both_values():
    db = FakeDB(one=[None])
    assert await update_user_average_best(db, 4, "3x3", 9.1, 11.2) == (True, True)
    assert "INSERT INTO UserStats" in db.executed[0][0]
    assert "UPDATE UserStats" in db.executed[1][0]


@pytest.mark.asyncio
async def test_update_user_average_best_ignores_none_and_dnf():
    db = FakeDB(one=[(8.0, 12.0)])
    assert await update_user_average_best(db, 4, "3x3", None, float("inf")) == (False, False)
    assert db.executed == []


@pytest.mark.asyncio
async def test_get_user_pbs_returns_null_shape_for_missing_row_and_casts_values():
    missing = FakeDB(one=[None])
    assert await get_user_pbs(missing, 1) == {"BestSingle": None, "BestAo5": None, "BestAo12": None}
    present = FakeDB(one=[(8, None, 12.5)])
    assert await get_user_pbs(present, 1) == {"BestSingle": 8.0, "BestAo5": None, "BestAo12": 12.5}


@pytest.mark.asyncio
async def test_recalculate_user_pbs_inserts_best_values_from_history():
    rows = [(10, "Completed"), (9, "Completed"), (11, "Completed"), (12, "Completed"), (13, "Completed")]
    db = FakeDB(one=[None], all_rows=rows)
    await recalculate_user_pbs(db, 2, "3x3")
    assert "INSERT INTO UserStats" in db.executed[0][0]
    assert db.executed[0][1] == (2, "3x3", 9.0, 11.0, None)


@pytest.mark.asyncio
async def test_recalculate_user_pbs_updates_existing_and_excludes_dnf_averages():
    rows = [(10, "Completed"), (float("inf"), "DNF"), (11, "Completed"), (12, "Completed"), (13, "Completed")]
    db = FakeDB(one=[(1,)], all_rows=rows)
    await recalculate_user_pbs(db, 2, "3x3")
    assert "UPDATE UserStats" in db.executed[0][0]
    assert db.executed[0][1][0] == 10.0
    assert db.executed[0][1][1:] == (12.0, None, 2, "3x3")


@pytest.mark.asyncio
async def test_recalculate_user_pbs_does_not_create_empty_stats_row():
    db = FakeDB(one=[None], all_rows=[(float("inf"), "DNF")])
    await recalculate_user_pbs(db, 2, "3x3")
    assert db.executed == []
