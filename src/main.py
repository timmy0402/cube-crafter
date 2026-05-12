import os
from dotenv import load_dotenv
from bot import RubiksBot
from database import DatabaseManager
import logging
from paths import SRC_DIR

# Load environment variables from .env file
load_dotenv()

load_dotenv(SRC_DIR / ".env")

def _odbc_escape(value: str) -> str:
# ODBC quotes values containing ;=space with {...}; any } inside must be doubled.
    return "{" + value.replace("}", "}}") + "}"

if __name__ == "__main__":
    """
    Main entry point for the Rubik Discord Bot.
    Initializes the bot, sets up logging, and runs with the appropriate token.
    """
    # Determine which token to use based on the environment
    if os.getenv("ENV", "").upper() == "PROD":
        token = os.getenv("TOKEN")
        # data base intialization
        server = os.getenv("AZURE_SQL_HOST")
        database = os.getenv("AZURE_SQL_DATABASE")
        username = os.getenv("AZURE_SQL_USERNAME")
        password = _odbc_escape(os.getenv("AZURE_SQL_PASSWORD"))
        driver = "{ODBC Driver 18 for SQL Server}"
        trust = "no"
    else:
        token = os.getenv("TEST_TOKEN")
        server = os.getenv("DEV_SQL_HOST")
        database = os.getenv("DEV_SQL_DATABASE")
        username = os.getenv("DEV_SQL_USERNAME")
        password = _odbc_escape(os.getenv("DEV_SQL_PASSWORD"))
        driver = "{ODBC Driver 18 for SQL Server}"
        trust = "yes"
    
    dsn =  f"DRIVER={driver};SERVER=tcp:{server};PORT=1433;DATABASE={database};UID={username};PWD={password};Encrypt=yes;TrustServerCertificate={trust};Connection Timeout=60;"

    db_manager = DatabaseManager(dsn=dsn)

    # Initialize the bot instance
    bot = RubiksBot(db_manager=db_manager)

    # Configure logging to display timestamps, levels, and source names
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:%(name)s: %(message)s", level=logging.INFO
    )

    # Set external libraries' logging levels to WARNING to reduce noise in logs
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)

    # Start the bot
    bot.run(token)