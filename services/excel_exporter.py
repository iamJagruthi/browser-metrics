"""
Excel exporter for Browser Metrics Validator.

Creates one Excel workbook containing:
- Summary
- Metadata
- Filters
- Filter Comparison
- KPI Details
- KPI Comparison
- Visual Details
- Visual Comparison
- Browser Metrics
"""

import logging
from pathlib import Path

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# Styles
# ---------------------------------------------------------

FONT_FAMILY = "Segoe UI"

HEADER_FONT = Font(
    name=FONT_FAMILY,
    size=11,
    bold=True,
    color="FFFFFF",
)

HEADER_FILL = PatternFill(
    start_color="1F4E78",
    end_color="1F4E78",
    fill_type="solid",
)

SUBHEADER_FONT = Font(
    name=FONT_FAMILY,
    size=11,
    bold=True,
)

CELL_FONT = Font(
    name=FONT_FAMILY,
    size=10,
)

THIN_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)

ALIGN_LEFT = Alignment(
    horizontal="left",
    vertical="center",
    wrap_text=True,
)

ALIGN_CENTER = Alignment(
    horizontal="center",
    vertical="center",
    wrap_text=True,
)

ALIGN_RIGHT = Alignment(
    horizontal="right",
    vertical="center",
)


# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------

def _format_header(ws, headers):
    """Format the first row of a worksheet."""

    ws.sheet_view.showGridLines = True
    ws.row_dimensions[1].height = 28

    for col_idx, header in enumerate(headers, start=1):

        cell = ws.cell(
            row=1,
            column=col_idx,
            value=header,
        )

        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = ALIGN_CENTER
        cell.border = THIN_BORDER


def _style_cell(cell, alignment=ALIGN_LEFT):
    """Apply standard cell formatting."""

    cell.font = CELL_FONT
    cell.border = THIN_BORDER
    cell.alignment = alignment


def _auto_fit(ws):
    """Automatically adjust worksheet column widths."""

    for column_cells in ws.columns:

        if not column_cells:
            continue

        max_length = 0

        column_letter = get_column_letter(
            column_cells[0].column
        )

        for cell in column_cells:

            value = cell.value

            if value is None:
                value = ""

            max_length = max(
                max_length,
                len(str(value))
            )

        ws.column_dimensions[column_letter].width = min(
            max(max_length + 4, 14),
            60,
        )


def _safe_list(value):
    """Convert None/non-list values into a list."""

    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def _values_to_string(value):
    """Convert list values into readable Excel text."""

    if value is None:
        return "N/A"

    if isinstance(value, list):

        if not value:
            return "N/A"

        return ", ".join(
            str(item)
            for item in value
        )

    return str(value)


# ---------------------------------------------------------
# Summary
# ---------------------------------------------------------

def _create_summary_sheet(
    wb,
    run_id,
    source_data,
    target_data,
    comparison_result,
    metrics,
):
    """Create the Summary worksheet."""

    logger.info("Creating Summary worksheet")

    ws = wb.create_sheet("Summary")

    summary = comparison_result.get(
        "summary",
        {}
    )

    source_metadata = source_data.get(
        "metadata",
        {}
    )

    target_metadata = target_data.get(
        "metadata",
        {}
    )

    rows = [
        ("Run ID", run_id),

        (
            "Source Dashboard",
            source_metadata.get(
                "dashboard_title"
            ) or "N/A",
        ),

        (
            "Target Dashboard",
            target_metadata.get(
                "dashboard_title"
            ) or "N/A",
        ),

        (
            "Overall Match %",
            summary.get(
                "overall_match_percentage",
                0,
            ),
        ),

        (
            "Filter Match %",
            summary.get(
                "filter_match_percentage",
                0,
            ),
        ),

        (
            "KPI Match %",
            summary.get(
                "kpi_match_percentage",
                0,
            ),
        ),

        (
            "Visual Match %",
            summary.get(
                "visual_match_percentage",
                0,
            ),
        ),

        (
            "Source Filter Count",
            len(source_data.get("filters", [])),
        ),

        (
            "Target Filter Count",
            len(target_data.get("filters", [])),
        ),

        (
            "Source KPI Count",
            len(source_data.get("kpi_cards", [])),
        ),

        (
            "Target KPI Count",
            len(target_data.get("kpi_cards", [])),
        ),

        (
            "Source Visual Count",
            len(source_data.get("charts", []))
            + len(source_data.get("tables", []))
            + len(source_data.get("kpi_cards", [])),
        ),

        (
            "Target Visual Count",
            len(target_data.get("charts", []))
            + len(target_data.get("tables", []))
            + len(target_data.get("kpi_cards", [])),
        ),
    ]

    _format_header(
        ws,
        ["Property", "Value"],
    )

    row_number = 2

    for property_name, value in rows:

        ws.cell(
            row=row_number,
            column=1,
            value=property_name,
        )

        ws.cell(
            row=row_number,
            column=2,
            value=value,
        )

        _style_cell(
            ws.cell(row=row_number, column=1)
        )

        _style_cell(
            ws.cell(row=row_number, column=2),
            ALIGN_CENTER,
        )

        row_number += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# Metadata
