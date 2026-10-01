"""
config.py

Loads all project configuration from the .env file.
"""

import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------
# Load .env (project root only)
# --------------------------------------------------

try:
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    logger.exception("Failed to load .env from project root")

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

# # --------------------------------------------------
# # Matrix / table scroll (Jagruthi: wider matrices need more horizontal steps)
# # --------------------------------------------------

# MATRIX_MAX_SCROLL_STEPS = int(os.getenv("MATRIX_MAX_SCROLL_STEPS", "60"))
# SCROLL_STEP_WAIT_MS = int(os.getenv("SCROLL_STEP_WAIT_MS", "350"))

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

try:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    logger.exception("Failed to create output directories")

REPORT_DIR = PROJECT_ROOT / os.getenv(
    "REPORT_DIR",
    "output/reports"
)

try:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    logger.exception("Failed to create report directory | path=%s", REPORT_DIR)

# --------------------------------------------------
# Screenshot side folders (hosted AI consumption)
# --------------------------------------------------

SCREENSHOT_SOURCE_FOLDER = os.getenv(
    "SCREENSHOT_SOURCE_FOLDER",
    "SpartanNash"
)

SCREENSHOT_TARGET_FOLDER = os.getenv(
    "SCREENSHOT_TARGET_FOLDER",
    "Tredence"
)

# Optional title-keyword identity hints used ONLY to decide which loaded
# dashboard is the ACTUAL source and which is the ACTUAL target, so the
# side folders above receive the correct dashboard regardless of the order
# the URLs arrive in. The target/source pages of these Snowflake-vs-GCP
# reports are distinguished by "GCP" appearing in the target page title.
# Empty (default) means no title-based resolution; the side then follows
# the request order (source_url first).
SCREENSHOT_SOURCE_TITLE_KEYWORDS = [
    keyword.strip().casefold()
    for keyword in os.getenv("SCREENSHOT_SOURCE_TITLE_KEYWORDS", "").split(",")
    if keyword.strip()
]
SCREENSHOT_TARGET_TITLE_KEYWORDS = [
    keyword.strip().casefold()
    for keyword in os.getenv(
        "SCREENSHOT_TARGET_TITLE_KEYWORDS",
        "GCP",
    ).split(",")
    if keyword.strip()
]

# Hosted AI validation service. When unset the validator stays in pure DOM
# mode; set it (e.g. via .env) once the hosted app exposes a usable API.
AI_VALIDATION_SERVICE_URL = (
    (os.getenv("AI_VALIDATION_SERVICE_URL") or "").strip() or None
)

# Folder identifiers the hosted service accepts in its upload path
# (documented contract: enum "spartnash" | "trendence"). Kept configurable
# so the mapping stays explicit instead of being embedded in code.
AI_VALIDATION_SOURCE_FOLDER = os.getenv(
    "AI_VALIDATION_SOURCE_FOLDER",
    "spartnash"
)
AI_VALIDATION_TARGET_FOLDER = os.getenv(
    "AI_VALIDATION_TARGET_FOLDER",
    "trendence"
)

# --------------------------------------------------
# Per-run screenshot folder (LLM-friendly artifact store)
# --------------------------------------------------

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(value) -> str:
    """Collapse any string into a Windows/Linux-safe filename fragment."""
    fragment = _INVALID_FILENAME_CHARS.sub("_", str(value).strip())
    fragment = re.sub(r"\s+", "_", fragment)
    return fragment.strip("._")


VALIDATION_REPORT_TEMPLATE = PROJECT_ROOT / os.getenv(
    "VALIDATION_REPORT_TEMPLATE",
    "templates/PBI Report Validation - Template.docx"
)


def run_screenshot_dir(run_id: str) -> Path:
    """Per-run subfolder under SCREENSHOT_DIR, created on demand.

    Storing captures under ``output/screenshots/<run_id>/`` keeps every
    run's artifacts grouped and LLM-friendly (stable naming, no
    cross-run collisions).
    """
    directory = SCREENSHOT_DIR / sanitize_filename(run_id)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.exception("Failed to create run screenshot directory | path=%s", directory)
    return directory


def screenshot_side_folder(side: str) -> str:
    """Folder label used for a screenshot side.

    Side keys are the positional source/target labels produced by the
    validator ("source" / "target"). The folder names themselves stay
    configurable (defaults SpartanNash / Tredence) so nothing is hardcoded.
    """
    normalized = str(side or "").strip().casefold()
    if normalized in ("source", "src", "snowflake", "gcp", "0"):
        return SCREENSHOT_SOURCE_FOLDER
    if normalized in ("target", "tgt", "tredence", "dst", "1"):
        return SCREENSHOT_TARGET_FOLDER
    return sanitize_filename(str(side)) or "screenshots"


def side_screenshot_dir(screenshot_dir: Path, side: str) -> Path:
    """Per-side subfolder (source/target) under the run screenshot directory.

    The hosted AI validation service consumes screenshots from these two
    folders, so every write site in the validator routes its captures here.
    """
    directory = Path(screenshot_dir) / sanitize_filename(screenshot_side_folder(side))
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.exception("Failed to create side screenshot directory | path=%s", directory)
    return directory


def dashboard_side_by_title(page_title: str | None) -> str | None:
    """Resolve a dashboard's ACTUAL side from its captured page title.

    Uses only the configurable SCREENSHOT_*_TITLE_KEYWORDS lists. Returns
    ``"source"`` / ``"target"`` when exactly one keyword list matches the
    title, and ``None`` when neither does (the caller then falls back to the
    request-order assignment). No report-specific value is hardcoded here.
    """
    lowered = str(page_title or "").strip().casefold()
    if not lowered:
        return None
    target_match = any(keyword in lowered for keyword in SCREENSHOT_TARGET_TITLE_KEYWORDS)
    source_match = any(keyword in lowered for keyword in SCREENSHOT_SOURCE_TITLE_KEYWORDS)
    if target_match and not source_match:
        return "target"
    if source_match and not target_match:
        return "source"
    return None