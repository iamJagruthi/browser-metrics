"""Browser-side extraction of Power BI visual data.

This module deliberately does not use Gemini.  It inspects the rendered Power
BI DOM in the existing Playwright page so callers can retain the current slicer
state and obtain data that is available to the signed-in browser session.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VISUAL_SELECTOR = ".visualContainer, [data-visual-container]"


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
                if attempt_export and visual["export"]["supported"]:
                    visual["export"] = await self._try_export(locator, visual, index)
                result["visuals"].append(visual)
            except Exception as exc:
                result["status"] = "partial"
                result["errors"].append(f"Visual {index + 1}: {exc}")

        return result

    async def _extract_filter_state(self) -> list[dict[str, Any]]:
        """Read selected slicer values from accessible Power BI controls."""
        selector = (
            ".slicerContainer, [aria-label*='Slicer' i], "
            "[data-visual-type*='slicer' i]"
        )
        try:
            return await self.page.locator(selector).evaluate_all(
                """nodes => nodes.map((node, index) => {
                    const selected = [...node.querySelectorAll(
                        '[aria-selected="true"], input:checked, [aria-checked="true"]'
                    )].map(item => (item.innerText || item.getAttribute('aria-label') || item.value || '').trim())
                     .filter(Boolean);
                    const values = [...node.querySelectorAll('[role="option"], label, button')]
                        .map(item => (item.innerText || item.getAttribute('aria-label') || '').trim())
                        .filter(Boolean);
                    return {
                        id: node.id || `slicer-${index + 1}`,
                        name: (node.getAttribute('aria-label') || node.querySelector('[title]')?.getAttribute('title') || '').trim(),
                        selected_values: [...new Set(selected)],
                        visible_values: [...new Set(values)].slice(0, 500),
                    };
                })"""
            )
        except Exception:
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
                const exportLabel = [...node.querySelectorAll('button, [role="button"]')]
                    .map(el => `${el.getAttribute('aria-label') || ''} ${el.title || ''} ${el.innerText || ''}`)
                    .some(text => /export data/i.test(text));
                return {
                    id: node.getAttribute('data-visual-id') || node.id || `visual-${index + 1}`,
                    title: (titleNode?.getAttribute('title') || titleNode?.getAttribute('aria-label') || '').trim(),
                    visual_type: typeSource || 'unknown',
                    accessible_text: text,
                    is_loading_placeholder: /^visuals are loading\.\.\.?$/i.test(text) || /^loading\.\.\.?$/i.test(text),
                    scrollable,
                    export_menu_present: exportLabel,
                };
            }""",
            index,
        )
        columns = await locator.evaluate(
            """node => [...node.querySelectorAll('[role="columnheader"], th')]
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
        metadata["export"] = {
            "supported": metadata.pop("export_menu_present"),
            "attempted": False,
            "status": "not_attempted",
            "file_path": None,
        }
        return metadata

    async def _collect_rows(self, locator, scrollable: bool) -> list[list[str]]:
        """Collect DOM rows and scroll virtualised tables to expose additional rows."""
        seen: set[tuple[str, ...]] = set()

        async def collect() -> None:
            rows = await locator.evaluate(
                """node => [...node.querySelectorAll('[role="row"], tr')].map(row =>
                    [...row.querySelectorAll('[role="gridcell"], [role="columnheader"], td, th')]
                        .map(cell => (cell.innerText || cell.getAttribute('aria-label') || '').trim())
                        .filter(Boolean)
                ).filter(row => row.length)"""
            )
            for row in rows:
                seen.add(tuple(row))

        await collect()
        if not scrollable:
            return [list(row) for row in seen]

        for _ in range(self.max_scroll_steps):
            moved = await locator.evaluate(
                """node => {
                    const element = [...node.querySelectorAll('*')].find(el => {
                        const style = getComputedStyle(el);
                        return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 2;
                    });
                    if (!element || element.scrollTop + element.clientHeight >= element.scrollHeight - 2) return false;
                    element.scrollTop = Math.min(element.scrollTop + Math.max(element.clientHeight * .8, 1), element.scrollHeight);
                    element.dispatchEvent(new Event('scroll', {bubbles: true}));
                    return true;
                }"""
            )
            if not moved:
                break
            await self.page.wait_for_timeout(150)
            await collect()

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


async def extract_visual_data(page, **kwargs) -> dict[str, Any]:
    """Convenience API used by the validator and future API/frontend callers."""
    attempt_export = kwargs.pop("attempt_export", False)
    return await VisualDataExporter(page, **kwargs).extract_dashboard_data(
        attempt_export=attempt_export
    )