# ---------------------------------------------------------

def _create_metadata_sheet(
    wb,
    source_data,
    target_data,
):
    """Create Metadata worksheet."""

    logger.info("Creating Metadata worksheet")

    ws = wb.create_sheet("Metadata")

    _format_header(
        ws,
        [
            "Dashboard",
            "Property",
            "Value",
        ],
    )

    row = 2

    for dashboard_name, data in [
        ("Source", source_data),
        ("Target", target_data),
    ]:

        metadata = data.get(
            "metadata",
            {}
        )

        for key, value in metadata.items():

            ws.cell(
                row=row,
                column=1,
                value=dashboard_name,
            )

            ws.cell(
                row=row,
                column=2,
                value=key.replace(
                    "_",
                    " "
                ).title(),
            )

            ws.cell(
                row=row,
                column=3,
                value=(
                    str(value)
                    if value is not None
                    else "N/A"
                ),
            )

            for col in range(1, 4):

                _style_cell(
                    ws.cell(row=row, column=col)
                )

            row += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# Filters
# ---------------------------------------------------------

def _create_filters_sheet(
    wb,
    source_data,
    target_data,
):
    """Create Filters worksheet."""

    logger.info("Creating Filters worksheet")

    ws = wb.create_sheet("Filters")

    headers = [
        "Dashboard",
        "Filter Name",
        "Filter Type",
        "Selected Values",
        "Available Values",
    ]

    _format_header(
        ws,
        headers,
    )

    row = 2

    for dashboard_name, data in [
        ("Source", source_data),
        ("Target", target_data),
    ]:

        filters = data.get(
            "filters",
            []
        )

        for filter_data in filters:

            values = [
                dashboard_name,
                filter_data.get(
                    "filter_name",
                    "N/A",
                ),
                filter_data.get(
                    "filter_type",
                    "N/A",
                ),
                _values_to_string(
                    filter_data.get(
                        "selected_values",
                        [],
                    )
                ),
                _values_to_string(
                    filter_data.get(
                        "available_values",
                        [],
                    )
                ),
            ]

            for col_idx, value in enumerate(
                values,
                start=1,
            ):

                cell = ws.cell(
                    row=row,
                    column=col_idx,
                    value=value,
                )

                _style_cell(cell)

            row += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# Filter Comparison
# ---------------------------------------------------------

