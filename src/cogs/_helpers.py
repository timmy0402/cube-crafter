import base64
import io
import logging
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)


def log_command_usage(db_manager, command_name: str) -> None:
    """
    Logs the usage of a specific command to the database.
    """
    try:
        db_manager.cursor.execute(
            "INSERT INTO CommandLog(CommandName) VALUES(?)", (command_name,)
        )
        db_manager.cursor.commit()
    except Exception as e:
        logger.error(f"Log usage failed: {e}")


def get_db_user_id(db_manager, discord_id: int) -> int | None:
    """
    Fetches the internal database UserID for a given Discord user ID.

    Input: discord_id (int) - The Discord user's ID.
    Output: int | None - The internal UserID, or None if not found.
    """
    db_manager.cursor.execute(
        "SELECT UserID FROM Users WHERE DiscordID = ?", (discord_id,)
    )
    return db_manager.cursor.fetchval()


def process_scramble_image(b64_string: str) -> io.BytesIO:
    """
    Decodes a base64-encoded image, resizes it, and enhances contrast.

    Input: b64_string (str) - Base64-encoded image data.
    Output: io.BytesIO - A PNG image buffer ready for Discord upload.
    """
    decoded = base64.b64decode(b64_string)
    png_buffer = io.BytesIO(decoded)
    png_buffer.seek(0)

    with Image.open(png_buffer) as img:
        resized = img.resize((500, 300))
        enhanced = ImageEnhance.Contrast(resized).enhance(2)

        out_buffer = io.BytesIO()
        enhanced.save(out_buffer, format="PNG")
        out_buffer.seek(0)
        return out_buffer
