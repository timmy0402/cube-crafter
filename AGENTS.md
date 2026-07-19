# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.12 Discord bot for cubing workflows. Main application code lives in `src/`. The entry point is `src/main.py`, with bot setup in `src/bot.py`. Slash command cogs are in `src/cogs/`, Discord UI views are in `src/views/`, cube logic is in `src/rubik/`, statistics helpers are in `src/stats/`, and database access is in `src/database/`. Algorithm data is stored in `src/data/algorithms.json`. Tests live in `test/`. SQL schema and trigger scripts are in `sql_tables/` and `sql_trigger/`; documentation lives in `docs/`.

`RubiksBot.setup_hook()` is the composition root: it creates the shared `aiohttp.ClientSession`, registers every cog, syncs application commands, connects the database pool, and starts background loops. Add a new cog there or its slash commands will not be available. The bot exposes its shared services as `bot.db_manager` and `bot.session`; command and view code should reuse them rather than creating per-request database pools or HTTP sessions.

The main feature areas are:

- Scrambles: `/scramble` and `/sessions` call the external Scrambler API. Puzzle display values and API identifiers live in `src/cogs/_constants.py`; update both mappings and session limits when adding puzzle support.
- Timed solves: `TimerView` owns the start/review/confirm flow, user creation, solve persistence, and PB/average updates. It stores regular solves in `SolveTimes` and daily solves in `DailySolves`.
- Daily challenge: `RubiksBot` creates one 3x3 daily scramble at midnight UTC and backfills it on startup. `/daily` uses that stored scramble and `/leaderboard` scopes results to members of the current guild.
- Reminders: reminder UI lives in `src/views/reminder.py`; the minute-level loop in `bot.py` interprets user IANA timezones and guards against duplicate sends with `LastSentDate`.
- Algorithms: `AlgorithmsView` loads OLL/PLL data from `src/data/algorithms.json` using the path constants in `src/paths.py`.

## Build, Test, and Development Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the bot locally after configuring `src/.env`:

```bash
python src/main.py
```

Run the test suite:

```bash
python -m pytest
```

Run a specific test file:

```bash
python -m pytest test/test_wca_avg.py
```

Run the suite with branch coverage:

```bash
python -m pytest test/ -v --cov=src --cov-branch --cov-report=term-missing --cov-report=xml:coverage.xml
```

`pyproject.toml` configures pytest with `test/` as the test path, `src/` on `PYTHONPATH`, and branch coverage for `src/`. `pytest-cov` is included in `requirements.txt`.

For the local SQL Server setup, run all table scripts before trigger scripts. `DailyReminders.sql` is also required for the reminder feature. The Docker image runs `src/main.py` with `src/` as its working directory; `docker-compose.yml` supplies `src/.env` and expects the external `rubik-net` Docker network.

## Runtime Configuration and Background Work

`ENV=PROD` selects `TOKEN` and the `AZURE_SQL_*` variables and globally syncs commands. Any other value selects `TEST_TOKEN` and `DEV_SQL_*` variables and syncs commands only to `GUILD_ID`, which is the intended fast development workflow. The ODBC driver is Microsoft ODBC Driver 18 and connections use encryption.

`bot.py` also runs database keep-alive, status rotation, bot-list reporting, server-count polling, daily-scramble generation, and daily-reminder delivery loops. Preserve their `before_loop` readiness guards, make their work idempotent, and handle API/database errors inside the loop so a transient failure does not stop it. Close resources through `RubiksBot.close()`; do not add an independent session lifecycle in a cog or view.

## Coding Style & Naming Conventions

Use standard Python style with 4-space indentation, clear function names, and type hints where practical. Keep async database and Discord calls explicit with `await`. Follow existing module patterns: cogs use command-oriented class names like `SolveCommands`, views use names like `TimerView`, and helper functions use snake_case. Prefer constants for repeated choices or limits, especially in `src/cogs/_constants.py`.

Use parameterized ODBC queries (`?` placeholders plus a parameter tuple); never interpolate user-controlled values into SQL. The only current dynamic SQL pattern is a placeholder list built from trusted collection length for leaderboard `IN` queries. Database writes are centralized through `DatabaseManager.execute()`, which commits each successful statement.

For Discord interactions, acknowledge within Discord's response window: defer before API/database work and use `interaction.followup` after a defer. Views must restrict stateful controls to their initiating user via `interaction_check`, disable controls on timeout, and retain/update the originating message when needed. User-facing failures should be short, while implementation details go to the module logger.

External API calls in cogs should use `bot.session`; avoid blocking calls in async handlers. If unavoidable background code uses a synchronous library, run it off the event loop as `check_and_generate_daily_scramble()` does.

## Testing Guidelines

Tests use `pytest` and `pytest-asyncio`. Name test files `test_*.py` and keep tests focused on pure logic where possible, such as WCA average calculations and image processing. Tests that construct `discord.ui.View` instances must be async and marked with `@pytest.mark.asyncio`, because discord.py requires a running event loop. Add tests when changing shared helpers in `src/stats/`, `src/rubik/`, or `src/cogs/_helpers.py`. For Discord or database behavior, isolate logic from network and SQL dependencies with fakes or mocks.

`test/conftest.py` provides `FakeDatabase`, `FakeResponse`, and `FakeFollowup`; extend those fakes or use small local mocks instead of requiring Discord, Azure SQL, or the Scrambler API in tests. For state changes in timer, daily, reminder, or SQL behavior, test both the successful path and the relevant failure/edge path (DNF/+2, duplicate daily solve, invalid reminder input, or missing database record).

## Commit & Pull Request Guidelines

Recent commits use short Conventional Commit-style prefixes, for example `fix: average calculation bug`, `feat: async database call`, `chore: minor optimization`, and `refactor: async server count update`. Keep commit messages concise and imperative.

Pull requests should describe the user-facing change, list tests run, and call out database schema changes, new environment variables, or Discord command changes. Include screenshots only for visible Discord embed/view changes.

## Security & Configuration Tips

Do not commit real tokens, SQL passwords, or production connection strings. Local secrets belong in `src/.env`. Keep production-only values in deployment secrets, and review changes to `Dockerfile`, `docker-compose.yml`, and SQL scripts carefully.

The production integrations also use `TOPGG_TOKEN` and `BOTLIST_TOKEN`. Treat API responses, base64 image data, timezone input, and Discord-provided IDs as untrusted input: validate before use, keep errors non-sensitive, and never log credentials or full connection strings.