def _create_filter_comparison_sheet(
    wb,
    comparison,
):
    """Create Filter Comparison worksheet."""

    logger.info(
        "Creating Filter Comparison worksheet"
    )

    ws = wb.create_sheet(
        "Filter Comparison"
    )

    headers = [
        "Filter Name",
        "Source Type",
        "Target Type",
        "Source Selected",
        "Target Selected",
        "Source Values",
        "Target Values",
        "Status",
    ]

    _format_header(
        ws,
        headers,
    )

    row = 2

    for result in comparison:

        values = [
            result.get(
                "filter_name",
                "N/A",
            ),
            result.get(
                "source_type",
                "N/A",
            ),
            result.get(
                "target_type",
                "N/A",
            ),
            _values_to_string(
                result.get(
                    "source_selected",
                    [],
                )
            ),
            _values_to_string(
                result.get(
                    "target_selected",
                    [],
                )
            ),
            _values_to_string(
                result.get(
                    "source_values",
                    [],
                )
            ),
            _values_to_string(
                result.get(
                    "target_values",
                    [],
                )
            ),
            result.get(
                "status",
                "Unknown",
            ),
        ]

        for col_idx, value in enumerate(
            values,
            start=1,
        ):

            _style_cell(
                ws.cell(
                    row=row,
                    column=col_idx,
                    value=value,
                )
            )

        row += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# KPI Details
# ---------------------------------------------------------

def _create_kpi_details_sheet(
    wb,
    source_data,
    target_data,
):
    """Create KPI Details worksheet."""

    logger.info(
        "Creating KPI Details worksheet"
    )

    ws = wb.create_sheet(
        "KPI Details"
    )

    headers = [
        "Dashboard",
        "Visual ID",
        "Metric Name",
        "Current Value",
        "Prior Period Value",
        "Variance",
        "Confidence",
    ]

    _format_header(
        ws,
        headers,
    )

    row = 2

    for dashboard_name, data in [
        ("Source", source_data),
        ("Target", target_data),
    ]:

        for kpi in data.get(
            "kpi_cards",
            [],
        ):

            confidence = kpi.get(
                "confidence"
            )

            if confidence is not None:
                confidence = (
                    f"{confidence * 100:.1f}%"
                )

            else:
                confidence = "N/A"

            values = [
                dashboard_name,
                kpi.get(
                    "visual_id",
                    "N/A",
                ),
                kpi.get(
                    "name",
                    "N/A",
                ),
                kpi.get(
                    "value",
                    "N/A",
                ),
                kpi.get(
                    "previous_value",
                    "N/A",
                ),
                kpi.get(
                    "variance",
                    "N/A",
                ),
                confidence,
            ]

            for col_idx, value in enumerate(
                values,
                start=1,
            ):

                alignment = (
                    ALIGN_RIGHT
                    if col_idx in [4, 5, 6, 7]
                    else ALIGN_LEFT
                )

                _style_cell(
                    ws.cell(
                        row=row,
                        column=col_idx,
                        value=value,
                    ),
                    alignment,
                )

            row += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# KPI Comparison
