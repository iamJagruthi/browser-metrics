"""
table_exporter.py

Service responsible only for exporting Power BI table and matrix visuals.
This module does NOT launch browsers, navigate dashboards, or use Gemini AI.
"""

from __future__ import annotations

import csv
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from utils.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

VISUAL_SELECTOR = ".visualContainer, [data-visual-container]"
MAX_EXPORT_RETRIES = 3
MENU_TIMEOUT = 8_000
DOWNLOAD_TIMEOUT = 30_000

EXPORT_DIR = OUTPUT_DIR / "table_exports"
RAW_DIR = EXPORT_DIR / "raw"


class TableExporter:

    def __init__(self, page, output_dir: str | Path = EXPORT_DIR):
        self.page = page
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def export_table_visual(
        self,
        locator,
        visual_metadata: dict[str, Any],
        dashboard_name: str,
    ) -> dict[str, Any]:
        """Export one already-identified Power BI table or matrix visual."""
        title = (
            visual_metadata.get("title")
            or f"table_visual_{visual_metadata.get('index', 'unknown')}"
        )

        logger.info("Starting table export | dashboard=%s | title=%s", dashboard_name, title)

        result = {
            "title": title,
            "visual_id": visual_metadata.get("id"),
            "index": visual_metadata.get("index"),
            "is_table": visual_metadata.get("is_table", False),
            "is_matrix": visual_metadata.get("is_matrix", False),
            "status": "not_exported",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "file_path": None,
            "error": None,
        }

        try:
            export_path = await self._export_visual_data(
                locator=locator,
                title=title,
                dashboard_name=dashboard_name,
            )

            if not export_path:
                result["status"] = "export_failed"
                result["error"] = "Power BI export did not produce a file."
                return result

            result["file_path"] = str(export_path)
            parsed_data = _read_export(export_path)

            result["columns"] = parsed_data.get("columns", [])
            result["rows"] = parsed_data.get("rows", [])
            result["row_count"] = len(result["rows"])
            result["status"] = "success"

            return result

        except Exception as exc:
            logger.exception("Table export failed | title=%s", title)
            result["status"] = "failed"
            result["error"] = str(exc)
            return result


def _safe_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_.")
    return value or fallback


def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _read_export(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            values = list(csv.reader(handle))
    elif path.suffix.lower() in {".xlsx", ".xlsm"}:
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        values = [list(row) for row in sheet.iter_rows(values_only=True)]
        workbook.close()
    else:
        raise ValueError(f"Unsupported export format: {path.suffix}")

    values = [[_clean(v) for v in row] for row in values if any(_clean(v) for v in row)]

    if not values:
        return {"columns": [], "rows": [], "row_count": 0}

    width = max(len(row) for row in values)
    values = [row + [""] * (width - len(row)) for row in values]

    return {
        "columns": values[0],
        "rows": values[1:],
        "row_count": max(0, len(values) - 1),
    }


async def _close_open_overlays(page) -> None:
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)
    except Exception:
        pass


async def _get_visual_locator(page, visual: dict[str, Any]):
    visuals = page.locator(VISUAL_SELECTOR)
    aria_label = _clean(visual.get("aria_label"))
    visual_type = _clean(visual.get("visual_type"))

<<<<<<< Updated upstream
    rows = tuple(
        tuple(
            _clean(value).casefold()
            for value in row
        )
        for row in table.get(
            "rows",
            [],
        )
    )

    return (columns,) + rows


 
# ---------------------------------------------------------------------------
# Visual detection
# ---------------------------------------------------------------------------
# NOTE:
# This function is retained for debugging/backward compatibility.
#
# Normal project flow does NOT call this function.
#
# Table/Matrix detection is performed by:
# services/visual_data_exporter.py
#
# Detected table metadata is then passed to:
# export_table_visuals()

 
# ---------------------------------------------------------------------------
# Visual lookup
# ---------------------------------------------------------------------------

async def _get_visual_locator(
    page,
    visual: dict[str, Any],
):
    """
    Re-find the visual every time.

    Power BI frequently rebuilds visual DOM nodes,
    so retaining an old locator can result in:

        element was detached from the DOM
    """

    visuals = page.locator(
        VISUAL_SELECTOR
    )

    aria_label = _clean(
        visual.get("aria_label")
    )

    visual_type = _clean(
        visual.get("visual_type")
    )

    # First try to locate using aria-label + role.
