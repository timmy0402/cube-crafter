-- =============================================================================
-- trg_AutoDeleteOldSolveTimes -- DISABLED IN PRODUCTION (confirmed 2026-08-16)
-- =============================================================================
-- Retention trigger: caps SolveTimes at the newest 15 rows per (UserID, PuzzleType).
--
-- STATUS: disabled, not dropped. A single ENABLE TRIGGER re-arms it. Read both
-- notes below before doing that.
--
--   1. It destroys personal bests. stats/personal_best.py::recalculate_user_pbs
--      rebuilds BestSingle/BestAo5/BestAo12 from "the full solve history" -- and
--      with this trigger on, that history IS the last 15 solves. So any
--      /delete_time or /adjust_time overwrites an older PB with the best of the
--      recent 15. The source row is already deleted, so the old PB cannot be
--      recovered.
--
--   2. The DELETE below is unfiltered. The CTE windows ROW_NUMBER() over ALL of
--      SolveTimes, not just the affected user, so every INSERT costs a full-table
--      sort proportional to total rows across all users. If this is ever
--      re-enabled, first add to the CTE:
--          WHERE UserID IN (SELECT UserID FROM inserted)
--
-- If per-user retention is wanted again, archive to a second table rather than
-- deleting, so PB recalculation still has a complete source to read from.
--
-- Check the live state:
--     SELECT name, is_disabled, create_date, modify_date
--     FROM sys.triggers
--     WHERE parent_id = OBJECT_ID('dbo.SolveTimes');
-- =============================================================================

CREATE OR ALTER TRIGGER trg_AutoDeleteOldSolveTimes
ON SolveTimes
AFTER INSERT
AS
BEGIN
    WITH CTE AS (
        SELECT
            TimeID,
            UserID,
            PuzzleType,
            ROW_NUMBER() OVER (
                PARTITION BY UserID, PuzzleType
                ORDER BY SolveAt DESC
            ) AS RowNum
        FROM SolveTimes
    )
    DELETE FROM SolveTimes
    WHERE TimeID IN (
        SELECT TimeID
        FROM CTE
        WHERE RowNum > 15
    );
END;
GO

-- Keep the definition available but inert. Production runs with this disabled,
-- so a fresh database must match or local behaviour will diverge from prod.
DISABLE TRIGGER trg_AutoDeleteOldSolveTimes ON SolveTimes;
GO
