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

from orchestration.canvas_diagnostics import log_scroll_delta, measure_scroll_chain
from utils.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

VISUAL_SELECTOR = ".visualContainer, [data-visual-container]"
MAX_EXPORT_RETRIES = 3
MENU_TIMEOUT = 8_000
DOWNLOAD_TIMEOUT = 30_000
CONTROL_WAIT_MS = 2_500  # conditional wait for hover-revealed controls / menu items
EXPORT_ITEM_WAIT_MS = 4_000  # wait for the "Export data" item itself to render
EXPORT_ENABLE_WAIT_MS = 3_000  # wait for a disabled "Export data" item to become enabled
UNAVAILABLE_CONFIRMATIONS = 2  # consistent "not offered" verdicts needed before reporting unavailable

# Hovering/clicking a visual is enough to reveal its More options (...) menu,
# so the canvas is left exactly where the user sees it. Only when the control
# cannot be reached that way -- typically because the visual sits outside the
# viewport -- is the canvas panned into position, and even then the snapshot
# taken at the start of the attempt is restored before returning.
# 1-based: attempt 1 stays in place, later attempts may scroll as a fallback.
SCROLL_FROM_ATTEMPT = 2

# Structured export outcomes exposed additively on each result dict under
# "export_outcome". "status" keeps its existing values ("downloaded"/"failed").
OUTCOME_SUCCEEDED = "succeeded"                  # A: export produced a file
OUTCOME_UNAVAILABLE = "unavailable"              # B: menu opened, no usable Export data
OUTCOME_EXPORT_FAILED = "export_failed"          # C: Export data found, export/download failed
OUTCOME_INTERACTION_FAILED = "interaction_failed"  # D: visual/menu could not be interacted with

EXPORT_UNAVAILABLE_MESSAGE = "Export data is not available for this visual."

EXPORT_DIR = OUTPUT_DIR / "table_exports"
RAW_DIR = EXPORT_DIR / "raw"


# ---------------------------------------------------------------------------
# GENERIC CANVAS-SCROLL FIX (capture -> operate -> restore)
#
# Playwright's scroll_into_view_if_needed mutates Power BI's programmatic
# canvas window (a computed-style scrollable panel, overflow auto/scroll/
# hidden, inside the report container). The mutation pans the ENTIRE report
# (title, KPIs, all visuals) horizontally and is never undone, which is the
# "dancing" canvas observed during validation.
#
# This fix is intentionally generic -- no Power BI class names, visual
# titles, or coordinates anywhere:
#   - the scrollable canvas panel is discovered purely from an element's own
#     ancestor chain via computed overflow style + scrollable extent,
#   - only its scrollLeft/scrollTop are touched (the same mechanism Power BI
#     itself uses, so restore is symmetric and safe),
#   - targets already in the viewport (or with no real box) are never
#     touched, so no pan happens for on-screen or zero-size visuals.
# ---------------------------------------------------------------------------

# Brings an element into the canvas viewport with the minimum possible move.
_SCROLL_TO_VIEW_JS = """(node) => {
    if (node.nodeType !== 1) return { scrolled: false, reason: 'not_element' };
    const MARGIN = 12;
    const r = node.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return { scrolled: false, reason: 'zero_size' };
    const inView = r.top >= 0 && r.left >= 0 &&
        r.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
        r.right <= (window.innerWidth || document.documentElement.clientWidth);
    if (inView) return { scrolled: false, reason: 'already_in_view' };

    let el = node;
    let depth = 0;
    let container = null;
    while (el && depth < 25) {
        if (/auto|scroll|hidden/.test(window.getComputedStyle(el).overflowY + ' ' +
                                     window.getComputedStyle(el).overflowX) &&
            (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
            container = el;
            break;
        }
        el = el.parentElement;
        depth += 1;
    }
    if (!container) return { scrolled: false, reason: 'no_scroll_container' };

    const cRect = container.getBoundingClientRect();
    let dx = 0, dy = 0;
    if (r.left < cRect.left + MARGIN) dx = r.left - (cRect.left + MARGIN);
    else if (r.right > cRect.right - MARGIN) dx = r.right - (cRect.right - MARGIN);
    if (r.top < cRect.top + MARGIN) dy = r.top - (cRect.top + MARGIN);
    else if (r.bottom > cRect.bottom - MARGIN) dy = r.bottom - (cRect.bottom - MARGIN);

    const nx = Math.max(0, Math.min(container.scrollLeft + dx,
                                    container.scrollWidth - container.clientWidth));
    const ny = Math.max(0, Math.min(container.scrollTop + dy,
                                    container.scrollHeight - container.clientHeight));
    const moved = Math.abs(container.scrollLeft - nx) > 0.5 ||
                  Math.abs(container.scrollTop - ny) > 0.5;
    container.scrollLeft = nx;
    container.scrollTop = ny;
    return { scrolled: moved, scrollLeft: container.scrollLeft,
             scrollTop: container.scrollTop };
}"""

