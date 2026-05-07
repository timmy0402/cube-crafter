# Cube Crafter Discord Bot

[![Servers](https://img.shields.io/badge/dynamic/json?label=Servers&query=%24.stats.guilds&url=https%3A%2F%2Fdiscordbotlist.com%2Fapi%2Fv1%2Fbots%2F1197268536918278236&color=blue&logo=discord)](https://discordbotlist.com/bots/cube-crafter)
[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Cube Crafter** is a high-performance Discord bot designed for the cubing community. It provides official WCA scrambles, visual cube representations, and a robust personal timing system directly within your Discord server.

[**Visit Official Website**](https://cube-crafter-site.vercel.app/) | [**Invite Bot**](https://discord.com/api/oauth2/authorize?client_id=1197268536918278236&permissions=2147483648&scope=bot%20applications.commands)

---

## Key Features

- **WCA Scrambles:** Generate high-quality scrambles for all official WCA puzzles (2x2 - 7x7, Megaminx, Pyraminx, etc.).
- **Visual Representations:** Every scramble comes with a 2D image of the scrambled state to help you verify your scramble.
- **Personal Stopwatch:** Time your solves with an interactive stopwatch view.
- **Solve History:** Track your progress with a database-backed history system.
- **WCA Averages:** Automatically calculates **Average of 5 (Ao5)** and **Average of 12 (Ao12)** according to WCA standards (removing best/worst solves).
- **Per-Puzzle Tracking:** Keeps your history organized by puzzle type with a 15-entry limit per puzzle to keep your data relevant.
- **Algorithm Library:** Access OLL and PLL algorithm guides with visual aids.
- **Daily Competition:** Compete with friends in your sever with unique daily scramble.

---

## 
Commands

| Command | Description |
| :--- | :--- |
| `/scramble [puzzle]` | Generates a scramble and visual for the specified puzzle. |
| `/sessions [puzzle] [count]` | Generates multiple scrambles of the same NxN puzzle (max count varies by size: 10 for 2x2–4x4, 7 for 5x5, 6 for 6x6, 5 for 7x7). |
| `/stopwatch [puzzle]` | Launches an interactive timer to record a new solve. |
| `/time [puzzle]` | Displays your 15 most recent solves and current averages for a puzzle. |
| `/delete_time [id]` | Removes a specific solve from your history using its TimeID. |
| `/oll [group]` | View OLL algorithms with visual guides and pagination. |
| `/pll [group]` | View PLL algorithms with visual guides and pagination. |
| `/daily` | View the daily scramble with timer. |
| `/leaderboard` | View the ranking of daily solve in current server. |
| `/invite` | Generates invite link. |

---

## Running Locally

These instructions cover running the bot on your own machine against a local SQL Server database.

### 1. Prerequisites

- **Python 3.12** (a conda environment named `rubik_bot_env` is recommended)
- **SQL Server** (Express edition works) running locally
- **Microsoft ODBC Driver 18 for SQL Server**
- A **Discord bot** created at the [Discord Developer Portal](https://discord.com/developers/applications) — note the bot token and application ID

### 2. Install dependencies

```bash
conda activate rubik_bot_env
pip install -r requirements.txt
```

### 3. Set up the local database

Create a database (e.g. `CubeCrafter`) on your local SQL Server instance, then create the tables and triggers by running every script in `sql_tables/` followed by every script in `sql_trigger/`.

Using `sqlcmd`:

```bash
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/Users.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/SolveTimes.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/UserStats.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/DailyScramble.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/DailySolves.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/DuelMatches.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/CommandLog.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_tables/CommandTrack.sql

sqlcmd -S localhost -d CubeCrafter -E -i sql_trigger/trg_AutoDeleteOldSolveTimes.sql
sqlcmd -S localhost -d CubeCrafter -E -i sql_trigger/trg_IncreaseCommandCount.sql
```

Or open each `.sql` file in SQL Server Management Studio and execute them against your database.

### 4. Configure environment variables

Create `src/.env` with the following values:

```dotenv
ENV=development

# Discord
TEST_TOKEN=your-discord-bot-token
APPLICATION_ID=your-discord-application-id
GUILD_ID=your-test-guild-id

# Local SQL Server
DEV_SQL_HOST=localhost
DEV_SQL_DATABASE=CubeCrafter
DEV_SQL_USERNAME=your-sql-user
DEV_SQL_PASSWORD=your-sql-password
```

In development mode, slash commands are synced to `GUILD_ID` for instant updates.

### 5. Run the bot

```bash
python src/main.py
```

### Run tests

```bash
python -m pytest test/cube_test.py
```

---

##  Technical Stack

- **Language:** Python 3.12 (`discord.py`)
- **Database:** Azure SQL (managed via `pyodbc`)
- **Storage:** Azure Blob Storage (for algorithm images)
- **Infrastructure:** Dockerized and hosted on Azure.

---

## 📊 Bot Stats

![Discord Bots](https://top.gg/api/widget/1197268536918278236.svg)
---
© 2024 Cube Crafter. All rights reserved.