# ---------------------------------------------------------
def compare_kpis(source_data: dict, target_data: dict) -> list:
    """
    Compare KPI cards between source and target dashboards.

    Uses the current DashboardExtraction schema:
        name
        value
        previous_value
        variance
    """

    logger.info("Starting KPI comparison")

    try:

        source_kpis = source_data.get(
            "kpi_cards",
            []
        )

        target_kpis = target_data.get(
            "kpi_cards",
            []
        )

        logger.info(
            "KPI counts | source=%d | target=%d",
            len(source_kpis),
            len(target_kpis)
        )

        # --------------------------------------------------
        # Create lookup maps using KPI name
        # --------------------------------------------------

        source_map = {
            kpi.get("name"): kpi
            for kpi in source_kpis
            if kpi.get("name")
        }

        target_map = {
            kpi.get("name"): kpi
            for kpi in target_kpis
            if kpi.get("name")
        }

        results = []

        all_names = sorted(
            set(source_map.keys()) |
            set(target_map.keys())
        )

        # --------------------------------------------------
        # Compare KPIs
        # --------------------------------------------------

        for name in all_names:

            source = source_map.get(name)
            target = target_map.get(name)

            # ----------------------------------------------
            # Missing in Source
            # ----------------------------------------------

            if source is None:

                status = "Missing in Source"

            # ----------------------------------------------
            # Missing in Target
            # ----------------------------------------------

            elif target is None:

                status = "Missing in Target"

            # ----------------------------------------------
            # Compare Source and Target
            # ----------------------------------------------

            else:

                source_value = str(
                    source.get("value", "")
                ).strip()

                target_value = str(
                    target.get("value", "")
                ).strip()

                source_previous = str(
                    source.get("previous_value", "")
                ).strip()

                target_previous = str(
                    target.get("previous_value", "")
                ).strip()

                source_variance = str(
                    source.get("variance", "")
                ).strip()

                target_variance = str(
                    target.get("variance", "")
                ).strip()

                # ------------------------------------------
                # KPI Match
                # ------------------------------------------

                if (
                    source_value == target_value
                    and
                    source_previous == target_previous
                    and
                    source_variance == target_variance
                ):

                    status = "Match"

                # ------------------------------------------
                # KPI Value Changed
                # ------------------------------------------

                elif source_value != target_value:

                    status = "Value Changed"

                # ------------------------------------------
                # Previous Value Changed
                # ------------------------------------------

                elif source_previous != target_previous:

                    status = "Previous Value Changed"

                # ------------------------------------------
                # Variance Changed
                # ------------------------------------------

                elif source_variance != target_variance:

                    status = "Variance Changed"

                else:

                    status = "Mismatch"

            # --------------------------------------------------
            # Result
            # --------------------------------------------------

            result = {
                "kpi": name,

                # IMPORTANT:
                # These names match excel_exporter.py

                "source": (
                    source.get("value")
                    if source
                    else None
                ),

                "target": (
                    target.get("value")
                    if target
                    else None
                ),

                "source_prior": (
                    source.get("previous_value")
                    if source
                    else None
                ),

                "target_prior": (
                    target.get("previous_value")
                    if target
                    else None
                ),

                "source_variance": (
                    source.get("variance")
                    if source
                    else None
                ),

                "target_variance": (
                    target.get("variance")
                    if target
                    else None
                ),

                "status": status,
            }

            results.append(result)

            logger.info(
                "KPI comparison | name=%s | status=%s",
                name,
                status
            )

        match_count = sum(
            1
            for result in results
            if result.get("status") == "Match"
        )

        logger.info(
            "KPI comparison completed | total=%d | matches=%d",
            len(results),
            match_count
        )

        return results

    except Exception:

        logger.exception(
            "Error during KPI comparison"
        )

        raise


def _create_kpi_comparison_sheet(
    wb,
    comparison,
):
    """Create KPI Comparison worksheet."""

    logger.info(
        "Creating KPI Comparison worksheet"
    )

    ws = wb.create_sheet(
        "KPI Comparison"
    )

    headers = [
        "KPI",
        "Source Value",
        "Target Value",
        "Source Prior Value",
        "Target Prior Value",
        "Source Variance",
        "Target Variance",
        "Status",
    ]

    _format_header(
        ws,
        headers,
    )

    row = 2

    for result in comparison:

        values = [
            result.get("kpi", "N/A"),
            result.get("source", "N/A"),
            result.get("target", "N/A"),
            result.get(
                "source_prior",
                "N/A",
            ),
            result.get(
                "target_prior",
                "N/A",
            ),
            result.get(
                "source_variance",
                "N/A",
            ),
            result.get(
                "target_variance",
                "N/A",
            ),
            result.get(
                "status",
                "Unknown",
            ),
        ]

        for col_idx, value in enumerate(
            values,
            start=1,
        ):

            _style_cell(
                ws.cell(
                    row=row,
                    column=col_idx,
                    value=value,
                )
            )

        row += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# Visual Details
# ---------------------------------------------------------

