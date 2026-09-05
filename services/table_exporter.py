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
from automation.canvas_diagnostics import measure_canvas, log_delta

logger = logging.getLogger(__name__)

VISUAL_SELECTOR = ".visualContainer, [data-visual-container]"
MAX_EXPORT_RETRIES = 3
MENU_TIMEOUT = 15_000
DOWNLOAD_TIMEOUT = 60_000

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


def _attach_lifecycle_diagnostics(page) -> None:
    """Attach one-time lifecycle diagnostics to identify premature closure."""
    try:
        if getattr(page, "_table_exporter_lifecycle_diagnostics_attached", False):
            return

        def _on_page_close() -> None:
            logger.error(
                "TABLE_EXPORT_LIFECYCLE | event=page_close | page_id=%s",
                id(page),
            )

        page.on("close", _on_page_close)

        try:
            context = page.context

            def _on_context_close() -> None:
                logger.error(
                    "TABLE_EXPORT_LIFECYCLE | event=context_close | page_id=%s | context_id=%s",
                    id(page),
                    id(context),
                )

            context.on("close", _on_context_close)
        except Exception:
            pass

        try:
            browser = page.context.browser
            if browser is not None:
                def _on_browser_disconnected() -> None:
                    logger.error(
                        "TABLE_EXPORT_LIFECYCLE | event=browser_disconnected | page_id=%s | browser_id=%s",
                        id(page),
                        id(browser),
                    )

                browser.on("disconnected", _on_browser_disconnected)
        except Exception:
            pass

        setattr(page, "_table_exporter_lifecycle_diagnostics_attached", True)
        logger.info(
            "TABLE_EXPORT_LIFECYCLE | event=diagnostics_attached | page_id=%s",
            id(page),
        )
    except Exception:
        logger.debug("Unable to attach table export lifecycle diagnostics", exc_info=True)


def _page_state(page) -> dict[str, Any]:
    """Return lifecycle state safely, including after closure."""
    state = {
        "page_id": id(page) if page is not None else None,
        "page_closed": None,
        "context_id": None,
        "browser_connected": None,
    }
    if page is None:
        return state

    try:
        state["page_closed"] = page.is_closed()
    except Exception:
        state["page_closed"] = True

    try:
        context = page.context
        state["context_id"] = id(context)
        try:
            browser = context.browser
            state["browser_connected"] = (
                browser.is_connected() if browser is not None else None
            )
        except Exception:
            state["browser_connected"] = False
    except Exception:
        state["context_id"] = None
        state["browser_connected"] = False

    return state


async def _get_visual_locator(page, visual: dict[str, Any]):
    visuals = page.locator(VISUAL_SELECTOR)
    aria_label = _clean(visual.get("aria_label"))
    title = _clean(visual.get("title"))
    visual_type = _clean(visual.get("visual_type"))

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
                    logger.info(
                        "_get_visual_locator | path=aria_label | title=%r | index=%s | matched=True",
                        visual.get("title"), visual.get("index"),
                    )
                    return candidate
            except Exception:
                continue

    # Fallback identity check: the DOM extractor does not currently populate
    # aria_label, so the block above never matches in production and this
    # function would otherwise fall straight through to a raw position index.
    # A position index is not stable across a Power BI DOM re-render (slicer
    # filtering, visual reflow, etc.), which risks opening the wrong visual's
    # menu. The visual's own displayed title is reliably populated instead,
    # so match on that before resorting to position.
    if title:
        for index in range(await visuals.count()):
            candidate = visuals.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                candidate_title = await candidate.evaluate(
                    """node => {
                        const el = node.querySelector(
                            '.visualTitle, [class*="visualTitle" i], [data-visual-title], [class*="title" i]'
                        );
                        return el ? el.textContent : "";
                    }"""
                )
                if _clean(candidate_title).casefold() == title.casefold():
                    logger.info(
                        "_get_visual_locator | path=title | title=%r | index=%s | matched=True",
                        visual.get("title"), visual.get("index"),
                    )
                    return candidate
            except Exception:
                continue

    original_index = visual.get("index")
    if original_index is not None and original_index < await visuals.count():
        logger.info(
            "_get_visual_locator | path=index | title=%r | index=%s | matched=True",
            visual.get("title"), visual.get("index"),
        )
        return visuals.nth(original_index)

    logger.info(
        "_get_visual_locator | path=none | title=%r | index=%s | matched=False",
        visual.get("title"), visual.get("index"),
    )
    return None

