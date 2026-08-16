"""Word report for a completed source-versus-target validation run."""

from pathlib import Path
import logging

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

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


def generate_validation_document(run_id, executions, comparison, output_directory):
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

    document.add_heading("Dashboard Metadata", level=1)
    _table(document, ["Field", "Source", "Target"], [
        ("Name", executions[0]["dashboard"].get("name"), executions[1]["dashboard"].get("name")),
        ("URL", executions[0]["dashboard"].get("url"), executions[1]["dashboard"].get("url")),
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
    document.add_heading("Browser Metrics", level=1)
    _table(document, ["Metric", "Source", "Target"], [
        ("Page load (seconds)", source_metrics.get("page_load_seconds"), target_metrics.get("page_load_seconds")),
        ("Render (seconds)", source_metrics.get("dashboard_render_seconds"), target_metrics.get("dashboard_render_seconds")),
    ])

    if comparison.get("status") == "success":
        document.add_heading("Gemini KPI Comparison", level=1)
        document.add_paragraph("KPI labels and values below are extracted from the source and target screenshots by Gemini.")
        _table(document, ["KPI", "Source", "Target", "Status"], [
            (item.get("kpi"), item.get("source"), item.get("target"), item.get("status"))
            for item in comparison.get("kpis", [])
        ])
        document.add_paragraph(_status_brief(comparison.get("kpis", []), "KPI result"))

    visual_comparison = build_visual_data_comparison({"Source": executions[0]["visual_data"], "Target": executions[1]["visual_data"]})
    document.add_heading("Visual Data Analysis", level=1)
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
        _table(document, ["Slicer", "Value", "Applied to Source", "Applied to Target", "Result"], [
            (item.get("slicer"), item.get("value"), item.get("source_applied"), item.get("target_applied"), item.get("status", "completed"))
            for item in scenarios
        ])
        for item in scenarios:
            if item.get("visual_comparison"):
                document.add_paragraph(_status_brief(item["visual_comparison"], f"Slicer test ({item.get('value')})"))

    path = output_directory / f"{run_id}_dashboard_validation.docx"
    document.save(path)
    logger.info("Word validation report generated | %s", path)
    return path
