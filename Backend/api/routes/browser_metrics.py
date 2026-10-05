"""Browser metrics (PERFORMANCE) capture route.

POST /api/browser-metrics is ASYNCHRONOUS:

    1. Validates source_url/target_url.
    2. Creates a pair-level run_id and persists status=running.
    3. Schedules the long-running browser capture as a FastAPI
       BackgroundTask (the project has no queue system; BackgroundTasks is
       the smallest safe execution model for a single-process dev server).
    4. Returns immediately with {run_id, status: "running"}.

The background job runs ``DashboardValidator.run_browser_metrics`` — the
PERFORMANCE pass ONLY (browser launch, per-dashboard render measurement,
baseline screenshots, one filter render test). No DOM extraction, table
exports, slicer scenarios, comparisons, AI, or DOCX generation happen here.
It persists ``browser_metrics.json`` and the terminal run status as soon as
the performance result is complete, so callers can display the metrics
immediately.

The Validation API (POST /api/validate) is a separate operation: it reuses
``validation_capture.json`` when present, otherwise runs its own validation
browser capture for the same run_id and produces the comparison + Word
report. Performance never waits for validation; validation never repeats
performance measurement.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.dependencies import get_validator
from api.schemas import BrowserMetricsRequest
from services.run_artifact_store import load_run_status, persist_run_status


logger = logging.getLogger(__name__)

router = APIRouter(tags=["browser-metrics"])


async def _run_capture_job(
    run_id: str,
    source_url: str,
    target_url: str,
) -> None:
    """Run the browser capture in the background and persist the final status."""
    try:
        validator = get_validator()
        links = [
            {"name": "Dashboard A", "url": source_url},
            {"name": "Dashboard B", "url": target_url},
        ]
        result = await validator.run_browser_metrics(links, run_id=run_id)
        final_status = result.get("status", "failed")
        # The terminal state belongs to the PERFORMANCE API: preserve the
        # dashboard URLs from the scheduled state so the separate Validation
        # API can re-run its own browser capture for the same run without
        # waiting on anything that happens here.
        prior = load_run_status(run_id) or {}
        prior_details = prior.get("details") or {}
        persist_run_status(
            run_id,
            final_status,
            details={
                "source_url": prior_details.get("source_url"),
                "target_url": prior_details.get("target_url"),
                "source": result.get("source"),
                "target": result.get("target"),
                "artifacts": result.get("artifacts"),
                "validation_capture_status": result.get(
                    "validation_capture_status"
                ),
                "error": result.get("error"),
            },
        )
        logger.info(
            "browser_metrics.job.completed | run_id=%s | status=%s",
            run_id,
            final_status,
        )
    except Exception as exc:
        logger.exception(
            "browser_metrics.job.failed | run_id=%s",
            run_id,
        )
        persist_run_status(
            run_id,
            "failed",
            details={"error": str(exc)},
        )


@router.post("/api/browser-metrics")
async def browser_metrics(
    request: BrowserMetricsRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    source_url = request.source_url.strip()
    target_url = request.target_url.strip()
    if not source_url or not target_url:
        raise HTTPException(
            status_code=400,
            detail="Both source_url and target_url are required.",
        )

    run_id = uuid.uuid4().hex
    persist_run_status(
        run_id,
        "running",
        details={
            "source_url": source_url,
            "target_url": target_url,
        },
    )
    logger.info(
        "browser_metrics.request_accepted | run_id=%s | scheduled=background",
        run_id,
    )

    background_tasks.add_task(
        _run_capture_job,
        run_id,
        source_url,
        target_url,
    )

    return {
        "run_id": run_id,
        "status": "running",
        "source": None,
        "target": None,
        "artifacts": {"source": None, "target": None},
        "validation_capture_status": "pending",
    }