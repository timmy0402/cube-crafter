# Daily Reminder System Documentation

The Daily Reminder System allows users to opt in to daily DM reminders at a specific time and timezone. Once enabled, the bot sends a single reminder per local day if the user hasn't yet completed the `/daily` challenge. The feature is timezone-aware and handles edge cases like DST transitions and daylight-savings time shifts transparently.

## User Flow

Users can enable reminders in two ways:

1. **Button on `/daily`:** After completing the daily challenge, a "Remind me daily" button appears. Clicking it triggers the timezone selection flow.
2. **`/reminder set` command:** Users can set a reminder directly without running `/daily` first.

Both flows follow the same path:
- **Timezone Select**: User picks from 24 preset IANA timezones (UTC, America/New_York, Asia/Tokyo, etc.) or chooses "Other" to enter a custom IANA string.
- **Time Modal**: For preset timezones, a simple modal asks for the time in 24-hour `HH:MM` format. For custom timezones, a larger modal prompts for both time and the IANA string.
- **Confirmation**: On success, an ephemeral message confirms the reminder is set. On validation error, the user gets inline feedback and can retry.

Users can later view (`/reminder show`), disable (`/reminder disable`), or update (`/reminder set` again) their reminders.

## Data Model

**Table:** `DailyReminders` (SQL schema: `sql_tables/DailyReminders.sql` - file:1)

- `ReminderID` (PK): Auto-incrementing reminder record ID.
- `UserID` (FK, UNIQUE): Links to `Users` table; ensures one reminder per user.
- `ReminderTime` (VARCHAR(5)): Time in 24-hour `HH:MM` format (e.g., "09:00").
- `Timezone` (NVARCHAR(64)): IANA timezone string (e.g., "America/New_York").
- `IsActive` (BIT): Flag indicating if the reminder is enabled (1) or disabled (0).
- `LastSentDate` (DATE, nullable): The local date the reminder was last sent. Keyed off the user's *local* date, not UTC. Allows the system to send exactly one reminder per local day.
- `CreatedAt`, `UpdatedAt`: Timestamps in UTC.

**Key constraint**: The UNIQUE constraint on `UserID` means the UPSERT operation in `upsert_reminder` (file:src/views/reminder.py - file:48) replaces the entire row when a user updates their reminder. This includes resetting `LastSentDate` to NULL, so if a user changes their reminder time, it can fire again on the same local day.

## Background Task: `daily_reminder_task`

**File:** `src/bot.py` (file:275)

The task runs **every minute** and performs the following:

1. **Fetch active reminders**: Queries the `DailyReminders` table (filtered on `IsActive = 1`), joining with `Users` to get Discord IDs.
2. **Convert to local time**: For each reminder, converts the current UTC time to the user's timezone using `zoneinfo.ZoneInfo`.
3. **Check if already sent today**: Compares `LastSentDate` against today's *local* date. If they match, skips this user (idempotency).
4. **Check if time threshold reached**: Compares the user's current local hour/minute against the target time. Only fires if `(local_hour, local_minute) >= (target_hour, target_minute)`.
5. **Skip if daily already done**: Queries `DailySolves` to see if the user has a row for today's local date. If they do, skips the DM (no reminder for users who've already solved).
6. **Send DM**: Calls `_send_reminder_dm` (file:src/bot.py - file:250) to dispatch the reminder message.
7. **Mark as sent**: Updates `LastSentDate` to today's local date and increments `UpdatedAt`. This happens *after* the DM attempt, and even if DMs are blocked (Forbidden exception) or another error occurs, we still mark it sent so the user doesn't get spammed on retry.

**How it handles:**
- **Timezone database changes**: If a user changes timezone via `/reminder set`, the `upsert_reminder` function clears `LastSentDate`, allowing a new time to fire on the same local day.
- **Bot restart catch-up**: If the bot restarts partway through a day, on the next minute-loop iteration, all reminders with `LastSentDate < today` will be re-evaluated and fired if the time threshold is met. The task is idempotent because we check `LastSentDate` and block duplicate sends.
- **DST spring-forward (lost hour)**: If a user's timezone springs forward (e.g., 02:00 → 03:00), and their target time was 02:30, the task will skip that minute since 02:30 never occurs. On the next minute, the local time jumps to 03:00+, so the reminder fires at 03:00 or later.
- **DST fall-back (repeated hour)**: If a user's timezone falls back (e.g., 02:00 → 01:00), and their target time was 01:30, the task will fire once at the first 01:30 (Eastern Daylight Time) and mark it sent. The second 01:30 (Eastern Standard Time) is skipped because `LastSentDate` is already set.

## DM Handling

**Function:** `_send_reminder_dm` (file:src/bot.py - file:250)

Fetches the Discord user object by ID and sends a DM with the message: "⏰ Time for your daily Rubik's scramble! Run `/daily` in any server with the bot."

**Error handling:**
- `discord.Forbidden`: User has DMs disabled. Logs at info level and silently continues (best-effort).
- `discord.HTTPException`: Network or API error. Logs at warning level and continues.
- Other exceptions: Logs at error level and continues.

The reminder task always marks `LastSentDate` after attempting the DM, regardless of success or failure. This prevents the bot from retrying thousands of times on transient failures. If DMs are genuinely blocked, the user can re-enable them and wait until the next calendar day for the reminder to be sent again (or manually trigger `/daily`).

## Validation & Edge Cases

**Time validation** (file:src/views/reminder.py - file:15, file:121):
- Regex pattern: `^([01]\d|2[0-3]):[0-5]\d$` (strict 24-hour HH:MM format).
- Failure: Ephemeral reply asks user to use 24-hour format (e.g., "09:00").

**Timezone validation** (file:src/views/reminder.py - file:128):
- Attempts to construct a `zoneinfo.ZoneInfo(timezone)` object.
- Failure: Ephemeral reply lists valid examples (America/New_York, Europe/London, Asia/Tokyo).
- Pre-validated timezones (24 presets) skip the check since they're known-good IANA strings.

**Custom timezone entry** (file:src/views/reminder.py - file:201):
- Modal allows up to 64 characters in the `tz_input` field, matching the database column width.
- Users copy-paste or type IANA identifiers (e.g., "America/Los_Angeles").

**User creation idempotency** (file:src/views/reminder.py - file:70):
- If a user sets a reminder before ever running a slash command, `upsert_reminder` creates a minimal `Users` row with just `UserName` and `DiscordID`.
- Subsequent commands/solves will update that row with additional data.

## File Map

| File | Purpose |
|------|---------|
| `sql_tables/DailyReminders.sql` | Table schema, indices, and constraints. |
| `src/views/reminder.py` | All UI classes: `TimezoneSelectView`, `TimezoneSelect`, `ReminderModal`, `TimeReminderModal`, `RemindMeView`, and the `upsert_reminder` helper. |
| `src/bot.py` | Background task `daily_reminder_task` and helper `_send_reminder_dm`. The task is initialized in `setup_hook`. |
| `src/cogs/commands.py` | Slash command group `/reminder` with `set`, `disable`, and `show` subcommands. The `RemindMeView` button is attached as a followup to `/daily`. |

## Related Features

- **Daily Challenge** (`/daily` command): Runs the timer and shows the daily scramble. Attaches the `RemindMeView` button as an opt-in.
- **Timer View** (`src/views/timer.py`): Manages the stopwatch UI. After a solve is recorded, it checks if the daily is complete and displays the reminder opt-in.
- **Daily Solves Table** (`sql_tables/DailySolves.sql`): Queried by the reminder task to check if a user has completed today's challenge.
