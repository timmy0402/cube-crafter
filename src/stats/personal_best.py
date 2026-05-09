from database import DatabaseManager

def update_user_pbs(db_manager: DatabaseManager, user_id: int, puzzle_type: str, new_time: float) -> bool:
    """
    Legacy incremental update for Best Single. 
    Note: Ideally use recalculate_user_pbs for full consistency.
    """
    # Fetch current PB for the user and puzzle type
    db_manager.cursor.execute(
        "SELECT BestSingle FROM UserStats WHERE UserID=? AND PuzzleType=?", (user_id, puzzle_type))
    current_pb = db_manager.cursor.fetchval()
    if current_pb is None or new_time < current_pb:
        # Update PB if new time is better or if no PB exists
        if current_pb is None:
            db_manager.cursor.execute(
                "INSERT INTO UserStats(UserID, PuzzleType, BestSingle) VALUES(?, ?, ?)",
                (user_id, puzzle_type, new_time),
            )
        else:
            db_manager.cursor.execute(
                "UPDATE UserStats SET BestSingle=? WHERE UserID=? AND PuzzleType=?",
                (new_time, user_id, puzzle_type),
            )
        db_manager.connection.commit()
        return True
    return False

def calculate_wca_avg(times: list[float], count: int) -> float | None:
    """
    Calculates the WCA average (Ao5, Ao12, etc.)
    Args:
        times: List of float times. DNF should be represented as float('inf').
        count: The size of the average (e.g., 5 or 12).
    Returns:
        float: The average time.
        float('inf'): If the average is DNF.
        None: If insufficient times provided.
    """
    # Take only the first 'count' elements if more are provided (legacy behavior compatibility)
    if len(times) < count:
        return None
    
    window = times[:count]
    
    # Check for DNFs
    dnf_count = sum(1 for t in window if t == float('inf'))
    
    if dnf_count > 1:
        return float('inf')
        
    subset = sorted(window)
    # Remove best (first) and worst (last)
    trimmed = subset[1:-1]
    return sum(trimmed) / len(trimmed)

def update_user_average_best(db_manager: DatabaseManager, user_id: int, puzzle_type: str, new_ao5: float, new_ao12: float) -> tuple[bool, bool]:
    """
    Legacy incremental update for Average Bests.
    Note: Ideally use recalculate_user_pbs for full consistency.
    """
    # Fetch current average best for the user and puzzle type
    db_manager.cursor.execute(
        "SELECT BestAo5, BestAo12 FROM UserStats WHERE UserID=? AND PuzzleType=?", (user_id, puzzle_type))
    row = db_manager.cursor.fetchone()
    
    current_ao5 = row[0] if row else None
    current_ao12 = row[1] if row else None

    updated_ao5 = False
    # Check Ao5 (Ignore DNF/inf for best)
    if new_ao5 is not None and new_ao5 != float('inf') and (current_ao5 is None or new_ao5 < current_ao5):
        if row is None:
             db_manager.cursor.execute(
                "INSERT INTO UserStats(UserID, PuzzleType, BestAo5) VALUES(?, ?, ?)",
                (user_id, puzzle_type, new_ao5),
            )
             row = [new_ao5, None] # Mock row update
        else:
            db_manager.cursor.execute(
                "UPDATE UserStats SET BestAo5=? WHERE UserID=? AND PuzzleType=?",
                (new_ao5, user_id, puzzle_type),
            )
        updated_ao5 = True

    updated_ao12 = False
    # Check Ao12 (Ignore DNF/inf for best)
    if new_ao12 is not None and new_ao12 != float('inf') and (current_ao12 is None or new_ao12 < current_ao12):
        db_manager.cursor.execute(
            "SELECT 1 FROM UserStats WHERE UserID=? AND PuzzleType=?", (user_id, puzzle_type))
        if not db_manager.cursor.fetchone():
            db_manager.cursor.execute(
                "INSERT INTO UserStats(UserID, PuzzleType, BestAo12) VALUES(?, ?, ?)",
                (user_id, puzzle_type, new_ao12),
            )
        else:
            db_manager.cursor.execute(
                "UPDATE UserStats SET BestAo12=? WHERE UserID=? AND PuzzleType=?",
                (new_ao12, user_id, puzzle_type),
            )
        updated_ao12 = True

    db_manager.connection.commit()
    return (updated_ao5, updated_ao12)

