"""
canvas_diagnostics.py

DIAGNOSTIC-ONLY instrumentation for isolating the cause of Power BI
report-canvas / visual repositioning observed during automation.

This module never clicks, scrolls, hovers, or otherwise interacts with
the page. It only *measures* page state (positions, scroll offsets) at
a point in time and logs the delta between two measurements taken by
the caller. It must never be used in a way that changes control flow,
selectors, waits/timeouts, or click/scroll behavior anywhere else in
the codebase.

This is intended to be temporary: once the root cause of the canvas
movement is established from evidence gathered with this module, the
instrumentation should be removed or gated off.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("automation.canvas_diagnostics")

# Reuses the exact generic visual-container selector already defined and
# proven to match in this codebase (browser.py's _VISUAL_SELECTOR and
# table_exporter.py's VISUAL_SELECTOR). No new, dashboard-specific
# selector is introduced by this diagnostic module.
_GENERIC_VISUAL_SELECTOR = ".visualContainer, [data-visual-container], visual-container"

# Read-only measurement. Computes:
#   - a landmark rect that is the union of every currently-present visual
#     container's bounding box (generic across any Power BI report, not
#     tied to a specific visual's identity/title/index)
#   - window and document scroll offsets
#   - the nearest scrollable ancestor of the report canvas, discovered
#     generically via computed style + scrollHeight/scrollWidth (not a
#     hardcoded class name), along with its own scroll offsets
_MEASURE_JS = """(selector) => {
    const nodes = [...document.querySelectorAll(selector)];

    const result = {
        landmarkFound: false,
        visualContainerCount: nodes.length,
        canvasRect: null,
        scrollableAncestor: null,
        windowScrollX: window.scrollX,
        windowScrollY: window.scrollY,
        documentScrollTop: document.documentElement.scrollTop,
        documentScrollLeft: document.documentElement.scrollLeft,
    };

    if (nodes.length === 0) {
        return result;
    }

    let top = Infinity, left = Infinity, bottom = -Infinity, right = -Infinity;
    for (const node of nodes) {
        const r = node.getBoundingClientRect();
        top = Math.min(top, r.top);
        left = Math.min(left, r.left);
        bottom = Math.max(bottom, r.bottom);
        right = Math.max(right, r.right);
    }

    result.landmarkFound = true;
    result.canvasRect = {
        top, left, bottom, right,
        width: right - left,
        height: bottom - top,
    };

    const isScrollable = el => {
        if (!el || el === document.body || el === document.documentElement) return false;
        const style = window.getComputedStyle(el);
        const scrollableY = /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 1;
        const scrollableX = /(auto|scroll)/.test(style.overflowX) && el.scrollWidth > el.clientWidth + 1;
        return scrollableY || scrollableX;
    };

    let ancestor = nodes[0].parentElement;
    let depth = 0;
    while (ancestor && depth < 25) {
        if (isScrollable(ancestor)) {
            result.scrollableAncestor = {
                tag: ancestor.tagName,
                id: ancestor.id || null,
                className: (ancestor.className && ancestor.className.toString)
                    ? ancestor.className.toString().slice(0, 200)
                    : null,
                scrollTop: ancestor.scrollTop,
                scrollLeft: ancestor.scrollLeft,
                clientWidth: ancestor.clientWidth,
                clientHeight: ancestor.clientHeight,
                scrollWidth: ancestor.scrollWidth,
                scrollHeight: ancestor.scrollHeight,
            };
            break;
        }
        ancestor = ancestor.parentElement;
        depth += 1;
    }

    return result;
}"""


async def measure_canvas(page) -> dict[str, Any]:
    """Take a single, read-only, point-in-time measurement of the report
    canvas landmark and scroll state. Never raises; returns an
    {"error": ...} dict instead so callers can log-and-continue without
    affecting production control flow."""
    try:
        if not page or page.is_closed():
            return {"error": "page_closed_or_none", "timestamp": time.time()}
        measurement = await page.evaluate(_MEASURE_JS, _GENERIC_VISUAL_SELECTOR)
        measurement["timestamp"] = time.time()
        return measurement
    except Exception as exc:
        return {"error": str(exc), "timestamp": time.time()}


def _rect_delta(before: dict, after: dict) -> dict[str, Any] | None:
    b, a = before.get("canvasRect"), after.get("canvasRect")
    if not b or not a:
        return None
    return {
        "dx_left": round(a["left"] - b["left"], 2),
        "dy_top": round(a["top"] - b["top"], 2),
        "dwidth": round(a["width"] - b["width"], 2),
        "dheight": round(a["height"] - b["height"], 2),
    }


def _scroll_delta(before: dict, after: dict) -> dict[str, Any]:
    return {
        "d_window_scroll_x": round(after.get("windowScrollX", 0) - before.get("windowScrollX", 0), 2),
        "d_window_scroll_y": round(after.get("windowScrollY", 0) - before.get("windowScrollY", 0), 2),
        "d_document_scroll_top": round(after.get("documentScrollTop", 0) - before.get("documentScrollTop", 0), 2),
        "d_document_scroll_left": round(after.get("documentScrollLeft", 0) - before.get("documentScrollLeft", 0), 2),
    }


def _ancestor_scroll_delta(before: dict, after: dict) -> dict[str, Any] | None:
    b, a = before.get("scrollableAncestor"), after.get("scrollableAncestor")
    if not b or not a:
        return None
    return {
        "ancestor_tag": a.get("tag"),
        "ancestor_id": a.get("id"),
        "ancestor_class": a.get("className"),
        "d_scroll_top": round(a.get("scrollTop", 0) - b.get("scrollTop", 0), 2),
        "d_scroll_left": round(a.get("scrollLeft", 0) - b.get("scrollLeft", 0), 2),
    }


def log_delta(operation: str, target_name: str | None, before: dict, after: dict) -> None:
    """Log one structured diagnostic line comparing two measurements taken
    by the caller around an existing operation. Pure logging: never
    raises, never touches the page, never affects control flow or the
    caller's return value."""
    try:
        if before.get("error") or after.get("error"):
            logger.info(
                "CANVAS_DIAG | op=%s | target=%r | measurement_error before=%s after=%s",
                operation, target_name, before.get("error"), after.get("error"),
            )
            return

        rect_delta = _rect_delta(before, after)
        scroll_delta = _scroll_delta(before, after)
        ancestor_delta = _ancestor_scroll_delta(before, after)

        landmark_moved = bool(
            rect_delta and (abs(rect_delta["dx_left"]) > 0.5 or abs(rect_delta["dy_top"]) > 0.5)
        )
        scrolled = bool(
            abs(scroll_delta["d_window_scroll_x"]) > 0.5
            or abs(scroll_delta["d_window_scroll_y"]) > 0.5
            or abs(scroll_delta["d_document_scroll_top"]) > 0.5
            or abs(scroll_delta["d_document_scroll_left"]) > 0.5
            or (
                ancestor_delta
                and (abs(ancestor_delta["d_scroll_top"]) > 0.5 or abs(ancestor_delta["d_scroll_left"]) > 0.5)
            )
        )

        logger.info(
            "CANVAS_DIAG | op=%s | target=%r | t_before=%.3f | t_after=%.3f | "
            "landmark_found=%s | visual_count_before=%s | visual_count_after=%s | "
            "rect_delta=%s | scroll_delta=%s | ancestor_delta=%s | "
            "landmark_moved=%s | page_or_ancestor_scrolled=%s",
            operation,
            target_name,
            before.get("timestamp", 0.0),
            after.get("timestamp", 0.0),
            before.get("landmarkFound"),
            before.get("visualContainerCount"),
            after.get("visualContainerCount"),
            rect_delta,
            scroll_delta,
            ancestor_delta,
            landmark_moved,
            scrolled,
        )
    except Exception as exc:
        logger.warning("CANVAS_DIAG | logging failed | op=%s | error=%s", operation, exc)