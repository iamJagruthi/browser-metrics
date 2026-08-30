"""Normalize DOM/Gemini filter state for API and report consumers.

Jagruthi — exposes available values, selected values, and button options with
per-option selection state for frontend and integration clients.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_BUTTON_FILTER_TYPES = frozenset({"buttons", "button", "button-style selector"})
_UI_NOISE = frozenset(
    {
        "more options",
        "focus mode",
        "drill down",
        "expand",
        "drill up",
        "see more",
    }
)


def _normalize_name(value: str) -> str:
    return " ".join(str(value).casefold().split())


def _is_button_filter(filter_type: str | None) -> bool:
    return _normalize_name(filter_type or "") in _BUTTON_FILTER_TYPES


def _build_options(
    dom_filter: dict[str, Any],
    gemini_filter: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build a unified options list with selection flags."""
    raw_options = dom_filter.get("options") or []
    if raw_options:
        return [
            {
                "value": str(item.get("value", "")).strip(),
                "selected": bool(item.get("selected")),
                "control_type": item.get("control_type") or "option",
            }
            for item in raw_options
            if str(item.get("value", "")).strip()
            and _normalize_name(str(item.get("value", ""))) not in _UI_NOISE
        ]

    visible = []
    for source in (dom_filter.get("visible_values"), (gemini_filter or {}).get("available_values")):
        for value in source or []:
            text = str(value).strip()
            if text and _normalize_name(text) not in _UI_NOISE:
                visible.append(text)

    selected_set = {
        _normalize_name(value)
        for value in (dom_filter.get("selected_values") or [])
        + ((gemini_filter or {}).get("selected_values") or [])
        if str(value).strip()
    }
    unique_visible: list[str] = []
    seen: set[str] = set()
    for value in visible:
        key = _normalize_name(value)
        if key in seen:
            continue
        seen.add(key)
        unique_visible.append(value)

    filter_type = dom_filter.get("filter_type") or (gemini_filter or {}).get("filter_type")
    control_type = "button" if _is_button_filter(str(filter_type or "")) else "option"
    return [
        {
            "value": value,
            "selected": _normalize_name(value) in selected_set,
            "control_type": control_type,
        }
        for value in unique_visible
    ]


def normalize_dom_filter(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape a single DOM filter record for API output."""
    filter_type = str(raw.get("filter_type") or "Dropdown")
    options = _build_options(raw, None)
    selected_values = [
        item["value"] for item in options if item.get("selected")
    ] or list(raw.get("selected_values") or [])
    available_values = [item["value"] for item in options] or list(raw.get("visible_values") or [])
    payload: dict[str, Any] = {
        "filter_id": raw.get("id"),
        "filter_name": raw.get("name"),
        "filter_type": filter_type,
        "selected_values": selected_values,
        "available_values": available_values,
        "options": options,
        "extraction_source": raw.get("extraction_source", "dom"),
    }
    if _is_button_filter(filter_type) or any(item.get("control_type") == "button" for item in options):
        payload["filter_type"] = "Buttons"
        payload["buttons"] = [
            {"label": item["value"], "selected": item["selected"]}
            for item in options
            if item.get("control_type") == "button" or _is_button_filter(filter_type)
        ]
    return payload


def normalize_merged_filter(
    dom_filter: dict[str, Any] | None,
    gemini_filter: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge DOM and Gemini filter records into one API object."""
    if not dom_filter and not gemini_filter:
        return None

    name = (dom_filter or {}).get("name") or (gemini_filter or {}).get("filter_name")
    if not name:
        return None

    filter_type = (
        (dom_filter or {}).get("filter_type")
        or (gemini_filter or {}).get("filter_type")
        or "Dropdown"
    )
    options = _build_options(dom_filter or {}, gemini_filter)
    selected_values = [
        item["value"] for item in options if item.get("selected")
    ]
    if not selected_values:
        selected_values = list((dom_filter or {}).get("selected_values") or [])
    if not selected_values:
        selected_values = list((gemini_filter or {}).get("selected_values") or [])

    available_values = [item["value"] for item in options]
    if not available_values:
        available_values = list((dom_filter or {}).get("visible_values") or [])
    if not available_values:
        available_values = list((gemini_filter or {}).get("available_values") or [])

    sources = []
    if dom_filter:
        sources.append("dom")
    if gemini_filter:
        sources.append("gemini")

    payload: dict[str, Any] = {
        "filter_id": (dom_filter or {}).get("id"),
        "filter_name": name,
        "filter_type": filter_type,
        "selected_values": selected_values,
        "available_values": available_values,
        "options": options,
        "extraction_source": "+".join(sources) if len(sources) > 1 else (sources[0] if sources else "unknown"),
    }
    if _is_button_filter(str(filter_type)) or any(
        item.get("control_type") == "button" for item in options
    ):
        payload["filter_type"] = "Buttons"
        payload["buttons"] = [
            {"label": item["value"], "selected": item["selected"]}
            for item in options
        ]
    return payload


def build_dashboard_filters_payload(execution: dict[str, Any]) -> dict[str, Any]:
    """Build filter API payload for one dashboard execution."""
    dashboard = execution.get("dashboard") or {}
    visual_data = execution.get("visual_data") or {}
    extraction = execution.get("extraction") or {}
    extraction_data = extraction.get("data") or {}

    dom_filters = {
        _normalize_name(item.get("name", "")): item
        for item in visual_data.get("filters", [])
        if item.get("name")
    }
    gemini_filters = {
        _normalize_name(item.get("filter_name", "")): item
        for item in extraction_data.get("filters", [])
        if item.get("filter_name")
    }

    filters: list[dict[str, Any]] = []
    for key in sorted(set(dom_filters) | set(gemini_filters)):
        merged = normalize_merged_filter(dom_filters.get(key), gemini_filters.get(key))
        if merged:
            filters.append(merged)

    return {
        "dashboard_name": dashboard.get("name"),
        "dashboard_url": dashboard.get("url"),
        "extraction_status": extraction.get("status"),
        "visual_extraction_status": visual_data.get("status"),
        "filter_count": len(filters),
        "filters": filters,
    }


def build_filters_api_payload(
    executions: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    comparison_filters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the full filters API response for a validation run."""
    try:
        dashboards = [build_dashboard_filters_payload(item) for item in executions]
        return {
            "run_id": run_id,
            "dashboards": dashboards,
            "comparison": comparison_filters or [],
            "filter_download_url": f"/api/reports/{run_id}/filters" if run_id else None,
        }
    except Exception:
        logger.exception("Failed to build filters API payload")
        raise


def save_filters_snapshot(
    run_id: str,
    payload: dict[str, Any],
    output_directory: Path,
) -> Path:
    """Persist filter payload so GET /api/reports/{run_id}/filters can retrieve it."""
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / f"{run_id}_filters.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Filter snapshot saved | run_id=%s | path=%s", run_id, path)
        return path
    except Exception:
        logger.exception("Failed to save filter snapshot | run_id=%s", run_id)
        raise


def load_filters_snapshot(run_id: str, output_directory: Path) -> dict[str, Any] | None:
    path = output_directory / f"{run_id}_filters.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load filter snapshot | run_id=%s", run_id)
        return None
