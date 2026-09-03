"""Mismatch-only payloads for frontend diff views.

Jagruthi — filters comparison results to non-matching filters, KPIs, visuals,
table cells, browser metrics, and slicer scenarios.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_MATCH_STATUSES = frozenset({"Match"})


def _is_mismatch(item: dict[str, Any]) -> bool:
    status = str(item.get("status", "")).strip()
    if not status:
        return False
    return status not in _MATCH_STATUSES


def _filter_mismatches(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [item for item in (items or []) if _is_mismatch(item)]


def _browser_metric_mismatches(metrics: list[dict[str, Any] | None] | None) -> list[dict[str, Any]]:
    """Compare source vs target browser metrics; return only differing rows."""
    if not metrics or len(metrics) < 2:
        return []

    source_metrics = metrics[0] or {}
    target_metrics = metrics[1] or {}
    mismatches: list[dict[str, Any]] = []

    skip_keys = {"network_details", "dashboard_name"}
    keys = sorted(
        {
            key
            for key in set(source_metrics) | set(target_metrics)
            if key not in skip_keys
        }
    )

    for key in keys:
        source_value = source_metrics.get(key)
        target_value = target_metrics.get(key)
        if source_value is None and target_value is None:
            continue

        source_text = "" if source_value is None else str(source_value)
        target_text = "" if target_value is None else str(target_value)
        if source_text == target_text:
            try:
                if float(source_text) == float(target_text):
                    continue
            except (ValueError, TypeError):
                pass

        status = "Different"
        if source_value is None:
            status = "Missing in Source"
        elif target_value is None:
            status = "Missing in Target"

        mismatches.append(
            {
                "metric": key,
                "source": source_value,
                "target": target_value,
                "status": status,
                "source_page_name": source_metrics.get("page_name"),
                "target_page_name": target_metrics.get("page_name"),
            }
        )

    return mismatches


def _slicer_mismatches(scenarios: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for scenario in scenarios or []:
        status = str(scenario.get("status", "completed")).strip()
        visual_comparison = scenario.get("visual_comparison") or []
        visual_mismatches = _filter_mismatches(visual_comparison)
        if status not in {"completed", "Match"} or visual_mismatches:
            entry = dict(scenario)
            if visual_mismatches:
                entry["visual_comparison"] = visual_mismatches
            results.append(entry)
    return results


def _page_mismatch_sections(page_comparisons: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for page in page_comparisons or []:
        filters = _filter_mismatches(page.get("filters"))
        kpis = _filter_mismatches(page.get("kpis"))
        visuals = _filter_mismatches(page.get("visuals"))
        
        if not filters and not kpis and not visuals:
            continue
            
        sections.append(
            {
                "page_name": page.get("page_name", "Unknown Page"),
                "filter_applied": page.get("filter_applied", "Default View"),
                "status": page.get("status"),
                "summary": page.get("summary") or {},
                "filters": filters,
                "kpis": kpis,
                "visuals": visuals,
            }
        )
    return sections

def build_mismatch_payload(
    comparison: dict[str, Any],
    *,
    visual_data: dict[str, Any] | None = None,
    metrics: list[dict[str, Any] | None] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build mismatch-only payload from a validation comparison result."""
    try:
        from services.excel_exporter import build_visual_data_comparison

        filters = _filter_mismatches(comparison.get("filters"))
        kpis = _filter_mismatches(comparison.get("kpis"))
        if not kpis:
            kpis = _filter_mismatches(comparison.get("results"))
        visuals = _filter_mismatches(comparison.get("visuals"))

        table_visuals: list[dict[str, Any]] = []
        table_cells: list[dict[str, Any]] = []
        if visual_data:
            table_comparison = build_visual_data_comparison(visual_data)
            table_visuals = _filter_mismatches(table_comparison.get("summary"))
            table_cells = _filter_mismatches(table_comparison.get("cells"))

        browser_metrics = _browser_metric_mismatches(metrics)
        slicer_scenarios = _slicer_mismatches(comparison.get("slicer_scenarios"))
        page_mismatches = _page_mismatch_sections(comparison.get("page_comparisons"))

        total = (
            len(filters)
            + len(kpis)
            + len(visuals)
            + len(table_cells)
            + len(browser_metrics)
            + len(slicer_scenarios)
        )

        summary = comparison.get("summary") or {}
        payload = {
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
                "slicer_mismatch_count": len(slicer_scenarios),
                "page_mismatch_count": len(page_mismatches),
                "overall_match_percentage": summary.get("overall_match_percentage"),
                "filter_match_percentage": summary.get("filter_match_percentage"),
                "kpi_match_percentage": summary.get("kpi_match_percentage"),
                "visual_match_percentage": summary.get("visual_match_percentage"),
            },
            "filters": filters,
            "kpis": kpis,
            "results": kpis,
            "visuals": visuals,
            "table_visuals": table_visuals,
            "table_cells": table_cells,
            "browser_metrics": browser_metrics,
            "slicer_scenarios": slicer_scenarios,
            "page_mismatches": page_mismatches,
            "match_percentage": comparison.get("match_percentage"),
            "mismatches_download_url": (
                f"/api/reports/{run_id}/mismatches" if run_id else None
            ),
        }

        logger.info(
            "Mismatch payload built | run_id=%s | total_mismatches=%d",
            run_id,
            total,
        )
        return payload
    except Exception:
        logger.exception("Failed to build mismatch payload | run_id=%s", run_id)
        raise


def save_mismatch_snapshot(
    run_id: str,
    payload: dict[str, Any],
    output_directory: Path,
) -> Path:
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / f"{run_id}_mismatches.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Mismatch snapshot saved | run_id=%s | path=%s", run_id, path)
        return path
    except Exception:
        logger.exception("Failed to save mismatch snapshot | run_id=%s", run_id)
        raise


 
