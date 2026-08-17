"""
comparison_service.py

Unified comparison layer for validation runs.

Jagruthi — routes KPI/filter/visual compare through the live code paths
(excel_exporter + Text_Extraction), not the removed automation/comparison.py.
"""

from __future__ import annotations

from typing import Any

from ai.Text_Extraction import compare_filters, compare_visuals
from services.excel_exporter import build_comparison_summary, compare_kpis


def compare_kpi_cards(source_data: dict[str, Any], target_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare KPI cards between source and target dashboard payloads."""
    return compare_kpis(source_data, target_data)


def compare_dashboard_payloads(
    source_data: dict[str, Any],
    target_data: dict[str, Any],
    *,
    source_gemini_ok: bool = True,
    target_gemini_ok: bool = True,
) -> dict[str, Any]:
    """Run filter, KPI, and visual (Gemini chart) comparisons."""
    filters = compare_filters(source_data, target_data)
    kpis = compare_kpis(source_data, target_data)
    gemini_ok = source_gemini_ok and target_gemini_ok
    visuals = compare_visuals(source_data, target_data) if gemini_ok else []
    summary = build_comparison_summary(filters, kpis, visuals)

    kpi_match_percentage = summary["kpi_match_percentage"]
    if not kpis:
        kpi_match_percentage = None

    return {
        "status": "success",
        "filters": filters,
        "kpis": kpis,
        "visuals": visuals,
        "summary": summary,
        "gemini_status": {
            "source": "success" if source_gemini_ok else "failed",
            "target": "success" if target_gemini_ok else "failed",
        },
        "results": kpis,
        "match_percentage": summary["overall_match_percentage"],
        "kpi_match_percentage": kpi_match_percentage,
        "kpi_note": (
            "No KPI cards were detected on either dashboard. "
            "Chart visuals are compared separately when Gemini extraction succeeds."
            if not kpis
            else None
        ),
    }