_CANVAS_SNAPSHOT_JS = """(node) => {
    let el = node;
    let depth = 0;
    while (el && depth < 25) {
        if (/auto|scroll|hidden/.test(window.getComputedStyle(el).overflowY + ' ' +
                                     window.getComputedStyle(el).overflowX) &&
            (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
            return { found: true, scrollLeft: el.scrollLeft, scrollTop: el.scrollTop };
        }
        el = el.parentElement;
        depth += 1;
    }
    return { found: false };
}"""

_CANVAS_RESTORE_JS = """(node, saved) => {
    let el = node;
    let depth = 0;
    while (el && depth < 25) {
        if (/auto|scroll|hidden/.test(window.getComputedStyle(el).overflowY + ' ' +
                                     window.getComputedStyle(el).overflowX) &&
            (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
            el.scrollLeft = saved.scrollLeft;
            el.scrollTop = saved.scrollTop;
            return { restored: true, scrollLeft: el.scrollLeft, scrollTop: el.scrollTop };
        }
        el = el.parentElement;
        depth += 1;
    }
    return { restored: false };
}"""


async def _scroll_visual_into_canvas_view(page, locator) -> None:
    """Bring a visual into the canvas viewport using the minimal, generic
    scroll described above. Never raises and never mutates anything except
    the discovered canvas panel's own scroll offsets."""
    try:
        if await locator.count() == 0:
            return
        await locator.first.evaluate(_SCROLL_TO_VIEW_JS)
    except Exception:
        pass


async def _snapshot_canvas_scroll(page, locator):
    try:
        if await locator.count() == 0:
            return None
        return await locator.first.evaluate(_CANVAS_SNAPSHOT_JS)
    except Exception:
        return None


async def _restore_canvas_scroll(page, locator, state) -> bool:
    if not state or not state.get("found"):
        return False
    try:
        if await locator.count() == 0:
            return False
        result = await locator.first.evaluate(_CANVAS_RESTORE_JS, state)
        return bool(result and result.get("restored"))
    except Exception:
        return False


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
        # Position-based match: if Power BI re-rendered or reordered visuals since
        # extraction this can be a DIFFERENT visual (one with no Export data).
        logger.warning(
            "TABLE_EXPORT | event=visual_resolved_by_index | visual=%r | index=%s | aria_label=%r",
            visual.get("title"), original_index, aria_label,
        )
        return visuals.nth(original_index)

    return None


# Picks a point inside the visual that is NOT a data value, relative to the
# visual's own box (no dashboard-specific coordinates). Candidates are the
# border/padding strips; each is verified with elementFromPoint so it must land
# on the visual itself (not a data cell, not another overlapping visual).
_SAFE_POINT_JS = """(node) => {
    if (!node || node.nodeType !== 1) return null;
    const r = node.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) return null;
    const isData = (el) => !!(el && el.closest && el.closest(
        "[role='gridcell'],[role='cell'],[role='columnheader'],[role='rowheader']," +
        "[role='row'],td,th"));
    const i = 4;
    const cands = [
        [r.width / 2, i], [r.width - i, r.height / 2], [i, r.height / 2],
        [r.width / 2, r.height - i], [r.width - i, i], [i, i],
    ];
    for (const [x, y] of cands) {
        const el = document.elementFromPoint(r.left + x, r.top + y);
        if (el && (el === node || node.contains(el)) && !isData(el)) {
            return { x: x, y: y };
        }
    }
    return null;
}"""

_MORE_OPTIONS_SELECTOR = (
    "button[data-testid='visual-more-options-btn'], "
    "button[aria-label='More options'], "
    "[role='button'][aria-label='More options']"
)


