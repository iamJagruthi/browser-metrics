"""Lightweight dashboard probe routes (filters, inventory, pages).

Jagruthi — DOM-only probes without a full validation run.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.dependencies import build_probe_links, get_validator
from api.schemas import ProbeRequest


logger = logging.getLogger(__name__)

router = APIRouter(tags=["probes"])


@router.post("/api/filters")
async def probe_filters(request: ProbeRequest) -> dict:
    source_url = request.source_url.strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url is required.")
    try:
        logger.info("Filter probe started | source=%s", source_url)
        validator = get_validator()
        links = build_probe_links(source_url, request.target_url)
        result = await validator.run_filter_probe(links)
        logger.info("Filter probe completed | dashboards=%d", len(result.get("dashboards", [])))
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Filter probe request failed")
        raise HTTPException(
            status_code=500,
            detail="Filter probe failed. Review the server logs for details.",
        )


@router.post("/api/inventory")
async def probe_inventory(request: ProbeRequest) -> dict:
    source_url = request.source_url.strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url is required.")
    try:
        logger.info("Inventory probe started | source=%s", source_url)
        validator = get_validator()
        links = build_probe_links(source_url, request.target_url)
        result = await validator.run_inventory_probe(links)
        logger.info("Inventory probe completed | dashboards=%d", len(result.get("dashboards", [])))
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Inventory probe request failed")
        raise HTTPException(
            status_code=500,
            detail="Inventory probe failed. Review the server logs for details.",
        )


@router.post("/api/pages")
async def probe_pages(request: ProbeRequest) -> dict:
    """Jagruthi — multi-page showcase: page names, KPIs, visuals, inventory."""
    source_url = request.source_url.strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="source_url is required.")
    try:
        logger.info("Pages showcase probe started | source=%s", source_url)
        validator = get_validator()
        links = build_probe_links(source_url, request.target_url)
        result = await validator.run_pages_probe(links)
        logger.info(
            "Pages showcase probe completed | multi_page=%s | dashboards=%d",
            result.get("multi_page_mode"),
            len(result.get("dashboards", [])),
        )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Pages showcase probe request failed")
        raise HTTPException(
            status_code=500,
            detail="Pages showcase probe failed. Review the server logs for details.",
        )
