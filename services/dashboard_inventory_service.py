"""Dashboard inventory for API consumers — filters (with selection) and visual counts.

Jagruthi — frontend-ready payload for filter state and visuals inventory
(tables, matrices, KPIs, chart types) per dashboard.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.filter_service import build_dashboard_filters_payload


logger = logging.getLogger(__name__)

_CHART_TYPE_ALIASES = {
    "bar": ("bar", "column", "clustered", "stacked bar"),
    "line": ("line", "area line"),
    "area": ("area", "stacked area"),
    "pie": ("pie", "donut", "doughnut"),
    "scatter": ("scatter", "bubble"),
    "map": ("map", "filled map", "shape map"),
    "card": ("card", "multi-row card"),
    "gauge": ("gauge", "kpi indicator"),
    "table": ("table", "grid"),
    "matrix": ("matrix", "pivot"),
    "treemap": ("treemap", "tree map"),
    "funnel": ("funnel"),
    "waterfall": ("waterfall"),
}


def _normalize_chart_bucket(chart_type: str | None) -> str:
    text = " ".join(str(chart_type or "").casefold().split())
    if not text:
        return "other"
    for bucket, tokens in _CHART_TYPE_ALIASES.items():
        if any(token in text for token in tokens):
            return bucket
    return "other"


def _empty_chart_types() -> dict[str, int]:
    return {bucket: 0 for bucket in _CHART_TYPE_ALIASES} | {"other": 0}


def _kpi_key(name: str | None) -> str:
    return " ".join(str(name or "").casefold().split())


def _classify_dom_visual(visual: dict[str, Any]) -> str:
    if visual.get("is_slicer"):
        return "slicer"
    type_source = str(visual.get("visual_type", "")).casefold()
    if "matrix" in type_source or "pivot" in type_source:
        return "matrix"
    data = visual.get("data") or {}
    if data.get("rows") or data.get("columns"):
        return "table"
    return _normalize_chart_bucket(type_source)


def _count_inventory_for_execution(execution: dict[str, Any]) -> dict[str, Any]:
    visual_data = execution.get("visual_data") or {}
    extraction_data = (execution.get("extraction") or {}).get("data") or {}

    chart_types = _empty_chart_types()
    tables = 0
    matrices = 0
    slicers = 0
    dom_charts = 0
    other = 0
    skipped = 0

    for visual in visual_data.get("visuals", []):
        if visual.get("is_loading_placeholder"):
            skipped += 1
            continue
        bucket = _classify_dom_visual(visual)
        if bucket == "slicer":
            slicers += 1
            continue
        if bucket == "table":
            tables += 1
            continue
        if bucket == "matrix":
            matrices += 1
            continue
        if bucket in chart_types:
            chart_types[bucket] += 1
            dom_charts += 1
        elif bucket == "other":
            other += 1
        else:
            chart_types[bucket] += 1
            dom_charts += 1

    skipped += len(visual_data.get("skipped_visuals", []))

    gemini_charts = 0
    for chart in extraction_data.get("charts", []):
        bucket = _normalize_chart_bucket(chart.get("chart_type"))
        chart_types[bucket] += 1
        gemini_charts += 1

    gemini_tables = len(extraction_data.get("tables", []))
    dom_tabular = tables + matrices
    if gemini_tables > dom_tabular:
        tables += gemini_tables - dom_tabular

    dom_kpis = visual_data.get("kpi_cards", []) or []
    gemini_kpis = extraction_data.get("kpi_cards", []) or []
    kpi_names = {
        _kpi_key(item.get("name"))
        for item in dom_kpis + gemini_kpis
        if item.get("name")
    }
    kpi_count = len(kpi_names)

    chart_count = sum(chart_types.values())
    filter_count = len(visual_data.get("filters", []))
    total_visuals = kpi_count + tables + matrices + chart_count + other

    metadata = extraction_data.get("metadata") or {}
    dashboard = execution.get("dashboard") or {}

    return {
        "filter_count": filter_count,
        "kpi_count": kpi_count,
        "table_count": tables,
        "matrix_count": matrices,
        "chart_count": chart_count,
        "chart_types": chart_types,
        "slicer_visual_count": slicers,
        "other_visual_count": other,
        "total_visuals": total_visuals,
        "dom_visual_count": len(visual_data.get("visuals", [])),
        "gemini_chart_count": gemini_charts,
        "gemini_table_count": gemini_tables,
        "skipped_visual_count": skipped,
        "page_name": dashboard.get("page_name") or metadata.get("page_name"),
        "page_number": metadata.get("page_number"),
        "refresh_date": metadata.get("data_refresh_date"),
        "dashboard_title": metadata.get("dashboard_title"),
    }


def _list_kpis_for_execution(execution: dict[str, Any]) -> list[dict[str, Any]]:
    """Jagruthi — merged DOM + Gemini KPI cards for page showcase and reports."""
    visual_data = execution.get("visual_data") or {}
    extraction_data = (execution.get("extraction") or {}).get("data") or {}
    seen: set[str] = set()
    kpis: list[dict[str, Any]] = []

    dom_kpis = visual_data.get("kpi_cards", []) or []
    gemini_kpis = extraction_data.get("kpi_cards", []) or []

    for item in dom_kpis:
        name = item.get("name")
        key = _kpi_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        kpis.append(
            {
                "name": name,
                "value": item.get("value"),
                "previous_value": item.get("previous_value"),
                "variance": item.get("variance"),
                "extraction_source": "dom",
            }
        )

    for item in gemini_kpis:
        name = item.get("name")
        key = _kpi_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        kpis.append(
            {
                "name": name,
                "value": item.get("value"),
                "previous_value": item.get("previous_value"),
                "variance": item.get("variance"),
                "extraction_source": "gemini",
            }
        )
    return kpis


def _list_visuals_for_execution(execution: dict[str, Any]) -> list[dict[str, Any]]:
    """Jagruthi — DOM visual inventory list (title, type, slicer flag)."""
    visual_data = execution.get("visual_data") or {}
    extraction_data = (execution.get("extraction") or {}).get("data") or {}
    visuals: list[dict[str, Any]] = []

    for visual in visual_data.get("visuals", []):
        if visual.get("is_loading_placeholder"):
            continue
        visuals.append(
            {
                "title": visual.get("title") or visual.get("name"),
                "visual_type": visual.get("visual_type"),
                "category": _classify_dom_visual(visual),
                "is_slicer": bool(visual.get("is_slicer")),
            }
        )

    for chart in extraction_data.get("charts", []):
        visuals.append(
            {
                "title": chart.get("title") or chart.get("name"),
                "visual_type": chart.get("chart_type"),
                "category": _normalize_chart_bucket(chart.get("chart_type")),
                "is_slicer": False,
                "extraction_source": "gemini",
            }
        )

    for table in extraction_data.get("tables", []):
        visuals.append(
            {
                "title": table.get("title") or table.get("name"),
                "visual_type": "table",
                "category": "table",
                "is_slicer": False,
                "extraction_source": "gemini",
            }
        )

    return visuals


def build_page_showcase_entry(execution: dict[str, Any]) -> dict[str, Any]:
    """Jagruthi — one report page: filters, KPIs, visuals, and inventory counts."""
    dashboard = execution.get("dashboard") or {}
    filters_section = build_dashboard_filters_payload(execution)
    inventory = _count_inventory_for_execution(execution)

    return {
        "page_name": dashboard.get("page_name") or inventory.get("page_name") or "Default",
        "filter_count": filters_section["filter_count"],
        "filters": filters_section["filters"],
        "inventory": inventory,
        "kpis": _list_kpis_for_execution(execution),
        "visuals": _list_visuals_for_execution(execution),
        "extraction_status": filters_section.get("extraction_status"),
        "visual_extraction_status": filters_section.get("visual_extraction_status"),
    }


def build_pages_showcase_payload(
    executions: list[dict[str, Any]],
    *,
    executions_by_dashboard: list[list[dict[str, Any]]] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Jagruthi — multi-page showcase: page names, KPIs, visuals, and visual inventory."""
    try:
        grouped = executions_by_dashboard or []
        if not grouped and executions:
            grouped = [executions]

        multi_page_mode = any(len(items) > 1 for items in grouped)
        dashboards: list[dict[str, Any]] = []

        for dashboard_executions in grouped:
            if not dashboard_executions:
                continue
            first = dashboard_executions[0]
            dashboard_info = first.get("dashboard") or {}
            pages = [build_page_showcase_entry(item) for item in dashboard_executions]
            dashboards.append(
                {
                    "dashboard_name": dashboard_info.get("name"),
                    "dashboard_url": dashboard_info.get("url"),
                    "page_count": len(pages),
                    "pages": pages,
                }
            )

        return {
            "run_id": run_id,
            "multi_page_mode": multi_page_mode,
            "dashboards": dashboards,
            "pages_download_url": f"/api/reports/{run_id}/pages" if run_id else None,
        }
    except Exception:
        logger.exception("Failed to build pages showcase payload")
        raise


