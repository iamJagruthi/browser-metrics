"""
comparison_service.py

Central DOM-only comparison layer.

Responsibilities:
- Compare DOM-extracted filters.
- Compare DOM-extracted KPIs.
- Compare DOM-extracted visuals.
- Compare exported table/matrix data.
- Build a consolidated comparison payload.

Does NOT:
- Interact with the browser.
- Extract dashboard data.
- Call Gemini/AI/LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from services.excel_exporter import build_comparison_summary


logger = logging.getLogger(__name__)


def _normalise(value: Any) -> str:
    """
    Normalise values for case-insensitive comparison.
    """
    return " ".join(
        str(value if value is not None else "").casefold().split()
    )


def _visual_key(
    item: dict[str, Any],
    fallback_index: int,
) -> str:
    """
    Build a stable visual matching key.

    Priority:
    1. title
    2. visual type + index
    3. index
    """
    title = _normalise(item.get("title"))

    if title:
        return f"title:{title}"

    visual_type = _normalise(item.get("visual_type"))

    if visual_type:
        return (
            f"type:{visual_type}|"
            f"index:{item.get('index', fallback_index)}"
        )

    return f"index:{item.get('index', fallback_index)}"


def compare_kpis(
    source_kpis: list[dict[str, Any]],
    target_kpis: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Compare DOM-extracted KPI cards.
    """
    logger.info(
        "Starting KPI comparison | source=%d | target=%d",
        len(source_kpis),
        len(target_kpis),
    )

    try:
        source_map = {
            _normalise(item.get("name")): item
            for item in source_kpis
            if item.get("name")
        }

        target_map = {
            _normalise(item.get("name")): item
            for item in target_kpis
            if item.get("name")
        }

        results = []

        for key in sorted(set(source_map) | set(target_map)):
            source = source_map.get(key)
            target = target_map.get(key)

            if not source:
                results.append({
                    "name": target.get("name"),
                    "status": "missing_in_source",
                    "source_value": None,
                    "target_value": target.get("value"),
                })
                continue

            if not target:
                results.append({
                    "name": source.get("name"),
                    "status": "missing_in_target",
                    "source_value": source.get("value"),
                    "target_value": None,
                })
                continue

            source_value = _normalise(source.get("value"))
            target_value = _normalise(target.get("value"))

            status = (
                "match"
                if source_value == target_value
                else "mismatch"
            )

            results.append({
                "name": source.get("name"),
                "status": status,
                "source_value": source.get("value"),
                "target_value": target.get("value"),
            })

        logger.info(
            "KPI comparison completed | total=%d | "
            "matches=%d | mismatches=%d",
            len(results),
            sum(
                item["status"] == "match"
                for item in results
            ),
            sum(
                item["status"] != "match"
                for item in results
            ),
        )

        return results

    except Exception:
        logger.exception("KPI comparison failed")
        return []


