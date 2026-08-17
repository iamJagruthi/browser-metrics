"""
config.py

Loads all project configuration from the .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------
# Load .env (project root only)
# --------------------------------------------------

load_dotenv(PROJECT_ROOT / ".env")

OUTPUT_DIR = PROJECT_ROOT / os.getenv(
    "OUTPUT_DIR",
    "output"
)

SCREENSHOT_DIR = PROJECT_ROOT / os.getenv(
    "SCREENSHOT_DIR",
    "output/screenshots"
)

DASHBOARD_CONFIG = PROJECT_ROOT / os.getenv(
    "DASHBOARD_CONFIG",
    "config/dashboards.json"
)

PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", 120000))

# --------------------------------------------------
# Matrix / table scroll (Jagruthi: wider matrices need more horizontal steps)
# --------------------------------------------------

MATRIX_MAX_SCROLL_STEPS = int(os.getenv("MATRIX_MAX_SCROLL_STEPS", "60"))
SCROLL_STEP_WAIT_MS = int(os.getenv("SCROLL_STEP_WAIT_MS", "350"))

# --------------------------------------------------
# Browser
# --------------------------------------------------
PROFILE_DIR = os.getenv("PROFILE_DIR") or "Profile 7"

# print(f"PROFILE_DIR = '{PROFILE_DIR}'")
EDGE_USER_DATA = (
    Path.home()
    / "AppData"
    / "Local"
    / "Microsoft"
    / "Edge"
    / "User Data"
)

BROWSER_CHANNEL = os.getenv(
    "BROWSER_CHANNEL",
    "msedge"
)

HEADLESS = os.getenv(
    "HEADLESS",
    "False"
).lower() == "true"

# --------------------------------------------------
# Dashboard
# --------------------------------------------------

RENDER_WAIT = int(
    os.getenv("RENDER_WAIT", "10000")
)

# --------------------------------------------------
# Table comparison config (Jagruthi: pandas table diff key strategy)
# --------------------------------------------------

TABLE_COMPARE_KEY_STRATEGY = os.getenv("TABLE_COMPARE_KEY_STRATEGY", "auto")
TABLE_COMPARE_KEY_COLUMNS = [
    column.strip()
    for column in os.getenv("TABLE_COMPARE_KEY_COLUMNS", "").split(",")
    if column.strip()
]

# --------------------------------------------------
# Create Required Directories
# --------------------------------------------------

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

SCREENSHOT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

REPORT_DIR = PROJECT_ROOT / os.getenv(
    "REPORT_DIR",
    "output/reports"
)

REPORT_DIR.mkdir(
    parents=True,
    exist_ok=True
)