def save_pages_snapshot(
    run_id: str,
    payload: dict[str, Any],
    output_directory: Path,
) -> Path:
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / f"{run_id}_pages.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Pages showcase snapshot saved | run_id=%s | path=%s", run_id, path)
        return path
    except Exception:
        logger.exception("Failed to save pages snapshot | run_id=%s", run_id)
        raise


def load_pages_snapshot(run_id: str, output_directory: Path) -> dict[str, Any] | None:
    path = output_directory / f"{run_id}_pages.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load pages snapshot | run_id=%s", run_id)
        return None


def build_dashboard_inventory_payload(execution: dict[str, Any]) -> dict[str, Any]:
    """One dashboard: filters (with selected values) plus visual inventory counts."""
    filters_section = build_dashboard_filters_payload(execution)
    inventory = _count_inventory_for_execution(execution)
    inventory["filter_count"] = filters_section["filter_count"]

    return {
        "dashboard_name": filters_section.get("dashboard_name"),
        "dashboard_url": filters_section.get("dashboard_url"),
        "extraction_status": filters_section.get("extraction_status"),
        "visual_extraction_status": filters_section.get("visual_extraction_status"),
        "filter_count": filters_section["filter_count"],
        "filters": filters_section["filters"],
        "inventory": inventory,
    }


def build_inventory_api_payload(
    executions: list[dict[str, Any]],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    try:
        dashboards = [build_dashboard_inventory_payload(item) for item in executions]
        return {
            "run_id": run_id,
            "dashboards": dashboards,
            "inventory_download_url": f"/api/reports/{run_id}/inventory" if run_id else None,
            "filters_download_url": f"/api/reports/{run_id}/filters" if run_id else None,
        }
    except Exception:
        logger.exception("Failed to build inventory API payload")
        raise


def save_inventory_snapshot(
    run_id: str,
    payload: dict[str, Any],
    output_directory: Path,
) -> Path:
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / f"{run_id}_inventory.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Inventory snapshot saved | run_id=%s | path=%s", run_id, path)
        return path
    except Exception:
        logger.exception("Failed to save inventory snapshot | run_id=%s", run_id)
        raise


def load_inventory_snapshot(run_id: str, output_directory: Path) -> dict[str, Any] | None:
    path = output_directory / f"{run_id}_inventory.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load inventory snapshot | run_id=%s", run_id)
        return None