def compare_visuals(
    source_visuals: list[dict[str, Any]],
    target_visuals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Compare DOM-extracted visual data.

    Matching priority:
    1. visual title
    2. visual type + index
    3. visual index

    Comparison checks:
    - visual type
    - DOM-visible content
    """
    logger.info(
        "Starting visual comparison | source=%d | target=%d",
        len(source_visuals),
        len(target_visuals),
    )

    try:
        source_map = {
            _visual_key(item, index): item
            for index, item in enumerate(source_visuals)
        }

        target_map = {
            _visual_key(item, index): item
            for index, item in enumerate(target_visuals)
        }

        results = []

        for key in sorted(set(source_map) | set(target_map)):
            source = source_map.get(key)
            target = target_map.get(key)

            if not source:
                results.append({
                    "title": target.get("title"),
                    "visual_type_target": target.get(
                        "visual_type"
                    ),
                    "status": "missing_in_source",
                })
                continue

            if not target:
                results.append({
                    "title": source.get("title"),
                    "visual_type_source": source.get(
                        "visual_type"
                    ),
                    "status": "missing_in_target",
                })
                continue

            type_match = (
                _normalise(source.get("visual_type"))
                == _normalise(target.get("visual_type"))
            )

            source_content = {
                _normalise(item.get("text"))
                for item in source.get("dom_content", [])
                if item.get("text")
            }

            target_content = {
                _normalise(item.get("text"))
                for item in target.get("dom_content", [])
                if item.get("text")
            }

            content_match = (
                source_content == target_content
            )

            overall_match = (
                type_match
                and content_match
            )

            results.append({
                "title": (
                    source.get("title")
                    or target.get("title")
                ),
                "comparison_key": key,
                "status": (
                    "match"
                    if overall_match
                    else "mismatch"
                ),

                "visual_type_source": source.get(
                    "visual_type"
                ),
                "visual_type_target": target.get(
                    "visual_type"
                ),
                "visual_type_match": type_match,

                "content_match": content_match,

                "source_content": sorted(
                    source_content
                ),
                "target_content": sorted(
                    target_content
                ),
            })

        logger.info(
            "Visual comparison completed | total=%d | "
            "matches=%d | mismatches=%d",
            len(results),
            sum(
                item["status"] == "match"
                for item in results
            ),
            sum(
                item["status"] != "match"
                for item in results
            ),
        )

        return results

    except Exception:
        logger.exception("Visual comparison failed")
        return []


def compare_filters(
    source_filters: list[dict[str, Any]],
    target_filters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Compare DOM-extracted filter state.
    """
    logger.info(
        "Starting filter comparison | source=%d | target=%d",
        len(source_filters),
        len(target_filters),
    )

    try:
        source_map = {
            _normalise(item.get("filter_name")): item
            for item in source_filters
            if item.get("filter_name")
        }

        target_map = {
            _normalise(item.get("filter_name")): item
            for item in target_filters
            if item.get("filter_name")
        }

        results = []

        for key in sorted(set(source_map) | set(target_map)):
            source = source_map.get(key)
            target = target_map.get(key)

            if not source:
                results.append({
                    "filter_name": target.get(
                        "filter_name"
                    ),
                    "status": "missing_in_source",
                })
                continue

            if not target:
                results.append({
                    "filter_name": source.get(
                        "filter_name"
                    ),
                    "status": "missing_in_target",
                })
                continue

            source_values = {
                _normalise(value)
                for value in source.get(
                    "selected_values",
                    [],
                )
            }

            target_values = {
                _normalise(value)
                for value in target.get(
                    "selected_values",
                    [],
                )
            }

            status = (
                "match"
                if source_values == target_values
                else "mismatch"
            )

            results.append({
                "filter_name": source.get(
                    "filter_name"
                ),
                "status": status,
                "source_selected_values": sorted(
                    source_values
                ),
                "target_selected_values": sorted(
                    target_values
                ),
            })

        logger.info(
            "Filter comparison completed | total=%d | "
            "matches=%d | mismatches=%d",
            len(results),
            sum(
                item["status"] == "match"
                for item in results
            ),
            sum(
                item["status"] != "match"
                for item in results
            ),
        )

        return results

    except Exception:
        logger.exception("Filter comparison failed")
        return []


def _normalise_table_rows(
    rows: list[Any],
) -> list[Any]:
    """
    Normalise table rows before comparison.

    Supports:
    - list[list]
    - list[dict]
    - scalar row values
    """
    normalised_rows = []

    for row in rows or []:
        if isinstance(row, dict):
            normalised_rows.append({
                _normalise(key): _normalise(value)
                for key, value in sorted(row.items())
            })

        elif isinstance(row, (list, tuple)):
            normalised_rows.append(
                [_normalise(value) for value in row]
            )

        else:
            normalised_rows.append(
                _normalise(row)
            )

    return normalised_rows


def compare_tables(
    source_tables: list[dict[str, Any]],
    target_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Compare exported table/matrix data.

    Matching priority:
    1. title
    2. visual id
    3. index
    """
    logger.info(
        "Starting table comparison | source=%d | target=%d",
        len(source_tables),
        len(target_tables),
    )

    try:
        def table_key(
            item: dict[str, Any],
            fallback_index: int,
        ) -> str:

            title = _normalise(item.get("title"))

            if title:
                return f"title:{title}"

            visual_id = _normalise(
                item.get("visual_id")
                or item.get("id")
            )

            if visual_id:
                return f"id:{visual_id}"

            return (
                f"index:"
                f"{item.get('index', fallback_index)}"
            )

        source_map = {
            table_key(item, index): item
            for index, item in enumerate(source_tables)
        }

        target_map = {
            table_key(item, index): item
            for index, item in enumerate(target_tables)
        }

        results = []

        for key in sorted(set(source_map) | set(target_map)):
            source = source_map.get(key)
            target = target_map.get(key)

            if not source:
                results.append({
                    "title": target.get("title"),
                    "status": "missing_in_source",
                })
                continue

            if not target:
                results.append({
                    "title": source.get("title"),
                    "status": "missing_in_target",
                })
                continue

            source_headers = [
                _normalise(value)
                for value in source.get(
                    "headers",
                    [],
                )
            ]

            target_headers = [
                _normalise(value)
                for value in target.get(
                    "headers",
                    [],
                )
            ]

            source_rows = _normalise_table_rows(
                source.get("rows", [])
            )

            target_rows = _normalise_table_rows(
                target.get("rows", [])
            )

            header_match = (
                source_headers
                == target_headers
            )

            row_match = (
                source_rows
                == target_rows
            )

            overall_match = (
                header_match
                and row_match
            )

            results.append({
                "title": (
                    source.get("title")
                    or target.get("title")
                ),
                "comparison_key": key,
                "status": (
                    "match"
                    if overall_match
                    else "mismatch"
                ),

                "header_match": header_match,
                "row_match": row_match,

                "source_headers": source.get(
                    "headers",
                    [],
                ),
                "target_headers": target.get(
                    "headers",
                    [],
                ),

                "source_row_count": len(
                    source_rows
                ),
                "target_row_count": len(
                    target_rows
                ),
            })

        logger.info(
            "Table comparison completed | total=%d | "
            "matches=%d | mismatches=%d",
            len(results),
            sum(
                item["status"] == "match"
                for item in results
            ),
            sum(
                item["status"] != "match"
                for item in results
            ),
        )

        return results

    except Exception:
        logger.exception("Table comparison failed")
        return []


def compare_dashboard_payloads(
    source_data: dict[str, Any],
    target_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Compare two extracted dashboard payloads.

    No:
    - browser calls
    - DOM extraction
    - Gemini/AI/LLM calls
    """
    logger.info(
        "Starting dashboard comparison"
    )

    try:
        source_kpis = (
            source_data.get("kpi_cards", [])
            or []
        )

        target_kpis = (
            target_data.get("kpi_cards", [])
            or []
        )

        source_visuals = (
            source_data.get("visuals", [])
            or []
        )

        target_visuals = (
            target_data.get("visuals", [])
            or []
        )

        source_filters = (
            source_data.get("filters", [])
            or []
        )

        target_filters = (
            target_data.get("filters", [])
            or []
        )

        source_tables = (
            source_data.get("tables", [])
            or source_data.get("table_data", [])
            or []
        )

        target_tables = (
            target_data.get("tables", [])
            or target_data.get("table_data", [])
            or []
        )

        logger.info(
            "Comparison input received | "
            "source_kpis=%d | target_kpis=%d | "
            "source_visuals=%d | target_visuals=%d | "
            "source_filters=%d | target_filters=%d | "
            "source_tables=%d | target_tables=%d",
            len(source_kpis),
            len(target_kpis),
            len(source_visuals),
            len(target_visuals),
            len(source_filters),
            len(target_filters),
            len(source_tables),
            len(target_tables),
        )

        kpis = compare_kpis(
            source_kpis,
            target_kpis,
        )

        visuals = compare_visuals(
            source_visuals,
            target_visuals,
        )

        filters = compare_filters(
            source_filters,
            target_filters,
        )

        tables = compare_tables(
            source_tables,
            target_tables,
        )

        summary = build_comparison_summary(
            filters,
            kpis,
            visuals,
        )

        logger.info(
            "Dashboard comparison completed | "
            "filters=%d | kpis=%d | "
            "visuals=%d | tables=%d",
            len(filters),
            len(kpis),
            len(visuals),
            len(tables),
        )

        return {
            "status": "success",

            "filters": filters,
            "kpis": kpis,
            "visuals": visuals,
            "tables": tables,

            "summary": summary,

            # Backward compatibility
            "results": kpis,

            "match_percentage": summary.get(
                "overall_match_percentage"
            ),

            "kpi_match_percentage": (
                summary.get(
                    "kpi_match_percentage"
                )
                if kpis
                else None
            ),
        }

    except Exception as exc:
        logger.exception(
            "Dashboard comparison failed"
        )

        return {
            "status": "not_compared",

            "reason": (
                "Dashboard comparison failed. "
                "See server logs."
            ),

            "error": str(exc),

            "filters": [],
            "kpis": [],
            "visuals": [],
            "tables": [],

            "summary": {
                "filter_match_percentage": 0.0,
                "kpi_match_percentage": 0.0,
                "visual_match_percentage": 0.0,
                "overall_match_percentage": 0.0,
            },
        }