# Playwright's locator.hover()/click() scroll the target into view first, which
# pans Power BI's canvas (the "dancing" report). When the target is already fully
# inside the viewport and nothing covers it, the same real mouse events can be sent
# with page.mouse, which never scrolls anything. Off-screen targets still fall back
# to the locator action (the canvas scroll snapshot/restore then undoes the pan).
_HIT_TEST_JS = """(el, pt) => {
    const t = document.elementFromPoint(pt[0], pt[1]);
    return !!t && (t === el || el.contains(t));
}"""


async def _viewport_point(page, locator, rel=None):
    """Absolute (x, y) of a point on `locator` when it is fully on-screen and
    actually hit-testable there; otherwise None (caller falls back to Playwright)."""
    try:
        box = await locator.bounding_box()
        size = page.viewport_size or await page.evaluate(
            "() => ({width: window.innerWidth, height: window.innerHeight})"
        )
        if not box or not size:
            return None
        if rel is not None:
            x, y = box["x"] + rel["x"], box["y"] + rel["y"]
        else:
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        if not (0 <= x <= size["width"] and 0 <= y <= size["height"]):
            return None
        if not await locator.evaluate(_HIT_TEST_JS, [x, y]):
            return None
        return x, y
    except Exception:
        return None


async def _focus_visual_no_scroll(locator) -> bool:
    """Focus the visual (reveals its header controls like keyboard navigation does)
    without clicking data and without scrolling."""
    try:
        return bool(await locator.evaluate(
            """(node) => {
                const t = node.matches('[tabindex]') ? node : node.querySelector('[tabindex]');
                if (!t) return false;
                t.focus({ preventScroll: true });
                return true;
            }"""
        ))
    except Exception:
        return False


async def _safe_hover_point(locator):
    """Return {'x','y'} of a non-value point inside the visual, or None."""
    try:
        point = await locator.evaluate(_SAFE_POINT_JS)
        if point and "x" in point and "y" in point:
            return point
    except Exception:
        pass
    return None


async def _hover_visual(locator, point, page=None) -> str:
    """Hover a safe area when one exists; otherwise the element center. On-screen
    targets use page.mouse (no canvas scroll); off-screen ones fall back to the
    Playwright locator hover (scrolls, restored later)."""
    if page is not None:
        pos = await _viewport_point(page, locator, point)
        if pos:
            try:
                await page.mouse.move(pos[0], pos[1])
                return "mouse_safe_area" if point else "mouse_center"
            except Exception:
                pass
    if point:
        try:
            await locator.hover(position=point, timeout=3000)
            return "safe_area"
        except Exception:
            pass
    try:
        await locator.hover(timeout=3000)
    except Exception:
        await locator.hover(timeout=3000, force=True)
    return "center"


async def _find_more_options(locator, wait_ms: int = CONTROL_WAIT_MS):
    """Find a VISIBLE More options control inside this visual only.

    Returns (button_or_None, present). `present` is True when a matching control
    exists in the DOM even though it is not (yet) visible/actionable.
    """
    candidates = locator.locator(_MORE_OPTIONS_SELECTOR)
    try:
        await candidates.first.wait_for(state="visible", timeout=wait_ms)
    except Exception:
        pass  # not visible yet; inspect what is present below

    present = False
    try:
        total = await candidates.count()
    except Exception:
        total = 0
    for i in range(total):
        present = True
        candidate = candidates.nth(i)
        try:
            if await candidate.is_visible():
                return candidate, True
        except Exception:
            continue
    return None, present


def _distance_to_rect(px: float, py: float, box: dict[str, float]) -> float:
    dx = max(box["x"] - px, 0, px - (box["x"] + box["width"]))
    dy = max(box["y"] - py, 0, py - (box["y"] + box["height"]))
    return (dx * dx + dy * dy) ** 0.5


async def _pick_nearest(candidates, anchor_box):
    """Disambiguate several visible candidates: nearest to the More options
    button that was clicked; without an anchor, the most recently opened
    (last in DOM order, where overlays are appended)."""
    if not candidates:
        return None
    if len(candidates) == 1 or not anchor_box:
        return candidates[-1]

    ax = anchor_box["x"] + anchor_box["width"] / 2
    ay = anchor_box["y"] + anchor_box["height"] / 2
    best, best_distance = None, None
    for candidate in candidates:
        try:
            box = await candidate.bounding_box()
        except Exception:
            box = None
        if not box:
            continue
        distance = _distance_to_rect(ax, ay, box)
        if best_distance is None or distance < best_distance:
            best, best_distance = candidate, distance
    return best if best is not None else candidates[-1]