async def _open_more_options(page, visual: dict[str, Any]):
    for attempt in range(1, MAX_EXPORT_RETRIES + 1):
        try:
            await _close_open_overlays(page)

            locator = await _get_visual_locator(page, visual)
            if locator is None:
                continue

            _diag_before = await measure_canvas(page)
            try:
                await locator.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            _diag_after = await measure_canvas(page)
            log_delta(
                "table_exporter._open_more_options.scroll_into_view_if_needed",
                visual.get("title"),
                _diag_before,
                _diag_after,
            )

            await page.wait_for_timeout(300)

            locator = await _get_visual_locator(page, visual)
            if locator is None:
                continue

            _diag_before = await measure_canvas(page)
            try:
                await locator.hover(timeout=3000)
            except Exception:
                await locator.hover(timeout=3000, force=True)
            _diag_after = await measure_canvas(page)
            log_delta(
                "table_exporter._open_more_options.hover",
                visual.get("title"),
                _diag_before,
                _diag_after,
            )

            await page.wait_for_timeout(500)

            locator = await _get_visual_locator(page, visual)
            if locator is None:
                continue

            more_options_btn = locator.locator(
                "button[data-testid='visual-more-options-btn'], "
                "button[aria-label='More options'], "
                "[role='button'][aria-label='More options']"
            ).first

            more_options_count = await more_options_btn.count()
            logger.info(
                "_open_more_options | attempt=%s | title=%r | more_options_btn_count=%s",
                attempt, visual.get("title"), more_options_count,
            )

            # TEMPORARY DIAGNOSTICS ONLY
            page_more_options = page.locator(
                "[aria-label*='More options' i], "
                "[data-testid*='more-options' i], "
                "[role='button'][aria-label*='More options' i]"
            )
            logger.info(
                "_open_more_options | AFTER HOVER | "
                "inside_visual=%s | anywhere_page=%s",
                await more_options_btn.count(),
                await page_more_options.count(),
            )
            if await page_more_options.count() > 0:
                for i in range(await page_more_options.count()):
                    candidate = page_more_options.nth(i)
                    try:
                        logger.info(
                            "_open_more_options | page_more_options[%s] | visible=%s",
                            i,
                            await candidate.is_visible(),
                        )
                    except Exception:
                        pass
            # END TEMPORARY DIAGNOSTICS

            if more_options_count == 0:
                continue

            _diag_before = await measure_canvas(page)
            try:
                await more_options_btn.click(timeout=3000)
            except Exception:
                await more_options_btn.click(timeout=3000, force=True)
            _diag_after = await measure_canvas(page)
            log_delta(
                "table_exporter._open_more_options.more_options_click",
                visual.get("title"),
                _diag_before,
                _diag_after,
            )

            opened_menu = page.get_by_role("menu").first

            menu_timed_out = False
            try:
                await opened_menu.wait_for(
                    state="visible",
                    timeout=MENU_TIMEOUT,
                )
            except Exception:
                menu_timed_out = True
                await page.wait_for_timeout(500)

            menu_count = await opened_menu.count()
            menu_visible = await opened_menu.is_visible() if menu_count > 0 else False
            logger.info(
                "_open_more_options | attempt=%s | title=%r | menu_count=%s | menu_visible=%s | wait_for_timed_out=%s",
                attempt, visual.get("title"), menu_count, menu_visible, menu_timed_out,
            )

            return opened_menu

        except Exception:
            await _close_open_overlays(page)
            await page.wait_for_timeout(500)

    return None


