"""Shared FastAPI dependencies and helpers.

Jagruthi — run-id validation and dashboard link builders for routes.
"""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException

from automation.validator import DashboardValidator


logger = logging.getLogger(__name__)

_RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def validate_run_id(run_id: str) -> str:
    """Return run_id when it matches the expected hex format."""
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        logger.warning("Invalid validation run ID received | run_id=%s", run_id)
        raise HTTPException(status_code=400, detail="Invalid validation run ID.")
    return run_id


def build_probe_links(source_url: str, target_url: str | None = None) -> list[dict[str, str]]:
    """Build dashboard link objects for probe endpoints."""
    links = [{"name": "Dashboard A", "url": source_url.strip()}]
    cleaned_target = (target_url or "").strip()
    if cleaned_target:
        links.append({"name": "Dashboard B", "url": cleaned_target})
    return links


def get_validator() -> DashboardValidator:
    """Factory for a fresh validator instance per request."""
    return DashboardValidator()
