from database import DatabaseManager


async def update_user_pbs(
    db_manager: DatabaseManager,
    user_id: int,
    puzzle_type: str,
    new_time: float,
) -> bool:
    """
    Legacy incremental update for Best Single.
    Note: Ideally use recalculate_user_pbs for full consistency.

    Input:
        db_manager (DatabaseManager): Shared async database manager.
        user_id (int): Internal Users.UserID.
        puzzle_type (str): Puzzle key (e.g. "3x3").
        new_time (float): Candidate single time (float('inf') for DNF).
    Output:
        bool: True if a new Best Single was written.
    """
    # DNFs (represented as float('inf')) can never be a Best Single, and
    # SQL Server FLOAT cannot store infinity — short-circuit before any I/O.
    if new_time == float('inf'):
        return False

    row = await db_manager.fetchone(
        "SELECT BestSingle FROM UserStats WHERE UserID=? AND PuzzleType=?",
        (user_id, puzzle_type),
    )
    current_pb = row[0] if row else None

    if current_pb is None or new_time < current_pb:
        if current_pb is None:
            await db_manager.execute(
                "INSERT INTO UserStats(UserID, PuzzleType, BestSingle) VALUES(?, ?, ?)",
                (user_id, puzzle_type, new_time),
            )
        else:
            await db_manager.execute(
                "UPDATE UserStats SET BestSingle=? WHERE UserID=? AND PuzzleType=?",
                (new_time, user_id, puzzle_type),
            )
        return True
    return False


def calculate_wca_avg(times: list[float], count: int) -> float | None:
    """
    Calculates the WCA average (Ao5, Ao12, etc.)

    Input:
        times (list[float]): List of float times. DNF should be represented as float('inf').
        count (int): The size of the average (e.g., 5 or 12).
    Output:
        float | None: The average time, float('inf') if it's a DNF average,
                      or None if insufficient times were provided.
    """
    if len(times) < count:
        return None

    window = times[:count]

    dnf_count = sum(1 for t in window if t == float('inf'))

    if dnf_count > 1:
        return float('inf')

    subset = sorted(window)
    # Remove best (first) and worst (last)
    trimmed = subset[1:-1]
    return sum(trimmed) / len(trimmed)


async def update_user_average_best(
    db_manager: DatabaseManager,
    user_id: int,
    puzzle_type: str,
    new_ao5: float,
    new_ao12: float,
) -> tuple[bool, bool]:
    """
    Legacy incremental update for Average Bests.
    Note: Ideally use recalculate_user_pbs for full consistency.

    Input:
        db_manager (DatabaseManager): Shared async database manager.
        user_id (int): Internal Users.UserID.
        puzzle_type (str): Puzzle key (e.g. "3x3").
        new_ao5 (float): Candidate Ao5 (float('inf') means DNF average — ignored).
        new_ao12 (float): Candidate Ao12 (float('inf') means DNF average — ignored).
    Output:
        tuple[bool, bool]: (updated_ao5, updated_ao12).
    """
    row = await db_manager.fetchone(
        "SELECT BestAo5, BestAo12 FROM UserStats WHERE UserID=? AND PuzzleType=?",
        (user_id, puzzle_type),
    )

    current_ao5 = row[0] if row else None
    current_ao12 = row[1] if row else None
    row_exists = row is not None

    updated_ao5 = False
    if (
        new_ao5 is not None
        and new_ao5 != float('inf')
        and (current_ao5 is None or new_ao5 < current_ao5)
    ):
        if not row_exists:
            await db_manager.execute(
                "INSERT INTO UserStats(UserID, PuzzleType, BestAo5) VALUES(?, ?, ?)",
                (user_id, puzzle_type, new_ao5),
            )
            row_exists = True
        else:
            await db_manager.execute(
                "UPDATE UserStats SET BestAo5=? WHERE UserID=? AND PuzzleType=?",
                (new_ao5, user_id, puzzle_type),
            )
        updated_ao5 = True

    updated_ao12 = False
    if (
        new_ao12 is not None
        and new_ao12 != float('inf')
        and (current_ao12 is None or new_ao12 < current_ao12)
    ):
        if not row_exists:
            await db_manager.execute(
                "INSERT INTO UserStats(UserID, PuzzleType, BestAo12) VALUES(?, ?, ?)",
                (user_id, puzzle_type, new_ao12),
            )
        else:
            await db_manager.execute(
                "UPDATE UserStats SET BestAo12=? WHERE UserID=? AND PuzzleType=?",
                (new_ao12, user_id, puzzle_type),
            )
        updated_ao12 = True

    return (updated_ao5, updated_ao12)


