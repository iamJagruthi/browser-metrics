"""
comparison_service.py

Central DOM-only comparison layer.
"""
from __future__ import annotations

import logging
from typing import Any
from services.excel_exporter import build_comparison_summary, calculate_match_percentage

logger = logging.getLogger(__name__)


def _normalise(value: Any) -> str:
    return " ".join(str(value if value is not None else "").casefold().split())

def _visual_key(item: dict[str, Any], fallback_index: int) -> str:
    title = _normalise(item.get("title"))
    if title:
        return f"title:{title}"
    visual_type = _normalise(item.get("visual_type"))
    if visual_type:
        return f"type:{visual_type}|index:{item.get('index', fallback_index)}"
    return f"index:{item.get('index', fallback_index)}"


def _pair_confidence(left: dict[str, Any] | None, right: dict[str, Any] | None) -> float | None:
    """Use the lower of the two 0-1 scores so a weak side keeps the pair cautious."""
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
    logger.info("Starting KPI comparison | source=%d | target=%d", len(source_kpis), len(target_kpis))
    try:
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
        logger.info("KPI comparison completed | total=%d", len(results))
        return results
    except Exception:
        logger.exception("KPI comparison failed")
        return []


def compare_visuals(source_visuals: list[dict[str, Any]], target_visuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger.info("Starting visual comparison | source=%d | target=%d", len(source_visuals), len(target_visuals))
    try:
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
            source_content = { _normalise(item.get("text")) for item in source.get("dom_content", []) if item.get("text") }
            target_content = { _normalise(item.get("text")) for item in target.get("dom_content", []) if item.get("text") }

            content_match = (source_content == target_content)
            overall_match = type_match and content_match
            confidence = _pair_confidence(source, target)
            status = "Match" if overall_match else "Mismatch"
            if confidence is not None and confidence < 0.7 and status == "Mismatch":
                status = "needs_review"

            results.append({
                "visual": source.get("title") or target.get("title"),
                "status": status,
                "source": f"Data points: {len(source_content)}",
                "target": f"Data points: {len(target_content)}",
                "confidence": confidence,
            })
        logger.info("Visual comparison completed | total=%d", len(results))
        return results
    except Exception:
        logger.exception("Visual comparison failed")
        return []


def compare_filters(source_filters: list[dict[str, Any]], target_filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger.info("Starting filter comparison | source=%d | target=%d", len(source_filters), len(target_filters))
    try:
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

            source_values = { _normalise(val) for val in source.get("selected_values", []) }
            target_values = { _normalise(val) for val in target.get("selected_values", []) }
            status = "Match" if source_values == target_values else "Mismatch"

            results.append({
                "filter_name": source.get("filter_name"),
                "status": status,
                "source_selected": list(source.get("selected_values", [])),
                "target_selected": list(target.get("selected_values", [])),
                "source_values": list(source.get("available_values", [])),
                "target_values": list(target.get("available_values", [])),
            })
        logger.info("Filter comparison completed | total=%d", len(results))
        return results
    except Exception:
        logger.exception("Filter comparison failed")
        return []


def compare_button_groups(
    source_groups: list[dict[str, Any]],
    target_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare which button-slicer chips are selected on Source vs Target."""
    logger.info("Starting button comparison | source=%d | target=%d", len(source_groups), len(target_groups))
    try:
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
        logger.info("Button comparison completed | total=%d", len(results))
        return results
    except Exception:
        logger.exception("Button comparison failed")
        return []


def compare_dashboard_payloads(source_data: dict[str, Any], target_data: dict[str, Any]) -> dict[str, Any]:
    logger.info("Starting dashboard comparison")
    try:
        source_kpis = source_data.get("kpi_cards", []) or []
        target_kpis = target_data.get("kpi_cards", []) or []
        source_visuals = source_data.get("visuals", []) or []
        target_visuals = target_data.get("visuals", []) or []
        source_filters = source_data.get("filters", []) or []
        target_filters = target_data.get("filters", []) or []

        kpis = compare_kpis(source_kpis, target_kpis)
        visuals = compare_visuals(source_visuals, target_visuals)
        filters = compare_filters(source_filters, target_filters)
        buttons = compare_button_groups(
            source_data.get("button_groups") or [],
            target_data.get("button_groups") or [],
        )

        summary = build_comparison_summary(filters, kpis, visuals)
        button_percentage = calculate_match_percentage(buttons)
        summary["button_match_percentage"] = button_percentage if button_percentage is not None else 0.0

        logger.info(
            "Dashboard comparison completed | filters=%d | kpis=%d | visuals=%d | buttons=%d",
            len(filters),
            len(kpis),
            len(visuals),
            len(buttons),
        )
        return {
            "status": "success",
            "filters": filters,
            "kpis": kpis,
            "visuals": visuals,
            "buttons": buttons,
            "tables": [],
            "summary": summary,
            "results": kpis, # Backward compatibility
            "match_percentage": summary.get("overall_match_percentage"),
        }
    except Exception as exc:
        logger.exception("Dashboard comparison failed")
        return {
            "status": "not_compared",
            "reason": str(exc),
            "filters": [], "kpis": [], "visuals": [], "tables": [],
            "summary": {"filter_match_percentage": 0.0, "kpi_match_percentage": 0.0, "visual_match_percentage": 0.0, "overall_match_percentage": 0.0},
        }