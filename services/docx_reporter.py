"""Word report for a completed source-versus-target validation run.

Jagruthi — includes Arun multi-page dashboard sections when page data is provided.
"""

from pathlib import Path
import logging

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from services.dashboard_inventory_service import (
    _count_inventory_for_execution,
    _list_kpis_for_execution,
    _list_visuals_for_execution,
)
from services.excel_exporter import build_visual_data_comparison


LIGHT_RED = "FCE4D6"
DARK_RED = "9C0006"
logger = logging.getLogger(__name__)


def _shade(cell, color):
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color)
    properties.append(shading)


def _table(document, headers, rows):
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = str(header)
        _shade(cell, LIGHT_RED)
        for run in cell.paragraphs[0].runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(156, 0, 6)
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = "" if value is None else str(value)
    return table


def _status_brief(items, label):
    """Create a plain-language matching/mismatching synopsis for a report."""
    total = len(items)
    matches = sum(1 for item in items if item.get("status") == "Match")
    differences = total - matches
    return f"{label}: {matches} matching and {differences} mismatching or missing out of {total} compared item(s)."


def _browser_metric_rows(source_metrics, target_metrics):
    """Jagruthi — expanded browser metrics for Word (not just load/render)."""
    rows = []
    for label, key in [
        ("Page name", "page_name"),
        ("Page load (seconds)", "page_load_seconds"),
        ("Render (seconds)", "dashboard_render_seconds"),
        ("Screenshot (seconds)", "screenshot_seconds"),
        ("Gemini extraction (seconds)", "gemini_extraction_seconds"),
        ("Total execution (seconds)", "total_execution_seconds"),
        ("HTTP requests", "total_requests"),
        ("Failed requests", "failed_requests"),
        ("Console messages", "console_messages"),
        ("Page errors", "page_errors"),
    ]:
        source_value = source_metrics.get(key)
        target_value = target_metrics.get(key)
        if source_value is None and target_value is None:
            continue
        rows.append((label, source_value, target_value))
    return rows