=======
>>>>>>> Stashed changes
    if aria_label:
        for index in range(await visuals.count()):
            candidate = visuals.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                candidate_info = await candidate.evaluate(
                    """node => ({
                        ariaLabel: (node.getAttribute("aria-label") || "").trim(),
                        ariaRole: (node.getAttribute("aria-roledescription") || "").trim()
                    })"""
                )
                if _clean(candidate_info["ariaLabel"]) == aria_label and (
                    not visual_type or _clean(candidate_info["ariaRole"]).casefold() == visual_type.casefold()
                ):
                    return candidate
            except Exception:
                continue

    original_index = visual.get("index")
    if original_index is not None and original_index < await visuals.count():
        return visuals.nth(original_index)

    return None


async def _open_more_options(page, visual: dict[str, Any]) -> bool:
    for attempt in range(1, MAX_EXPORT_RETRIES + 1):
        try:
            await _close_open_overlays(page)
            locator = await _get_visual_locator(page, visual)
            if locator is None:
                continue

            try:
                await locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            await page.wait_for_timeout(300)
            locator = await _get_visual_locator(page, visual)
            if locator is None:
                continue

            try:
                await locator.hover(timeout=3000)
            except Exception:
                await locator.hover(timeout=3000, force=True)

            await page.wait_for_timeout(500)
            locator = await _get_visual_locator(page, visual)
            if locator is None:
                continue

            menu = locator.locator(
                "button[data-testid='visual-more-options-btn'], "
                "button[aria-label='More options'], "
                "[role='button'][aria-label='More options']"
            ).first

            if await menu.count() == 0:
                continue

            try:
                await menu.click(timeout=3000)
            except Exception:
                await menu.click(timeout=3000, force=True)

            try:
                await page.get_by_role("menu").wait_for(state="visible", timeout=MENU_TIMEOUT)
            except Exception:
                await page.wait_for_timeout(500)

            return True
        except Exception:
            await _close_open_overlays(page)
            await page.wait_for_timeout(500)

    return False


async def _find_export_data_item(page):
    try:
        item = page.get_by_role("menuitem", name=re.compile(r"^\s*export data\s*$", re.I)).first
        if await item.count() > 0:
            return item
    except Exception:
        pass

    try:
        item = page.get_by_text(re.compile(r"^\s*export data\s*$", re.I)).first
        if await item.count() > 0:
            return item
    except Exception:
        pass

    return None


async def _handle_export_dialog(page) -> dict[str, Any]:
    dialog = None
    try:
        candidate = page.get_by_role("dialog").filter(
            has_text=re.compile(r"which data do you want to export", re.I)
        ).first
        if await candidate.count() > 0 and await candidate.is_visible():
            dialog = candidate
    except Exception:
        pass

    if dialog is None:
        return {"data_type": "full", "option": "direct_export", "note": "Full data export successful."}

    current_layout = dialog.get_by_text(re.compile(r"^\s*data with current layout\s*$", re.I)).first
    if await current_layout.count() > 0:
        try:
            await current_layout.click(timeout=3000)
        except Exception:
            await current_layout.click(timeout=3000, force=True)

        export_button = dialog.get_by_role("button", name=re.compile(r"^\s*export\s*$", re.I)).first
        if await export_button.count() == 0:
            export_button = dialog.get_by_text(re.compile(r"^\s*export\s*$", re.I)).last

        return {
            "data_type": "full",
            "option": "Data with current layout",
            "export_button": export_button,
        }

    summarized = dialog.get_by_text(re.compile(r"^\s*summarized data\s*$", re.I)).first
    if await summarized.count() > 0:
        try:
            await summarized.click(timeout=3000)
        except Exception:
            await summarized.click(timeout=3000, force=True)

        export_button = dialog.get_by_role("button", name=re.compile(r"^\s*export\s*$", re.I)).first
        return {
            "data_type": "summarized",
            "option": "Summarized data",
            "export_button": export_button,
        }

    raise RuntimeError("Neither 'Data with current layout' nor 'Summarized data' could be selected.")


