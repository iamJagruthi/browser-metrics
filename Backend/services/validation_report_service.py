"""Automated PBI validation DOCX report built from persisted artifacts.

This module is intentionally isolated from the browser pipeline:

* It never launches Playwright.
* It never calls an LLM or vision model.
* It never contacts Power BI or triggers another export/DOM extraction.
* It only reads the persisted artifacts (validation_capture.json,
  browser_metrics.json, run_status.json under ``output/reports/<run_id>/``)
  plus the screenshot/export files those artifacts reference.

The report is produced deterministically in two steps:

1. ``_build_report_model`` turns the persisted JSON into a plain report
   model covering ``report_metadata``, ``execution_context``,
   ``refresh_validation``, ``filter_validation``,
   ``visual_functional_validation``, ``data_export_validation``,
   ``mismatch_report``, ``summary`` and ``sign_off``. Every value comes
   from recorded data only; anything the capture did not record becomes
   ``Not Available`` (or ``Not Required``), never ``None``, ``null``,
   ``{}`` or an empty string.
2. ``_render`` lays that model out with python-docx: a cover page and the
   narrative sections in portrait, one landscape section for the wide
   tables (filters, visuals, exports, mismatches), then portrait again for
   the breakdown, sign-off and appendices.

Entry point:

    from services.validation_report_service import build_validation_report

    path = await build_validation_report(run_id)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from services.run_artifact_store import (
    load_browser_metrics,
    load_run_status,
    load_validation_capture,
)
from utils.config import REPORT_DIR, SCREENSHOT_DIR


logger = logging.getLogger(__name__)

# Presentation-only markers. Fields the automation cannot determine are
# reported with one of these words so a blank cell never has to be
# interpreted by the reader.
_NOT_AVAILABLE = "Not Available"
_NOT_REQUIRED = "Not Required"

_PASS = "PASS"
_FAIL = "FAIL"
_UNCERTAIN = "UNCERTAIN"
_NOT_AVAILABLE_LABEL = "NOT AVAILABLE"

_STATUS_COLORS = {
    _PASS: RGBColor(0x1E, 0x7B, 0x34),
    _FAIL: RGBColor(0xB0, 0x00, 0x20),
    _UNCERTAIN: RGBColor(0x9C, 0x65, 0x00),
    _NOT_AVAILABLE_LABEL: RGBColor(0x59, 0x59, 0x59),
}

_SIGN_OFF_STATUS = "Pending Manual Sign-off"

# Generic dictionary-key markers for a persisted refresh timestamp. Key-driven
# only - no dashboard location, coordinate, label, or date format is assumed.
_PERSISTED_REFRESH_KEYWORDS = (
    "refresh",
    "last_updated",
    "updated_at",
    "updated_as_of",
    "data_as_of",
)

_CHECKS = ("kpis", "visuals", "filters", "buttons")

# Generic statement describing what a successfully applied filter is
# expected to do. Filled only for real, runtime-applied filter scenarios
# (never for DOM-only comparison rows, and never for results/values that
# were not actually observed).
_FILTER_EXPECTED_BEHAVIOR = (
    "Dashboard visuals update according to the selected filter"
)

# The comparison engine records the mismatch total as filter + KPI + visual +
# table-cell + browser-metric items; table-visual mismatches are tallied in
# their own category. Stated in the report so the two numbers reconcile.
_MISMATCH_TOTAL_NOTE = (
    "The mismatch total is recorded by the comparison engine as filter + KPI "
    "+ visual + table-cell + browser-metric items. Table-visual mismatches "
    "are counted in their own category and are therefore not part of that "
    "total."
)

# US-Letter portrait with 1.0in margins leaves a 6.5in printable width; the
# landscape section uses 0.6in margins for a 9.8in printable width.
_PORTRAIT_MARGIN_IN = 1.0
_LANDSCAPE_MARGIN_IN = 0.6
_PORTRAIT_WIDTH_IN = 6.5
_LANDSCAPE_WIDTH_IN = 9.8

_SCREENSHOT_PAGE_WIDTH_IN = 6.5
_SCREENSHOT_PAGE_MAX_HEIGHT_IN = 9.0

_TABLE_FONT_PT = 8.5
_BODY_FONT_PT = 10.0

_HEADER_FILL = "1F3864"
_ALT_ROW_FILL = "F2F5FA"


class ValidationReportNotFound(Exception):
    """Raised when no persisted capture exists for a run_id."""


class ValidationReportError(Exception):
    """Raised when the DOCX report cannot be generated."""


def _safe(value, default: str = _NOT_AVAILABLE) -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple, dict)):
        return default if not value else str(value)
    text = str(value).strip()
    return text if text else default


def _safe_filename_dashboard(name: str) -> str:
    """Turn a captured dashboard/report title into a filesystem-safe name.

    Matches the requested ``<Dashboard_Name>_<run_id>.docx`` convention
    (spaces/punctuation become underscores). Never derived from run_id and
    never hardcoded.
    """
    text = _safe(name, "Dashboard")
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip(" ._") or "Dashboard"


def report_filename(run_id: str, dashboard_name: str) -> str:
    """Return the DOCX file name: ``<Dashboard_Name>_<run_id>.docx``.

    The dashboard name is the actual captured dashboard/report title (the
    same value used in the report's "Report Name" field); only its
    filesystem-safe form is embedded in the file name.
    """
    fragment = _safe_filename_dashboard(_safe(dashboard_name, "Dashboard"))
    return f"{fragment}_{run_id}.docx"


def _workspace_name(dashboard: dict | None) -> str:
    """Return an actual workspace name when the dashboard object already
    carries one, otherwise the honest "Not Available" marker.

    The URL's ``/groups/{guid}`` fragment is a workspace *id*, never a
    workspace *name*, so it is never surfaced as a name. No value is derived
    from run_id.
    """
    return _safe((dashboard or {}).get("workspace_name"), _NOT_AVAILABLE)


def _resolve_screenshot_path(recorded: str | None) -> Path | None:
    """Return an existing screenshot file for a recorded path.

    Handles stale absolute paths (e.g. captures taken before the backend
    folder reorganisation) by re-rooting them under PROJECT_ROOT and, as a
    final fallback, searching the screenshots store by filename.
    """
    if not recorded:
        return None

    candidate = Path(recorded)
    if candidate.exists():
        return candidate

    rerooted = Path(
        str(recorded)
        .replace("\\output\\", "\\Backend\\output\\")
        .replace("/output/", "/Backend/output/")
    )
    if rerooted.exists():
        return rerooted

    matches = sorted(Path(SCREENSHOT_DIR).rglob(candidate.name))
    if matches:
        return matches[0]

    return None


def _scan_refresh(obj) -> str | None:
    """Return the first non-empty value stored under a refresh-ish key.

    Key-driven only (e.g. ``refresh_timestamp``, ``last_updated``,
    ``updated_at``) so no dashboard location, label, or date format is
    hardcoded. Handles both persisted dicts and flat key/value entries.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = str(key).casefold()
            if any(
                token in lowered for token in _PERSISTED_REFRESH_KEYWORDS
            ) and isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = _scan_refresh(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _scan_refresh(item)
            if found:
                return found
    return None


def _extract_refresh_stamp(executions: list) -> str:
    for execution in executions or []:
        containers = (
            execution,
            execution.get("dashboard") or {},
            execution.get("metrics") or {},
            execution.get("extraction") or {},
            execution.get("visual_data") or {},
        )
        for container in containers:
            found = _scan_refresh(container)
            if found:
                return found
    return _NOT_AVAILABLE


def _report_display_name(source_name: str, target_name: str, metrics: list) -> str:
    candidates: dict[str, int] = {}
    for metric in metrics or []:
        if not isinstance(metric, dict):
            continue
        title = _safe(metric.get("page_title"), "")
        parts = title.split(" - ")
        if not parts:
            continue
        trailing = parts[-1].strip().casefold()
        if trailing not in ("power bi", "microsoft power bi"):
            continue
        # Power BI tab titles are "<Page> - <Report> - Power BI" for
        # multi-page reports and "<Report> - Power BI" for single-page
        # reports; the report/dashboard title is the segment directly before
        # the Power BI suffix. The most frequently observed segment across
        # all pages/sides wins, so a report name repeated on every page
        # beats any single page's title.
        if len(parts) >= 3:
            segment = parts[-2].strip()
        elif len(parts) == 2:
            segment = parts[0].strip()
        else:
            continue
        if segment:
            candidates[segment] = candidates.get(segment, 0) + 1
    if candidates:
        return max(candidates, key=candidates.get)
    if source_name and target_name and source_name != target_name:
        return f"{source_name} vs {target_name}"
    return source_name or _NOT_AVAILABLE


def resolve_dashboard_name(source_name: str, target_name: str, metrics: list) -> str:
    """Public resolver for the report/dashboard display name.

    Single sourced place so the API response (``dashboard_name``) and the
    DOCX report agree. Kept DOM-derived for now; the AI pipeline surfaces a
    ``dashboard_name`` when the hosted service returns one.
    """
    return _report_display_name(source_name, target_name, metrics)


# ---------------------------------------------------------------------------
# Value formatting helpers (deterministic, never invent a value)
# ---------------------------------------------------------------------------


def _seconds(value) -> str:
    if value is None:
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _duration(value) -> str:
    if value is None:
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.2f} s"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _pct(value) -> str:
    if value is None:
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return _NOT_AVAILABLE


def _confidence(value) -> str:
    if value is None:
        return _NOT_AVAILABLE
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return _safe(value)


def _yes_no(value, default: str = _NOT_AVAILABLE) -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    if not text:
        return default
    lowered = text.casefold()
    if lowered in ("true", "yes"):
        return "Yes"
    if lowered in ("false", "no"):
        return "No"
    return text


def _values(value) -> str:
    """Render a recorded scalar/list/dict value as report text.

    An empty list/dict is a recorded fact ("nothing selected"), so it is
    shown as ``(none)`` rather than being dropped; a missing value is
    ``Not Available``.
    """
    if value is None:
        return _NOT_AVAILABLE
    if isinstance(value, (list, tuple)):
        if not value:
            return "(none)"
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        if not value:
            return "(none)"
        return "; ".join(f"{key}: {val}" for key, val in value.items())
    text = str(value).strip()
    return text if text else _NOT_AVAILABLE


# ---------------------------------------------------------------------------
# Status presentation (presentation only - no validation logic lives here)
# ---------------------------------------------------------------------------


def _status_label(status, reason=None) -> str:
    """Map a recorded comparison status onto PASS/FAIL/UNCERTAIN/NOT AVAILABLE.

    The raw status text is always preserved separately in the report; this
    function only decides how it is presented.
    """
    text = str(status) if status is not None else ""
    text = text.strip()
    if not text:
        return _NOT_AVAILABLE_LABEL
    lowered = " ".join(text.casefold().replace("_", " ").split())

    if lowered in (
        "match",
        "matched",
        "table matched",
        "pass",
        "passed",
        "success",
        "succeeded",
        "verified",
        "stable",
        "completed",
        "applied",
        "confirmed",
    ):
        return _PASS

    if lowered in (
        "mismatch",
        "mismatched",
        "table mismatch",
        "table mismatched",
        "missing in source",
        "missing in target",
        "fail",
        "failed",
        "failure",
        "error",
        "unstable",
        "render not confirmed",
    ):
        return _FAIL

    if lowered in (
        "needs review",
        "uncertain",
        "mixed",
        "partial",
        "inconclusive",
        "ambiguous",
    ):
        return _UNCERTAIN

    if lowered in (
        "not compared",
        "table not compared",
        "unavailable",
        "not available",
        "no data",
        "not tested",
        "skipped",
    ):
        # A table recorded as "not compared" because one side is missing is
        # a real difference, not a missing observation.
        if reason and "missing" in str(reason).casefold():
            return _FAIL
        return _NOT_AVAILABLE_LABEL

    # An unrecognised recorded status must never be presented as a pass.
    return _UNCERTAIN


def _run_status_label(status) -> str:
    """Map the persisted run lifecycle status onto the presentation labels."""
    lowered = _safe(status, "").casefold().replace("_", " ")
    lowered = " ".join(lowered.split())
    if lowered in ("completed", "complete", "success", "succeeded", "passed"):
        return _PASS
    if lowered in ("failed", "failure", "error"):
        return _FAIL
    if lowered in ("partial", "partially completed", "needs review"):
        return _UNCERTAIN
    if lowered:
        return _UNCERTAIN
    return _NOT_AVAILABLE_LABEL


# ---------------------------------------------------------------------------
# Persisted structure readers
# ---------------------------------------------------------------------------


@dataclass
class PagePair:
    page_name: str
    source: dict
    target: dict
    comparison: dict | None = None
    source_image: Path | None = None
    target_image: Path | None = None


def _split_executions(document: dict) -> tuple[list, list]:
    groups = document.get("executions_by_dashboard") or []
    source_executions = groups[0] if len(groups) > 0 else []
    target_executions = groups[1] if len(groups) > 1 else []
    return source_executions or [], target_executions or []


def _collect_pages(document: dict, response: dict) -> list[PagePair]:
    source_executions, target_executions = _split_executions(document)
    comparisons_by_page = {
        item.get("page_name"): item
        for item in (response.get("comparison") or {}).get("page_comparisons", [])
    }

    pages: list[PagePair] = []
    for source_execution in source_executions:
        page_name = (source_execution.get("dashboard") or {}).get("page_name")
        if not page_name:
            continue
        target_execution = next(
            (
                item
                for item in target_executions
                if (item.get("dashboard") or {}).get("page_name") == page_name
            ),
            None,
        )
        if target_execution is None:
            continue
        pages.append(
            PagePair(
                page_name=page_name,
                source=source_execution,
                target=target_execution,
                comparison=comparisons_by_page.get(page_name),
                source_image=_resolve_screenshot_path(
                    (source_execution.get("metrics") or {}).get("screenshot_path")
                ),
                target_image=_resolve_screenshot_path(
                    (target_execution.get("metrics") or {}).get("screenshot_path")
                ),
            )
        )
    return pages


def _side_meta(response: dict, index: int, key: str, default: str) -> str:
    dashboards = response.get("dashboards") or []
    if index >= len(dashboards):
        return default
    entry = dashboards[index] or {}
    if key == "name":
        return _safe((entry.get("dashboard") or {}).get("name"), default)
    if key == "url":
        return _safe((entry.get("dashboard") or {}).get("url"), default)
    if key == "page":
        return _safe(entry.get("page_name"), default)
    if key == "extraction":
        return _safe((entry.get("visual_data") or {}).get("status"), _NOT_AVAILABLE)
    return default


def _iter_comparison_items(response: dict):
    """Yield ``(page_name, kind, item)`` for every recorded comparison item.

    KPIs/visuals/filters/buttons plus the table comparisons all count as
    validation checks, so the same iteration feeds the counts, the visual
    section and the breakdown.
    """
    comparison = response.get("comparison") or {}
    page_comparisons = comparison.get("page_comparisons") or []
    if page_comparisons:
        for page in page_comparisons:
            page_name = _safe(page.get("page_name"), _NOT_AVAILABLE)
            for kind in _CHECKS:
                for item in page.get(kind) or []:
                    if isinstance(item, dict):
                        yield page_name, kind, item
            tables = page.get("tables") or {}
            for item in tables.get("comparisons") or []:
                if isinstance(item, dict):
                    yield page_name, "tables", item
        return

    for kind in _CHECKS:
        for item in comparison.get(kind) or []:
            if isinstance(item, dict):
                yield _NOT_AVAILABLE, kind, item
    tables = comparison.get("tables") or {}
    if isinstance(tables, dict):
        for item in tables.get("comparisons") or []:
            if isinstance(item, dict):
                yield _NOT_AVAILABLE, "tables", item


def _count_results(response: dict) -> dict:
    counts = {
        "total": 0,
        "matched": 0,
        "mismatched": 0,
        "uncertain": 0,
        "unavailable": 0,
    }
    for _page, _kind, item in _iter_comparison_items(response):
        label = _status_label(item.get("status"), item.get("reason"))
        counts["total"] += 1
        if label == _PASS:
            counts["matched"] += 1
        elif label == _FAIL:
            counts["mismatched"] += 1
        elif label == _UNCERTAIN:
            counts["uncertain"] += 1
        else:
            counts["unavailable"] += 1
    return counts


def _overall_label(counts: dict, response: dict) -> str:
    """Deterministic overall result: PASS / FAIL / NOT AVAILABLE."""
    comparison = response.get("comparison") or {}
    status = _safe(comparison.get("status"), "").casefold()
    if status and status not in ("success", "succeeded"):
        return _FAIL if status in ("failed", "failure", "error") else _NOT_AVAILABLE_LABEL
    if counts["total"] == 0:
        return _NOT_AVAILABLE_LABEL
    if counts["mismatched"] > 0:
        return _FAIL
    if counts["uncertain"] > 0 or counts["unavailable"] > 0:
        # Not every check concluded, so no pass can be claimed.
        return _NOT_AVAILABLE_LABEL
    return _PASS


def _scenario_page(scenario: dict) -> str:
    """Best-effort page/tab name for a slicer scenario that does not carry
    one; falls back to an empty string rather than fabricating a value."""
    return _safe(scenario.get("page") or scenario.get("page_name"), "")


# ---------------------------------------------------------------------------
# Report model: every section built from the persisted JSON only
# ---------------------------------------------------------------------------


def _build_report_model(
    document: dict,
    metrics_doc: dict,
    response: dict,
    run_status: dict,
) -> dict:
    pages = _collect_pages(document, response)
    comparison = response.get("comparison") or {}
    summary = comparison.get("summary") or {}
    counts = _count_results(response)
    overall = _overall_label(counts, response)

    source_executions, target_executions = _split_executions(document)
    source_name = _side_meta(response, 0, "name", _NOT_AVAILABLE)
    target_name = _side_meta(response, 1, "name", _NOT_AVAILABLE)
    source_refresh = _extract_refresh_stamp(source_executions)
    target_refresh = _extract_refresh_stamp(target_executions)

    metrics = response.get("metrics") or []
    report_name = (
        (response.get("dashboard_name") or "").strip()
        or _report_display_name(source_name, target_name, metrics)
    )

    run_id = _safe(response.get("run_id"), _NOT_AVAILABLE)
    validation_date = (document.get("created_at") or "").strip() or _NOT_AVAILABLE
    mismatches = response.get("mismatches") or {}
    mismatch_summary = mismatches.get("summary") or {}
    run_status_doc = run_status or {}
    run_status_text = _safe(run_status_doc.get("status"), _NOT_AVAILABLE)
    pages_doc = response.get("pages") or {}
    page_side_counts = [
        (entry or {}).get("page_count")
        for entry in (pages_doc.get("dashboards") or [])
    ]
    downloads = response.get("report_downloads") or {}
    ai_analysis = response.get("ai_analysis") or {}
    page_comparisons = comparison.get("page_comparisons") or []

    notes: list[str] = []
    if not pages:
        notes.append("No matching pages found between the two dashboards.")
    capture_error = document.get("capture_error")
    if capture_error:
        notes.append(f"Capture error: {_safe(capture_error)}")
    if response.get("document_report_error"):
        notes.append(
            f"Document report generation failed: "
            f"{_safe(response.get('document_report_error'))}"
        )

    model: dict = {
        "overall": overall,
        "report_name": report_name,
        "run_id": run_id,
        "counts": counts,
        "pages": pages,
        "notes": notes,
    }

    # ---- cover / report metadata -----------------------------------------
    model["report_metadata"] = {
        "title": "Dashboard Validation Report",
        "subtitle": "Automated Power BI validation - Viz Match",
        "rows": [
            ("Report Name", report_name),
            ("Run ID", run_id),
            ("Validation Date", validation_date),
            ("Report Generated", datetime.now().isoformat(timespec="seconds")),
            ("Tester", _NOT_AVAILABLE),
            (
                "Source Workspace",
                _workspace_name(
                    source_executions[0].get("dashboard")
                    if source_executions
                    else None
                ),
            ),
            (
                "Target Workspace",
                _workspace_name(
                    target_executions[0].get("dashboard")
                    if target_executions
                    else None
                ),
            ),
            ("Overall Result", overall),
        ],
    }

    # ---- 1. Executive Summary ---------------------------------------------
    executive_rows = [
        ("Total checks", str(counts["total"])),
        ("Matched", str(counts["matched"])),
        ("Mismatched", str(counts["mismatched"])),
        ("Uncertain", str(counts["uncertain"])),
    ]
    if counts["unavailable"]:
        executive_rows.append(("Not available", str(counts["unavailable"])))
    executive_rows.append(
        ("Overall match percentage", _pct(summary.get("overall_match_percentage")))
    )
    executive_rows.append(("Overall result", overall))

    category_labels = (
        ("total_mismatches", "Total mismatches (as recorded)"),
        ("filter_mismatch_count", "Filter mismatches"),
        ("kpi_mismatch_count", "KPI mismatches"),
        ("visual_mismatch_count", "Visual mismatches"),
        ("table_visual_mismatch_count", "Table visual mismatches"),
        ("table_cell_mismatch_count", "Table cell mismatches"),
        ("browser_metric_mismatch_count", "Browser metric mismatches"),
        ("overall_match_percentage", "Overall match percentage"),
    )
    category_rows = []
    for key, label in category_labels:
        value = mismatch_summary.get(key)
        if value is None:
            rendered = _NOT_AVAILABLE
        elif key == "overall_match_percentage":
            rendered = _pct(value)
        else:
            rendered = str(value)
        category_rows.append((label, rendered))

    model["executive_summary"] = {
        "rows": executive_rows,
        "category_rows": category_rows,
        "notes": [_MISMATCH_TOTAL_NOTE],
    }

    # ---- 2. Execution Details ---------------------------------------------
    compared_pages = [
        _safe(page.get("page_name"), _NOT_AVAILABLE) for page in page_comparisons
    ]
    execution_rows = [
        ("Report Name", report_name),
        ("Run ID", run_id),
        ("Validation date", validation_date),
        ("Run status", run_status_text),
        ("Run last updated", _safe(run_status_doc.get("updated_at"))),
        ("Multi-page capture", _yes_no(pages_doc.get("multi_page_mode"))),
        ("Source dashboard", source_name),
        ("Source dashboard URL", _side_meta(response, 0, "url", _NOT_AVAILABLE)),
        ("Source workspace", _workspace_name(
            source_executions[0].get("dashboard") if source_executions else None
        )),
        ("Target dashboard", target_name),
        ("Target dashboard URL", _side_meta(response, 1, "url", _NOT_AVAILABLE)),
        ("Target workspace", _workspace_name(
            target_executions[0].get("dashboard") if target_executions else None
        )),
        (
            "Source pages captured",
            _safe(page_side_counts[0]) if page_side_counts else _NOT_AVAILABLE,
        ),
        (
            "Target pages captured",
            _safe(page_side_counts[1]) if len(page_side_counts) > 1 else _NOT_AVAILABLE,
        ),
        ("Pages compared", str(len(page_comparisons))),
        (
            "Compared page names",
            ", ".join(compared_pages) if compared_pages else _NOT_AVAILABLE,
        ),
        ("Comparison status", _safe(comparison.get("status"))),
        ("Comparison reason", _safe(comparison.get("reason"))),
        ("Overall match percentage", _pct(summary.get("overall_match_percentage"))),
        ("Overall result", overall),
        ("AI visual comparison status", _safe(ai_analysis.get("status"))),
        (
            "Document report",
            _safe(
                response.get("document_report_path") or response.get("report_path")
            ),
        ),
    ]
    for label, key in (
        ("Download: mismatches", "mismatches"),
        ("Download: filters", "filters"),
        ("Download: inventory", "inventory"),
        ("Download: pages", "pages"),
    ):
        if downloads.get(key):
            execution_rows.append((label, str(downloads[key])))
    model["execution_context"] = {"rows": execution_rows}

    # ---- 3. Refresh Validation --------------------------------------------
    refresh_rows: list[list[str]] = []

    both_refresh = source_refresh != _NOT_AVAILABLE and target_refresh != _NOT_AVAILABLE
    if both_refresh:
        refresh_result = _PASS
        refresh_details = "Refresh timestamps recorded for both dashboards."
    elif source_refresh == _NOT_AVAILABLE and target_refresh == _NOT_AVAILABLE:
        refresh_result = _NOT_AVAILABLE_LABEL
        refresh_details = "No refresh timestamp recorded for this run."
    else:
        refresh_result = _NOT_AVAILABLE_LABEL
        missing = "source" if source_refresh == _NOT_AVAILABLE else "target"
        refresh_details = f"No refresh timestamp recorded for the {missing} dashboard."
    refresh_rows.append(
        ["Refresh date & time", source_refresh, target_refresh,
         refresh_result, refresh_details]
    )

    source_extraction = _side_meta(response, 0, "extraction", _NOT_AVAILABLE)
    target_extraction = _side_meta(response, 1, "extraction", _NOT_AVAILABLE)
    extraction_states = (source_extraction, target_extraction)
    if any(state in ("failed", "error") for state in extraction_states):
        execution_result = _FAIL
    elif all(state in ("success", "not_used") for state in extraction_states):
        execution_result = _PASS
    else:
        execution_result = _NOT_AVAILABLE_LABEL
    refresh_rows.append(
        [
            "Execution status",
            f"{source_extraction} (run: {run_status_text})",
            f"{target_extraction} (run: {run_status_text})",
            execution_result,
            "Visual extraction status per dashboard and the run lifecycle "
            "status recorded in run_status.json.",
        ]
    )

    source_shots = [page.source_image for page in pages]
    target_shots = [page.target_image for page in pages]
    source_have = sum(1 for path in source_shots if path)
    target_have = sum(1 for path in target_shots if path)
    page_total = len(pages)
    if page_total == 0:
        shot_result = _NOT_AVAILABLE_LABEL
        shot_details = "No comparable pages captured for this run."
        shot_source = shot_target = _NOT_AVAILABLE
    else:
        shot_source = f"{source_have} of {page_total} pages"
        shot_target = f"{target_have} of {page_total} pages"
        if source_have == page_total and target_have == page_total:
            shot_result = _PASS
            shot_details = "Page screenshots present for both dashboards."
        elif source_have == 0 and target_have == 0:
            shot_result = _NOT_AVAILABLE_LABEL
            shot_details = "No page screenshot captured for either dashboard."
        else:
            shot_result = _UNCERTAIN
            shot_details = (
                "Screenshots captured for some pages only "
                f"(source {source_have}/{page_total}, "
                f"target {target_have}/{page_total})."
            )
    refresh_rows.append(
        ["Screenshot availability", shot_source, shot_target,
         shot_result, shot_details]
    )

    source_pages_count = _safe(page_side_counts[0]) if page_side_counts else _NOT_AVAILABLE
    target_pages_count = (
        _safe(page_side_counts[1]) if len(page_side_counts) > 1 else _NOT_AVAILABLE
    )
    if page_comparisons:
        comparison_details = (
            f"Overall match: "
            f"{_pct(summary.get('overall_match_percentage'))} across "
            f"{len(page_comparisons)} compared page(s)."
        )
    else:
        comparison_details = "No page comparison recorded for this run."
    refresh_rows.append(
        [
            "Comparison result",
            f"{source_pages_count} page(s)",
            f"{target_pages_count} page(s)",
            overall,
            comparison_details,
        ]
    )

    model["refresh_validation"] = {
        "rows": refresh_rows,
        "notes": [
            "Result values are presentation labels only: PASS, FAIL, "
            "UNCERTAIN or NOT AVAILABLE."
        ],
    }

    model.update(
        _build_filter_model(document, response, pages),
    )
    model.update(_build_visual_model(response, ai_analysis))
    model["data_export_validation"] = _build_export_model(pages)
    model["mismatch_report"] = _build_mismatch_model(response)
    model["summary"] = _build_summary_model(response, counts, overall)
    model["sign_off"] = {
        "rows": [
            ("Prepared by", "Viz Match automated validation"),
            ("Tester name", _NOT_AVAILABLE),
            ("Agent ID", _NOT_AVAILABLE),
            ("Semantic model", _NOT_AVAILABLE),
            (
                "Source workspace",
                _workspace_name(
                    source_executions[0].get("dashboard")
                    if source_executions
                    else None
                ),
            ),
            (
                "Target workspace",
                _workspace_name(
                    target_executions[0].get("dashboard")
                    if target_executions
                    else None
                ),
            ),
            ("Overall result", overall),
            ("Sign-off status", _SIGN_OFF_STATUS),
            ("Sign-off date", _NOT_AVAILABLE),
            ("Signature", "____________________________"),
            ("Comments", _NOT_AVAILABLE),
        ]
    }
    model["appendix_screenshots"] = _build_screenshot_appendix(pages)
    model["appendix_ai"] = _build_ai_appendix(ai_analysis)
    return model


def _build_filter_model(document: dict, response: dict, pages: list[PagePair]) -> dict:
    """Sections 4.1 (runtime slicer evidence) and 4.2 (DOM filter state).

    Runtime scenario evidence and DOM filter-state comparison are kept as two
    separate tables: scenario rows are not associated with DOM/AI filter rows
    by index or by name, because the two lists are recorded independently.
    """
    comparison = response.get("comparison") or {}
    scenarios = document.get("slicer_scenarios") or comparison.get(
        "slicer_scenarios"
    ) or []

    runtime_rows: list[list[str]] = []
    any_applied = False
    render_not_confirmed = 0
    for index, scenario in enumerate(scenarios, start=1):
        if not isinstance(scenario, dict):
            continue
        slicer = _safe(scenario.get("slicer"))
        page = _scenario_page(scenario)
        label = slicer if not page or page.casefold() == "default" else f"{slicer} ({page})"
        value = _safe(scenario.get("value"))

        applied = {
            "source": scenario.get("source_applied"),
            "target": scenario.get("target_applied"),
        }
        render = {
            "source": scenario.get("source_render_stable"),
            "target": scenario.get("target_render_stable"),
        }
        render_time = {
            "source": scenario.get("source_dashboard_render_seconds"),
            "target": scenario.get("target_dashboard_render_seconds"),
        }

        applied_text = {
            side: (
                "Applied" if flag is True
                else "Not Applied" if flag is False
                else _NOT_AVAILABLE
            )
            for side, flag in applied.items()
        }
        # True: the re-render was observed after the click. False: it timed
        # out or the page closed. None: no interaction was needed (the value
        # was already selected). A key that is absent at all predates the
        # render observation and stays Not Available.
        render_text: dict[str, str] = {}
        for side in ("source", "target"):
            key = f"{side}_render_stable"
            if key not in scenario:
                render_text[side] = _NOT_AVAILABLE
            elif scenario[key] is True:
                render_text[side] = "Confirmed"
            elif scenario[key] is False:
                render_text[side] = "Not Confirmed"
            else:
                render_text[side] = _NOT_REQUIRED

        applied_ok = bool(applied["source"] and applied["target"])
        render_failed = any(flag is False for flag in render.values())
        if applied["source"] is None and applied["target"] is None:
            runtime_result = _NOT_AVAILABLE_LABEL
        elif not applied_ok:
            runtime_result = _FAIL
        elif render_failed:
            runtime_result = _FAIL
            render_not_confirmed += 1
        else:
            runtime_result = _PASS
            any_applied = True

        time_parts = [
            f"{side}={_duration(value_)}"
            for side, value_ in render_time.items()
            if value_ is not None
        ]
        runtime_rows.append(
            [
                f"{index:02d}",
                label,
                value,
                value,
                applied_text["source"],
                applied_text["target"],
                render_text["source"],
                render_text["target"],
                " | ".join(time_parts) if time_parts else _NOT_AVAILABLE,
                runtime_result,
            ]
        )

    runtime_notes: list[str] = []
    if not runtime_rows:
        runtime_rows.append(
            [
                "01",
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE_LABEL,
            ]
        )
        runtime_notes.append(
            "No runtime slicer scenario was executed during this capture."
        )
    else:
        runtime_notes.append(
            "Source/Target Value show the slicer value requested for both "
            "dashboards; the Applied columns report whether that value was "
            "actually applied on each side."
        )
        runtime_notes.append(
            "Render columns report the post-filter dashboard re-render "
            "observed by the capture: Confirmed, Not Confirmed, Not Required "
            "(no interaction was needed) or Not Available (not recorded)."
        )
        if render_not_confirmed:
            runtime_notes.append(
                f"{render_not_confirmed} scenario(s) applied the value but the "
                "dashboard re-render was not confirmed within the wait window; "
                "these rows are reported as FAIL."
            )
        if any_applied:
            runtime_notes.append(
                f"Expected behavior for applied filters: "
                f"{_FILTER_EXPECTED_BEHAVIOR}."
            )

    dom_rows: list[list[str]] = []
    for page in pages:
        page_comparison = page.comparison or {}
        for item in page_comparison.get("filters") or []:
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            result = _status_label(status, item.get("reason"))
            details = (
                "Filter selection matches on both dashboards."
                if result == _PASS
                else _safe(status)
            )
            dom_rows.append(
                [
                    page.page_name,
                    _safe(
                        item.get("filter_name")
                        or item.get("name")
                        or item.get("filter")
                    ),
                    _values(
                        item.get("source_selected", item.get("source"))
                    ),
                    _values(
                        item.get("target_selected", item.get("target"))
                    ),
                    _safe(status),
                    result,
                    details,
                ]
            )

    dom_notes: list[str] = []
    if not dom_rows:
        dom_rows.append(
            [
                _NOT_AVAILABLE,
                "No DOM filter-state comparison rows recorded",
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE_LABEL,
                "The comparison recorded no filter-state rows for this run.",
            ]
        )

    return {
        "filter_validation": {
            "runtime_rows": runtime_rows,
            "runtime_notes": runtime_notes,
            "dom_rows": dom_rows,
            "dom_notes": dom_notes,
        }
    }


_KIND_LABELS = {"kpis": "KPI", "visuals": "Visual", "buttons": "Button"}


def _build_visual_model(response: dict, ai_analysis: dict) -> dict:
    """Section 5: every recorded KPI/visual/button comparison row."""
    comparison = response.get("comparison") or {}
    page_comparisons = comparison.get("page_comparisons") or []
    show_page = len(page_comparisons) > 1

    rows: list[list[str]] = []
    for page_name, kind, item in _iter_comparison_items(response):
        if kind in ("filters", "tables"):
            # Filters have their own subsection (4.2), tables their own
            # section (6); both are counted as checks elsewhere.
            continue
        if kind == "kpis":
            name = _safe(item.get("kpi") or item.get("name"))
            source = _values(item.get("source"))
            target = _values(item.get("target"))
            details = _safe(item.get("reason"))
        elif kind == "visuals":
            name = _safe(item.get("visual") or item.get("name"))
            source = _values(item.get("source"))
            target = _values(item.get("target"))
            details = _safe(item.get("reason"))
        else:
            name = _safe(item.get("name") or "Button group")
            source = _values(item.get("source_selected"))
            target = _values(item.get("target_selected"))
            available = item.get("source_available") or item.get("target_available")
            details = (
                f"Available options: {_values(available)}" if available else _NOT_AVAILABLE
            )

        label = _KIND_LABELS.get(kind, "Item")
        display = f"{label}: {name}"
        if show_page:
            display = f"[{page_name}] {display}"
        status = item.get("status")
        rows.append(
            [
                display,
                source,
                target,
                _safe(status),
                _status_label(status, item.get("reason")),
                _confidence(item.get("confidence")),
                details,
            ]
        )

    if not rows:
        rows.append(
            [
                "No visual or functional comparison rows recorded",
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                _NOT_AVAILABLE_LABEL,
                _NOT_AVAILABLE,
                "The comparison recorded no KPI, visual or button rows.",
            ]
        )

    ai_pairs_rows: list[list[str]] | None = None
    payload = _ai_payload(ai_analysis) if ai_analysis else {}
    pairs = payload.get("pairs") if isinstance(payload, dict) else None
    if isinstance(pairs, list) and pairs:
        ai_pairs_rows = _ai_pairs_rows(pairs)

    notes: list[str] = []
    if not ai_pairs_rows:
        if not ai_analysis:
            notes.append("No AI visual comparison was recorded for this run.")
        else:
            notes.append(
                "The AI visual comparison recorded no pair results for this run."
            )

    return {
        "visual_functional_validation": {
            "rows": rows,
            "ai_pairs_rows": ai_pairs_rows,
            "notes": notes,
        }
    }


# ---------------------------------------------------------------------------
# Data export validation (section 6) - preserves the Case A..E semantics
# ---------------------------------------------------------------------------


def _normalise_table_title(title) -> str:
    return " ".join(str(title or "").casefold().split())


def _table_pairing_key(record: dict) -> str:
    """Identity used to pair a table across the two dashboards.

    A table the report gives no caption of its own is displayed as
    ``<dashboard>_table_<n>``, so its display name is dashboard-specific and
    cannot pair anything. ``comparison_key`` is the page-scoped ordinal that is
    identical on both dashboards, so it wins whenever present.
    """
    comparison_key = str((record or {}).get("comparison_key") or "").strip()
    if comparison_key:
        return comparison_key.casefold()
    return _normalise_table_title((record or {}).get("title"))


def _export_reference(export: dict | None) -> str:
    if not export:
        return _NOT_AVAILABLE
    if export.get("file_path"):
        reference = str(export["file_path"])
    elif export.get("status") in ("downloaded", "success"):
        reference = "Export succeeded (no file path recorded)"
    else:
        reference = f"Failed: {_safe(export.get('error'), 'no export produced')}"
    data = export.get("data")
    rows = None
    if isinstance(data, dict):
        rows = data.get("rows")
    if isinstance(rows, list):
        reference = f"{reference} ({len(rows)} rows)"
    return reference


def _is_browser_gone_error(error: str) -> bool:
    """True when a failure was caused by the browser closing, not by the visual.

    These read as "Export data is not available for this visual" in a report even
    though the export option was found and clicked, so they must be labelled
    separately or a working export looks permanently unsupported.
    """
    text = str(error or "").casefold()
    return (
        "has been closed" in text
        or "targetclosederror" in text
        or "target page closed" in text
        or "browser has been closed" in text
        or "connection closed" in text
    )


def _export_remarks(
    source_export: dict | None,
    target_export: dict | None,
    comparison: dict | None = None,
    dom_detected: bool = False,
) -> str:
    if not source_export and not target_export:
        if dom_detected:
            return (
                "Case E: Table/matrix visual detected on one or both reports but "
                "no export data was produced - Not compared"
            )
        return "Case D: No table/matrix export available"

    source_ok = bool(
        source_export
        and source_export.get("status") in ("downloaded", "success")
    )
    target_ok = bool(
        target_export
        and target_export.get("status") in ("downloaded", "success")
    )

    if not source_ok and not target_ok:
        # "Export data is not available for this visual" means Power BI's menu
        # genuinely offered no export for that visual. A browser that died
        # mid-save is a completely different fact and must not be reported as a
        # property of the visual, or a working export looks permanently broken.
        errors: list[str] = []
        unavailable: list[str] = []
        for export in (source_export, target_export):
            error = (export or {}).get("error")
            outcome = (export or {}).get("export_outcome")
            if outcome == "browser_closed" or (
                error and _is_browser_gone_error(error)
            ):
                errors.append(
                    _safe(error, "the browser closed before the export file was saved")
                )
            elif error:
                unavailable.append(_safe(error))
        if errors:
            return (
                "Case C: Not compared - the browser closed while saving the "
                f"export file (the visual does offer Export data): "
                f"{' | '.join(errors)}"
            )
        suffix = f": {' | '.join(unavailable)}" if unavailable else ""
        return f"Case C: Not compared - both exports failed{suffix}"
    if not (source_ok and target_ok):
        failed_side = "Target" if source_ok else "Source"
        failed_export = target_export if source_ok else source_export
        reason = _safe((failed_export or {}).get("error"), "no export produced")
        return f"Case B: Not compared - {failed_side} export failed: {reason}"
    if not comparison:
        return "Case E: Exports produced but no comparison result recorded"
    status = comparison.get("status")
    if status == "TABLE_MATCHED":
        return "Case A: Match (TABLES MATCHED)"
    if status != "TABLE_MISMATCHED":
        return (
            f"Case E: Not compared - status "
            f"{_safe(status, 'unreported')}"
        )
    parts = [
        "Case A: Mismatch",
        f"{_safe(comparison.get('source_row_count'))} source rows vs "
        f"{_safe(comparison.get('target_row_count'))} target rows",
    ]
    matched = comparison.get("matched_row_count")
    if matched is not None:
        parts.append(f"{matched} matched rows")
    if comparison.get("reason"):
        parts.append(_safe(comparison.get("reason")))
    cells = comparison.get("cell_mismatches") or []
    if cells:
        parts.append(f"{len(cells)} differing cell values")
    missing_cols = comparison.get("missing_columns_in_target") or []
    extra_cols = comparison.get("extra_columns_in_target") or []
    if missing_cols:
        parts.append(f"columns only in source: {', '.join(map(str, missing_cols))}")
    if extra_cols:
        parts.append(f"columns only in target: {', '.join(map(str, extra_cols))}")
    missing_rows = comparison.get("missing_rows_in_target") or []
    extra_rows = comparison.get("extra_rows_in_target") or []
    if missing_rows:
        parts.append(f"{len(missing_rows)} rows only in source")
    if extra_rows:
        parts.append(f"{len(extra_rows)} rows only in target")
    return " | ".join(parts)


def _comparison_details(comparison: dict | None) -> str:
    """Details for a table comparison whose exports were not recorded."""
    if not comparison:
        return _NOT_AVAILABLE
    parts = [f"Recorded status: {_safe(comparison.get('status'))}"]
    if comparison.get("reason"):
        parts.append(_safe(comparison.get("reason")))
    source_rows = comparison.get("source_row_count")
    target_rows = comparison.get("target_row_count")
    if source_rows is not None or target_rows is not None:
        parts.append(f"{_safe(source_rows)} source rows vs {_safe(target_rows)} target rows")
    matched = comparison.get("matched_row_count")
    if matched is not None:
        parts.append(f"{matched} matched rows")
    cells = comparison.get("cell_mismatches") or []
    if cells:
        parts.append(f"{len(cells)} differing cell values")
    missing_cols = comparison.get("missing_columns_in_target") or []
    extra_cols = comparison.get("extra_columns_in_target") or []
    if missing_cols:
        parts.append(f"columns only in source: {', '.join(map(str, missing_cols))}")
    if extra_cols:
        parts.append(f"columns only in target: {', '.join(map(str, extra_cols))}")
    missing_rows = comparison.get("missing_rows_in_target")
    extra_rows = comparison.get("extra_rows_in_target")
    if isinstance(missing_rows, list) and missing_rows:
        parts.append(f"{len(missing_rows)} rows only in source")
    if isinstance(extra_rows, list) and extra_rows:
        parts.append(f"{len(extra_rows)} rows only in target")
    return " | ".join(parts)


def _export_result(
    source_export: dict | None,
    target_export: dict | None,
    comparison: dict | None,
) -> str:
    source_ok = bool(
        source_export and source_export.get("status") in ("downloaded", "success")
    )
    target_ok = bool(
        target_export and target_export.get("status") in ("downloaded", "success")
    )
    if source_ok and target_ok:
        if not comparison:
            return _UNCERTAIN
        return _status_label(comparison.get("status"), comparison.get("reason"))
    # An export that never happened means the comparison never ran, so the
    # result is unavailable rather than failed.
    return _NOT_AVAILABLE_LABEL


def _build_export_model(pages: list[PagePair]) -> dict:
    rows: list[list[str]] = []

    for page in pages:
        comparison = page.comparison or {}
        tables = comparison.get("tables") or {}
        comparisons = (
            tables.get("comparisons") or []
            if isinstance(tables, dict)
            else []
        )
        comparison_by_table: dict[str, dict] = {}
        for item in comparisons:
            for key in (
                _table_pairing_key(item),
                _normalise_table_title(item.get("source_table")),
                _normalise_table_title(item.get("target_table")),
            ):
                if key and key != "n/a":
                    comparison_by_table.setdefault(key, item)

        visual_data_source = page.source.get("visual_data") or {}
        visual_data_target = page.target.get("visual_data") or {}
        source_exports = visual_data_source.get("table_exports") or []
        target_exports = visual_data_target.get("table_exports") or []
        source_table_visuals = visual_data_source.get("table_visuals") or []
        target_table_visuals = visual_data_target.get("table_visuals") or []

        display_title_by_key: dict[str, str] = {}
        dom_detected_keys: set[str] = set()
        for visual in [*source_table_visuals, *target_table_visuals]:
            key = _table_pairing_key(visual)
            if key:
                dom_detected_keys.add(key)
                display_title_by_key.setdefault(key, _safe(visual.get("title")))
        for export in [*source_exports, *target_exports]:
            key = _table_pairing_key(export)
            if key:
                display_title_by_key.setdefault(key, _safe(export.get("title")))

        titles = sorted(set(display_title_by_key) | set(comparison_by_table))

        if not titles:
            rows.append(
                [
                    f"{page.page_name}: No table or matrix visual detected",
                    _NOT_AVAILABLE_LABEL,
                    "Case D: No table/matrix visual detected on either report - "
                    "cannot compare exports",
                ]
            )
            continue

        for title in titles:
            source_export = next(
                (
                    export
                    for export in source_exports
                    if _table_pairing_key(export) == title
                ),
                None,
            )
            target_export = next(
                (
                    export
                    for export in target_exports
                    if _table_pairing_key(export) == title
                ),
                None,
            )
            entry = comparison_by_table.get(title)
            dom_detected = title in dom_detected_keys
            name = _safe(
                (source_export or target_export or {}).get("title"),
            ) or display_title_by_key.get(title) or title
            validation = f"{page.page_name} / {name or title}"

            if entry and not (source_export or target_export):
                rows.append(
                    [
                        validation,
                        _status_label(entry.get("status"), entry.get("reason")),
                        _comparison_details(entry),
                    ]
                )
                continue

            details = _export_remarks(
                source_export,
                target_export,
                entry,
                dom_detected=dom_detected,
            )
            references = []
            if source_export:
                references.append(f"Source: {_export_reference(source_export)}")
            if target_export:
                references.append(f"Target: {_export_reference(target_export)}")
            if references:
                details = f"{details} | {' | '.join(references)}"
            rows.append(
                [
                    validation,
                    _export_result(source_export, target_export, entry),
                    details,
                ]
            )

    if not rows:
        rows.append(
            [
                "No table or matrix export validation recorded",
                _NOT_AVAILABLE_LABEL,
                "No page comparison captured for this run.",
            ]
        )
    return {"rows": rows}


# ---------------------------------------------------------------------------
# Mismatch report (section 7) - every recorded item, never dropped
# ---------------------------------------------------------------------------


def _status_cell(status, reason=None) -> str:
    """Raw recorded status next to its presentation label."""
    label = _status_label(status, reason)
    raw = str(status).strip() if status is not None else ""
    if not raw:
        return label
    return f"{raw} ({label})"


def _build_mismatch_model(response: dict) -> dict:
    mismatches = response.get("mismatches") or {}
    summary = mismatches.get("summary") or {}
    rows: list[list[str]] = []

    categories = (
        ("KPI", "kpis", "kpi_mismatch_count"),
        ("Visual", "visuals", "visual_mismatch_count"),
        ("Filter", "filters", "filter_mismatch_count"),
        ("Table visual", "table_visuals", "table_visual_mismatch_count"),
        ("Table cell", "table_cells", "table_cell_mismatch_count"),
        ("Browser metric", "browser_metrics", "browser_metric_mismatch_count"),
    )

    for category, key, _count_key in categories:
        for item in mismatches.get(key) or []:
            if not isinstance(item, dict):
                continue
            rows.append(_mismatch_row(category, item))

    # A category whose recorded count exceeds the recorded items still gets a
    # row, so the report never silently drops part of the summary.
    for category, _key, count_key in categories:
        listed = sum(1 for row in rows if row[0] == category)
        recorded = summary.get(count_key)
        try:
            recorded_count = int(recorded) if recorded is not None else None
        except (TypeError, ValueError):
            recorded_count = None
        if recorded_count is not None and recorded_count > listed:
            rows.append(
                [
                    category,
                    "Items not listed in the mismatch report",
                    _NOT_AVAILABLE,
                    _NOT_AVAILABLE,
                    _NOT_AVAILABLE,
                    f"Recorded count: {recorded_count}; "
                    f"{listed} item(s) present in the mismatch payload.",
                    _NOT_AVAILABLE,
                ]
            )

    if not rows:
        rows.append(
            [
                "All",
                "No mismatches recorded",
                _NOT_AVAILABLE,
                _NOT_AVAILABLE,
                "PASS (recorded items: 0)",
                "The mismatch report contains no items for this run.",
                _NOT_AVAILABLE,
            ]
        )

    return {
        "rows": rows,
        "notes": [_MISMATCH_TOTAL_NOTE],
    }


def _mismatch_row(category: str, item: dict) -> list[str]:
    status = item.get("status")
    reason = item.get("reason")
    name = _NOT_AVAILABLE
    source = _NOT_AVAILABLE
    target = _NOT_AVAILABLE
    extras: list[str] = []

    if category == "KPI":
        name = _safe(item.get("kpi") or item.get("name"))
        source = _values(item.get("source"))
        target = _values(item.get("target"))
    elif category == "Visual":
        name = _safe(item.get("visual") or item.get("name"))
        source = _values(item.get("source"))
        target = _values(item.get("target"))
    elif category == "Filter":
        name = _safe(
            item.get("filter_name") or item.get("name") or item.get("filter")
        )
        source = _values(item.get("source_selected", item.get("source")))
        target = _values(item.get("target_selected", item.get("target")))
    elif category == "Table visual":
        name = _safe(item.get("table_title") or item.get("title"))
        source_rows = item.get("source_row_count")
        target_rows = item.get("target_row_count")
        source = f"{source_rows} rows" if source_rows is not None else _NOT_AVAILABLE
        target = f"{target_rows} rows" if target_rows is not None else _NOT_AVAILABLE
        if item.get("missing_columns_in_target"):
            extras.append(
                "columns only in source: "
                + ", ".join(map(str, item["missing_columns_in_target"]))
            )
        if item.get("extra_columns_in_target"):
            extras.append(
                "columns only in target: "
                + ", ".join(map(str, item["extra_columns_in_target"]))
            )
        missing_count = item.get("missing_rows_in_target_count")
        if missing_count:
            extras.append(f"{missing_count} rows only in source")
        extra_count = item.get("extra_rows_in_target_count")
        if extra_count:
            extras.append(f"{extra_count} rows only in target")
    elif category == "Table cell":
        table_title = _safe(item.get("table_title"))
        row_identifier = _safe(item.get("row_identifier"))
        column = _safe(item.get("column"))
        name = f"{table_title} | row {row_identifier} | column {column}"
        source = _values(item.get("source_value"))
        target = _values(item.get("target_value"))
        extras.append(f"Table: {table_title}")
    else:
        name = _safe(
            item.get("name") or item.get("metric") or item.get("label") or item.get("key")
        )
        source = _values(item.get("source", item.get("value")))
        target = _values(item.get("target"))

    if reason:
        extras.append(_safe(reason))
    details = f"Recorded status: {_safe(status, _NOT_AVAILABLE)}"
    if extras:
        details = f"{details} | {' | '.join(extras)}"

    return [
        category,
        name,
        source,
        target,
        _status_cell(status, reason),
        details,
        _confidence(item.get("confidence")),
    ]


# ---------------------------------------------------------------------------
# Summary / breakdown (section 8)
# ---------------------------------------------------------------------------


def _build_summary_model(response: dict, counts: dict, overall: str) -> dict:
    comparison = response.get("comparison") or {}
    summary = comparison.get("summary") or {}
    page_comparisons = comparison.get("page_comparisons") or []

    compared_tables = match_tables = mismatch_tables = 0
    for page in page_comparisons:
        tables = page.get("tables") or {}
        compared_tables += int(tables.get("compared_table_count") or 0)
        match_tables += int(tables.get("match_count") or 0)
        mismatch_tables += int(tables.get("mismatch_count") or 0)
    if not page_comparisons and isinstance(comparison.get("tables"), dict):
        tables = comparison.get("tables") or {}
        compared_tables = int(tables.get("compared_table_count") or 0)
        match_tables = int(tables.get("match_count") or 0)
        mismatch_tables = int(tables.get("mismatch_count") or 0)

    rows = [
        ("Comparison status", _safe(comparison.get("status"))),
        ("Comparison reason", _safe(comparison.get("reason"))),
        ("Filter match percentage", _pct(summary.get("filter_match_percentage"))),
        ("KPI match percentage", _pct(summary.get("kpi_match_percentage"))),
        ("Visual match percentage", _pct(summary.get("visual_match_percentage"))),
        ("Button match percentage", _pct(summary.get("button_match_percentage"))),
        ("Overall match percentage", _pct(summary.get("overall_match_percentage"))),
        ("Filters compared", _yes_no(summary.get("filter_compared"))),
        ("KPIs compared", _yes_no(summary.get("kpi_compared"))),
        ("Visuals compared", _yes_no(summary.get("visual_compared"))),
        ("Checks counted in this report", str(counts["total"])),
        ("Matched", str(counts["matched"])),
        ("Mismatched", str(counts["mismatched"])),
        ("Uncertain", str(counts["uncertain"])),
        ("Not available", str(counts["unavailable"])),
        ("Tables compared", str(compared_tables)),
        ("Tables matched", str(match_tables)),
        ("Tables mismatched", str(mismatch_tables)),
        ("Overall result", overall),
    ]

    page_rows: list[list[str]] = []
    for page in page_comparisons:
        page_counts = {"total": 0, "matched": 0, "mismatched": 0,
                       "uncertain": 0, "unavailable": 0}
        for kind in _CHECKS:
            for item in page.get(kind) or []:
                if not isinstance(item, dict):
                    continue
                label = _status_label(item.get("status"), item.get("reason"))
                page_counts["total"] += 1
                if label == _PASS:
                    page_counts["matched"] += 1
                elif label == _FAIL:
                    page_counts["mismatched"] += 1
                elif label == _UNCERTAIN:
                    page_counts["uncertain"] += 1
                else:
                    page_counts["unavailable"] += 1
        tables = page.get("tables") or {}
        for item in tables.get("comparisons") or []:
            if not isinstance(item, dict):
                continue
            label = _status_label(item.get("status"), item.get("reason"))
            page_counts["total"] += 1
            if label == _PASS:
                page_counts["matched"] += 1
            elif label == _FAIL:
                page_counts["mismatched"] += 1
            elif label == _UNCERTAIN:
                page_counts["uncertain"] += 1
            else:
                page_counts["unavailable"] += 1
        page_summary = page.get("summary") or {}
        page_rows.append(
            [
                _safe(page.get("page_name")),
                str(page_counts["total"]),
                str(page_counts["matched"]),
                str(page_counts["mismatched"]),
                str(page_counts["uncertain"]),
                str(page_counts["unavailable"]),
                _pct(
                    page.get("match_percentage")
                    if page.get("match_percentage") is not None
                    else page_summary.get("overall_match_percentage")
                ),
            ]
        )

    notes: list[str] = []
    if not page_rows:
        notes.append("No page comparison recorded for this run.")

    return {
        "rows": rows,
        "page_rows": page_rows,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Appendices
# ---------------------------------------------------------------------------


def _page_summary_text(page: PagePair) -> str:
    summary = (page.comparison or {}).get("summary") or {}
    percentage = summary.get("overall_match_percentage")
    if percentage is None:
        return "Not compared"
    return f"Overall match: {float(percentage):.2f}%"


def _build_screenshot_appendix(pages: list[PagePair]) -> list[dict]:
    entries = []
    for page in pages:
        if not page.source_image and not page.target_image:
            continue
        entries.append(
            {
                "page": page.page_name,
                "source_image": page.source_image,
                "target_image": page.target_image,
                "summary": _page_summary_text(page),
            }
        )
    return entries


def _ai_payload(ai: dict) -> dict:
    results = ai.get("results")
    if isinstance(results, dict):
        return results
    return ai.get("compare_status_payload") or {}


def _ai_summary_rows(ai: dict) -> list[list[str]]:
    payload = _ai_payload(ai)
    rows: list[list[str]] = []

    def add(label: str, value) -> None:
        if value in (None, "", _NOT_AVAILABLE):
            return
        rows.append([label, str(value)])

    add("Status", ai.get("status"))
    add("Reason / Error", ai.get("reason") or ai.get("error"))
    add("Job ID", ai.get("job_id"))
    uploaded = ai.get("uploaded") or {}
    if uploaded.get("source") is not None or uploaded.get("target") is not None:
        add(
            "Images uploaded (Source / Target)",
            f"{_safe(uploaded.get('source'), '0')} / "
            f"{_safe(uploaded.get('target'), '0')}",
        )
    add("Dashboard (per AI)", ai.get("dashboard_name"))
    add("Duration (seconds)", _seconds(ai.get("duration_seconds")))
    total = payload if ai.get("status") == "completed" else ai
    add("LLM calls", total.get("total_llm_calls"))
    add("Total tokens", total.get("total_tokens"))
    add("Total prompt tokens", total.get("total_prompt_tokens"))
    add("Total image tokens", total.get("total_image_tokens"))
    add("Total input tokens", total.get("total_input_tokens"))
    add("Total output tokens", total.get("total_output_tokens"))
    add("Total cost (USD)", total.get("total_cost_usd"))
    add("Total cost (INR)", total.get("total_cost_inr"))
    workbook = ai.get("workbook_available") or payload.get("workbook_available")
    add("Workbook available", "Yes" if workbook else None)
    add("Workbook download", ai.get("download_url") or payload.get("download_url"))
    add("JSON download", ai.get("json_download_url") or payload.get("json_download_url"))
    return rows


def _ai_pairs_rows(pairs: list) -> list[list[str]]:
    return [
        [
            _safe(pair.get("pair")),
            _safe(pair.get("spartnash_title")),
            _safe(pair.get("trendence_title")),
            _safe(pair.get("total_items")),
            _safe(pair.get("matches")),
            _safe(pair.get("differences")),
            _safe(pair.get("spartnash_only")),
            _safe(pair.get("trendence_only")),
            _safe(pair.get("uncertain")),
            (
                f"{float(pair.get('match_percentage')) * 100:.1f}%"
                if pair.get("match_percentage") is not None
                else _NOT_AVAILABLE
            ),
        ]
        for pair in pairs
    ]


_IMAGE_STAT_LABELS = (
    ("folder", "Folder"),
    ("image", "Image"),
    ("width", "Width (px)"),
    ("height", "Height (px)"),
    ("prompt_tokens", "Prompt tokens"),
    ("image_input_tokens", "Image input tokens"),
    ("input_tokens", "Input tokens"),
    ("output_tokens", "Output tokens"),
    ("total_tokens", "Total tokens"),
    ("total_cost_usd", "Cost (USD)"),
    ("total_cost_inr", "Cost (INR)"),
    ("llm_calls", "LLM calls"),
)


def _build_ai_appendix(ai_analysis: dict) -> dict:
    if not ai_analysis:
        return {"summary_rows": [], "image_stats": []}
    payload = _ai_payload(ai_analysis)
    image_stats = payload.get("image_stats")
    if not isinstance(image_stats, list):
        image_stats = []
    return {
        "summary_rows": _ai_summary_rows(ai_analysis),
        "image_stats": image_stats,
    }


# ---------------------------------------------------------------------------
# DOCX layout primitives
# ---------------------------------------------------------------------------

_COVER_WIDTHS = [2.1, 4.4]
_EXEC_SUMMARY_WIDTHS = [4.2, 2.3]
_CATEGORY_WIDTHS = [4.5, 2.0]
_EXECUTION_WIDTHS = [2.3, 4.2]
_BREAKDOWN_WIDTHS = [3.6, 2.9]
_SIGN_OFF_WIDTHS = [2.0, 4.5]
_AI_SUMMARY_WIDTHS = [3.2, 3.3]
_IMAGE_STAT_WIDTHS = [2.6, 3.9]

_REFRESH_HEADERS = ["Validation", "Source", "Target", "Result", "Details"]
_REFRESH_WIDTHS = [1.4, 1.2, 1.2, 1.0, 1.7]

_RUNTIME_HEADERS = [
    "#",
    "Filter / Slicer",
    "Source Value",
    "Target Value",
    "Source Applied",
    "Target Applied",
    "Source Render",
    "Target Render",
    "Render Time (s)",
    "Result",
]
_RUNTIME_WIDTHS = [0.4, 1.6, 1.05, 1.05, 0.9, 0.9, 0.95, 0.95, 1.1, 0.9]

_DOM_HEADERS = [
    "Page",
    "Filter",
    "Source Value",
    "Target Value",
    "Status",
    "Result",
    "Details",
]
_DOM_WIDTHS = [1.3, 1.5, 1.4, 1.4, 1.2, 0.9, 2.1]

_VISUAL_HEADERS = [
    "Visual / KPI",
    "Source",
    "Target",
    "Status",
    "Result",
    "Confidence",
    "Details",
]
_VISUAL_WIDTHS = [2.3, 1.3, 1.3, 1.4, 0.9, 0.8, 1.8]

_AI_PAIRS_HEADERS = [
    "Pair",
    "Source Title",
    "Target Title",
    "Total Items",
    "Matches",
    "Differences",
    "Source-only",
    "Target-only",
    "Uncertain",
    "Match %",
]
_AI_PAIRS_WIDTHS = [0.8, 1.4, 1.4, 0.8, 0.7, 0.8, 1.0, 1.0, 0.9, 1.0]

_EXPORT_HEADERS = ["Validation", "Result", "Details"]
_EXPORT_WIDTHS = [3.2, 1.4, 5.2]

_MISMATCH_HEADERS = [
    "Category",
    "Item",
    "Source",
    "Target",
    "Status",
    "Details",
    "Confidence",
]
_MISMATCH_WIDTHS = [1.1, 2.1, 1.2, 1.2, 1.1, 2.5, 0.6]

_BREAKDOWN_PAGE_HEADERS = [
    "Page",
    "Checks",
    "Matched",
    "Mismatched",
    "Uncertain",
    "Not available",
    "Match %",
]
_BREAKDOWN_PAGE_WIDTHS = [1.4, 0.7, 0.85, 1.0, 0.9, 0.9, 0.75]

_GRAY = RGBColor(0x59, 0x59, 0x59)
_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
_ACCENT = RGBColor(0x1F, 0x38, 0x64)


def _shade_cell(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def _repeat_header(row) -> None:
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    properties.append(header)


def _set_table_borders(table) -> None:
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "BFBFBF")
        borders.append(element)
    table._tbl.tblPr.append(borders)


def _status_color_for(text: str):
    stripped = str(text or "").strip().upper()
    if stripped in _STATUS_COLORS:
        return _STATUS_COLORS[stripped]
    for label, color in _STATUS_COLORS.items():
        if stripped.endswith(f"({label})"):
            return color
    return None


def _write_cell(
    cell,
    text: str,
    *,
    font_pt: float,
    bold: bool = False,
    color: RGBColor | None = None,
) -> None:
    cell.text = text
    for paragraph in cell.paragraphs:
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.space_before = Pt(0)
        for run in paragraph.runs:
            run.font.size = Pt(font_pt)
            if bold:
                run.bold = True
            if color is not None:
                run.font.color.rgb = color


def _add_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
    widths: list[float],
    *,
    status_columns: tuple[int, ...] = (),
    font_pt: float = _TABLE_FONT_PT,
    bold_first_column: bool = False,
) -> object:
    columns = len(headers)
    table = doc.add_table(rows=1, cols=columns)
    try:
        table.style = "Table Grid"
    except KeyError:
        _set_table_borders(table)
    table.autofit = False

    for index, text in enumerate(headers):
        cell = table.rows[0].cells[index]
        _write_cell(cell, str(text), font_pt=font_pt, bold=True, color=_WHITE)
        _shade_cell(cell, _HEADER_FILL)
    _repeat_header(table.rows[0])

    for row_index, row_values in enumerate(rows):
        cells = table.add_row().cells
        for index in range(columns):
            value = row_values[index] if index < len(row_values) else _NOT_AVAILABLE
            text = "" if value is None else str(value)
            status_color = (
                _status_color_for(text) if index in status_columns else None
            )
            emphasised = status_color is not None or (
                bold_first_column and index == 0
            )
            _write_cell(
                cells[index],
                text,
                font_pt=font_pt,
                bold=emphasised,
                color=status_color,
            )
        if row_index % 2 == 1:
            for cell in cells:
                _shade_cell(cell, _ALT_ROW_FILL)

    for row in table.rows:
        for index, width in enumerate(widths):
            if index < len(row.cells):
                row.cells[index].width = Inches(width)
    for index, width in enumerate(widths):
        if index < len(table.columns):
            table.columns[index].width = Inches(width)
    return table


def _add_kv_table(
    doc: Document,
    rows: list[tuple],
    widths: list[float],
    *,
    status_value: bool = True,
    font_pt: float = _BODY_FONT_PT,
    header: tuple[str, str] = ("Item", "Value"),
) -> object:
    data = [[str(label), str(value)] for label, value in rows]
    return _add_table(
        doc,
        list(header),
        data,
        widths,
        status_columns=(1,) if status_value else (),
        font_pt=font_pt,
        bold_first_column=True,
    )


def _add_heading(doc: Document, text: str, level: int = 1):
    paragraph = doc.add_heading(text, level=level)
    paragraph.paragraph_format.keep_with_next = True
    return paragraph


def _add_note(doc: Document, text: str, *, style: str | None = None) -> None:
    if style:
        try:
            doc.add_paragraph(text, style=style)
            return
        except KeyError:
            pass
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = _GRAY


def _add_notes(doc: Document, notes: list[str]) -> None:
    for note in notes or []:
        _add_note(doc, f"Note: {note}")


def _configure_styles(doc: Document) -> None:
    try:
        normal = doc.styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(_BODY_FONT_PT)
    except KeyError:
        pass
    for name, size, space_before in (
        ("Title", 26, 0),
        ("Heading 1", 15, 14),
        ("Heading 2", 11.5, 10),
    ):
        try:
            style = doc.styles[name]
        except KeyError:
            continue
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = _ACCENT
        style.paragraph_format.space_before = Pt(space_before)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.keep_with_next = True


def _configure_section(section, *, landscape: bool, margin_in: float) -> None:
    # US Letter, explicitly sized so the printable width stays predictable.
    if landscape:
        section.page_width = Inches(11)
        section.page_height = Inches(8.5)
        section.orientation = WD_ORIENT.LANDSCAPE
    else:
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.orientation = WD_ORIENT.PORTRAIT
    margin = Inches(margin_in)
    section.left_margin = margin
    section.right_margin = margin
    section.top_margin = margin
    section.bottom_margin = margin


def _add_field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    run.font.size = Pt(8)
    run.font.color.rgb = _GRAY
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    text = OxmlElement("w:instrText")
    text.set(qn("xml:space"), "preserve")
    text.text = f" {instruction} "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(text)
    run._r.append(end)


def _add_header_footer(section, run_id: str) -> None:
    header = section.header
    paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run(f"Dashboard Validation Report | Run {run_id}")
    run.italic = True
    run.font.size = Pt(8)
    run.font.color.rgb = _GRAY

    footer = section.footer
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("Viz Match automated validation  |  Page ")
    run.font.size = Pt(8)
    run.font.color.rgb = _GRAY
    _add_field(paragraph, "PAGE")
    run = paragraph.add_run(" of ")
    run.font.size = Pt(8)
    run.font.color.rgb = _GRAY
    _add_field(paragraph, "NUMPAGES")


def _fit_image_size(
    image_path: Path,
    max_width_in: float,
    max_height_in: float,
) -> tuple[Inches, Inches | None]:
    """Return an aspect-preserving image size that fits within the box.

    Falls back to max-width-only sizing when the pixel dimensions cannot be
    read (unknown format, unavailable PIL), which Word still renders without
    distortion because it derives the height from the width automatically.
    """
    try:
        from PIL import Image

        with Image.open(str(image_path)) as image:
            width_px, height_px = image.size
    except Exception:
        logger.debug(
            "Image dimensions unavailable; using width-only sizing | path=%s",
            image_path,
        )
        return Inches(max_width_in), None

    if width_px <= 0 or height_px <= 0:
        return Inches(max_width_in), None

    scale = min(
        max_width_in / width_px,
        max_height_in / height_px,
    )
    return Inches(width_px * scale), Inches(height_px * scale)


def _add_image(
    doc: Document,
    image_path: Path,
    max_width_in: float = _SCREENSHOT_PAGE_WIDTH_IN,
    max_height_in: float = _SCREENSHOT_PAGE_MAX_HEIGHT_IN,
) -> None:
    if not image_path or not Path(image_path).is_file():
        return
    try:
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        width, height = _fit_image_size(Path(image_path), max_width_in, max_height_in)
        run.add_picture(str(image_path), width=width, height=height)
    except Exception:
        logger.exception("Failed to embed screenshot | path=%s", image_path)


# ---------------------------------------------------------------------------
# Render: report model -> DOCX
# ---------------------------------------------------------------------------


def _render(
    run_id: str,
    document: dict,
    metrics_doc: dict,
    response: dict,
    run_status: dict,
    destination: Path | None,
) -> Path:
    model = _build_report_model(document, metrics_doc, response, run_status)
    report_name = model["report_name"]

    doc = Document()
    _configure_styles(doc)
    _configure_section(
        doc.sections[0], landscape=False, margin_in=_PORTRAIT_MARGIN_IN
    )
    _add_header_footer(doc.sections[0], run_id)

    # ---- cover -----------------------------------------------------------
    metadata = model["report_metadata"]
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(metadata["title"])
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_run = subtitle.add_run(metadata["subtitle"])
    subtitle_run.italic = True
    subtitle_run.font.size = Pt(11)
    subtitle_run.font.color.rgb = _GRAY
    doc.add_paragraph()
    _add_kv_table(doc, metadata["rows"], _COVER_WIDTHS)
    _add_note(
        doc,
        "Generated from the persisted run artifacts. Fields the capture did "
        "not record are reported as Not Available.",
    )
    doc.add_page_break()

    # ---- 1. Executive Summary --------------------------------------------
    executive = model["executive_summary"]
    _add_heading(doc, "1. Executive Summary", 1)
    _add_kv_table(doc, executive["rows"], _EXEC_SUMMARY_WIDTHS)
    _add_heading(doc, "1.1 Mismatch report counts (as recorded)", 2)
    _add_kv_table(
        doc,
        executive["category_rows"],
        _CATEGORY_WIDTHS,
        status_value=False,
        font_pt=_TABLE_FONT_PT,
    )
    _add_notes(doc, executive["notes"])

    # ---- 2. Execution Details --------------------------------------------
    _add_heading(doc, "2. Execution Details", 1)
    _add_kv_table(doc, model["execution_context"]["rows"], _EXECUTION_WIDTHS)

    # ---- 3. Refresh Validation --------------------------------------------
    refresh = model["refresh_validation"]
    _add_heading(doc, "3. Refresh Validation", 1)
    _add_table(
        doc,
        _REFRESH_HEADERS,
        refresh["rows"],
        _REFRESH_WIDTHS,
        status_columns=(3,),
    )
    _add_notes(doc, refresh["notes"])

    # ---- 4-7 in a landscape section ---------------------------------------
    _configure_section(
        doc.add_section(WD_SECTION.NEW_PAGE),
        landscape=True,
        margin_in=_LANDSCAPE_MARGIN_IN,
    )

    filter_model = model["filter_validation"]
    _add_heading(doc, "4. Filter / Slicer Validation", 1)
    _add_heading(doc, "4.1 Runtime slicer evidence", 2)
    _add_table(
        doc,
        _RUNTIME_HEADERS,
        filter_model["runtime_rows"],
        _RUNTIME_WIDTHS,
        status_columns=(9,),
    )
    _add_notes(doc, filter_model["runtime_notes"])

    _add_heading(doc, "4.2 DOM filter-state comparison", 2)
    _add_table(
        doc,
        _DOM_HEADERS,
        filter_model["dom_rows"],
        _DOM_WIDTHS,
        status_columns=(5,),
    )
    _add_notes(doc, filter_model["dom_notes"])

    visual_model = model["visual_functional_validation"]
    _add_heading(doc, "5. Visual / Functional Validation", 1)
    _add_table(
        doc,
        _VISUAL_HEADERS,
        visual_model["rows"],
        _VISUAL_WIDTHS,
        status_columns=(4,),
    )
    _add_notes(doc, visual_model["notes"])
    if visual_model.get("ai_pairs_rows"):
        _add_heading(doc, "5.1 AI visual comparison (Gemini)", 2)
        _add_table(
            doc,
            _AI_PAIRS_HEADERS,
            visual_model["ai_pairs_rows"],
            _AI_PAIRS_WIDTHS,
            font_pt=7.5,
        )

    export_model = model["data_export_validation"]
    _add_heading(doc, "6. Data Export Validation", 1)
    _add_table(
        doc,
        _EXPORT_HEADERS,
        export_model["rows"],
        _EXPORT_WIDTHS,
        status_columns=(1,),
    )

    mismatch_model = model["mismatch_report"]
    _add_heading(doc, "7. Mismatch Report", 1)
    _add_table(
        doc,
        _MISMATCH_HEADERS,
        mismatch_model["rows"],
        _MISMATCH_WIDTHS,
        status_columns=(4,),
    )
    _add_notes(doc, mismatch_model["notes"])

    # ---- 8-9 and appendices, back to portrait -----------------------------
    _configure_section(
        doc.add_section(WD_SECTION.NEW_PAGE),
        landscape=False,
        margin_in=_PORTRAIT_MARGIN_IN,
    )

    summary_model = model["summary"]
    _add_heading(doc, "8. Validation Breakdown", 1)
    _add_kv_table(doc, summary_model["rows"], _BREAKDOWN_WIDTHS)
    if summary_model["page_rows"]:
        _add_heading(doc, "8.1 Per-page breakdown", 2)
        _add_table(
            doc,
            _BREAKDOWN_PAGE_HEADERS,
            summary_model["page_rows"],
            _BREAKDOWN_PAGE_WIDTHS,
            status_columns=(),
            font_pt=_TABLE_FONT_PT,
        )
    _add_notes(doc, summary_model["notes"])

    _add_heading(doc, "9. Sign-off", 1)
    _add_kv_table(doc, model["sign_off"]["rows"], _SIGN_OFF_WIDTHS)

    # ---- Appendix A: page screenshots -------------------------------------
    doc.add_page_break()
    _add_heading(doc, "Appendix A: Page Screenshots", 1)
    screenshots = model["appendix_screenshots"]
    if not screenshots:
        _add_note(
            doc,
            "No page screenshot was recorded for this run (Not Available).",
        )
    for index, entry in enumerate(screenshots, start=1):
        _add_heading(doc, f"A.{index} {entry['page']} - {entry['summary']}", 2)
        if entry["source_image"]:
            _add_note(doc, f"Source: {model['report_name']}")
            _add_image(doc, entry["source_image"])
        if entry["target_image"]:
            _add_note(doc, "Target dashboard")
            _add_image(doc, entry["target_image"])
        if not entry["source_image"] and not entry["target_image"]:
            _add_note(doc, "No screenshot file resolved for this page.")

    # ---- Appendix B: AI telemetry -----------------------------------------
    doc.add_page_break()
    _add_heading(doc, "Appendix B: AI Validation Telemetry", 1)
    ai_appendix = model["appendix_ai"]
    if not ai_appendix["summary_rows"]:
        _add_note(doc, "No AI validation telemetry recorded for this run.")
    else:
        _add_kv_table(
            doc,
            ai_appendix["summary_rows"],
            _AI_SUMMARY_WIDTHS,
            status_value=False,
            font_pt=_TABLE_FONT_PT,
        )
    for index, stats in enumerate(ai_appendix["image_stats"], start=1):
        folder = str((stats or {}).get("folder") or "").strip()
        image = str((stats or {}).get("image") or "").strip()
        title = (
            f"{folder} / {image}"
            if folder and image
            else image or folder or f"Image {index}"
        )
        _add_heading(doc, f"B.{index} {title}", 2)
        rows = []
        for key, label in _IMAGE_STAT_LABELS:
            value = (stats or {}).get(key)
            if value is None:
                continue
            if key in ("width", "height"):
                continue
            rows.append((label, value))
        width = (stats or {}).get("width")
        height = (stats or {}).get("height")
        if width is not None and height is not None:
            rows.insert(2, ("Dimensions", f"{width} x {height}"))
        if rows:
            _add_kv_table(
                doc,
                rows,
                _IMAGE_STAT_WIDTHS,
                status_value=False,
                font_pt=_TABLE_FONT_PT,
            )

    # ---- Appendix C: notes -------------------------------------------------
    doc.add_page_break()
    _add_heading(doc, "Appendix C: Notes", 1)
    notes = model["notes"]
    if not notes:
        _add_note(doc, "No additional notes recorded for this run.")
    for note in notes:
        _add_note(doc, note, style="List Bullet")

    destination = destination or (
        REPORT_DIR / run_id / report_filename(run_id, report_name)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc.save(str(destination))
    except Exception as exc:
        raise ValidationReportError(
            f"Failed to save DOCX report to {destination}"
        ) from exc

    logger.info(
        "PBI validation report generated | run_id=%s | checks=%d | "
        "mismatch_rows=%d | filter_rows=%d | overall=%s | path=%s",
        run_id,
        model["counts"]["total"],
        len(mismatch_model["rows"]),
        len(filter_model["runtime_rows"]) + len(filter_model["dom_rows"]),
        model["overall"],
        destination,
    )
    return destination


async def build_validation_report(
    run_id: str,
    *,
    destination: Path | None = None,
) -> Path:
    """Generate the automated PBI validation DOCX for a persisted run.

    Operates entirely from the persisted artifacts:
    ``load_validation_capture`` + ``load_run_status`` + the pure-compute
    validation response. No browser, no LLM, no Power BI export, no DOM
    extraction, and no new AI call is made for the report.

    Raises ``ValidationReportNotFound`` when no capture exists for run_id.
    """
    document = load_validation_capture(run_id)
    if document is None:
        raise ValidationReportNotFound(
            f"No validation capture found for run_id {run_id}."
        )
    metrics_doc = load_browser_metrics(run_id) or {}
    run_status = load_run_status(run_id) or {}

    from orchestration.validator import DashboardValidator

    validator = DashboardValidator()
    response = await validator.run_validation_from_artifacts(run_id)
    if response is None:
        raise ValidationReportNotFound(
            f"No validation capture found for run_id {run_id}."
        )

    return await asyncio.to_thread(
        _render,
        run_id,
        document,
        metrics_doc,
        response,
        run_status,
        destination,
    )
