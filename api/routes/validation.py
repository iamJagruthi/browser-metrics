"""Full source-vs-target validation route."""
#jagruthi

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.dependencies import get_validator
from api.schemas import ValidateRequest


logger = logging.getLogger(__name__)

router = APIRouter(tags=["validation"])


@router.post("/api/validate")
async def validate(request: ValidateRequest) -> dict:
    source_url = request.source_url.strip()
    target_url = request.target_url.strip()
    if not source_url or not target_url:
        raise HTTPException(
            status_code=400,
            detail="Both source_url and target_url are required.",
        )
    try:
        logger.info("Validation request received | source=%s | target=%s", source_url, target_url)
        validator = get_validator()
        links = [
            {"name": "Dashboard A", "url": source_url},
            {"name": "Dashboard B", "url": target_url},
        ]
        result = await validator.run_links(links)
        logger.info("Validation completed | run_id=%s", result.get("run_id"))
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Validation request failed")
        raise HTTPException(
            status_code=500,
            detail="Validation failed. Review the server logs for details.",
        )
