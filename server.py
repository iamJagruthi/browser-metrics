"""
server.py

FastAPI backend that exposes the dashboard validator over HTTP.
Run from the project root with:

    uvicorn server:app --reload --port 8000

Frontend (Vite/React dev server on http://localhost:5173) posts two
dashboard URLs to POST /api/validate and receives metrics + comparison.
"""

import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from automation.validator import DashboardValidator
from utils.config import REPORT_DIR


logger = logging.getLogger(__name__)

app = FastAPI(title="Browser Metrics Validator API")

# Allow the Vite dev server to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ValidateRequest(BaseModel):
    source_url: str
    target_url: str


def _report_path(run_id: str, extension: str) -> Path:
    """Resolve a generated report without allowing path traversal."""
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise HTTPException(status_code=400, detail="Invalid validation run ID.")
    path = REPORT_DIR / f"{run_id}_dashboard_validation.{extension}"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{extension.upper()} report is not ready for this run.")
    return path


@app.get("/api/health")
async def health():
    """
    Simple health check so the frontend can verify the API is up.
    """
    return {"status": "ok", "service": "browser-metrics-validator"}


@app.get("/api/reports/{run_id}")
async def report_status(run_id: str):
    """Return frontend-ready report download links for a completed run."""
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise HTTPException(status_code=400, detail="Invalid validation run ID.")
    return {
        "run_id": run_id,
        "excel_ready": (REPORT_DIR / f"{run_id}_dashboard_validation.xlsx").is_file(),
        "docx_ready": (REPORT_DIR / f"{run_id}_dashboard_validation.docx").is_file(),
        "excel_download_url": f"/api/reports/{run_id}/excel",
        "docx_download_url": f"/api/reports/{run_id}/docx",
    }


@app.get("/api/reports/{run_id}/excel")
async def download_excel_report(run_id: str):
    path = _report_path(run_id, "xlsx")
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=path.name)


@app.get("/api/reports/{run_id}/docx")
async def download_docx_report(run_id: str):
    path = _report_path(run_id, "docx")
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=path.name)


@app.post("/api/validate")
async def validate(request: ValidateRequest):
    """
    Runs the validator against the two supplied URLs and returns
    metrics for each dashboard plus the KPI comparison between them.
    """

    if not request.source_url.strip() or not request.target_url.strip():
        raise HTTPException(
            status_code=400,
            detail="Both source_url and target_url are required.",
        )

    try:
        validator = DashboardValidator()

        links = [
            {"name": "Dashboard A", "url": request.source_url.strip()},
            {"name": "Dashboard B", "url": request.target_url.strip()},
        ]
        logger.info("Validation request received")
        result = await validator.run_links(links)
        logger.info("Validation completed | run_id=%s", result.get("run_id"))
        return result

    except Exception:
        logger.exception("Validation request failed")
        raise HTTPException(status_code=500, detail="Validation failed. Review the server logs for details.")
