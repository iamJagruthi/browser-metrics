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

Jagruthi — features:
- Tabular-only visual data sheets (skips slicer/button visuals)
- build_visual_data_comparison() for DOM table cell diffs
- KPI match summary when no KPI cards are detected
- Reliable Excel export with table-comparison config dependencies
"""

import logging
import re
from pathlib import Path

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


logger = logging.getLogger(__name__)


def _kpi_key(name):
    """Canonicalise a KPI label without deleting business terms."""
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", str(name or "").casefold()).split())


def _normalise_comparison_value(value):
    return re.sub(r"\s+", "", str(value or "")).replace(",", "").casefold()


def _match_abbreviated_kpis(source_map, target_map):
    """Pair only unambiguous abbreviated KPI labels.

    A shorter label is eligible only when its tokens are a strict subset of
    the longer label's tokens, the values match, and it has one candidate.
    Thus ``30 Days`` can pair with ``30 Days Retention``, but ``30 Days
    Turnover`` can never be mistaken for it.
    """
    matched = {}
    source_only = set(source_map) - set(target_map)
    target_only = set(target_map) - set(source_map)
    for target_key in target_only:
        target_tokens = set(target_key.split())
        target_value = _normalise_comparison_value(target_map[target_key].get("value"))
        candidates = [
            source_key for source_key in source_only
            if target_tokens and target_tokens < set(source_key.split())
            and target_value
            and target_value == _normalise_comparison_value(source_map[source_key].get("value"))
        ]
        if len(candidates) == 1:
            source_key = candidates[0]
            matched[source_key] = target_map[target_key]
            source_only.remove(source_key)
    return matched


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
            _kpi_key(kpi.get("name")): kpi
            for kpi in source_kpis
            if kpi.get("name")
        }

        target_map = {
            _kpi_key(kpi.get("name")): kpi
            for kpi in target_kpis
            if kpi.get("name")
        }

        # Preserve every business word for exact matching first.  Only then
        # resolve a unique, value-backed abbreviated label such as a dashboard
        # that omits the final word from an otherwise identical KPI caption.
        for source_key, target_kpi in _match_abbreviated_kpis(source_map, target_map).items():
            for target_key, candidate in list(target_map.items()):
                if candidate is target_kpi:
                    del target_map[target_key]
                    break
            target_map[source_key] = target_kpi
            logger.info("Matched abbreviated KPI label | source=%s | target=%s", source_key, target_kpi.get("name"))

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

                source_value = _normalise_comparison_value(source.get("value"))
                target_value = _normalise_comparison_value(target.get("value"))
                source_previous = _normalise_comparison_value(source.get("previous_value"))
                target_previous = _normalise_comparison_value(target.get("previous_value"))
                source_variance = _normalise_comparison_value(source.get("variance"))
                target_variance = _normalise_comparison_value(target.get("variance"))

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
                "kpi": source.get("name") if source else target.get("name"),
                "source_kpi_name": source.get("name") if source else None,
                "target_kpi_name": target.get("name") if target else None,

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
    visual_comparison=None,
    table_comparison=None,
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
        "Comparison Status",
    ]

    _format_header(
        ws,
        headers,
    )

    status_by_visual = {
        str(item.get("visual_id")): item.get("status", "Not Compared")
        for item in (visual_comparison or [])
        if item.get("visual_id")
    }
    table_status_by_title = {
        " ".join(str(item.get("visual", "")).casefold().split()): item.get("status", "Not Compared")
        for item in (table_comparison or {}).get("summary", [])
    }
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
                status_by_visual.get(str(chart.get("visual_id")), "Not Compared"),
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
                (
                    f"{len(table.get('rows', []))} rows × "
                    f"{len(table.get('columns', []))} columns; see Table Data"
                ),
                "N/A",
                table_status_by_title.get(
                    " ".join(str(table.get("table_title", "")).casefold().split()),
                    "Not Compared",
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


def _column_key(value):
    return " ".join(str(value or "").casefold().split())


def _table_columns(visual):
    """Return an ordered, non-empty column list for a rendered visual."""
    columns = visual.get("data", {}).get("columns", [])
    if columns:
        return [str(column) for column in columns]
    width = max((len(row) for row in visual.get("data", {}).get("rows", [])), default=0)
    return [f"Column {index}" for index in range(1, width + 1)]


def build_visual_data_comparison(visual_data):
    """Compare every rendered table column and row, visual by visual.

    Jagruthi: tabular-only comparison; column names are the merge key.

    Column names—not the temporary horizontal viewport position—are used as
    the comparison key.  This avoids the previous behaviour where only the
    first few visible columns of a Power BI matrix were compared.
    """
    from services.table_comparison import is_tabular_visual

    source = [
        item for item in visual_data.get("Source", {}).get("visuals", [])
        if is_tabular_visual(item)
    ]
    target = [
        item for item in visual_data.get("Target", {}).get("visuals", [])
        if is_tabular_visual(item)
    ]
    source_map = {_visual_key(item): item for item in source if _visual_key(item)}
    target_map = {_visual_key(item): item for item in target if _visual_key(item)}
    summaries, cells = [], []
    for key in sorted(set(source_map) | set(target_map)):
        left, right = source_map.get(key), target_map.get(key)
        if not left or not right:
            summaries.append({"visual": (left or right).get("title"), "status": "Missing in Target" if left else "Missing in Source", "source_rows": len((left or {}).get("data", {}).get("rows", [])), "target_rows": len((right or {}).get("data", {}).get("rows", [])), "matched_cells": 0, "mismatched_cells": 0})
            continue
        left_rows, right_rows = left.get("data", {}).get("rows", []), right.get("data", {}).get("rows", [])
        left_columns, right_columns = _table_columns(left), _table_columns(right)
        if not left_rows and not right_rows and not left_columns and not right_columns:
            summaries.append({"visual": left.get("title"), "status": "No table data captured", "source_rows": 0, "target_rows": 0, "matched_cells": 0, "mismatched_cells": 0})
            continue
        left_column_map = {_column_key(name): index for index, name in enumerate(left_columns)}
        right_column_map = {_column_key(name): index for index, name in enumerate(right_columns)}
        column_keys = list(dict.fromkeys([_column_key(name) for name in left_columns + right_columns]))
        matched = mismatched = 0
        for row_number in range(max(len(left_rows), len(right_rows))):
            left_row = left_rows[row_number] if row_number < len(left_rows) else []
            right_row = right_rows[row_number] if row_number < len(right_rows) else []
            for column_key in column_keys:
                source_column = left_column_map.get(column_key)
                target_column = right_column_map.get(column_key)
                source_value = left_row[source_column] if source_column is not None and source_column < len(left_row) else None
                target_value = right_row[target_column] if target_column is not None and target_column < len(right_row) else None
                status = "Match" if source_value == target_value else ("Missing in Source" if source_value is None else "Missing in Target" if target_value is None else "Mismatch")
                matched += status == "Match"
                mismatched += status != "Match"
                display_column = left_columns[source_column] if source_column is not None else right_columns[target_column]
                cells.append({"visual": left.get("title"), "row_number": row_number + 1, "column": display_column, "source_value": source_value, "target_value": target_value, "status": status})
        summaries.append({"visual": left.get("title"), "status": "Match" if not mismatched else "Mismatch", "source_rows": len(left_rows), "target_rows": len(right_rows), "matched_cells": matched, "mismatched_cells": mismatched})
    return {"summary": summaries, "cells": cells}


def _create_visual_data_sheets(wb, visual_data):
    """Create side-by-side table blocks plus complete cell-level comparisons."""
    from services.table_comparison import is_tabular_visual

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

    # One sheet holds each matched pair beside each other.  Individual visual
    # blocks preserve their own real headers, which makes the raw data usable
    # without jumping between Source and Target worksheets.
    raw = wb.create_sheet("Table Data")
    source_visuals = {
        _visual_key(item): item
        for item in visual_data.get("Source", {}).get("visuals", [])
        if _visual_key(item) and is_tabular_visual(item)
    }
    target_visuals = {
        _visual_key(item): item
        for item in visual_data.get("Target", {}).get("visuals", [])
        if _visual_key(item) and is_tabular_visual(item)
    }
    row_idx = 1
    for key in sorted(set(source_visuals) | set(target_visuals)):
        source_visual, target_visual = source_visuals.get(key), target_visuals.get(key)
        source_columns = _table_columns(source_visual) if source_visual else []
        target_columns = _table_columns(target_visual) if target_visual else []
        source_width = max(1, len(source_columns))
        target_start = source_width + 3
        raw.cell(row=row_idx, column=1, value=f"Source: {(source_visual or target_visual).get('title')}")
        raw.cell(row=row_idx, column=target_start, value=f"Target: {(target_visual or source_visual).get('title')}")
        for cell in (raw.cell(row=row_idx, column=1), raw.cell(row=row_idx, column=target_start)):
            cell.font = SUBHEADER_FONT
        row_idx += 1
        for index, column in enumerate(source_columns, start=1):
            _style_cell(raw.cell(row=row_idx, column=index, value=column), ALIGN_CENTER)
            raw.cell(row=row_idx, column=index).font = HEADER_FONT
            raw.cell(row=row_idx, column=index).fill = HEADER_FILL
        for index, column in enumerate(target_columns, start=target_start):
            _style_cell(raw.cell(row=row_idx, column=index, value=column), ALIGN_CENTER)
            raw.cell(row=row_idx, column=index).font = HEADER_FONT
            raw.cell(row=row_idx, column=index).fill = HEADER_FILL
        row_idx += 1
        height = max(len((source_visual or {}).get("data", {}).get("rows", [])), len((target_visual or {}).get("data", {}).get("rows", [])))
        for data_row in range(height):
            for index, value in enumerate(((source_visual or {}).get("data", {}).get("rows", []) or [[]])[data_row] if data_row < len((source_visual or {}).get("data", {}).get("rows", [])) else [], start=1):
                _style_cell(raw.cell(row=row_idx, column=index, value=value))
            for index, value in enumerate(((target_visual or {}).get("data", {}).get("rows", []) or [[]])[data_row] if data_row < len((target_visual or {}).get("data", {}).get("rows", [])) else [], start=target_start):
                _style_cell(raw.cell(row=row_idx, column=index, value=value))
            row_idx += 1
        row_idx += 2
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


def _create_slicer_test_sheet(wb, scenarios):
    """Record the matched-slicer run and its visual comparison result."""
    if not scenarios:
        return
    ws = wb.create_sheet("Slicer Test")
    _format_header(ws, ["Slicer", "Selected Value", "Source Applied", "Target Applied", "Visual", "Status", "Matching Cells", "Different Cells", "AI Analysis Error"])
    row = 2
    for scenario in scenarios:
        visual_results = scenario.get("visual_comparison") or [{}]
        for visual in visual_results:
            values = [scenario.get("slicer"), scenario.get("value"), scenario.get("source_applied"), scenario.get("target_applied"), visual.get("visual"), visual.get("status", scenario.get("status", "completed")), visual.get("matched_cells"), visual.get("mismatched_cells"), scenario.get("ai_analysis_error")]
            for col_idx, value in enumerate(values, start=1):
                _style_cell(ws.cell(row=row, column=col_idx, value=value))
            row += 1
    _auto_fit(ws)


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
    slicer_scenarios=None,
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

        table_comparison = build_visual_data_comparison(visual_data or {})
        combined_visual_comparison = list(visual_comparison or []) + [
            {
                "visual": item.get("visual"),
                "source": f"{item.get('source_rows', 0)} rows / {item.get('matched_cells', 0)} matching cells",
                "target": f"{item.get('target_rows', 0)} rows / {item.get('mismatched_cells', 0)} differing cells",
                "status": item.get("status", "Not Compared"),
            }
            for item in table_comparison.get("summary", [])
        ]

        _create_visual_details_sheet(
            wb,
            source_data,
            target_data,
            visual_comparison,
            table_comparison,
        )

        _create_visual_comparison_sheet(
            wb,
            combined_visual_comparison,
        )

        _create_browser_metrics_sheet(
            wb,
            metrics,
        )

        _create_visual_data_sheets(wb, visual_data)
        _create_slicer_test_sheet(wb, slicer_scenarios or [])

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

def calculate_match_percentage(results: list) -> float | None:
    """
    Calculate percentage of comparison items with status 'Match'.
    """

    if not results:
        return None

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

    Jagruthi: skip empty KPI/visual buckets when computing overall match %.
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

    scored = [
        value
        for value in (filter_percentage, kpi_percentage, visual_percentage)
        if value is not None
    ]
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