async def _export_visual(
    page,
    visual: dict[str, Any],
    dashboard_name: str,
) -> dict[str, Any]:
    result = {
        "title": visual["title"],
        "visual_index": visual.get("index"),
        "status": "failed",
        "file_path": None,
        "data": None,
        "error": None,
        "validation_data_type": "unavailable",
        "validation_option": None,
        "validation_note": None,
    }

    last_error = None

    for attempt in range(1, MAX_EXPORT_RETRIES + 1):
        if not page or page.is_closed():
            logger.error("Target page closed before export attempt. Aborting.")
            last_error = "Target page closed."
            break

        try:
            logger.info("Export attempt %s/%s | dashboard=%s | visual=%s", attempt, MAX_EXPORT_RETRIES, dashboard_name, visual["title"])

            opened = await _open_more_options(page, visual)
            if not opened:
                last_error = "Could not open More options."
                continue

            item = await _find_export_data_item(page)
            if item is None:
                last_error = "Export data menu item not found."
                await _close_open_overlays(page)
                continue

            RAW_DIR.mkdir(parents=True, exist_ok=True)

            # REGISTER DOWNLOAD HANDLER BEFORE CLICKING EXPORT
            async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                try:
                    await item.click(timeout=5000)
                except Exception:
                    await item.click(timeout=5000, force=True)

                await page.wait_for_timeout(500)
                export_info = await _handle_export_dialog(page)

                export_btn = export_info.get("export_button")
                if export_btn and await export_btn.count() > 0:
                    try:
                        await export_btn.click(timeout=5000)
                    except Exception:
                        await export_btn.click(timeout=5000, force=True)

            download = await download_info.value
            suffix = Path(download.suggested_filename).suffix or ".csv"
            filename = f"{_safe_filename(dashboard_name, 'dashboard')}_{_safe_filename(visual['title'], 'table')}_{uuid.uuid4().hex[:8]}{suffix}"
            path = RAW_DIR / filename

            await download.save_as(str(path))
            
            # Guard: Only wait if page is open
            if page and not page.is_closed():
                await page.wait_for_timeout(1000)

            data = _read_export(path)

            result.update(
                status="downloaded",
                file_path=str(path),
                data=data,
                validation_data_type=export_info.get("data_type", "unknown"),
                validation_option=export_info.get("option"),
            )

            logger.info("Export successful | dashboard=%s | visual=%s | rows=%d", dashboard_name, visual["title"], len(data.get("rows", [])))
            await _close_open_overlays(page)
            return result

        except Exception as exc:
            last_error = str(exc)
            logger.warning("Export attempt %s failed | visual=%s | error=%s", attempt, visual["title"], exc)

            if "TargetClosedError" in str(exc) or "browser has been closed" in str(exc):
                break

            try:
                await _close_open_overlays(page)
                await page.wait_for_timeout(750)
            except Exception:
                break

    result["error"] = last_error or "Export failed."
    return result


async def export_table_visuals(
    page,
    table_visuals: list[dict[str, Any]],
    dashboard_name: str,
) -> list[dict[str, Any]]:
    exported_tables: list[dict[str, Any]] = []

    if not table_visuals:
        return exported_tables

    for table_number, table_visual in enumerate(table_visuals, start=1):
        try:
            result = await _export_visual(page, table_visual, dashboard_name)
            exported_tables.append(result)
        except Exception as exc:
<<<<<<< Updated upstream

            logger.exception(
                "Unexpected table export failure | dashboard=%s | "
                "title=%s",
                dashboard_name,
                table_visual.get("title"),
            )

            exported_tables.append(
                {
                    "title": table_visual.get("title"),
                    "visual_index": table_visual.get("index"),
                    "status": "failed",
                    "file_path": None,
                    "data": None,
                    "error": str(exc),
                    "validation_data_type": "unavailable",
                    "validation_option": None,
                    "validation_note": None,
                }
            )

    successful = sum(
        1
        for item in exported_tables
        if item.get("status") == "downloaded"
    )

    failed = len(exported_tables) - successful

    logger.info(
        "Table export completed | dashboard=%s | "
        "successful=%d | failed=%d",
        dashboard_name,
        successful,
        failed,
    )

    return exported_tables

# Add this at the bottom of table_exporter.py

from services.table_comparison import build_table_comparisons
=======
            exported_tables.append({
                "title": table_visual.get("title"),
                "visual_index": table_visual.get("index"),
                "status": "failed",
                "file_path": None,
                "data": None,
                "error": str(exc),
                "validation_data_type": "unavailable",
            })

    return exported_tables
>>>>>>> Stashed changes
