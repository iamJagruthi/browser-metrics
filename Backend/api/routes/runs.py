"""Run status routes.

GET /api/runs/{run_id}/status returns the persisted lifecycle status of a
capture run (running/completed/partial/failed) so a caller can poll after
POST /api/browser-metrics returns its immediate run_id.

GET /api/runs/{run_id}/report generates and streams the automated PBI
validation DOCX for a completed capture run, built purely from the
persisted artifacts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.dependencies import validate_run_id
from services.run_artifact_store import load_run_status
from services.validation_report_service import (
    ValidationReportError,
    ValidationReportNotFound,
    build_validation_report,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])


@router.get("/api/runs/{run_id}/status")
async def run_status(run_id: str) -> dict:
    valid_run_id = validate_run_id(run_id)
    status_doc = load_run_status(valid_run_id)
    if status_doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"No run found for run_id {valid_run_id}.",
        )
    return status_doc


@router.get("/api/runs/{run_id}/report")
async def validation_report(run_id: str) -> FileResponse:
    valid_run_id = validate_run_id(run_id)
    try:
        destination = await build_validation_report(valid_run_id)
    except ValidationReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationReportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        destination,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename=destination.name,
    )