async def get_user_pbs(
    db_manager: DatabaseManager,
    user_id: int,
    puzzle_type: str = "3x3",
) -> dict:
    """
    Get the user's Best Single, Best Ao5, and Best Ao12 for a given puzzle.

    Input:
        db_manager (DatabaseManager): Shared async database manager.
        user_id (int): Internal Users.UserID.
        puzzle_type (str): Puzzle key (defaults to "3x3").
    Output:
        dict: {'BestSingle': float|None, 'BestAo5': float|None, 'BestAo12': float|None}.
    """
    row = await db_manager.fetchone(
        "SELECT BestSingle, BestAo5, BestAo12 FROM UserStats WHERE UserID=? AND PuzzleType=?",
        (user_id, puzzle_type),
    )

    if not row:
        return {"BestSingle": None, "BestAo5": None, "BestAo12": None}

    return {
        "BestSingle": float(row[0]) if row[0] is not None else None,
        "BestAo5": float(row[1]) if row[1] is not None else None,
        "BestAo12": float(row[2]) if row[2] is not None else None,
    }


async def recalculate_user_pbs(
    db_manager: DatabaseManager,
    user_id: int,
    puzzle_type: str,
) -> None:
    """
    Recalculates Best Single / Ao5 / Ao12 for a user+puzzle from the full solve history.

    Input:
        db_manager (DatabaseManager): Shared async database manager.
        user_id (int): Internal Users.UserID.
        puzzle_type (str): Puzzle key (e.g. "3x3").
    Output:
        None
    """
    rows = await db_manager.fetchall(
        "SELECT SolveTime, SolveStatus FROM SolveTimes WHERE UserID=? AND PuzzleType=? ORDER BY SolveAt ASC, TimeID ASC",
        (user_id, puzzle_type),
    )

    times = []
    for r in rows:
        val = float(r[0])
        status = r[1] if r[1] else "Completed"
        if status == 'DNF':
            times.append(float('inf'))
        else:
            times.append(val)

    valid_singles = [t for t in times if t != float('inf')]
    best_single = min(valid_singles) if valid_singles else None

    best_ao5 = None
    best_ao12 = None

    if len(times) >= 5:
        for i in range(len(times) - 4):
            window = times[i : i + 5]
            avg = calculate_wca_avg(window, 5)
            if avg is not None and avg != float('inf'):
                if best_ao5 is None or avg < best_ao5:
                    best_ao5 = avg

    if len(times) >= 12:
        for i in range(len(times) - 11):
            window = times[i : i + 12]
            avg = calculate_wca_avg(window, 12)
            if avg is not None and avg != float('inf'):
                if best_ao12 is None or avg < best_ao12:
                    best_ao12 = avg

    exists = await db_manager.fetchone(
        "SELECT 1 FROM UserStats WHERE UserID=? AND PuzzleType=?",
        (user_id, puzzle_type),
    )

    if exists:
        await db_manager.execute(
            "UPDATE UserStats SET BestSingle=?, BestAo5=?, BestAo12=? "
            "WHERE UserID=? AND PuzzleType=?",
            (best_single, best_ao5, best_ao12, user_id, puzzle_type),
        )
    elif best_single is not None or best_ao5 is not None or best_ao12 is not None:
        await db_manager.execute(
            "INSERT INTO UserStats (UserID, PuzzleType, BestSingle, BestAo5, BestAo12) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, puzzle_type, best_single, best_ao5, best_ao12),
        )
