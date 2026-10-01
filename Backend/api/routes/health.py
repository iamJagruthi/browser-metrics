"""Health check routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter


logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health() -> dict[str, str]:
    try:
        logger.debug("Health check requested")
        return {"status": "ok", "service": "browser-metrics-validator"}
    except Exception:
        logger.exception("Health check failed")
        raise
