"""Validation route (the VALIDATION API).

POST /api/validate accepts ``{"run_id": "..."}``. It rebuilds the
source-vs-target comparison from the persisted capture artifacts and
generates the DOCX report (embedded screenshots) into the run folder.

Capture must happen first via POST /api/browser-metrics (the PERFORMANCE
API), and callers should poll GET /api/runs/{run_id}/status until the
performance capture reaches a terminal state, then call POST /api/validate.

Validation is deliberately separate from performance:

* When ``validation_capture.json`` already exists for the run_id, this is
  pure computation — no browser launch, no metrics recalculation.
* When it is missing, validation runs its own browser capture (DOM
  extraction, table exports, slicer scenarios, AI) against the baseline
  screenshots produced earlier by the Performance API, persists the capture,
  and computes. Performance is never repeated here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.dependencies import get_validator, validate_run_id
from api.schemas import ValidateRequest
from services.validation_report_service import (
    ValidationReportError,
    ValidationReportNotFound,
    build_validation_report,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["validation"])


@router.post("/api/validate")
async def validate(request: ValidateRequest) -> dict:
    run_id = (request.run_id or "").strip()
    if not run_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "run_id is required. Capture the dashboards first via "
                "POST /api/browser-metrics, then poll "
                "GET /api/runs/{run_id}/status until completed."
            ),
        )

    validate_run_id(run_id)

    try:
        logger.info("Artifact validation request received | run_id=%s", run_id)
        validator = get_validator()
        result = await validator.run_validation_from_artifacts(run_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Artifact validation request failed | run_id=%s",
            run_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Validation failed. Review the server logs for details.",
        )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No validation capture found for run_id {run_id}.",
        )

    logger.info("Validation completed | run_id=%s", result.get("run_id"))

    result["docx_download_url"] = f"/api/runs/{run_id}/report"
    try:
        document_path = await build_validation_report(run_id)
        result["docx_ready"] = True
        result["docx_path"] = str(document_path)
        logger.info(
            "Validation report generated | run_id=%s | path=%s",
            result.get("run_id"),
            document_path,
        )
    except (ValidationReportNotFound, ValidationReportError) as exc:
        logger.warning(
            "Validation report generation failed | run_id=%s | %s",
            run_id,
            exc,
        )
        result["docx_ready"] = False
        result["docx_path"] = None
        result["docx_error"] = str(exc)

    return result