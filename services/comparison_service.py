"""
comparison_service.py

Unified DOM comparison, filter normalization, and mismatch extraction service.
Pure DOM Extraction Mode 
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.table_comparison import build_table_comparisons

logger = logging.getLogger(__name__)

# ============================================================================
# 1. FILTER NORMALIZATION & HELPERS
# ============================================================================

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
_MATCH_STATUSES = frozenset({"Match"})


def _normalise(name: Any) -> str:
    if not name:
        return ""
    cleaned = str(name).replace("\xa0", " ").strip().lower()
    return " ".join(cleaned.split())


def _is_button_filter(filter_type: str | None) -> bool:
    return _normalise(filter_type or "") in _BUTTON_FILTER_TYPES


def _build_options(dom_filter: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a normalized options list with selection flags strictly from DOM filter data."""
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
            and _normalise(str(item.get("value", ""))) not in _UI_NOISE
        ]

    visible = [
        str(value).strip()
        for value in (dom_filter.get("visible_values") or [])
        if str(value).strip() and _normalise(str(value)) not in _UI_NOISE
    ]

    selected_set = {
        _normalise(value)
        for value in (dom_filter.get("selected_values") or [])
        if str(value).strip()
    }

    unique_visible: list[str] = []
    seen: set[str] = set()
    for value in visible:
        key = _normalise(value)
        if key in seen:
            continue
        seen.add(key)
        unique_visible.append(value)

    filter_type = dom_filter.get("filter_type")
    control_type = "button" if _is_button_filter(str(filter_type or "")) else "option"
    
    return [
        {
            "value": value,
            "selected": _normalise(value) in selected_set,
            "control_type": control_type,
        }
        for value in unique_visible
    ]