_MARK_STALE_MENUS_JS = """() => {
    document.querySelectorAll('[role="menu"]').forEach((m) => {
        const r = m.getBoundingClientRect();
        const cs = window.getComputedStyle(m);
        if (r.width > 0 && r.height > 0 && cs.visibility !== 'hidden') {
            m.setAttribute('data-dv-stale', '1');
        }
    });
}"""

_CLEAR_STALE_MENUS_JS = """() => {
    document.querySelectorAll('[data-dv-stale]').forEach((m) => m.removeAttribute('data-dv-stale'));
}"""


async def _tag_menu(page, menu):
    """Tag the exact menu element so later lookups cannot drift to a different
    menu when the DOM order of role=menu elements changes (nth(i) is positional)."""
    token = uuid.uuid4().hex[:10]
    try:
        await menu.evaluate("(el, t) => el.setAttribute('data-dv-menu', t)", token)
        return page.locator('[data-dv-menu="%s"]' % token).first
    except Exception:
        return menu


async def _resolve_open_menu(page, button, anchor_box):
    """Identify the menu that the just-clicked More options button opened.

    Order: a NEWLY opened menu (not one that was already open before the click),
    polled until it renders; then the button's aria-controls target; then any
    visible role=menu nearest the button. The chosen menu is tagged so later
    lookups stay bound to it. Returns a locator, or None when none could be confirmed.
    """
    fresh = page.locator('[role="menu"]:not([data-dv-stale])')
    waited = 0
    while waited <= MENU_TIMEOUT:
        visible = []
        try:
            for i in range(await fresh.count()):
                candidate = fresh.nth(i)
                if await candidate.is_visible():
                    visible.append(candidate)
        except Exception:
            visible = []
        if visible:
            picked = await _pick_nearest(visible, anchor_box)
            if picked is not None:
                return await _tag_menu(page, picked)
        await page.wait_for_timeout(200)
        waited += 200

    try:
        controls = await button.get_attribute("aria-controls", timeout=1000)
    except Exception:
        controls = None
    if controls:
        scoped = page.locator('[id="%s"]' % controls.replace('"', ""))
        try:
            if await scoped.count() == 1 and await scoped.first.is_visible():
                return await _tag_menu(page, scoped.first)
        except Exception:
            pass

    menus = page.get_by_role("menu")
    visible = []
    try:
        for i in range(await menus.count()):
            menu = menus.nth(i)
            if await menu.is_visible():
                visible.append(menu)
    except Exception:
        return None
    picked = await _pick_nearest(visible, anchor_box)
    return await _tag_menu(page, picked) if picked is not None else None


