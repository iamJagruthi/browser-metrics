"""Browser-side extraction of Power BI visual data.

This module deliberately does not use Gemini.  It inspects the rendered Power
BI DOM in the existing Playwright page so callers can retain the current slicer
state and obtain data that is available to the signed-in browser session.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


VISUAL_SELECTOR = ".visualContainer, [data-visual-container]"
logger = logging.getLogger(__name__)


def _normalise_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _safe_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_.")
    return value or fallback


class VisualDataExporter:
    """Extract visible visual data without modifying the dashboard's filters."""

    def __init__(
        self,
        page,
        *,
        download_directory: str | Path | None = None,
        max_scroll_steps: int = 30,
    ):
        self.page = page
        self.download_directory = Path(download_directory) if download_directory else None
        self.max_scroll_steps = max_scroll_steps

    async def extract_dashboard_data(self, *, attempt_export: bool = False) -> dict[str, Any]:
        """Return slicer state, visual metadata, visible/scrollable rows and exports.

        ``attempt_export`` is opt-in because Power BI tenants can disable Export
        data and because clicking the visual menu changes the live UI.  DOM data
        collection remains available regardless of that setting.
        """
        result: dict[str, Any] = {
            "status": "success",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "filters": await self._extract_filter_state(),
            "visuals": [],
            "skipped_visuals": [],
            "errors": [],
        }

        try:
            visual_count = await self.page.locator(VISUAL_SELECTOR).count()
        except Exception as exc:
            result.update(status="failed")
            result["errors"].append(f"Unable to locate Power BI visuals: {exc}")
            return result

        if not visual_count:
            result.update(status="partial")
            result["errors"].append("No Power BI visual containers were found.")
            return result

        for index in range(visual_count):
            locator = self.page.locator(VISUAL_SELECTOR).nth(index)
            try:
                if not await locator.is_visible():
                    result["skipped_visuals"].append({"index": index + 1, "reason": "hidden"})
                    continue
                visual = await self._inspect_visual(locator, index)
                if visual.pop("is_loading_placeholder", False):
                    result["skipped_visuals"].append({"index": index + 1, "reason": "Power BI loading placeholder"})
                    continue
                # Native export is the accuracy fallback for virtualised Power
                # BI tables/matrices: request it only for visuals that expose
                # a grid/scrollbar, never for every chart on the page.
                is_tabular = bool(visual["data"]["columns"] or visual["data"]["rows"] or visual["scrollable"] or visual["horizontally_scrollable"])
                if attempt_export and is_tabular and visual["export"]["supported"]:
                    visual["export"] = await self._try_export(locator, visual, index)
                    if visual["export"].get("status") == "downloaded":
                        exported = await asyncio.to_thread(self._read_exported_table, visual["export"]["file_path"])
                        if exported and exported["rows"]:
                            visual["data"] = exported
                            visual["data"]["collection_method"] = "power_bi_export"
                result["visuals"].append(visual)
            except Exception as exc:
                result["status"] = "partial"
                result["errors"].append(f"Visual {index + 1}: {exc}")

        logger.info("Visual extraction completed | visuals=%d | skipped=%d | errors=%d", len(result["visuals"]), len(result["skipped_visuals"]), len(result["errors"]))
        return result

    async def _extract_filter_state(self) -> list[dict[str, Any]]:
        """Read filters/buttons from the live Power BI accessibility DOM.

        Button slicers often do not expose the ``slicerContainer`` class, so
        examine visual containers as well and use their pressed/checked state
        instead of asking Gemini to infer selection from colour.
        """
        selector = (
            ".slicerContainer, [aria-label*='Slicer' i], "
            "[data-visual-type*='slicer' i], " + VISUAL_SELECTOR
        )
        try:
            filters = await self.page.locator(selector).evaluate_all(
                """nodes => nodes.map((node, index) => {
                    const visual = node.closest('.visualContainer, [data-visual-container]') || node;
                    const text = item => (item.innerText || item.getAttribute('aria-label') || item.value || '').replace(/\\s+/g, ' ').trim();
                    const title = text(visual.querySelector('.visualTitle, [class*="visualTitle"], [data-visual-title]'))
                        || (visual.getAttribute('aria-label') || '').trim()
                        || (visual.querySelector('[title]')?.getAttribute('title') || '').trim();
                    const controls = [...node.querySelectorAll('[role="option"], [role="radio"], [role="checkbox"], label, button, input')]
                        .map(item => ({
                            value: text(item),
                            selected: item.matches('input:checked, [aria-selected="true"], [aria-checked="true"], [aria-pressed="true"]')
                                || /(^|\\s)(selected|active)(\\s|$)/i.test(item.className || ''),
                        }))
                        .filter(item => item.value);
                    const selected = controls.filter(item => item.selected).map(item => item.value);
                    const values = controls.map(item => item.value);
                    const hasSlicerMarkup = node.matches('.slicerContainer, [class*="slicer" i], [aria-label*="Slicer" i], [data-visual-type*="slicer" i]')
                        || visual.matches('[data-visual-type*="slicer" i]');
                    const hasChoiceControl = controls.some(item => item.value && !/^(more options|focus mode|drill down|expand)$/i.test(item.value));
                    const looksLikeFilter = hasSlicerMarkup || (title && hasChoiceControl && controls.length >= 2);
                    return {
                        id: node.id || `slicer-${index + 1}`,
                        name: title,
                        filter_type: controls.some(item => item.selected) ? 'Buttons' : 'Dropdown',
                        selected_values: [...new Set(selected)],
                        visible_values: [...new Set(values)].slice(0, 500),
                        looks_like_filter: looksLikeFilter,
                        extraction_source: 'dom',
                    };
                }).filter(item => item.looks_like_filter && item.name)"""
            )
            # The selector can overlap (a slicer is also a visual container).
            # Keep the record with the most actual option/selection evidence,
            # not simply the last wrapper returned by the DOM query.
            unique = {}
            for item in filters:
                key = " ".join(item["name"].casefold().split())
                score = len(item.get("visible_values", [])) + (1000 if item.get("selected_values") else 0)
                previous = unique.get(key)
                previous_score = len(previous.get("visible_values", [])) + (1000 if previous.get("selected_values") else 0) if previous else -1
                if score > previous_score:
                    unique[key] = item
            return list(unique.values())
        except Exception:
            logger.exception("Unable to read slicer state")
            return []

    async def _inspect_visual(self, locator, index: int) -> dict[str, Any]:
        metadata = await locator.evaluate(
            r"""(node, index) => {
                const text = (node.innerText || '').trim();
                const titleNode = node.querySelector('[title], [aria-label], .title, .visualTitle');
                const typeSource = [node.className, node.getAttribute('data-visual-type'), node.getAttribute('aria-roledescription')]
                    .filter(Boolean).join(' ');
                const scrollable = [...node.querySelectorAll('*')].some(el => {
                    const style = getComputedStyle(el);
                    return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 2;
                });
                const horizontallyScrollable = [...node.querySelectorAll('*')].some(el => {
                    const style = getComputedStyle(el);
                    return /(auto|scroll)/.test(style.overflowX) && el.scrollWidth > el.clientWidth + 2;
                });
                const exportLabel = [...node.querySelectorAll('button, [role="button"]')]
                    .map(el => `${el.getAttribute('aria-label') || ''} ${el.title || ''} ${el.innerText || ''}`)
                    .some(text => /export data|more options|more/i.test(text));
                return {
                    id: node.getAttribute('data-visual-id') || node.id || `visual-${index + 1}`,
                    title: (titleNode?.getAttribute('title') || titleNode?.getAttribute('aria-label') || '').trim(),
                    visual_type: typeSource || 'unknown',
                    accessible_text: text,
                    is_loading_placeholder: /\bvisuals?\s+are\s+loading\b/i.test(text) || /^loading\.\.\.?$/i.test(text),
                    scrollable,
                    horizontally_scrollable: horizontallyScrollable,
                    export_menu_present: exportLabel,
                };
            }""",
            index,
        )
        columns = await locator.evaluate(
            """node => [...node.querySelectorAll('[role="columnheader"], th, .columnHeader, [class*="columnHeader" i]')]
                .map(cell => (cell.innerText || cell.getAttribute('aria-label') || '').trim())
                .filter(Boolean)"""
        )
        rows = await self._collect_rows(locator, metadata["scrollable"])
        if columns and rows and rows[0] == columns:
            rows = rows[1:]
        lines = _normalise_lines(metadata.pop("accessible_text", ""))
        title = metadata["title"] or (lines[0] if lines else metadata["id"])
        metadata["title"] = title
        metadata["data"] = {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "collection_method": "rendered_dom",
        }
        logger.info("Visual collected | title=%s | rows=%d | vertical_scroll=%s | horizontal_scroll=%s", title, len(rows), metadata["scrollable"], metadata["horizontally_scrollable"])
        metadata["export"] = {
            "supported": metadata.pop("export_menu_present"),
            "attempted": False,
            "status": "not_attempted",
            "file_path": None,
        }
        return metadata

    async def _collect_rows(self, locator, scrollable: bool) -> list[list[str]]:
        """Collect virtualised table rows while scrolling vertically and horizontally.

        Power BI frequently renders only the viewport columns for a matrix.  We
        retain first-seen order and scan both axes so a later column is not
        silently omitted from the comparison workbook.
        """
        seen: dict[tuple[str, ...], None] = {}

        async def collect() -> None:
            rows = await locator.evaluate(
                """node => {
                    const directRows = [...node.querySelectorAll('[role="row"], tr')].map(row =>
                        [...row.querySelectorAll('[role="gridcell"], [role="columnheader"], td, th, .cell, [class*="cell" i]')]
                            .map(cell => (cell.innerText || cell.getAttribute('aria-label') || '').trim())
                            .filter(Boolean)
                    ).filter(row => row.length);
                    if (directRows.length) return directRows;
                    const groups = new Map();
                    [...node.querySelectorAll('[role="gridcell"], td, .cell, [class*="cell" i]')].forEach(cell => {
                        const value = (cell.innerText || cell.getAttribute('aria-label') || '').trim();
                        const box = cell.getBoundingClientRect();
                        if (!value || box.width < 1 || box.height < 1) return;
                        const key = Math.round(box.top / 3) * 3;
                        if (!groups.has(key)) groups.set(key, []);
                        groups.get(key).push({ left: box.left, value });
                    });
                    return [...groups.entries()].sort((a, b) => a[0] - b[0])
                        .map(([, cells]) => cells.sort((a, b) => a.left - b.left).map(cell => cell.value));
                }"""
            )
            for row in rows:
                seen.setdefault(tuple(row), None)

        await collect()
        # Scan the complete two-dimensional viewport grid.  A previous pass
        # reached the bottom vertically and only then moved horizontally,
        # which missed the upper rows of later columns in a Power BI matrix.
        for horizontal_step in range(self.max_scroll_steps + 1):
            await locator.evaluate(
                """node => [...node.querySelectorAll('*')].forEach(el => {
                    const style = getComputedStyle(el);
                    if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 2) el.scrollTop = 0;
                })"""
            )
            await collect()
            if scrollable:
                for _ in range(self.max_scroll_steps):
                    moved_down = await locator.evaluate(
                        """node => {
                            const element = [...node.querySelectorAll('*')].filter(el => {
                                const style = getComputedStyle(el);
                                return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 2;
                            }).sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
                            if (!element || element.scrollTop + element.clientHeight >= element.scrollHeight - 2) return false;
                            element.scrollTop = Math.min(element.scrollTop + Math.max(element.clientHeight * .8, 1), element.scrollHeight);
                            element.dispatchEvent(new Event('scroll', {bubbles: true}));
                            return true;
                        }"""
                    )
                    if not moved_down:
                        break
                    await self.page.wait_for_timeout(200)
                    await collect()
            moved_right = await locator.evaluate(
                """node => {
                    const element = [...node.querySelectorAll('*')].filter(el => {
                        const style = getComputedStyle(el);
                        return /(auto|scroll)/.test(style.overflowX) && el.scrollWidth > el.clientWidth + 2;
                    }).sort((a, b) => (b.scrollWidth - b.clientWidth) - (a.scrollWidth - a.clientWidth))[0];
                    if (!element || element.scrollLeft + element.clientWidth >= element.scrollWidth - 2) return false;
                    element.scrollLeft = Math.min(element.scrollLeft + Math.max(element.clientWidth * .8, 1), element.scrollWidth);
                    element.dispatchEvent(new Event('scroll', {bubbles: true}));
                    return true;
                }"""
            )
            if not moved_right:
                break
            await self.page.wait_for_timeout(200)

        return [list(row) for row in seen]

    async def _try_export(self, locator, visual: dict[str, Any], index: int) -> dict[str, Any]:
        export = dict(visual["export"], attempted=True, status="unavailable")
        try:
            menu = locator.locator("button, [role='button']").filter(has_text=re.compile("more options|more", re.I))
            if await menu.count() == 0:
                return export
            await menu.first.click()
            item = self.page.get_by_text(re.compile(r"export data", re.I)).first
            if await item.count() == 0:
                return export
            async with self.page.expect_download(timeout=10_000) as download_info:
                await item.click()
            download = await download_info.value
            if self.download_directory:
                self.download_directory.mkdir(parents=True, exist_ok=True)
                path = self.download_directory / _safe_filename(visual["title"], f"visual-{index + 1}")
                path = path.with_suffix(Path(download.suggested_filename).suffix or ".csv")
                await download.save_as(str(path))
                export["file_path"] = str(path)
            export["status"] = "downloaded"
        except Exception as exc:
            export["error"] = str(exc)
        return export

    @staticmethod
    def _read_exported_table(file_path: str | None) -> dict[str, Any] | None:
        """Read a Power BI CSV/XLSX export into the common table schema."""
        if not file_path:
            return None
        path = Path(file_path)
        try:
            if path.suffix.lower() == ".csv":
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    values = list(csv.reader(handle))
            elif path.suffix.lower() in {".xlsx", ".xlsm"}:
                workbook = load_workbook(path, read_only=True, data_only=True)
                sheet = workbook.active
                values = [list(row) for row in sheet.iter_rows(values_only=True)]
                workbook.close()
            else:
                logger.warning("Unsupported Power BI export format | %s", path.suffix)
                return None
            values = [["" if value is None else str(value) for value in row] for row in values if any(value is not None and str(value).strip() for value in row)]
            if not values:
                return None
            return {"columns": values[0], "rows": values[1:], "row_count": max(0, len(values) - 1)}
        except Exception:
            logger.exception("Unable to parse Power BI export | %s", path)
            return None