def normalize_dom_filter(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Shape a single DOM filter record for API output."""
    if not raw or not raw.get("name"):
        return None

    name = str(raw.get("name")).strip()
    filter_type = str(raw.get("filter_type") or "Dropdown")
    options = _build_options(raw)
    
    selected_values = [
        item["value"] for item in options if item.get("selected")
    ] or list(raw.get("selected_values") or [])
    
    available_values = [item["value"] for item in options] or list(raw.get("visible_values") or [])

    payload: dict[str, Any] = {
        "filter_id": raw.get("id"),
        "filter_name": name,
        "filter_type": filter_type,
        "selected_values": selected_values,
        "available_values": available_values,
        "options": options,
        "extraction_source": "dom",
    }
    
    if _is_button_filter(filter_type) or any(
        item.get("control_type") == "button" for item in options
    ):
        payload["filter_type"] = "Buttons"
        payload["buttons"] = [
            {"label": item["value"], "selected": item["selected"]}
            for item in options
        ]
        
    return payload


def build_dashboard_filters_payload(execution: dict[str, Any]) -> dict[str, Any]:
    """Build filter API payload for one dashboard execution using DOM data."""
    dashboard = execution.get("dashboard") or {}
    visual_data = execution.get("visual_data") or {}
    extraction = execution.get("extraction") or {}

    dom_filters = {
        _normalise(item.get("name", "")): item
        for item in visual_data.get("filters", [])
        if item.get("name")
    }

    filters: list[dict[str, Any]] = []
    for key in sorted(dom_filters):
        normalized = normalize_dom_filter(dom_filters[key])
        if normalized:
            filters.append(normalized)

    return {
        "dashboard_name": dashboard.get("name"),
        "dashboard_url": dashboard.get("url"),
        "extraction_status": extraction.get("status", "skipped"),
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
    dashboards = [build_dashboard_filters_payload(item) for item in executions]
    return {
        "run_id": run_id,
        "dashboards": dashboards,
        "comparison": comparison_filters or [],
        "filter_download_url": f"/api/reports/{run_id}/filters" if run_id else None,
    }


# ============================================================================
# 2. SANITIZATION & COMPARISON ENGINE
# ============================================================================

def sanitize_execution_for_api(execution: dict) -> dict:
    """Strip internal DOM bloat, full table rows, and redundant UI fields."""
    if not execution:
        return execution

    visual_data = execution.get("visual_data") or {}

    # 1. Clean visual metadata
    for key in ("visuals", "table_visuals"):
        if key in visual_data:
            for vis in visual_data[key]:
                vis.pop("accessible_text", None)
                vis.pop("position", None)
                vis.pop("svg_text", None)
                vis.pop("dom_content", None)
                vis.pop("type_source", None)

    # 2. Strip raw CSV rows from table exports (keep only summary row_count)
    if "table_exports" in visual_data:
        for tbl in visual_data["table_exports"]:
            data = tbl.get("data")
            if isinstance(data, dict):
                tbl["data"] = {
                    "columns": data.get("columns", []),
                    "row_count": data.get("row_count", len(data.get("rows", []))),
                    "rows_truncated": True,
                }

    return execution


def compare_browser_metrics(
    source_metrics: dict[str, Any] | None,
    target_metrics: dict[str, Any] | None,
    *,
    page_name: str | None = None,
) -> list[dict[str, Any]]:
    """Compare performance timing metrics between Source and Target executions."""
    if not source_metrics or not target_metrics:
        return []

    mismatches = []
    
    metric_keys = [
        "page_load_seconds",
        "dashboard_render_seconds",
        "total_execution_seconds",
        "visual_extraction_seconds",
        "screenshot_seconds",
    ]

    for key in metric_keys:
        source_val = source_metrics.get(key)
        target_val = target_metrics.get(key)

        if source_val is None and target_val is None:
            continue

        s_formatted = round(float(source_val), 2) if source_val is not None else "N/A"
        t_formatted = round(float(target_val), 2) if target_val is not None else "N/A"

        if s_formatted != t_formatted:
            mismatches.append({
                "metric": key,
                "page_name": page_name or source_metrics.get("page_name", "Default"),
                "source": s_formatted,
                "target": t_formatted,
                "status": "Different",
            })

    return mismatches


def _visual_key(item: dict[str, Any], fallback_index: int) -> str:
    title = _normalise(item.get("title"))
    if title:
        return f"title:{title}"
    visual_type = _normalise(item.get("visual_type"))
    if visual_type:
        return f"type:{visual_type}|index:{item.get('index', fallback_index)}"
    return f"index:{item.get('index', fallback_index)}"


def _pair_confidence(left: dict[str, Any] | None, right: dict[str, Any] | None) -> float | None:
    scores = []
    for item in (left, right):
        if not item:
            continue
        raw = item.get("confidence")
        try:
            if raw is not None:
                scores.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not scores:
        return None
    return min(scores)


def compare_kpis(source_kpis: list[dict[str, Any]], target_kpis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_map = {_normalise(item.get("name")): item for item in source_kpis if item.get("name")}
    target_map = {_normalise(item.get("name")): item for item in target_kpis if item.get("name")}
    results = []

    for key in sorted(set(source_map) | set(target_map)):
        source = source_map.get(key)
        target = target_map.get(key)

        if not source:
            results.append({"kpi": target.get("name"), "status": "Missing in Source", "source": None, "target": target.get("value")})
            continue
        if not target:
            results.append({"kpi": source.get("name"), "status": "Missing in Target", "source": source.get("value"), "target": None})
            continue

        source_value = _normalise(source.get("value"))
        target_value = _normalise(target.get("value"))
        status = "Match" if source_value == target_value else "Mismatch"
        confidence = _pair_confidence(source, target)
        if confidence is not None and confidence < 0.7 and status == "Mismatch":
            status = "needs_review"

        results.append({
            "kpi": source.get("name"),
            "status": status,
            "source": source.get("value"),
            "target": target.get("value"),
            "source_prior": source.get("previous_value"),
            "target_prior": target.get("previous_value"),
            "source_variance": source.get("variance"),
            "target_variance": target.get("variance"),
            "confidence": confidence,
        })
    return results


def compare_visuals(source_visuals: list[dict[str, Any]], target_visuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_map = {_visual_key(item, index): item for index, item in enumerate(source_visuals)}
    target_map = {_visual_key(item, index): item for index, item in enumerate(target_visuals)}
    results = []

    for key in sorted(set(source_map) | set(target_map)):
        source = source_map.get(key)
        target = target_map.get(key)

        if not source:
            results.append({"visual": target.get("title"), "status": "Missing in Source", "source": "N/A", "target": "Present"})
            continue
        if not target:
            results.append({"visual": source.get("title"), "status": "Missing in Target", "source": "Present", "target": "N/A"})
            continue

        type_match = _normalise(source.get("visual_type")) == _normalise(target.get("visual_type"))
        confidence = _pair_confidence(source, target)
        status = "Match" if type_match else "Mismatch"
        if confidence is not None and confidence < 0.7 and status == "Mismatch":
            status = "needs_review"

        results.append({
            "visual": source.get("title") or target.get("title"),
            "status": status,
            "source": f"Type: {source.get('visual_type', 'unknown')}",
            "target": f"Type: {target.get('visual_type', 'unknown')}",
            "confidence": confidence,
        })
    return results


def compare_filters(source_filters: list[dict[str, Any]], target_filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_map = {_normalise(item.get("filter_name")): item for item in source_filters if item.get("filter_name")}
    target_map = {_normalise(item.get("filter_name")): item for item in target_filters if item.get("filter_name")}
    results = []

    for key in sorted(set(source_map) | set(target_map)):
        source = source_map.get(key)
        target = target_map.get(key)

        if not source:
            results.append({"filter_name": target.get("filter_name"), "status": "Missing in Source"})
            continue
        if not target:
            results.append({"filter_name": source.get("filter_name"), "status": "Missing in Target"})
            continue

        source_values = {_normalise(val) for val in source.get("selected_values", [])}
        target_values = {_normalise(val) for val in target.get("selected_values", [])}
        status = "Match" if source_values == target_values else "Mismatch"

        results.append({
            "filter_name": source.get("filter_name"),
            "status": status,
            "source_selected": list(source.get("selected_values", [])),
            "target_selected": list(target.get("selected_values", [])),
            "source_values": list(source.get("available_values", [])),
            "target_values": list(target.get("available_values", [])),
        })
    return results


# services/comparison_service.py

def _extract_table_cell_mismatches(table_comparison: dict[str, Any], max_cells: int = 50) -> list[dict[str, Any]]:
    """Extract cell-level differences from structured table comparisons."""
    mismatched_cells: list[dict[str, Any]] = []
    
    # 1. Unpack tables dict structure
    tables_data = table_comparison.get("tables", {})
    comparisons = tables_data.get("comparisons", []) if isinstance(tables_data, dict) else tables_data

    # 2. Extract cell diffs across all compared tables
    for comp in comparisons:
        title = comp.get("source_table") or comp.get("target_table") or "Table"
        
        for cell_diff in comp.get("cell_mismatches", []):
            mismatched_cells.append({
                "table_title": title,
                "row_identifier": cell_diff.get("row_identifier"),
                "column": cell_diff.get("column"),
                "source_value": cell_diff.get("source_value"),
                "target_value": cell_diff.get("target_value"),
                "status": "Mismatch",
            })
            if len(mismatched_cells) >= max_cells:
                break
                
        if len(mismatched_cells) >= max_cells:
            break

    return mismatched_cells


def compare_button_groups(source_groups: list[dict[str, Any]], target_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_map = {_normalise(item.get("name")): item for item in source_groups if item.get("name")}
    target_map = {_normalise(item.get("name")): item for item in target_groups if item.get("name")}
    results = []

    for key in sorted(set(source_map) | set(target_map)):
        source = source_map.get(key)
        target = target_map.get(key)
        if not source:
            results.append({
                "name": target.get("name"),
                "status": "Missing in Source",
                "source_selected": None,
                "target_selected": target.get("selected_values"),
                "confidence": target.get("confidence"),
            })
            continue
        if not target:
            results.append({
                "name": source.get("name"),
                "status": "Missing in Target",
                "source_selected": source.get("selected_values"),
                "target_selected": None,
                "confidence": source.get("confidence"),
            })
            continue
        source_sel = {_normalise(val) for val in (source.get("selected_values") or [])}
        target_sel = {_normalise(val) for val in (target.get("selected_values") or [])}
        status = "Match" if source_sel == target_sel else "Mismatch"
        confidence = _pair_confidence(source, target)
        if confidence is not None and confidence < 0.7 and status == "Mismatch":
            status = "needs_review"
        results.append({
            "name": source.get("name"),
            "status": status,
            "source_selected": source.get("selected_values") or [],
            "target_selected": target.get("selected_values") or [],
            "source_available": source.get("available_values") or [],
            "target_available": target.get("available_values") or [],
            "confidence": confidence,
        })
    return results


def calculate_match_percentage(results: list) -> float | None:
    if not results:
        return None
    matches = sum(1 for result in results if result.get("status") == "Match")
    return round((matches / len(results)) * 100, 2)


def build_comparison_summary(filter_comparison, kpi_comparison, visual_comparison) -> dict:
    filter_percentage = calculate_match_percentage(filter_comparison)
    kpi_percentage = calculate_match_percentage(kpi_comparison)
    visual_percentage = calculate_match_percentage(visual_comparison)

    scored = [v for v in (filter_percentage, kpi_percentage, visual_percentage) if v is not None]
    overall_percentage = round(sum(scored) / len(scored), 2) if scored else 0.0

    return {
        "filter_match_percentage": filter_percentage if filter_percentage is not None else 0.0,
        "kpi_match_percentage": kpi_percentage if kpi_percentage is not None else 0.0,
        "visual_match_percentage": visual_percentage if visual_percentage is not None else 0.0,
        "overall_match_percentage": overall_percentage,
        "kpi_compared": bool(kpi_comparison),
        "filter_compared": bool(filter_comparison),
        "visual_compared": bool(visual_comparison),
    }


# services/comparison_service.py

def compare_dashboard_payloads(source_data: dict[str, Any], target_data: dict[str, Any]) -> dict[str, Any]:
    try:
        source_data = sanitize_execution_for_api(source_data)
        target_data = sanitize_execution_for_api(target_data)

        kpis = compare_kpis(source_data.get("kpi_cards") or [], target_data.get("kpi_cards") or [])
        visuals = compare_visuals(source_data.get("visuals") or [], target_data.get("visuals") or [])
        filters = compare_filters(source_data.get("filters") or [], target_data.get("filters") or [])
        buttons = compare_button_groups(source_data.get("button_groups") or [], target_data.get("button_groups") or [])

        summary = build_comparison_summary(filters, kpis, visuals)
        button_percentage = calculate_match_percentage(buttons)
        summary["button_match_percentage"] = button_percentage if button_percentage is not None else 0.0

        # Build table comparisons
        table_comparison_result = build_table_comparisons({
            "Source": source_data,
            "Target": target_data,
        })

        return {
            "status": "success",
            "filters": filters,
            "kpis": kpis,
            "visuals": visuals,
            "buttons": buttons,
            "tables": table_comparison_result.get("tables", {}),  # Preserves detailed comparison structure
            "summary": summary,
            "results": kpis,
            "match_percentage": summary.get("overall_match_percentage"),
        }
    except Exception as exc:
        logger.exception("Dashboard comparison failed")
        return {
            "status": "not_compared",
            "reason": str(exc),
            "filters": [], "kpis": [], "visuals": [], "tables": {},
            "summary": {"filter_match_percentage": 0.0, "kpi_match_percentage": 0.0, "visual_match_percentage": 0.0, "overall_match_percentage": 0.0},
        }


# ============================================================================
# 3. MISMATCH EXTRACTION & SNAPSHOTS
# ============================================================================

def _is_mismatch(item: dict[str, Any]) -> bool:
    status = str(item.get("status", "")).strip()
    return bool(status and status not in _MATCH_STATUSES)


def _filter_mismatches(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [item for item in (items or []) if _is_mismatch(item)]


def build_mismatch_payload(
    comparison: dict[str, Any],
    *,
    visual_data: dict[str, Any] | None = None,
    metrics: list[dict[str, Any] | None] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build mismatch-only payload from a validation comparison result."""
    filters = _filter_mismatches(comparison.get("filters"))
    kpis = _filter_mismatches(comparison.get("kpis")) or _filter_mismatches(comparison.get("results"))
    visuals = _filter_mismatches(comparison.get("visuals"))

    # services/comparison_service.py (inside build_mismatch_payload)

    table_visuals: list[dict[str, Any]] = []
    table_cells: list[dict[str, Any]] = []
    
    if visual_data:
        table_comp_input = (
            visual_data
            if isinstance(visual_data, dict) and "Source" in visual_data
            else {"Source": visual_data.get("source", {}), "Target": visual_data.get("target", {})}
        )
        table_comparison = build_table_comparisons(table_comp_input)
        
        # Pull table-level shape/column mismatches
        tables_data = table_comparison.get("tables", {})
        comparisons = tables_data.get("comparisons", []) if isinstance(tables_data, dict) else tables_data
        
        for comp in comparisons:
            if comp.get("status") != "TABLE_MATCHED":
                table_visuals.append({
                    "table_title": comp.get("source_table"),
                    "status": comp.get("status"),
                    "source_row_count": comp.get("source_row_count"),
                    "target_row_count": comp.get("target_row_count"),
                    "missing_columns_in_target": comp.get("missing_columns_in_target"),
                    "extra_columns_in_target": comp.get("extra_columns_in_target"),
                    "missing_rows_in_target_count": len(comp.get("missing_rows_in_target", [])),
                    "extra_rows_in_target_count": len(comp.get("extra_rows_in_target", [])),
                })
        
        # Pull cell-level value diffs
        table_cells = _extract_table_cell_mismatches(table_comparison, max_cells=50)

    browser_metrics: list[dict[str, Any]] = []
    if metrics and len(metrics) >= 2:
        browser_metrics = compare_browser_metrics(metrics[0], metrics[1])

    total = (
        len(filters)
        + len(kpis)
        + len(visuals)
        + len(table_cells)
        + len(browser_metrics)
    )
    summary = comparison.get("summary") or {}

    return {
        "run_id": run_id,
        "status": comparison.get("status"),
        "reason": comparison.get("reason"),
        "summary": {
            "total_mismatches": total,
            "filter_mismatch_count": len(filters),
            "kpi_mismatch_count": len(kpis),
            "visual_mismatch_count": len(visuals),
            "table_visual_mismatch_count": len(table_visuals),
            "table_cell_mismatch_count": len(table_cells),
            "browser_metric_mismatch_count": len(browser_metrics),
            "overall_match_percentage": summary.get("overall_match_percentage"),
        },
        "filters": filters,
        "kpis": kpis,
        "results": kpis,
        "visuals": visuals,
        "table_visuals": table_visuals,
        "table_cells": table_cells,
        "browser_metrics": browser_metrics,
        "match_percentage": comparison.get("match_percentage"),
        "mismatches_download_url": f"/api/reports/{run_id}/mismatches" if run_id else None,
    }


 


 