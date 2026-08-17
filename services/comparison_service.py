"""
comparison_service.py

Unified comparison layer for validation runs.

Jagruthi — routes KPI/filter/visual compare through the live code paths
(excel_exporter + Text_Extraction), not the removed automation/comparison.py.
"""

from __future__ import annotations

import logging
from typing import Any

from ai.Text_Extraction import compare_filters, compare_visuals
from services.excel_exporter import build_comparison_summary, compare_kpis


logger = logging.getLogger(__name__)


def compare_kpi_cards(source_data: dict[str, Any], target_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare KPI cards between source and target dashboard payloads."""
    try:
        return compare_kpis(source_data, target_data)
    except Exception:
        logger.exception("KPI card comparison failed")
        raise


def compare_dashboard_payloads(
    source_data: dict[str, Any],
    target_data: dict[str, Any],
    *,
    source_gemini_ok: bool = True,
    target_gemini_ok: bool = True,
) -> dict[str, Any]:
    """Run filter, KPI, and visual (Gemini chart) comparisons."""
    try:
        filters = compare_filters(source_data, target_data)
        kpis = compare_kpis(source_data, target_data)
        gemini_ok = source_gemini_ok and target_gemini_ok
        visuals = compare_visuals(source_data, target_data) if gemini_ok else []
        summary = build_comparison_summary(filters, kpis, visuals)

        kpi_match_percentage = summary["kpi_match_percentage"]
        if not kpis:
            kpi_match_percentage = None

        logger.info(
            "Dashboard comparison complete | overall_match=%s | filters=%d | kpis=%d | visuals=%d",
            summary.get("overall_match_percentage"),
            len(filters),
            len(kpis),
            len(visuals),
        )

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
    except Exception:
        logger.exception("Dashboard payload comparison failed")
        return {
            "status": "not_compared",
            "reason": "Comparison failed due to an internal error. See server logs.",
            "filters": [],
            "kpis": [],
            "visuals": [],
            "summary": {
                "filter_match_percentage": 0.0,
                "kpi_match_percentage": 0.0,
                "visual_match_percentage": 0.0,
                "overall_match_percentage": 0.0,
            },
        }