async def _open_more_options(page, visual: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
    """Open the More options menu of THIS visual.

    Returns True when the control was activated. When a `state` dict is passed
    it is filled with: menu (locator of the opened menu, or None),
    anchor_box (bounding box of the clicked button) and reason (why it failed).
    """
    if state is None:
        state = {}
    state.update(menu=None, anchor_box=None, reason=None)
    title = visual.get("title")

    for attempt in range(1, MAX_EXPORT_RETRIES + 1):
        try:
            await _close_open_overlays(page)
            locator = await _get_visual_locator(page, visual)
            if locator is None:
                state["reason"] = "visual_not_found"
                logger.warning("TABLE_EXPORT | event=visual_not_found | visual=%r | attempt=%s", title, attempt)
                continue

            # Snapshot the canvas scroll offsets BEFORE any interaction so both
            # Playwright-side pans and Power BI's own menu-open re-center can be
            # undone immediately after the menu is confirmed open.
            _canvas_state = await _snapshot_canvas_scroll(page, locator)

            try:
                _diag_before = await measure_scroll_chain(page, locator)
                if attempt >= SCROLL_FROM_ATTEMPT:
                    await _scroll_visual_into_canvas_view(page, locator)
                    _diag_after_scroll = await measure_scroll_chain(page, locator)
                    log_scroll_delta(
                        "table_export.open_more_options.scroll",
                        visual.get("title"),
                        _diag_before,
                        _diag_after_scroll,
                        "after_scroll",
                    )
                else:
                    logger.info(
                        "TABLE_EXPORT | event=operate_in_place | visual=%r | attempt=%s",
                        title, attempt,
                    )
            except Exception:
                pass

            await page.wait_for_timeout(300)
            locator = await _get_visual_locator(page, visual)
            if locator is None:
                state["reason"] = "visual_not_found"
                continue

            safe_point = await _safe_hover_point(locator)
            hover_mode = await _hover_visual(locator, safe_point, page)
            logger.info(
                "TABLE_EXPORT | event=hover_visual | visual=%r | attempt=%s | target=%s",
                title, attempt, hover_mode,
            )

            locator = await _get_visual_locator(page, visual)
            if locator is None:
                state["reason"] = "visual_not_found"
                continue

            button, present = await _find_more_options(locator)

            if button is None:
                # Keyboard-style reveal: focus the visual (no click on data, no scroll).
                if await _focus_visual_no_scroll(locator):
                    logger.info("TABLE_EXPORT | event=more_options_focus_reveal | visual=%r", title)
                    button, present = await _find_more_options(locator)

            if button is None and safe_point:
                # Control missing or not actionable after hover: focus/select the
                # visual by clicking a NON-value point of its own box, then re-check.
                logger.info(
                    "TABLE_EXPORT | event=more_options_fallback_click | visual=%r | control_present=%s",
                    title, present,
                )
                try:
                    await locator.click(position=safe_point, timeout=3000)
                except Exception:
                    pass
                button, present = await _find_more_options(locator)

            if button is None:
                state["reason"] = "more_options_not_actionable" if present else "more_options_not_found"
                logger.warning(
                    "TABLE_EXPORT | event=more_options_unavailable | visual=%r | attempt=%s | reason=%s",
                    title, attempt, state["reason"],
                )
                continue

            logger.info("TABLE_EXPORT | event=more_options_found | visual=%r", title)
            try:
                state["anchor_box"] = await button.bounding_box()
            except Exception:
                state["anchor_box"] = None

            # Mark menus that are ALREADY open so the one this click opens can be
            # told apart from a stale one (the old code waited for "any first menu").
            try:
                await page.evaluate(_MARK_STALE_MENUS_JS)
            except Exception:
                pass

            clicked = False
            click_pos = await _viewport_point(page, button)
            if click_pos:
                try:
                    await page.mouse.click(click_pos[0], click_pos[1])
                    clicked = True
                except Exception:
                    clicked = False
            if not clicked:
                try:
                    await button.click(timeout=3000)
                except Exception:
                    await button.click(timeout=3000, force=True)
            logger.info(
                "TABLE_EXPORT | event=more_options_activated | visual=%r | via=%s",
                title, "mouse" if clicked else "locator",
            )

            # Bind to the menu this click opened (before any scroll restore).
            state["menu"] = await _resolve_open_menu(page, button, state["anchor_box"])
            try:
                await page.evaluate(_CLEAR_STALE_MENUS_JS)
            except Exception:
                pass
            if state["menu"] is None:
                logger.warning(
                    "TABLE_EXPORT | event=menu_not_confirmed | visual=%r | note=falling back to visible-item lookup",
                    title,
                )

            try:
                _diag_after_done = await measure_scroll_chain(page, locator)
                log_scroll_delta(
                    "table_export.open_more_options.complete",
                    visual.get("title"),
                    _diag_before,
                    _diag_after_done,
                    "after_operation",
                )
            except Exception:
                pass

            # Undo the canvas pan (Playwright hover/click scrolls plus Power BI's
            # own menu-open re-center) IMMEDIATELY, so the report does not sit
            # displaced during the download and never visibly "settles" elsewhere.
            # The open menu stays functional; the dataset download continues.
            try:
                _restored = await _restore_canvas_scroll(page, locator, _canvas_state)
                if _restored:
                    _diag_after_restore = await measure_scroll_chain(page, locator)
                    log_scroll_delta(
                        "table_export.open_more_options.restore.complete",
                        visual.get("title"),
                        _diag_before,
                        _diag_after_restore,
                        "after_operation",
                    )
            except Exception:
                pass

            return True
        except Exception:
            state["reason"] = "interaction_error"
            await _close_open_overlays(page)
            await page.wait_for_timeout(500)

    return False


async def _find_export_data_item(page, scope=None, anchor_box=None, diag: dict[str, Any] | None = None):
    """Find the "Export data" item of the menu that was just opened.

    `scope` is the opened menu locator (from _open_more_options). The lookup is
    confined to it and only VISIBLE items qualify, so an Export data entry of
    another open/stale menu can never be picked. Without a scope, only visible
    items are considered and the one nearest the clicked button wins.

    Returns a locator or None. `diag["reason"]` explains a None:
      found          - item returned
      disabled       - item exists but is aria-disabled (treated as unavailable)
      not_in_menu    - menu confirmed and populated, no Export data item
      menu_empty     - menu confirmed but has no content (not ready)
      menu_unconfirmed - no menu could be tied to the click, nothing found
    """
    if diag is None:
        diag = {}
    diag["reason"] = "menu_unconfirmed"

    name = re.compile(r"^\s*export data\s*$", re.I)
    root = scope if scope is not None else page

    async def visible_matches():
        for finder in (
            lambda r: r.get_by_role("menuitem", name=name),
            lambda r: r.get_by_text(name),
        ):
            found = []
            try:
                loc = finder(root)
                for i in range(await loc.count()):
                    candidate = loc.nth(i)
                    if await candidate.is_visible():
                        found.append(candidate)
            except Exception:
                continue
            if found:
                return found
        return []

    matches = await visible_matches()
    if not matches and scope is not None:
        # Menu items render progressively. Wait for the "Export data" item ITSELF,
        # not just the first menu item of any kind (the old code could conclude
        # "not offered" while the item had simply not rendered yet).
        try:
            await scope.get_by_role("menuitem", name=name).first.wait_for(
                state="visible", timeout=EXPORT_ITEM_WAIT_MS
            )
        except Exception:
            pass
        matches = await visible_matches()

    scoped_empty = not matches
    if not matches and scope is not None:
        # Last resort before declaring it absent: the scoped menu may be the wrong
        # one. Look page-wide and take the visible item nearest the clicked button.
        root = page
        matches = await visible_matches()
        if matches:
            logger.info("TABLE_EXPORT | event=export_item_found_outside_scoped_menu")

    if matches:
        item = await _pick_nearest(matches, anchor_box) if (scope is None or scoped_empty) else matches[0]
        waited = 0
        while waited <= EXPORT_ENABLE_WAIT_MS:
            try:
                disabled = (await item.get_attribute("aria-disabled", timeout=1000) or "").lower() == "true"
            except Exception:
                disabled = False
            if not disabled:
                diag["reason"] = "found"
                return item
            await page.wait_for_timeout(250)
            waited += 250
        diag["reason"] = "disabled"
        return None

    if scope is not None:
        try:
            populated = bool(_clean(await scope.inner_text(timeout=1000)))
        except Exception:
            populated = False
        diag["reason"] = "not_in_menu" if populated else "menu_empty"
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


def _lifecycle_state(page) -> dict[str, Any]:
    """Return page/context/browser lifecycle state using three genuinely
    distinct, safe checks -- not the same underlying value repeated under
    different labels.

    - page_closed: Page.is_closed() (the only supported page-level check).
    - context_closed: BrowserContext has no is_closed() method in
      Playwright's Python API, so liveness is probed by actually touching
      the context (reading .pages). If the context is gone, this raises;
      if it's alive, it returns normally -- a real, independent signal,
      not a duplicate of the browser check below.
    - browser_connected: Browser.is_connected(), independent of the above.

    Each check is isolated so a failure in one can never mask or distort
    another, and this function itself can never raise.
    """
    state: dict[str, Any] = {
        "page_closed": None,
        "context_closed": None,
        "browser_connected": None,
    }

    try:
        state["page_closed"] = page.is_closed()
    except Exception:
        state["page_closed"] = True

    try:
        _ = page.context.pages
        state["context_closed"] = False
    except Exception:
        state["context_closed"] = True

    try:
        browser = page.context.browser
        state["browser_connected"] = browser.is_connected() if browser is not None else None
    except Exception:
        state["browser_connected"] = False

    return state


async def _export_visual(
    page,
    visual: dict[str, Any],
    dashboard_name: str,
) -> dict[str, Any]:
    result = {
        "title": visual["title"],
        # Carried through so an export can be paired with its counterpart on
        # the other dashboard even when the display name is generated.
        "comparison_key": visual.get("comparison_key"),
        "page_name": visual.get("page_name"),
        "visual_index": visual.get("index"),
        "status": "failed",
        "file_path": None,
        "data": None,
        "error": None,
        "validation_data_type": "unavailable",
        "validation_option": None,
        "validation_note": None,
        # Additive, structured outcome (existing keys/values are unchanged).
        # export_outcome: succeeded | unavailable | export_failed | interaction_failed
        "table_detected": True,
        "export_attempted": False,
        "export_option_found": None,
        "export_outcome": OUTCOME_INTERACTION_FAILED,
    }

    last_error = None
    outcome = OUTCOME_INTERACTION_FAILED
    unavailable_hits = 0

    for attempt in range(1, MAX_EXPORT_RETRIES + 1):
        if not page or page.is_closed():
            logger.error("Target page closed before export attempt. Aborting.")
            last_error = "Target page closed."
            outcome = OUTCOME_INTERACTION_FAILED
            break

        try:
            result["export_attempted"] = True
            logger.info("Export attempt %s/%s | dashboard=%s | visual=%s", attempt, MAX_EXPORT_RETRIES, dashboard_name, visual["title"])

            menu_state: dict[str, Any] = {}
            opened = await _open_more_options(page, visual, menu_state)
            if not opened:
                last_error = "Could not open More options."
                outcome = OUTCOME_INTERACTION_FAILED
                continue

            lookup: dict[str, Any] = {}
            item = await _find_export_data_item(
                page, menu_state.get("menu"), menu_state.get("anchor_box"), lookup
            )
            if item is None:
                reason = lookup.get("reason")
                await _close_open_overlays(page)
                if reason in ("not_in_menu", "disabled"):
                    # "Not offered" is only reported after it is seen on
                    # UNAVAILABLE_CONFIRMATIONS separate, freshly opened menus.
                    # One verdict can be a half-rendered menu, a stale menu, or an
                    # export still busy from an earlier attempt.
                    unavailable_hits += 1
                    result["export_option_found"] = False
                    outcome = OUTCOME_UNAVAILABLE
                    last_error = EXPORT_UNAVAILABLE_MESSAGE
                    logger.info(
                        "TABLE_EXPORT | event=export_unavailable_verdict | visual=%r | reason=%s | hit=%s/%s | attempt=%s",
                        visual["title"], reason, unavailable_hits, UNAVAILABLE_CONFIRMATIONS, attempt,
                    )
                    if unavailable_hits >= UNAVAILABLE_CONFIRMATIONS or attempt >= MAX_EXPORT_RETRIES:
                        break
                    await page.wait_for_timeout(750)
                    continue
                last_error = "Export data menu item not found; could not confirm the More options menu for this visual."
                outcome = OUTCOME_INTERACTION_FAILED
                logger.warning(
                    "TABLE_EXPORT | event=export_item_not_found | visual=%r | reason=%s",
                    visual["title"], reason,
                )
                continue

            result["export_option_found"] = True
            unavailable_hits = 0
            outcome = OUTCOME_EXPORT_FAILED  # until a file is actually saved
            logger.info("TABLE_EXPORT | event=export_item_found | visual=%r", visual["title"])
            RAW_DIR.mkdir(parents=True, exist_ok=True)

            # REGISTER DOWNLOAD HANDLER BEFORE CLICKING EXPORT
            logger.info("TABLE_EXPORT | event=export_started | visual=%r", visual["title"])
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

            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=download_event_received | visual=%r | "
                "suggested_filename=%r | state=%s",
                visual["title"],
                download.suggested_filename,
                _lifecycle_state(page),
            )

            # download.failure() is read-only and cannot itself alter
            # control flow. It reports Chromium's own view of whether the
            # download succeeded (None) or failed (a reason string),
            # independent of Playwright's page/context/browser connection.
            try:
                failure_reason = await download.failure()
            except Exception as failure_exc:
                failure_reason = f"<failure() raised: {failure_exc}>"
            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=download_failure_checked | visual=%r | "
                "failure=%r | browser_connected=%s",
                visual["title"],
                failure_reason,
                _lifecycle_state(page)["browser_connected"],
            )

            suffix = Path(download.suggested_filename).suffix or ".csv"
            filename = f"{_safe_filename(dashboard_name, 'dashboard')}_{_safe_filename(visual['title'], 'table')}_{uuid.uuid4().hex[:8]}{suffix}"
            path = RAW_DIR / filename

            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=before_save_as | visual=%r | "
                "destination_path=%s | state=%s",
                visual["title"],
                path,
                _lifecycle_state(page),
            )

            await download.save_as(str(path))

            # Filesystem existence check is independent of browser/page/context
            # state -- it cannot raise for lifecycle reasons and cannot be
            # affected by whatever closed the target. This is the actual
            # ground truth of whether the export persisted, regardless of
            # whether save_as() itself reported success.
            file_exists = path.exists()
            logger.info(
                "TABLE_EXPORT_LIFECYCLE | event=after_save_as | visual=%r | "
                "destination_path=%s | file_exists=%s | state=%s",
                visual["title"],
                path,
                file_exists,
                _lifecycle_state(page),
            )

            if not file_exists:
                last_error = (
                    f"save_as() returned without raising, but destination file "
                    f"does not exist: {path}"
                )
                logger.error(
                    "TABLE_EXPORT_LIFECYCLE | event=save_as_no_file | visual=%r | %s",
                    visual["title"], last_error,
                )
                continue

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
                export_outcome=OUTCOME_SUCCEEDED,
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

    # Export data was reachable at some point => a later interaction hiccup must
    # not mask that the real problem is the export itself (outcome C).
    if outcome != OUTCOME_UNAVAILABLE and result["export_option_found"]:
        outcome = OUTCOME_EXPORT_FAILED

    result["export_outcome"] = outcome
    result["error"] = last_error or "Export failed."
    if outcome != OUTCOME_UNAVAILABLE:
        logger.warning(
            "TABLE_EXPORT | event=export_failed | visual=%r | outcome=%s | error=%s",
            visual["title"], outcome, result["error"],
        )
    return result