async def extract_visual_data(page, **kwargs) -> dict[str, Any]:
    """Convenience API used by the validator and future API/frontend callers."""
    attempt_export = kwargs.pop("attempt_export", False)
    return await VisualDataExporter(page, **kwargs).extract_dashboard_data(
        attempt_export=attempt_export
    )


async def apply_slicer_value(page, slicer_name: str, value: str) -> bool:
    """Select an exact slicer option in the currently loaded Power BI page.

    Returns ``False`` when the accessible DOM does not expose a safe matching
    control; callers can report this rather than claiming a filter was applied.
    """
    try:
        selected = await page.locator(
            ".slicerContainer, [aria-label*='Slicer' i], [data-visual-type*='slicer' i]"
        ).evaluate_all(
            """(nodes, args) => {
                const normalise = text => (text || '').replace(/\\s+/g, ' ').trim().toLocaleLowerCase();
                const wantedName = normalise(args.name);
                const wantedValue = normalise(args.value);
                const container = nodes.find(node => normalise(node.innerText).includes(wantedName));
                if (!container) return false;
                const option = [...container.querySelectorAll('[role="option"], label, button, input')]
                    .find(node => normalise(node.innerText || node.getAttribute('aria-label') || node.value) === wantedValue);
                if (!option || option.disabled) return false;
                option.click();
                return true;
            }""",
            {"name": slicer_name, "value": value},
        )
        if selected:
            await self_wait_for_dashboard(page)
        return bool(selected)
    except Exception:
        logger.exception("Failed to apply slicer value | slicer=%s | value=%s", slicer_name, value)
        return False


async def self_wait_for_dashboard(page) -> None:
    """Wait briefly for a slicer action to repaint without reloading the page."""
    await page.wait_for_timeout(500)
    for _ in range(8):
        loading = await page.locator(".loading, [aria-label*='loading' i], [aria-busy='true']").count()
        if not loading:
            await page.wait_for_timeout(350)
            return
        await page.wait_for_timeout(350)