def _create_visual_details_sheet(
    wb,
    source_data,
    target_data,
):
    """Create Visual Details worksheet."""

    logger.info(
        "Creating Visual Details worksheet"
    )

    ws = wb.create_sheet(
        "Visual Details"
    )

    headers = [
        "Dashboard",
        "Visual ID",
        "Visual Type",
        "Title",
        "Data",
        "Confidence",
    ]

    _format_header(
        ws,
        headers,
    )

    row = 2

    for dashboard_name, data in [
        ("Source", source_data),
        ("Target", target_data),
    ]:

        for chart in data.get(
            "charts",
            [],
        ):

            confidence = chart.get(
                "confidence"
            )

            if confidence is not None:
                confidence = (
                    f"{confidence * 100:.1f}%"
                )
            else:
                confidence = "N/A"

            values = [
                dashboard_name,
                chart.get(
                    "visual_id",
                    "N/A",
                ),
                chart.get(
                    "chart_type",
                    "Chart",
                ),
                chart.get(
                    "chart_title",
                    "Untitled",
                ),
                _values_to_string(
                    chart.get(
                        "data",
                        [],
                    )
                ),
                confidence,
            ]

            for col_idx, value in enumerate(
                values,
                start=1,
            ):

                _style_cell(
                    ws.cell(
                        row=row,
                        column=col_idx,
                        value=value,
                    )
                )

            row += 1

        for table in data.get(
            "tables",
            [],
        ):

            values = [
                dashboard_name,
                table.get(
                    "visual_id",
                    "N/A",
                ),
                "Table",
                table.get(
                    "table_title",
                    "Table",
                ),
                _values_to_string(
                    table.get(
                        "rows",
                        [],
                    )
                ),
                "N/A",
            ]

            for col_idx, value in enumerate(
                values,
                start=1,
            ):

                _style_cell(
                    ws.cell(
                        row=row,
                        column=col_idx,
                        value=value,
                    )
                )

            row += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# Visual Comparison
# ---------------------------------------------------------

def _create_visual_comparison_sheet(
    wb,
    comparison,
):
    """Create Visual Comparison worksheet."""

    logger.info(
        "Creating Visual Comparison worksheet"
    )

    ws = wb.create_sheet(
        "Visual Comparison"
    )

    headers = [
        "Visual",
        "Source",
        "Target",
        "Status",
    ]

    _format_header(
        ws,
        headers,
    )

    row = 2

    for result in comparison:

        values = [
            result.get(
                "visual",
                result.get(
                    "visual_id",
                    "N/A",
                ),
            ),
            _values_to_string(
                result.get(
                    "source",
                    "N/A",
                )
            ),
            _values_to_string(
                result.get(
                    "target",
                    "N/A",
                )
            ),
            result.get(
                "status",
                "Unknown",
            ),
        ]

        for col_idx, value in enumerate(
            values,
            start=1,
        ):

            _style_cell(
                ws.cell(
                    row=row,
                    column=col_idx,
                    value=value,
                )
            )

        row += 1

    _auto_fit(ws)


# ---------------------------------------------------------
# Browser Metrics
# ---------------------------------------------------------

def _create_browser_metrics_sheet(
    wb,
    metrics,
):
    """Create Browser Metrics worksheet."""

    logger.info(
        "Creating Browser Metrics worksheet"
    )

    ws = wb.create_sheet(
        "Browser Metrics"
    )

    headers = [
        "Dashboard",
        "Metric",
        "Value",
    ]

    _format_header(
        ws,
        headers,
    )

    row = 2

    for dashboard_metrics in metrics:

        if not dashboard_metrics:
            continue

        dashboard_name = dashboard_metrics.get(
            "dashboard_name",
            "N/A",
        )

        for key, value in dashboard_metrics.items():

            if key == "dashboard_name":
                continue

            if isinstance(value, dict):
                value = str(value)

            values = [
                dashboard_name,
                key,
                value,
            ]

            for col_idx, item in enumerate(
                values,
                start=1,
            ):

                _style_cell(
                    ws.cell(
                        row=row,
                        column=col_idx,
                        value=item,
                    )
                )

            row += 1

    _auto_fit(ws)


def _visual_key(visual):
    return " ".join(str(visual.get("title") or visual.get("id") or "").lower().split())