def generate_validation_document(
    run_id,
    executions,
    comparison,
    output_directory,
    page_comparisons=None,
    executions_by_dashboard=None,
):
    """Generate a concise metadata, match and exception report for stakeholders."""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    document = Document()
    for style_name in ("Heading 1", "Heading 2"):
        document.styles[style_name].font.color.rgb = RGBColor(156, 0, 6)
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.7)
    title = document.add_heading("Power BI Dashboard Validation Report", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.color.rgb = RGBColor(156, 0, 6)
    document.add_paragraph(f"Validation run: {run_id}")

    document.add_heading("Validation Status", level=1)
    document.add_paragraph(comparison.get("status", "not_compared").replace("_", " ").title())
    if comparison.get("reason"):
        document.add_paragraph(comparison["reason"])

    # Jagruthi — Arun multi-page per-page comparison summary
    if page_comparisons:
        document.add_heading("Multi-Page Comparison Summary", level=1)
        document.add_paragraph(
            "Each report page is compared independently between source and target dashboards."
        )
        _table(
            document,
            ["Page Name", "Status", "Overall %", "Filter %", "KPI %", "Visual %"],
            [
                (
                    item.get("page_name"),
                    item.get("status"),
                    (item.get("summary") or {}).get("overall_match_percentage"),
                    (item.get("summary") or {}).get("filter_match_percentage"),
                    (item.get("summary") or {}).get("kpi_match_percentage"),
                    (item.get("summary") or {}).get("visual_match_percentage"),
                )
                for item in page_comparisons
            ],
        )

    document.add_heading("Dashboard Metadata", level=1)
    _table(document, ["Field", "Source", "Target"], [
        ("Name", executions[0]["dashboard"].get("name"), executions[1]["dashboard"].get("name")),
        ("URL", executions[0]["dashboard"].get("url"), executions[1]["dashboard"].get("url")),
        ("Page", executions[0]["dashboard"].get("page_name"), executions[1]["dashboard"].get("page_name")),
        ("Gemini extraction", executions[0]["extraction"].get("status"), executions[1]["extraction"].get("status")),
        ("Browser visual extraction", executions[0]["visual_data"].get("status"), executions[1]["visual_data"].get("status")),
    ])

    if comparison.get("status") == "success":
        document.add_heading("Validation Match Summary", level=1)
        summary = comparison["summary"]
        _table(document, ["Area", "Match %"], [
            ("Filters", summary["filter_match_percentage"]), ("KPIs", summary["kpi_match_percentage"]),
            ("Visuals", summary["visual_match_percentage"]), ("Overall", summary["overall_match_percentage"]),
        ])

    source_metrics = executions[0]["metrics"] or {}
    target_metrics = executions[1]["metrics"] or {}
    document.add_heading("Browser Metrics (First Compared Page)", level=1)
    metric_rows = _browser_metric_rows(source_metrics, target_metrics)
    if metric_rows:
        _table(document, ["Metric", "Source", "Target"], metric_rows)
    else:
        document.add_paragraph("No browser metrics were captured for the first compared page.")

    # Jagruthi — per-page inventory, KPIs, and visuals for all dashboard pages
    if executions_by_dashboard:
        document.add_heading("Page Inventory (All Pages)", level=1)
        inventory_rows = []
        for dashboard_executions in executions_by_dashboard:
            for execution in dashboard_executions:
                dashboard = execution.get("dashboard") or {}
                inventory = _count_inventory_for_execution(execution)
                inventory_rows.append(
                    (
                        dashboard.get("name"),
                        dashboard.get("page_name") or inventory.get("page_name") or "Default",
                        inventory.get("filter_count", 0),
                        inventory.get("kpi_count", 0),
                        inventory.get("table_count", 0),
                        inventory.get("matrix_count", 0),
                        inventory.get("chart_count", 0),
                        inventory.get("total_visuals", 0),
                    )
                )
        _table(
            document,
            ["Dashboard", "Page", "Filters", "KPIs", "Tables", "Matrices", "Charts", "Total Visuals"],
            inventory_rows,
        )

        document.add_heading("Page KPIs (All Pages)", level=1)
        kpi_rows = []
        for dashboard_executions in executions_by_dashboard:
            for execution in dashboard_executions:
                dashboard = execution.get("dashboard") or {}
                page_name = dashboard.get("page_name") or "Default"
                for kpi in _list_kpis_for_execution(execution):
                    kpi_rows.append(
                        (
                            dashboard.get("name"),
                            page_name,
                            kpi.get("name"),
                            kpi.get("value"),
                            kpi.get("extraction_source"),
                        )
                    )
        if kpi_rows:
            _table(document, ["Dashboard", "Page", "KPI", "Value", "Source"], kpi_rows)
        else:
            document.add_paragraph("No KPI cards were detected on any page.")

        document.add_heading("Page Visuals (All Pages)", level=1)
        visual_rows = []
        for dashboard_executions in executions_by_dashboard:
            for execution in dashboard_executions:
                dashboard = execution.get("dashboard") or {}
                page_name = dashboard.get("page_name") or "Default"
                for visual in _list_visuals_for_execution(execution):
                    visual_rows.append(
                        (
                            dashboard.get("name"),
                            page_name,
                            visual.get("title"),
                            visual.get("visual_type"),
                            visual.get("category"),
                            visual.get("extraction_source", "dom"),
                        )
                    )
        if visual_rows:
            _table(
                document,
                ["Dashboard", "Page", "Visual", "Type", "Category", "Source"],
                visual_rows,
            )
        else:
            document.add_paragraph("No visuals were detected on any page.")

    if comparison.get("status") == "success":
        document.add_heading("Gemini KPI Comparison", level=1)
        document.add_paragraph("KPI labels and values below are extracted from the source and target screenshots by Gemini.")
        _table(document, ["KPI", "Source", "Target", "Status"], [
            (item.get("kpi"), item.get("source"), item.get("target"), item.get("status"))
            for item in comparison.get("kpis", [])
        ])
        document.add_paragraph(_status_brief(comparison.get("kpis", []), "KPI result"))

    visual_comparison = build_visual_data_comparison({"Source": executions[0]["visual_data"], "Target": executions[1]["visual_data"]})
    document.add_heading("Visual Data Analysis (First Compared Page)", level=1)
    document.add_paragraph("Each visual is matched by its displayed title. Table values are compared cell by cell in the generated Excel workbook.")
    _table(document, ["Visual", "Status", "Source Rows", "Target Rows", "Matching Cells", "Different Cells"], [
        (item["visual"], item["status"], item["source_rows"], item["target_rows"], item["matched_cells"], item["mismatched_cells"])
        for item in visual_comparison["summary"]
    ])
    document.add_paragraph(_status_brief(visual_comparison["summary"], "Table and visual result"))

    scenarios = comparison.get("slicer_scenarios", [])
    if scenarios:
        document.add_heading("Matched Slicer Test", level=1)
        document.add_paragraph("The same randomly selected common slicer value was applied to both dashboards before a fresh screenshot and AI analysis were captured.")
        _table(document, ["Slicer", "Value", "Page", "Applied to Source", "Applied to Target", "Result"], [
            (
                item.get("slicer"),
                item.get("value"),
                item.get("page_name"),
                item.get("source_applied"),
                item.get("target_applied"),
                item.get("status", "completed"),
            )
            for item in scenarios
        ])
        for item in scenarios:
            if item.get("visual_comparison"):
                page_label = item.get("page_name") or "page"
                document.add_paragraph(
                    _status_brief(item["visual_comparison"], f"Slicer test ({page_label} / {item.get('value')})")
                )

    path = output_directory / f"{run_id}_dashboard_validation.docx"
    document.save(path)
    logger.info("Word validation report generated | %s", path)
    return path