async def _find_export_data_item(page):
    """Find the Power BI Export data command from the currently open menu.

    Power BI can render the More Options menu as an overlay outside the
    visual's DOM subtree, so this lookup intentionally searches the page.
    """
    try:
        item = page.get_by_role(
            "menuitem",
            name=re.compile(r"^\s*export data\s*$", re.I),
        ).first

        if await item.count() > 0:
            return item
    except Exception:
        pass

    try:
        item = page.get_by_text(
            re.compile(r"^\s*export data\s*$", re.I),
        ).first

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
        if await candidate.count() > 0:
            try:
                # Wait for the actual Power BI dialog state instead of relying
                # on a fixed post-click sleep. Direct-export flows simply time
                # out here and continue to the download event.
                await candidate.wait_for(state="visible", timeout=2_000)
                dialog = candidate
            except Exception:
                pass
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

    _attach_lifecycle_diagnostics(page)

    for attempt in range(1, MAX_EXPORT_RETRIES + 1):
        if not page or page.is_closed():
            logger.error("Target page closed before export attempt. Aborting.")
            last_error = "Target page closed."
            break

        try:
            logger.info(
                "Export attempt %s/%s | dashboard=%s | visual=%s",
                attempt,
                MAX_EXPORT_RETRIES,
                dashboard_name,
                visual["title"],
            )

            menu = await _open_more_options(page, visual)

            if menu is None:
                last_error = "Could not open More options."
                logger.warning(
                    "_export_visual | attempt=%s | title=%r | %s",
                    attempt, visual["title"], last_error,
                )
                continue

            item = await _find_export_data_item(page)

            if item is None:
                last_error = "Export data menu item not found."
                logger.warning(
                    "_export_visual | attempt=%s | title=%r | %s",
                    attempt, visual["title"], last_error,
                )
                await _close_open_overlays(page)
                continue
            RAW_DIR.mkdir(parents=True, exist_ok=True)

            # REGISTER DOWNLOAD HANDLER BEFORE CLICKING EXPORT
            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=before_expect_download | visual=%r | state=%s",
                visual["title"],
                _page_state(page),
            )

            async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                try:
                    await item.click(timeout=5000)
                except Exception:
                    await item.click(timeout=5000, force=True)

                logger.info(
                    "TABLE_EXPORT_LIFECYCLE | event=export_data_clicked | visual=%r | state=%s",
                    visual["title"],
                    _page_state(page),
                )

                export_info = await _handle_export_dialog(page)

                export_btn = export_info.get("export_button")
                if export_btn and await export_btn.count() > 0:
                    try:
                        await export_btn.click(timeout=5000)
                    except Exception:
                        await export_btn.click(timeout=5000, force=True)

                    logger.info(
                        "TABLE_EXPORT_LIFECYCLE | event=dialog_export_clicked | visual=%r | state=%s",
                        visual["title"],
                        _page_state(page),
                    )

            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=download_event_received | visual=%r | state=%s",
                visual["title"],
                _page_state(page),
            )
            download = await download_info.value
            suffix = Path(download.suggested_filename).suffix or ".csv"
            filename = f"{_safe_filename(dashboard_name, 'dashboard')}_{_safe_filename(visual['title'], 'table')}_{uuid.uuid4().hex[:8]}{suffix}"
            path = RAW_DIR / filename

            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=before_save_as | visual=%r | path=%s | state=%s",
                visual["title"],
                path,
                _page_state(page),
            )

            await download.save_as(str(path))

            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=after_save_as | visual=%r | state=%s",
                visual["title"],
                _page_state(page),
            )
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
            logger.warning(
                "Export attempt %s failed | visual=%s | state=%s | error=%s",
                attempt,
                visual["title"],
                _page_state(page),
                exc,
            )

            if (
                "TargetClosedError" in str(exc)
                or "Target page, context or browser has been closed" in str(exc)
                or "browser has been closed" in str(exc)
            ):
                logger.error(
                    "TABLE_EXPORT_LIFECYCLE | event=terminal_close_during_export | visual=%r | state=%s",
                    visual["title"],
                    _page_state(page),
                )
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