def build_visual_data_comparison(visual_data):
    """Compare rendered Power BI table cells, visual by visual and row by row."""
    source = visual_data.get("Source", {}).get("visuals", [])
    target = visual_data.get("Target", {}).get("visuals", [])
    source_map = {_visual_key(item): item for item in source if _visual_key(item)}
    target_map = {_visual_key(item): item for item in target if _visual_key(item)}
    summaries, cells = [], []
    for key in sorted(set(source_map) | set(target_map)):
        left, right = source_map.get(key), target_map.get(key)
        if not left or not right:
            summaries.append({"visual": (left or right).get("title"), "status": "Missing in Target" if left else "Missing in Source", "source_rows": len((left or {}).get("data", {}).get("rows", [])), "target_rows": len((right or {}).get("data", {}).get("rows", [])), "matched_cells": 0, "mismatched_cells": 0})
            continue
        left_rows, right_rows = left.get("data", {}).get("rows", []), right.get("data", {}).get("rows", [])
        left_columns = left.get("data", {}).get("columns", [])
        right_columns = right.get("data", {}).get("columns", [])
        matched = mismatched = 0
        for row_number in range(max(len(left_rows), len(right_rows))):
            left_row = left_rows[row_number] if row_number < len(left_rows) else []
            right_row = right_rows[row_number] if row_number < len(right_rows) else []
            for col_number in range(max(len(left_row), len(right_row))):
                source_value = left_row[col_number] if col_number < len(left_row) else None
                target_value = right_row[col_number] if col_number < len(right_row) else None
                status = "Match" if source_value == target_value else ("Missing in Source" if source_value is None else "Missing in Target" if target_value is None else "Mismatch")
                matched += status == "Match"
                mismatched += status != "Match"
                cells.append({"visual": left.get("title"), "row_number": row_number + 1, "column": left_columns[col_number] if col_number < len(left_columns) else right_columns[col_number] if col_number < len(right_columns) else f"Column {col_number + 1}", "source_value": source_value, "target_value": target_value, "status": status})
        summaries.append({"visual": left.get("title"), "status": "Match" if not mismatched else "Mismatch", "source_rows": len(left_rows), "target_rows": len(right_rows), "matched_cells": matched, "mismatched_cells": mismatched})
    return {"summary": summaries, "cells": cells}


def _create_visual_data_sheets(wb, visual_data):
    """Create one visual summary plus raw rows and cell-level comparison tables."""
    if not visual_data:
        return {"summary": [], "cells": []}
    comparison = build_visual_data_comparison(visual_data)
    summary = wb.create_sheet("Visual Data Summary")
    _format_header(summary, ["Visual", "Status", "Source Rows", "Target Rows", "Matched Cells", "Mismatched Cells"])
    for row_idx, item in enumerate(comparison["summary"], start=2):
        for col_idx, value in enumerate([item["visual"], item["status"], item["source_rows"], item["target_rows"], item["matched_cells"], item["mismatched_cells"]], start=1):
            _style_cell(summary.cell(row=row_idx, column=col_idx, value=value))
        if item["status"] != "Match":
            for col_idx in range(1, 7):
                summary.cell(row=row_idx, column=col_idx).fill = PatternFill(fill_type="solid", fgColor="FCE4D6")
    _auto_fit(summary)

    # Keep raw source and target values apart so reviewers can inspect each
    # table independently before using the cell-level comparison sheet.
    for dashboard in ("Source", "Target"):
        payload = visual_data.get(dashboard, {})
        max_cells = max((len(row) for visual in payload.get("visuals", []) for row in visual.get("data", {}).get("rows", [])), default=0)
        raw = wb.create_sheet(f"{dashboard} Visual Data")
        _format_header(raw, ["Visual ID", "Visual Title", "Row Number"] + [f"Column {index}" for index in range(1, max_cells + 1)])
        row_idx = 2
        for visual in payload.get("visuals", []):
            for row_number, row in enumerate(visual.get("data", {}).get("rows", []), start=1):
                for col_idx, value in enumerate([visual.get("id"), visual.get("title"), row_number] + row, start=1):
                    _style_cell(raw.cell(row=row_idx, column=col_idx, value=value))
                row_idx += 1
        _auto_fit(raw)

    cells = wb.create_sheet("Visual Data Comparison")
    _format_header(cells, ["Visual", "Row Number", "Column", "Source Value", "Target Value", "Status"])
    for row_idx, item in enumerate(comparison["cells"], start=2):
        for col_idx, value in enumerate([item["visual"], item["row_number"], item["column"], item["source_value"], item["target_value"], item["status"]], start=1):
            _style_cell(cells.cell(row=row_idx, column=col_idx, value=value))
        if item["status"] != "Match":
            for col_idx in range(1, 7):
                cells.cell(row=row_idx, column=col_idx).fill = PatternFill(fill_type="solid", fgColor="FCE4D6")
    _auto_fit(cells)
    return comparison


