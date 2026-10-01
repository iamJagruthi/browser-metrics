"""Persistent storage for browser-metrics capture artifacts.

Stores both capture layers under ``output/reports/<run_id>/`` (the
existing REPORT_DIR filesystem infrastructure):

* ``browser_metrics.json`` — the compact, browser-facing performance
  result of the browser-metrics run.
* ``validation_capture.json`` — the FULL validation capture (public
  executions, per-dashboard groups, page mode, source filter
  selections, and slicer scenario results) so a later
  ``POST /api/validate`` can rebuild the validation report as pure
  computation without launching a second browser.

Only JSON-serializable data is persisted here. Live Playwright
objects (Page/BrowserContext) are never stored; ``_page`` references
are stripped before writing via the validator's public-execution
helpers.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from utils.config import REPORT_DIR


logger = logging.getLogger(__name__)

BROWSER_METRICS_FILENAME = "browser_metrics.json"
VALIDATION_CAPTURE_FILENAME = "validation_capture.json"
RUN_STATUS_FILENAME = "run_status.json"
DOM_RESULTS_FILENAME = "dom_results.json"
AI_RESULTS_FILENAME = "ai_results.json"


def _run_dir(run_id: str) -> Path:
    directory = REPORT_DIR / run_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def persist_browser_metrics(run_id: str, payload: dict) -> Path:
    """Write the compact browser-metrics payload for a run.

    Returns the written file path.
    Raises on write failure (caller decides how to surface it).
    """
    path = _run_dir(run_id) / BROWSER_METRICS_FILENAME
    document = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Persisted browser metrics | run_id=%s | path=%s", run_id, path)
    return path


def load_browser_metrics(run_id: str) -> dict | None:
    """Load a previously persisted browser-metrics payload.

    Returns None when the run artifact does not exist.
    """
    path = Path(REPORT_DIR) / run_id / BROWSER_METRICS_FILENAME
    if not path.exists():
        logger.warning(
            "Browser metrics artifact not found | run_id=%s | path=%s",
            run_id,
            path,
        )
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        logger.info("Loaded browser metrics artifact | run_id=%s", run_id)
        return document
    except Exception:
        logger.exception(
            "Failed to parse browser metrics artifact | run_id=%s | path=%s",
            run_id,
            path,
        )
        return None


def persist_validation_capture(run_id: str, payload: dict) -> Path:
    """Write the full JSON-serializable validation capture for a run.

    The payload must be free of live Playwright objects (no Page /
    BrowserContext references). Returns the written file path. Raises on
    write failure (caller decides how to surface it).
    """
    path = _run_dir(run_id) / VALIDATION_CAPTURE_FILENAME
    document = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "Persisted validation capture | run_id=%s | path=%s",
        run_id,
        path,
    )
    return path


def load_validation_capture(run_id: str) -> dict | None:
    """Load a previously persisted full validation capture.

    Returns None when the run artifact does not exist or cannot be
    parsed.
    """
    path = Path(REPORT_DIR) / run_id / VALIDATION_CAPTURE_FILENAME
    if not path.exists():
        logger.warning(
            "Validation capture artifact not found | run_id=%s | path=%s",
            run_id,
            path,
        )
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        logger.info("Loaded validation capture artifact | run_id=%s", run_id)
        return document
    except Exception:
        logger.exception(
            "Failed to parse validation capture artifact | run_id=%s | path=%s",
            run_id,
            path,
        )
        return None


def persist_run_status(
    run_id: str,
    status: str,
    *,
    details: dict | None = None,
) -> Path:
    """Persist the lifecycle status of a run (running/completed/partial/failed).

    The status file lives alongside the other run artifacts so any later
    request (e.g. ``GET /api/runs/{run_id}/status``) can query it without
    holding the browser or re-running the job.
    """
    path = _run_dir(run_id) / RUN_STATUS_FILENAME
    document = {
        "run_id": run_id,
        "status": status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "details": details or {},
    }
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Persisted run status | run_id=%s | status=%s", run_id, status)
    return path


def load_run_status(run_id: str) -> dict | None:
    """Load the persisted lifecycle status for a run.

    Returns None when the run artifact does not exist or cannot be parsed.
    """
    path = Path(REPORT_DIR) / run_id / RUN_STATUS_FILENAME
    if not path.exists():
        logger.warning(
            "Run status artifact not found | run_id=%s | path=%s",
            run_id,
            path,
        )
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception(
            "Failed to parse run status artifact | run_id=%s | path=%s",
            run_id,
            path,
        )
        return None


def persist_dom_results(run_id: str, response: dict) -> Path:
    """Write the pure DOM/compute validation result for a run.

    The persisted payload is the validation response EXCLUDING the
    ``ai_analysis`` channel (which lives separately as ``ai_results.json``),
    so the DOM result can be compared directly against the AI result.
    Returns the written file path. Raises on write failure.
    """
    path = _run_dir(run_id) / DOM_RESULTS_FILENAME
    document = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **{
            key: value
            for key, value in response.items()
            if key != "ai_analysis"
        },
    }
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Persisted DOM results | run_id=%s | path=%s", run_id, path)
    return path


def persist_ai_results(run_id: str, ai_analysis: dict | None) -> Path | None:
    """Write the hosted AI validation result for a run as its own JSON.

    Returns the written path, or None when there is no AI result to save
    (``ai_results.json`` stays absent so the DOM-vs-AI comparison clearly
    shows AI was not run for this run). Raises on write failure.
    """
    if not ai_analysis:
        logger.info("No AI result to persist | run_id=%s", run_id)
        return None
    path = _run_dir(run_id) / AI_RESULTS_FILENAME
    document = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **ai_analysis,
    }
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Persisted AI results | run_id=%s | path=%s", run_id, path)
    return path