def _attach_lifecycle_listeners(page, tracker: dict[str, Any]):
    """Log WHICH of crash / page close / context close / browser disconnect fires,
    and which table was being exported at that moment. Returns a detach callable."""
    handlers = []

    def _make(label):
        def _handler(*_args):
            logger.error(
                "TABLE_EXPORT_LIFECYCLE | event=%s | current_visual=%r | dashboard=%s",
                label, tracker.get("current"), tracker.get("dashboard"),
            )
        return _handler

    try:
        for target, event_name, label in (
            (page, "crash", "page_crash"),
            (page, "close", "page_close"),
            (page.context, "close", "context_close"),
            (page.context.browser, "disconnected", "browser_disconnected"),
        ):
            if target is None:
                continue
            handler = _make(label)
            target.on(event_name, handler)
            handlers.append((target, event_name, handler))
    except Exception:
        pass

    def _detach():
        for target, event_name, handler in handlers:
            try:
                target.remove_listener(event_name, handler)
            except Exception:
                pass

    return _detach


async def export_table_visuals(
    page,
    table_visuals: list[dict[str, Any]],
    dashboard_name: str,
) -> list[dict[str, Any]]:
    exported_tables: list[dict[str, Any]] = []

    if not table_visuals:
        return exported_tables

    _tracker: dict[str, Any] = {"current": None, "dashboard": dashboard_name}
    _detach_listeners = _attach_lifecycle_listeners(page, _tracker)

    try:
        canvas_anchor = page.locator(VISUAL_SELECTOR).first
        _diag_batch_before = await measure_scroll_chain(page, canvas_anchor)
        _diag_batch_snapshot = await _snapshot_canvas_scroll(page, canvas_anchor)
    except Exception:
        _diag_batch_before = None
        _diag_batch_snapshot = None

    for table_number, table_visual in enumerate(table_visuals, start=1):
        _tracker["current"] = table_visual.get("title")
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
                "table_detected": True,
                "export_attempted": False,
                "export_option_found": None,
                "export_outcome": OUTCOME_INTERACTION_FAILED,
            })

    try:
        if _diag_batch_before is not None:
            _diag_batch_after = await measure_scroll_chain(page, canvas_anchor)
            log_scroll_delta(
                "table_export.batch.complete",
                f"{len(table_visuals)}_visuals",
                _diag_batch_before,
                _diag_batch_after,
                "after_operation",
            )
    except Exception:
        pass

    # Restore the canvas scroll position to its pre-extraction state so the
    # visible report never stays displaced (capture -> operate -> restore).
    try:
        _restored = await _restore_canvas_scroll(page, canvas_anchor, _diag_batch_snapshot)
        _diag_after_restore = await measure_scroll_chain(page, canvas_anchor)
        log_scroll_delta(
            "table_export.batch.restore.complete",
            f"{len(table_visuals)}_visuals",
            _diag_batch_before,
            _diag_after_restore,
            "after_operation",
        )
    except Exception:
        pass

    _detach_listeners()

    return exported_tables