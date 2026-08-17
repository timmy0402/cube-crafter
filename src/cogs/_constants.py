from discord import app_commands

# This is for the database related like time, personal bests
PUZZLE_CHOICES = [
    app_commands.Choice(name="2x2", value="2x2"),
    app_commands.Choice(name="3x3", value="3x3"),
    app_commands.Choice(name="4x4", value="4x4"),
    app_commands.Choice(name="5x5", value="5x5"),
    app_commands.Choice(name="6x6", value="6x6"),
    app_commands.Choice(name="7x7", value="7x7"),
    app_commands.Choice(name="pyraminx", value="PYRA"),
    app_commands.Choice(name="square1", value="SQ1"),
    app_commands.Choice(name="megaminx", value="MEGA"),
    app_commands.Choice(name="skewb", value="SKEWB"),
    app_commands.Choice(name="clock", value="CLOCK"),
]

# This is a map to scramble api value
SCRAMBLE_API_MAP = {
    "2x2" : "TWO",
    "3x3" : "THREE",
    "4x4" : "FOUR",
    "5x5" : "FIVE",
    "6x6" : "SIX",
    "7x7" : "SEVEN",
    "PYRA" : "PYRA",
    "SQ1" : "SQ1",
    "MEGA" : "MEGA",
    "SKEWB" : "SKEWB",
    "CLOCK" : "CLOCK",
}

# Subset for /sessions: NxN only — other puzzles produce scrambles too long
# to fit multiple in a single Discord message.
SCRAMBLE_API_NXN_CHOICES = [
    app_commands.Choice(name="2x2", value="TWO"),
    app_commands.Choice(name="3x3", value="THREE"),
    app_commands.Choice(name="4x4", value="FOUR"),
    app_commands.Choice(name="5x5", value="FIVE"),
    app_commands.Choice(name="6x6", value="SIX"),
    app_commands.Choice(name="7x7", value="SEVEN"),
]

# Per-puzzle scramble count caps for /sessions. Larger cubes have longer
# scramble strings, so fewer fit inside Discord's 2000-char message limit.
SESSIONS_MAX_COUNT = {
    "TWO": 10,
    "THREE": 10,
    "FOUR": 10,
    "FIVE": 7,
    "SIX": 6,
    "SEVEN": 5,
}
SESSIONS_ABS_MAX = max(SESSIONS_MAX_COUNT.values())