# ---------------------------------------------------------
# Main Export Function
# ---------------------------------------------------------

def export_validation_workbook(
    run_id,
    source_data,
    target_data,
    filter_comparison,
    kpi_comparison,
    visual_comparison,
    comparison_summary,
    metrics,
    output_directory,
    visual_data=None,
):
    """
    Create one Excel workbook for the complete validation run.

    Returns
    -------
    Path
        Path to generated Excel workbook.
    """

    logger.info(
        "Starting Excel workbook generation | run_id=%s",
        run_id,
    )

    try:

        output_directory = Path(
            output_directory
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file = (
            output_directory
            / f"{run_id}_dashboard_validation.xlsx"
        )

        logger.info(
            "Excel output path: %s",
            output_file,
        )

        wb = Workbook()

        # Remove default sheet.
        default_sheet = wb.active

        wb.remove(default_sheet)

        # -------------------------------------------------
        # Create all worksheets
        # -------------------------------------------------

        _create_summary_sheet(
            wb,
            run_id,
            source_data,
            target_data,
            {
                "summary": comparison_summary
            },
            metrics,
        )

        _create_metadata_sheet(
            wb,
            source_data,
            target_data,
        )

        _create_filters_sheet(
            wb,
            source_data,
            target_data,
        )

        _create_filter_comparison_sheet(
            wb,
            filter_comparison,
        )

        _create_kpi_details_sheet(
            wb,
            source_data,
            target_data,
        )

        _create_kpi_comparison_sheet(
            wb,
            kpi_comparison,
        )

        _create_visual_details_sheet(
            wb,
            source_data,
            target_data,
        )

        _create_visual_comparison_sheet(
            wb,
            visual_comparison,
        )

        _create_browser_metrics_sheet(
            wb,
            metrics,
        )

        _create_visual_data_sheets(wb, visual_data)

        # -------------------------------------------------
        # Save workbook
        # -------------------------------------------------

        wb.save(output_file)

        logger.info(
            "Excel workbook generated successfully | %s",
            output_file,
        )

        return output_file

    except Exception:

        logger.exception(
            "Failed to generate Excel workbook | run_id=%s",
            run_id,
        )

        raise

def calculate_match_percentage(results: list) -> float:
    """
    Calculate percentage of comparison items with status 'Match'.
    """

    # An absent comparison is not evidence of a perfect match.  Callers can
    # distinguish it from a genuinely empty successful comparison via the
    # extraction status carried in the API result.
    if not results:
        return 0.0

    matches = sum(
        1
        for result in results
        if result.get("status") == "Match"
    )

    return round(
        (matches / len(results)) * 100,
        2,
    )

def build_comparison_summary(
    filter_comparison,
    kpi_comparison,
    visual_comparison,
) -> dict:
    """
    Build dashboard-level comparison summary.
    """

    logger.info(
        "Building dashboard comparison summary"
    )

    filter_percentage = calculate_match_percentage(
        filter_comparison
    )

    kpi_percentage = calculate_match_percentage(
        kpi_comparison
    )

    visual_percentage = calculate_match_percentage(
        visual_comparison
    )

    overall_percentage = round(
        (
            filter_percentage
            + kpi_percentage
            + visual_percentage
        ) / 3,
        2,
    )

    return {
        "filter_match_percentage": filter_percentage,
        "kpi_match_percentage": kpi_percentage,
        "visual_match_percentage": visual_percentage,
        "overall_match_percentage": overall_percentage,
    }
