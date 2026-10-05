"""
canvas_diagnostics.py

DIAGNOSTIC-ONLY instrumentation for isolating the cause of Power BI
report-canvas / visual repositioning observed during orchestration.

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
import os
import time
from typing import Any

logger = logging.getLogger("orchestration.canvas_diagnostics")

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
            # logger.info(
            #     "CANVAS_DIAG | op=%s | target=%r | measurement_error before=%s after=%s",
            #     operation, target_name, before.get("error"), after.get("error"),
            # )
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

        # logger.info(
        #     "CANVAS_DIAG | op=%s | target=%r | t_before=%.3f | t_after=%.3f | "
        #     "landmark_found=%s | visual_count_before=%s | visual_count_after=%s | "
        #     "rect_delta=%s | scroll_delta=%s | ancestor_delta=%s | "
        #     "landmark_moved=%s | page_or_ancestor_scrolled=%s",
        #     operation,
        #     target_name,
        #     before.get("timestamp", 0.0),
        #     after.get("timestamp", 0.0),
        #     before.get("landmarkFound"),
        #     before.get("visualContainerCount"),
        #     after.get("visualContainerCount"),
        #     rect_delta,
        #     scroll_delta,
        #     ancestor_delta,
        #     landmark_moved,
        #     scrolled,
        # )
    except Exception as exc:
        logger.warning("CANVAS_DIAG | logging failed | op=%s | error=%s", operation, exc)


# ---------------------------------------------------------------------------
# TARGET-AWARE SCROLL-CHAIN INSTRUMENTATION (TEMPORARY)
#
# Records, for any given element locator, the scroll containers that can move
# when the element is scrolled into view (the target's own scrollable ancestor
# chain plus window/document), including container identity (tag/id/class
# discovered via computed style -- never hardcoded) and scrollLeft/scrollTop.
#
# Usage pattern (behavior-neutral; never raises, never alters control flow):
#     before = await measure_scroll_chain(page, locator)
#     <existing operation that may scroll>
#     after  = await measure_scroll_chain(page, locator)
#     log_scroll_delta("my.op", target_label, before, after, "after_scroll")
#
# Logging is gated behind CANVAS_DIAG=1 so normal runs stay clean and the
# whole block is intended to be removed once the diagnosis is confirmed.
# ---------------------------------------------------------------------------


_DIAG_DIAL_EXEC = os.environ.get("CANVAS_DIAG") == "1"

# Walks a target element's ancestor chain, listing EVERY ancestor (any
# overflow type, including overflow:hidden which scrollIntoView can scroll)
# with its identity and scroll offsets, plus window/document offsets and the
# target's own bounding rect + in-viewport status. No dashboard/visual/page-
# name/coordinate knowledge.
_MEASURE_CHAIN_JS = """(node) => {
    const result = {
        found: !!node,
        targetInViewport: false,
        targetRect: null,
        windowScrollX: window.scrollX,
        windowScrollY: window.scrollY,
        documentScrollTop: document.documentElement.scrollTop,
        documentScrollLeft: document.documentElement.scrollLeft,
        anchor: null,
        ancestors: [],
    };
    if (!node) return result;

    const r = node.getBoundingClientRect();
    result.targetInViewport = (
        r.top >= 0 && r.left >= 0 &&
        r.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
        r.right <= (window.innerWidth || document.documentElement.clientWidth)
    );
    result.targetRect = {
        top: Math.round(r.top), left: Math.round(r.left),
        bottom: Math.round(r.bottom), right: Math.round(r.right),
    };
    result.anchor = {
        tag: node.tagName,
        id: node.id || null,
        cls: (node.className && node.className.toString)
            ? node.className.toString().slice(0, 120)
            : null,
    };

    let ancestor = node.parentElement;
    let depth = 0;
    while (ancestor && depth < 25) {
        const style = window.getComputedStyle(ancestor);
        result.ancestors.push({
            depth: depth,
            tag: ancestor.tagName,
            id: ancestor.id || null,
            cls: (ancestor.className && ancestor.className.toString)
                ? ancestor.className.toString().slice(0, 120)
                : null,
            overflowX: style.overflowX,
            overflowY: style.overflowY,
            transform: (style.transform && style.transform !== "none")
                ? style.transform.slice(0, 60)
                : null,
            scrollTop: ancestor.scrollTop,
            scrollLeft: ancestor.scrollLeft,
            clientWidth: ancestor.clientWidth,
            clientHeight: ancestor.clientHeight,
            scrollWidth: ancestor.scrollWidth,
            scrollHeight: ancestor.scrollHeight,
            rect: (() => {
                const b = ancestor.getBoundingClientRect();
                return { left: Math.round(b.left), top: Math.round(b.top) };
            })(),
        });
        ancestor = ancestor.parentElement;
        depth += 1;
    }

    return result;
}"""


async def measure_scroll_chain(page, locator=None) -> dict[str, Any]:
    """Read-only measurement of a target element's scrollable ancestor chain.

    ``locator`` may be a Playwright locator (evaluated on its first match) or
    None, in which case the nearest visual container is used as the anchor.
    Never raises; returns an {"error": ...} dict instead."""
    try:
        if not page or page.is_closed():
            return {"error": "page_closed_or_none", "timestamp": time.time()}
        if locator is not None:
            try:
                if await locator.count() == 0:
                    return {"error": "locator_not_found", "timestamp": time.time()}
            except Exception as exc:
                return {"error": f"locator_count_failed:{exc}", "timestamp": time.time()}
            measurement = await locator.first.evaluate(_MEASURE_CHAIN_JS)
        else:
            visual = page.locator(_GENERIC_VISUAL_SELECTOR).first
            if await visual.count() == 0:
                return {"error": "no_visual_anchor", "timestamp": time.time()}
            measurement = await visual.evaluate(_MEASURE_CHAIN_JS)
        measurement["timestamp"] = time.time()
        return measurement
    except Exception as exc:
        return {"error": str(exc), "timestamp": time.time()}


def _ancestor_deltas(before: dict, after: dict) -> list[dict[str, Any]]:
    b_map = {a.get("depth"): a for a in (before.get("ancestors") or [])}
    deltas = []
    for a in (after.get("ancestors") or []):
        b = b_map.get(a.get("depth"))
        if b is None:
            continue
        d_top = round((a.get("scrollTop") or 0) - (b.get("scrollTop") or 0), 2)
        d_left = round((a.get("scrollLeft") or 0) - (b.get("scrollLeft") or 0), 2)
        b_rect = b.get("rect") or {}
        a_rect = a.get("rect") or {}
        d_x = round((a_rect.get("left") or 0) - (b_rect.get("left") or 0), 2)
        d_y = round((a_rect.get("top") or 0) - (b_rect.get("top") or 0), 2)
        if abs(d_top) > 0.01 or abs(d_left) > 0.01 or abs(d_x) > 0.01 or abs(d_y) > 0.01:
            deltas.append({
                "depth": a.get("depth"),
                "container": a.get("tag"),
                "id": a.get("id"),
                "cls": a.get("cls"),
                "overflow": f"{a.get('overflowX')}/{a.get('overflowY')}",
                "d_scroll_top": d_top,
                "d_scroll_left": d_left,
                "d_rect_x": d_x,
                "d_rect_y": d_y,
                "scrollTop": a.get("scrollTop"),
                "scrollLeft": a.get("scrollLeft"),
            })
    return deltas


def log_scroll_delta(
    operation: str,
    target_name: str | None,
    before: dict,
    after: dict,
    phase: str,
) -> None:
    """Log one structured diagnostic line comparing a before/after scroll-chain
    measurement. Pure logging, gated by CANVAS_DIAG=1; never raises, never
    touches the page, never affects control flow."""
    if not _DIAG_DIAL_EXEC:
        return
    try:
        if before.get("error") or after.get("error"):
            logger.info(
                "CANVAS_DIAG | op=%s | phase=%s | target=%r | measurement_error before=%s after=%s",
                operation, phase, target_name, before.get("error"), after.get("error"),
            )
            return

        deltas = _ancestor_deltas(before, after)
        win_dx = round((after.get("windowScrollX") or 0) - (before.get("windowScrollX") or 0), 2)
        win_dy = round((after.get("windowScrollY") or 0) - (before.get("windowScrollY") or 0), 2)
        doc_dx = round((after.get("documentScrollLeft") or 0) - (before.get("documentScrollLeft") or 0), 2)
        doc_dy = round((after.get("documentScrollTop") or 0) - (before.get("documentScrollTop") or 0), 2)
        b_rect = before.get("targetRect") or {}
        a_rect = after.get("targetRect") or {}
        target_dx = round((a_rect.get("left") or 0) - (b_rect.get("left") or 0), 2)
        target_dy = round((a_rect.get("top") or 0) - (b_rect.get("top") or 0), 2)

        logger.info(
            "CANVAS_DIAG | op=%s | phase=%s | target=%r | "
            "in_view_before=%s -> in_view_after=%s | target_rect_delta=(%s,%s) | "
            "window_scroll_delta=(%s,%s) | document_scroll_delta=(%s,%s) | ancestor_scroll_deltas=%s",
            operation,
            phase,
            target_name,
            before.get("targetInViewport"),
            after.get("targetInViewport"),
            target_dx, target_dy,
            win_dx, win_dy,
            doc_dx, doc_dy,
            deltas if deltas else "none",
        )
    except Exception as exc:
        logger.warning("CANVAS_DIAG | logging failed | op=%s | phase=%s | error=%s", operation, phase, exc)