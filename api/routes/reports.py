"""Report download and snapshot retrieval routes.

Jagruthi — Excel/DOCX downloads plus filters, inventory, and pages snapshots.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.dependencies import validate_run_id
from services.dashboard_inventory_service import load_inventory_snapshot, load_pages_snapshot
from services.filter_service import load_filters_snapshot
from services.mismatch_service import load_mismatch_snapshot
from utils.config import REPORT_DIR


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _report_file_path(run_id: str, extension: str) -> Path:
    validate_run_id(run_id)
    path = REPORT_DIR / f"{run_id}_dashboard_validation.{extension}"
    if not path.is_file():
        logger.warning(
            "Report file not ready | run_id=%s | extension=%s",
            run_id,
            extension,
        )
        raise HTTPException(
            status_code=404,
            detail=f"{extension.upper()} report is not ready for this run.",
        )
    return path


@router.get("/{run_id}")
async def report_status(run_id: str) -> dict[str, object]:
    try:
        validate_run_id(run_id)
        logger.info("Report status requested | run_id=%s", run_id)
        return {
            "run_id": run_id,
            "excel_ready": (REPORT_DIR / f"{run_id}_dashboard_validation.xlsx").is_file(),
            "docx_ready": (REPORT_DIR / f"{run_id}_dashboard_validation.docx").is_file(),
            "filters_ready": (REPORT_DIR / f"{run_id}_filters.json").is_file(),
            "inventory_ready": (REPORT_DIR / f"{run_id}_inventory.json").is_file(),
            "pages_ready": (REPORT_DIR / f"{run_id}_pages.json").is_file(),
            "mismatches_ready": (REPORT_DIR / f"{run_id}_mismatches.json").is_file(),
            "excel_download_url": f"/api/reports/{run_id}/excel",
            "docx_download_url": f"/api/reports/{run_id}/docx",
            "filters_url": f"/api/reports/{run_id}/filters",
            "inventory_url": f"/api/reports/{run_id}/inventory",
            "pages_url": f"/api/reports/{run_id}/pages",
            "mismatches_url": f"/api/reports/{run_id}/mismatches",
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Report status failed | run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="Unable to read report status.")


@router.get("/{run_id}/excel")
async def download_excel_report(run_id: str) -> FileResponse:
    try:
        path = _report_file_path(run_id, "xlsx")
        logger.info("Excel download | run_id=%s", run_id)
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=path.name,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Excel download failed | run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="Excel download failed.")


@router.get("/{run_id}/docx")
async def download_docx_report(run_id: str) -> FileResponse:
    try:
        path = _report_file_path(run_id, "docx")
        logger.info("DOCX download | run_id=%s", run_id)
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=path.name,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("DOCX download failed | run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="DOCX download failed.")


@router.get("/{run_id}/filters")
async def get_run_filters(run_id: str) -> dict:
    try:
        validate_run_id(run_id)
        payload = load_filters_snapshot(run_id, REPORT_DIR)
        if payload is None:
            logger.warning("Filter snapshot missing | run_id=%s", run_id)
            raise HTTPException(status_code=404, detail="Filter snapshot is not ready for this run.")
        return payload
    except HTTPException:
        raise
    except Exception:
        logger.exception("Filter snapshot read failed | run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="Unable to load filter snapshot.")


@router.get("/{run_id}/inventory")
async def get_run_inventory(run_id: str) -> dict:
    try:
        validate_run_id(run_id)
        payload = load_inventory_snapshot(run_id, REPORT_DIR)
        if payload is None:
            logger.warning("Inventory snapshot missing | run_id=%s", run_id)
            raise HTTPException(status_code=404, detail="Inventory snapshot is not ready for this run.")
        return payload
    except HTTPException:
        raise
    except Exception:
        logger.exception("Inventory snapshot read failed | run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="Unable to load inventory snapshot.")


@router.get("/{run_id}/pages")
async def get_run_pages(run_id: str) -> dict:
    """Jagruthi — page names, KPIs, visuals, and inventory per report page."""
    try:
        validate_run_id(run_id)
        payload = load_pages_snapshot(run_id, REPORT_DIR)
        if payload is None:
            logger.warning("Pages snapshot missing | run_id=%s", run_id)
            raise HTTPException(
                status_code=404,
                detail="Pages showcase snapshot is not ready for this run.",
            )
        return payload
    except HTTPException:
        raise
    except Exception:
        logger.exception("Pages snapshot read failed | run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="Unable to load pages snapshot.")


@router.get("/{run_id}/mismatches")
async def get_run_mismatches(run_id: str) -> dict:
    """Jagruthi — mismatch-only comparison data for frontend diff views."""
    try:
        validate_run_id(run_id)
        payload = load_mismatch_snapshot(run_id, REPORT_DIR)
        if payload is None:
            logger.warning("Mismatch snapshot missing | run_id=%s", run_id)
            raise HTTPException(
                status_code=404,
                detail="Mismatch snapshot is not ready for this run.",
            )
        return payload
    except HTTPException:
        raise
    except Exception:
        logger.exception("Mismatch snapshot read failed | run_id=%s", run_id)
        raise HTTPException(status_code=500, detail="Unable to load mismatch snapshot.")