def get_user_pbs(db_manager: DatabaseManager, user_id: int, puzzle_type: str = "3x3") -> dict:
    """
    Get user best single, average 5, 12 of a given puzzle
    """
    db_manager.cursor.execute(
        "SELECT BestSingle, BestAo5, BestAo12 FROM UserStats WHERE UserID=? AND PuzzleType=?", (user_id, puzzle_type))
    row = db_manager.cursor.fetchone()
    
    if not row:
        return {
            "BestSingle": None,
            "BestAo5": None,
            "BestAo12": None,
        }
        
    return {
        "BestSingle": float(row[0]) if row[0] is not None else None,
        "BestAo5": float(row[1]) if row[1] is not None else None,
        "BestAo12": float(row[2]) if row[2] is not None else None,
    }

def recalculate_user_pbs(db_manager: DatabaseManager, user_id: int, puzzle_type: str) -> None:
    """
    Recalculates and updates the personal bests (Single, Ao5, Ao12) for a user and puzzle type
    by scanning the entire solve history.
    """
    # Fetch all solve times and statuses in chronological order
    db_manager.cursor.execute(
        "SELECT SolveTime, SolveStatus FROM SolveTimes WHERE UserID=? AND PuzzleType=? ORDER BY SolveAt ASC, TimeID ASC",
        (user_id, puzzle_type),
    )
    rows = db_manager.cursor.fetchall()
    
    # Pre-process times: DNF becomes inf
    times = []
    for r in rows:
        val = float(r[0])
        status = r[1] if r[1] else "Completed"
        if status == 'DNF':
            times.append(float('inf'))
        else:
            times.append(val)

    # 1. Best Single
    # Filter out DNFs for single (unless only DNFs exist)
    valid_singles = [t for t in times if t != float('inf')]
    best_single = min(valid_singles) if valid_singles else None

    best_ao5 = None
    best_ao12 = None

    # 2. Best Ao5
    if len(times) >= 5:
        for i in range(len(times) - 4):
            window = times[i : i + 5]
            avg = calculate_wca_avg(window, 5)
            if avg is not None and avg != float('inf'):
                if best_ao5 is None or avg < best_ao5:
                    best_ao5 = avg

    # 3. Best Ao12
    if len(times) >= 12:
        for i in range(len(times) - 11):
            window = times[i : i + 12]
            avg = calculate_wca_avg(window, 12)
            if avg is not None and avg != float('inf'):
                if best_ao12 is None or avg < best_ao12:
                    best_ao12 = avg

    # Update UserStats
    db_manager.cursor.execute(
        "SELECT 1 FROM UserStats WHERE UserID=? AND PuzzleType=?",
        (user_id, puzzle_type),
    )
    exists = db_manager.cursor.fetchone()

    if exists:
        db_manager.cursor.execute(
            """
            UPDATE UserStats 
            SET BestSingle=?, BestAo5=?, BestAo12=? 
            WHERE UserID=? AND PuzzleType=?
            """,
            (best_single, best_ao5, best_ao12, user_id, puzzle_type),
        )
    else:
        if best_single is not None or best_ao5 is not None or best_ao12 is not None:
            db_manager.cursor.execute(
                """
                INSERT INTO UserStats (UserID, PuzzleType, BestSingle, BestAo5, BestAo12)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, puzzle_type, best_single, best_ao5, best_ao12),
            )

    db_manager.connection.commit()
