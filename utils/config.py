"""
config.py

Loads all project configuration from the .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# --------------------------------------------------
# Load .env
# --------------------------------------------------

load_dotenv()

# --------------------------------------------------
# Project Paths
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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
PAGE_TIMEOUT
# -----------------------------------
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
# Storage
# --------------------------------------------------

STORAGE_TYPE = os.getenv(
    "STORAGE_TYPE",
    "both"
)

CSV_FILE = OUTPUT_DIR / os.getenv(
    "CSV_FILE",
    "DashboardMetrics.csv"
)

EXCEL_FILE = OUTPUT_DIR / os.getenv(
    "EXCEL_FILE",
    "DashboardMetrics.xlsx"
)

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