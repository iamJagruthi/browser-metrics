"""
Browser-side DOM extraction for Power BI KPIs and visuals.

Responsibilities:
- Extract KPI/card values from the DOM.
- Extract visual metadata and DOM-visible visual content.
- Keep KPI data separate from visual data.
- Preserve scroll/tabular characteristics as metadata.
- Never modify slicer/filter selections.
- No Gemini/AI.
- No table scrolling or table export.
"""

from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import Any

from services.table_exporter import export_table_visuals


logger = logging.getLogger(__name__)


class VisualDataExporter:
    """Extract KPI and visual information directly from the Power BI DOM."""

    def __init__(self, page, dashboard_name: str = "Dashboard"):
        self.page = page
        self.dashboard_name = dashboard_name

    async def _extract_kpi_cards(self) -> list[dict[str, Any]]:
        """Extract KPI/card values directly from the DOM."""
        try:
            logger.info("Starting DOM KPI extraction")

            visual_count = await self.page.locator(
                ".visualContainer, [data-visual-container]"
            ).count()

            logger.info(
                "DOM KPI extraction | visual containers detected=%d",
                visual_count,
            )

            cards = await self.page.evaluate(
                """() => {
                    const clean = value =>
                        String(value || '')
                            .replace(/\\s+/g, ' ')
                            .trim();

                    const getText = element => {
                        if (!element) return '';

                        return clean(
                            element.innerText ||
                            element.getAttribute('aria-label') ||
                            element.textContent ||
                            ''
                        );
                    };

                    const noise =
                        /^(more options|focus mode|drill down|drill up|expand|see more)$/i;

                    // Split "50 Last Year: 45(+11%)" into current value, last period, and %.
                    const parseKpiParts = (title, rawValue) => {
                        const text = clean(rawValue);
                        let value = text;
                        let previous_value = null;
                        let variance = null;

                        const lastYear = text.match(/last\\s*year\\s*:?\\s*([^\\n]+)/i);
                        if (lastYear) {
                            previous_value = clean(lastYear[1].replace(/\\([^)]*\\)/g, ''));
                            value = clean(text.slice(0, lastYear.index));
                        }
                        const varMatch = text.match(/\\(([+-]?\\d+(?:\\.\\d+)?%?)\\)/);
                        if (varMatch) variance = varMatch[1];
                        if (title && value) {
                            value = clean(value.replace(title, ''));
                        }
                        return { value, previous_value, variance };
                    };

                    // Higher score = we found a real title and a real callout number.
                    const kpiConfidence = ({ title, value, previous_value, usedCallout }) => {
                        let score = 0.45;
                        if (title && !/^KPI Card /i.test(title)) score += 0.2;
                        if (usedCallout) score += 0.25;
                        else if (/[$€£¥%]|\\d/.test(value || '')) score += 0.1;
                        if (previous_value) score += 0.1;
                        return Math.min(0.99, Math.round(score * 100) / 100);
                    };

                    const visuals = [
                        ...document.querySelectorAll(
                            '.visualContainer, [data-visual-container]'
                        )
                    ];

                    const cards = [];

                    for (const visual of visuals) {
                        if (!visual || !visual.isConnected) continue;

                        const typeSource = [
                            visual.getAttribute('data-visual-type'),
                            visual.getAttribute('aria-roledescription'),
                            visual.className
                        ]
                            .filter(Boolean)
                            .join(' ')
                            .toLowerCase();

                        // Skip filters, tables, charts — those are not KPI cards.
                        // Note: We don't skip "button" here because some KPIs may have button-like elements.
                        if (/slicer|dropdown|table|matrix|columnchart|barchart|linechart|pie|donut|scatter/i.test(typeSource)) {
                            continue;
                        }

                        // Skip button slicers — those are not KPI cards.
                        const buttonNodes = [...visual.querySelectorAll(
                            '[role="button"], button, .buttonSlicerVisual, [class*="buttonSlicer" i]'
                        )].filter(el => {
                            const label = clean(el.innerText || el.getAttribute('aria-label'));
                            return label && !chrome.test(label);
                        });

                        const isButtonSlicer =
                            /buttonslicer|chicletslicer/i.test(typeSource)
                            || (buttonNodes.length >= 2 && /slicer|button/i.test(typeSource));

                        if (isButtonSlicer) {
                            continue;
                        }

                        // TITLE EXTRACTION
                        const titleNode = visual.querySelector(
                            '.visualTitle, [class*="visualTitle" i], [data-visual-title], [class*="title" i]'
                        );

                        let title =
                            getText(titleNode) ||
                            getText(visual.querySelector('[title]'));

                        if (!title) {
                            title = clean(visual.getAttribute('aria-label'));
                        }

                        if (title && noise.test(title)) {
                            continue;
                        }

                        // EXPANDED SELECTORS FOR POWER BI CARD / KPI VALUES
                        const valueSelectors = [
                            '[class*="calloutValue" i]',
                            '[class*="callout-value" i]',
                            '[class*="callout" i]',
                            '[class*="value-label" i]',
                            '[class*="dataLabel" i]',
                            '[class*="cardValue" i]',
                            '[class*="kpiValue" i]',
                            '[class*="value" i]',
                            'text.value',
                            'div.value'
                        ];

                        let valueNode = null;

                        for (const selector of valueSelectors) {
                            const candidate = visual.querySelector(selector);
                            if (candidate && getText(candidate)) {
                                valueNode = candidate;
                                break;
                            }
                        }

                        let value = getText(valueNode);

                        // GENERAL FALLBACK: EXTRACT NUMERIC / CURRENCY TEXT FROM VISUAL
                        if (!value) {
                            // Find elements containing digits, percentages, or currency symbols
                            const allNodes = [...visual.querySelectorAll('span, div, text, p')];
                            const numericRegex = /[$€£¥%\\d]/;

                            for (const node of allNodes) {
                                const nodeText = getText(node);
                                if (
                                    nodeText &&
                                    numericRegex.test(nodeText) &&
                                    nodeText !== title &&
                                    !noise.test(nodeText) &&
                                    nodeText.length < 50
                                ) {
                                    value = nodeText;
                                    break;
                                }
                            }
                        }

                        // LAST RESORT FALLBACK: RAW TEXT DIFFERENCE
                        if (!value) {
                            let allText = clean(visual.innerText || visual.textContent || "");
                            if (title) {
                                allText = allText.replace(title, "").trim();
                            }

                            if (!allText) {
                                const svgTexts = [...visual.querySelectorAll('svg text, [role="graphics-symbol"]')];
                                for (const t of svgTexts) {
                                    const tVal = clean(t.textContent || t.getAttribute('aria-label'));
                                    if (tVal && tVal !== title && !noise.test(tVal)) {
                                        allText = tVal;
                                        break;
                                    }
                                }
                            }

                            value = allText;
                        }

                        if (!value) {
                            continue;
                        }

                        if (value.length > 100) {
                            value = value.substring(0, 100).trim() + "...";
                        }

                        const finalTitle = title || `KPI Card ${cards.length + 1}`;
                        const parts = parseKpiParts(title, value);
                        const usedCallout = Boolean(valueNode);

                        // Keep name, value, previous, variance, and a 0-1 confidence score.
                        // Do not store extraction_source — everything here is DOM.
                        cards.push({
                            name: finalTitle,
                            value: parts.value,
                            previous_value: parts.previous_value,
                            variance: parts.variance,
                            confidence: kpiConfidence({
                                title: finalTitle,
                                value: parts.value,
                                previous_value: parts.previous_value,
                                usedCallout,
                            }),
                        });
                    }

                    const unique = new Map();

                    for (const card of cards) {
                        const key =
                            clean(card.name).toLowerCase() +
                            '|' +
                            clean(card.value).toLowerCase();

                        if (!unique.has(key)) {
                            unique.set(key, card);
                        }
                    }

                    return {
                        raw_count: cards.length,
                        unique_cards: [...unique.values()]
                    };
                }"""
            )

            raw_count = cards.get("raw_count", 0)
            unique_cards = cards.get("unique_cards", [])

            logger.info(
                "DOM KPI extraction | raw KPI candidates=%d | unique KPIs=%d",
                raw_count,
                len(unique_cards),
            )

            if not unique_cards:
                logger.warning(
                    "DOM KPI extraction completed but no KPI cards were detected"
                )
            else:
                logger.info(
                    "DOM KPI extraction completed successfully | KPI count=%d",
                    len(unique_cards),
                )

            return unique_cards

        except Exception:
            logger.exception("Unable to extract DOM KPI cards")
            return []

    async def _extract_button_groups(self) -> list[dict[str, Any]]:
        """Read button slicers (Overall, names, chips) and which option is selected."""
        try:
            groups = await self.page.evaluate(
                r"""() => {
                    const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
                    // Hide Power BI chrome so scroll arrows are not treated as filters.
                    const chrome = /^(more options|focus mode|scroll up|scroll down|scroll left|scroll right|search)$/i;

                    const isSelected = el => {
                        const pressed = (el.getAttribute('aria-pressed') || '').toLowerCase();
                        const checked = (el.getAttribute('aria-checked') || '').toLowerCase();
                        const selected = (el.getAttribute('aria-selected') || '').toLowerCase();
                        const cls = String(el.className || '');
                        return pressed === 'true' || checked === 'true' || selected === 'true'
                            || /\b(selected|isSelected|slicer-selected|checked)\b/i.test(cls);
                    };

                    const visuals = [...document.querySelectorAll('.visualContainer, [data-visual-container]')];
                    const results = [];

                    for (const visual of visuals) {
                        const typeSource = [
                            visual.getAttribute('data-visual-type'),
                            visual.getAttribute('aria-roledescription'),
                            visual.className,
                        ].filter(Boolean).join(' ').toLowerCase();

                        const buttonNodes = [...visual.querySelectorAll(
                            '[role="button"], button, .buttonSlicerVisual, [class*="buttonSlicer" i]'
                        )].filter(el => {
                            const label = clean(el.innerText || el.getAttribute('aria-label'));
                            return label && !chrome.test(label);
                        });

                        const looksLikeButtonSlicer =
                            /buttonslicer|chicletslicer|slicer/i.test(typeSource)
                            || buttonNodes.length >= 2;

                        // Skip bookmark / nav action buttons. Keep real button slicers.
                        if (!looksLikeButtonSlicer || /actionbutton|shape/i.test(typeSource)) {
                            continue;
                        }

                        const titleNode = visual.querySelector(
                            '.visualTitle, [class*="visualTitle" i], [data-visual-title]'
                        );
                        let name = clean(titleNode && (titleNode.innerText || titleNode.getAttribute('aria-label')));
                        if (!name) name = clean(visual.getAttribute('aria-label')) || 'Button group';

                        const seen = new Set();
                        const options = [];
                        for (const el of buttonNodes) {
                            const label = clean(el.innerText || el.getAttribute('aria-label'));
                            const key = label.toLowerCase();
                            if (!label || seen.has(key)) continue;
                            seen.add(key);
                            options.push({
                                label,
                                selected: isSelected(el),
                                control_type: 'button',
                            });
                        }
                        if (!options.length) continue;

                        const selected_values = options.filter(o => o.selected).map(o => o.label);
                        const available_values = options.map(o => o.label);
                        // More options + a selected chip = more confident reading.
                        let confidence = 0.55;
                        if (options.length >= 2) confidence += 0.2;
                        if (selected_values.length) confidence += 0.2;
                        if (selected_values.length > 0 && selected_values.length < options.length) confidence += 0.05;

                        results.push({
                            name,
                            filter_type: 'Buttons',
                            selected_values,
                            available_values,
                            options,
                            buttons: options.map(o => ({ label: o.label, selected: o.selected })),
                            confidence: Math.min(0.99, Math.round(confidence * 100) / 100),
                        });
                    }
                    return results;
                }"""
            )
            logger.info("Button group extraction completed | groups=%d", len(groups or []))
            return groups or []
        except Exception:
            logger.exception("Unable to extract button groups")
            return []

    async def _inspect_visual(
        self,
        locator,
        index: int,
    ) -> dict[str, Any]:
        """Inspect one Power BI visual and extract DOM-based metadata/content."""
        try:
            logger.debug(
                "Inspecting visual | dashboard=%s | index=%d",
                self.dashboard_name,
                index + 1,
            )

            metadata = await locator.evaluate(
                r"""(node, index) => {

                    const clean = value =>
                        String(value || '')
                            .replace(/\s+/g, ' ')
                            .trim();

                    const getText = element => {
                        if (!element) return '';

                        return clean(
                            element.innerText ||
                            element.getAttribute('aria-label') ||
                            element.textContent ||
                            ''
                        );
                    };

                    const unique = values =>
                        [...new Set(
                            values
                                .map(value => clean(value))
                                .filter(Boolean)
                        )];

                    const typeAttributes = [
                        node.getAttribute('data-visual-type'),
                        node.getAttribute('aria-roledescription'),
                        node.getAttribute('role'),
                        typeof node.className === 'string'
                            ? node.className
                            : ''
                    ].filter(Boolean);

                    const typeSource = typeAttributes.join(' ');

                    const chromeButton = /^(more options|focus mode|scroll up|scroll down|scroll left|scroll right|search)$/i;

                    const isSelected = el => {
                        const pressed = (el.getAttribute('aria-pressed') || '').toLowerCase();
                        const checked = (el.getAttribute('aria-checked') || '').toLowerCase();
                        const selected = (el.getAttribute('aria-selected') || '').toLowerCase();
                        return pressed === 'true' || checked === 'true' || selected === 'true'
                            || /\b(selected|isSelected|slicer-selected|checked)\b/i.test(String(el.className || ''));
                    };

                    const buttonNodes = [...node.querySelectorAll(
                        '[role="button"], button, .buttonSlicerVisual, [class*="buttonSlicer" i]'
                    )].filter(el => {
                        const label = clean(el.innerText || el.getAttribute('aria-label'));
                        return label && !chromeButton.test(label);
                    });

                    // Bookmark/nav = action button. Name chips like Overall = button slicer.
                    const isActionButton = /actionbutton|bookmark|navigation/i.test(typeSource);
                    const isButtonSlicer =
                        /buttonslicer|chicletslicer/i.test(typeSource)
                        || Boolean(node.querySelector('.buttonSlicerVisual, [class*="buttonSlicer" i]'))
                        || (buttonNodes.length >= 2 && /slicer|button/i.test(typeSource));
                    const isButton = isButtonSlicer && !isActionButton;

                    const isDropdown =
                        /dropdown/i.test(typeSource) ||
                        Boolean(node.querySelector('.dropdown, [class*="dropdown" i]'));

                    const isSlicer =
                        (
                            /slicer/i.test(typeSource) ||
                            node.matches('.slicerContainer, [class*="slicer" i], [aria-label*="Slicer" i], [data-visual-type*="slicer" i]') ||
                            Boolean(node.querySelector('.slicerContainer, [class*="slicer" i], [aria-label*="Slicer" i]')) ||
                            isDropdown
                        ) && !isButton;

                    const isKpiOrCard =
                        /card|kpi|callout|multirowcard/i.test(typeSource) && !isButton && !isSlicer;

                    // TABLE / MATRIX DETECTION
                    const visualType = clean(
                        node.getAttribute('data-visual-type')
                    ).toLowerCase();

                    const ariaRoleDescription = clean(
                        node.getAttribute('aria-roledescription')
                    ).toLowerCase();

                    const classSource = [
                        typeof node.className === 'string'
                            ? node.className
                            : '',

                        ...[...node.querySelectorAll('*')]
                            .slice(0, 300)
                            .map(element =>
                                typeof element.className === 'string'
                                    ? element.className
                                    : ''
                            )
                    ].join(' ');

                    const hasTableElement =
                        Boolean(
                            node.querySelector(
                                'table, thead, tbody, tr, td, th'
                            )
                        );

                    const hasGrid =
                        Boolean(
                            node.querySelector(
                                '[role="grid"], ' +
                                '[role="table"], ' +
                                '[role="row"], ' +
                                '[role="gridcell"], ' +
                                '[role="columnheader"], ' +
                                '[role="rowheader"]'
                            )
                        );

                    const hasPowerBITabularClass =
                        /table|matrix|pivot|tabular|grid|bodycells|headercells|rowcells/i
                            .test(classSource);

                    const hasPowerBITabularStructure =
                        Boolean(
                            node.querySelector(
                                '.mid-viewport, ' +
                                '[class*="table" i], ' +
                                '[class*="matrix" i], ' +
                                '[class*="pivot" i], ' +
                                '[class*="grid" i], ' +
                                '[class*="bodyCell" i], ' +
                                '[class*="headerCell" i], ' +
                                '[class*="rowCell" i]'
                            )
                        );

                    const isTable =
                        visualType === 'table' ||
                        ariaRoleDescription === 'table' ||
                        /\btable\b/i.test(typeSource) ||
                        /\btable\b/i.test(classSource);

                    const isMatrix =
                        visualType === 'matrix' ||
                        ariaRoleDescription === 'matrix' ||
                        /\bmatrix\b/i.test(typeSource) ||
                        /\bmatrix\b/i.test(classSource);

                    const isTabular =
                        Boolean(
                            isTable ||
                            isMatrix ||
                            (
                                (
                                    hasGrid ||
                                    hasTableElement ||
                                    hasPowerBITabularStructure ||
                                    hasPowerBITabularClass
                                ) &&
                                !isSlicer &&
                                !isKpiOrCard &&
                                !isButton &&
                                !isDropdown
                            )
                        );

                    // TITLE EXTRACTION
                    const titleSelectors = [
                        '.visualTitle',
                        '[class*="visualTitle" i]',
                        '[data-visual-title]',
                        '[class*="title" i]'
                    ];

                    let title = '';

                    for (const selector of titleSelectors) {
                        const titleNode = node.querySelector(selector);
                        const candidate = getText(titleNode);
                        if (candidate) {
                            title = candidate;
                            break;
                        }
                    }

                    if (!title) {
                        const labelled = clean(node.getAttribute('aria-label'));
                        if (labelled) title = labelled;
                    }

                    if (!title) {
                        const titled = clean(node.getAttribute('title'));
                        if (titled) title = titled;
                    }

                    // SCROLL DETECTION
                    const canScrollY = element =>
                        element.scrollHeight > element.clientHeight + 2;

                    const canScrollX = element =>
                        element.scrollWidth > element.clientWidth + 2;

                    const grid = node.querySelector(
                        '[role="grid"], [role="table"], .mid-viewport, [class*="scrollRegion" i]'
                    );

                    const scrollable =
                        Boolean(grid && canScrollY(grid)) ||
                        [...node.querySelectorAll('*')].some(element => {
                            const style = getComputedStyle(element);
                            return canScrollY(element) && /(auto|scroll|hidden)/i.test(style.overflowY);
                        });

                    const horizontallyScrollable =
                        Boolean(grid && canScrollX(grid)) ||
                        [...node.querySelectorAll('*')].some(element => {
                            const style = getComputedStyle(element);
                            return canScrollX(element) && /(auto|scroll|hidden)/i.test(style.overflowX);
                        });

                    // GRAPH / VISUAL CONTENT EXTRACTION
                    const contentSelectors = [
                        'svg text',
                        '[aria-label]',
                        '[title]',
                        '[role="img"]',
                        '[role="graphics-symbol"]',
                        '[role="graphics-document"]',
                        '[role="listitem"]'
                    ];

                    const elements = [...node.querySelectorAll(contentSelectors.join(','))];
                    const domContent = [];
                    const seenContent = new Set();

                    for (const element of elements) {
                        if (!element || !element.isConnected) continue;

                        const text =
                            getText(element) ||
                            clean(element.getAttribute('aria-label')) ||
                            clean(element.getAttribute('title'));

                        if (!text) continue;

                        const item = {
                            tag: clean(element.tagName).toLowerCase(),
                            role: clean(element.getAttribute('role')),
                            aria_label: clean(element.getAttribute('aria-label')),
                            title: clean(element.getAttribute('title')),
                            text
                        };

                        const key = [item.tag, item.role, item.aria_label, item.title, item.text].join('|');
                        if (seenContent.has(key)) continue;

                        seenContent.add(key);
                        domContent.push(item);
                    }

                    const svgText = unique([...node.querySelectorAll('svg text')].map(e => clean(e.textContent)));
                    const ariaLabels = unique([...node.querySelectorAll('[aria-label]')].map(e => clean(e.getAttribute('aria-label'))));
                    const titles = unique([...node.querySelectorAll('[title]')].map(e => clean(e.getAttribute('title'))));
                    const accessibleText = clean(node.innerText);
                    const rect = node.getBoundingClientRect();
                    const loadingText = clean(node.innerText);

                    const isLoadingPlaceholder =
                        /\bvisuals?\s+are\s+loading\b/i.test(loadingText) ||
                        /^loading(\.{3}|…)?$/i.test(loadingText);

                    const buttonLabels = buttonNodes.map(el => clean(el.innerText || el.getAttribute('aria-label'))).filter(Boolean);
                    const selectedValues = buttonNodes
                        .filter(isSelected)
                        .map(el => clean(el.innerText || el.getAttribute('aria-label')))
                        .filter(Boolean);

                    // Score how sure we are this visual was read correctly from the page.
                    let confidence = 0.4;
                    if (title && !/^Visual \d+$/i.test(title)) confidence += 0.2;
                    const knownType = clean(node.getAttribute('data-visual-type') || node.getAttribute('aria-roledescription'));
                    if (knownType && knownType !== 'unknown') confidence += 0.15;
                    if (domContent.length >= 2) confidence += 0.15;
                    if ((accessibleText || '').length > 20) confidence += 0.1;
                    if (isButton && selectedValues.length) confidence = Math.max(confidence, 0.75);
                    confidence = Math.min(0.99, Math.round(confidence * 100) / 100);

                    return {
                        id: node.getAttribute('data-visual-id') || node.id || `visual-${index + 1}`,
                        index: index,
                        title: title || `Visual ${index + 1}`,
                        visual_type: clean(node.getAttribute('data-visual-type')) || clean(node.getAttribute('aria-roledescription')) || 'unknown',
                        aria_role: clean(node.getAttribute('aria-roledescription')),
                        type_source: clean(typeSource),
                        accessible_text: accessibleText,
                        accessible_text_length: accessibleText.length,
                        dom_content: domContent,
                        svg_text: svgText,
                        aria_labels: ariaLabels,
                        titles: titles,
                        position: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        },
                        is_button: Boolean(isButton),
                        is_dropdown: Boolean(isDropdown),
                        is_kpi_or_card: Boolean(isKpiOrCard),
                        is_slicer: Boolean(isSlicer),
                        is_tabular: Boolean(isTabular),
                        is_table: Boolean(isTable),
                        is_matrix: Boolean(isMatrix),
                        scrollable: Boolean(scrollable),
                        horizontally_scrollable: Boolean(horizontallyScrollable),
                        is_loading_placeholder: Boolean(isLoadingPlaceholder),
                        selected_values: selectedValues,
                        available_values: buttonLabels,
                        options: buttonLabels.map(label => ({
                            label,
                            selected: selectedValues.includes(label),
                            control_type: 'button',
                        })),
                        buttons: buttonLabels.map(label => ({
                            label,
                            selected: selectedValues.includes(label),
                        })),
                        confidence,
                    };
                }""",
                index,
            )

            return metadata

        except Exception as exc:
            logger.exception("Visual inspection failed | dashboard=%s | index=%d", self.dashboard_name, index + 1)
            return {
                "id": f"visual-{index + 1}",
                "index": index,
                "title": f"Visual {index + 1}",
                "visual_type": "unknown",
                "is_button": False,
                "is_dropdown": False,
                "is_kpi_or_card": False,
                "is_slicer": False,
                "is_tabular": False,
                "is_table": False,
                "is_matrix": False,
                "scrollable": False,
                "horizontally_scrollable": False,
                "is_loading_placeholder": False,
                "confidence": 0.3,
                "selected_values": [],
                "available_values": [],
                "inspection_error": str(exc),
            }

    async def extract_dashboard_data(self) -> dict[str, Any]:
        """Extract dashboard data using DOM inspection."""
        result: dict[str, Any] = {
            "status": "success",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "kpi_cards": [],
            "button_groups": [],
            "visuals": [],
            "table_visuals": [],
            "table_exports": [],
            "skipped_visuals": [],
            "errors": [],
        }

        logger.info("Starting dashboard DOM extraction")
        VISUAL_SELECTOR = ".visualContainer, [data-visual-container]"

        # KPI EXTRACTION
        try:
            result["kpi_cards"] = await self._extract_kpi_cards()
            logger.info("KPI extraction completed | kpis=%d", len(result["kpi_cards"]))
        except Exception as exc:
            logger.exception("KPI extraction failed")
            result["status"] = "partial"
            result["errors"].append(f"KPI extraction failed: {exc}")

        # BUTTON SLICERS (selected chips like Overall / names)
        try:
            result["button_groups"] = await self._extract_button_groups()
            logger.info("Button extraction completed | groups=%d", len(result["button_groups"]))
        except Exception as exc:
            logger.exception("Button extraction failed")
            result["status"] = "partial"
            result["errors"].append(f"Button extraction failed: {exc}")

        # LOCATE VISUALS
        try:
            visual_count = await self.page.locator(VISUAL_SELECTOR).count()
            logger.info("Visual containers found using selector '%s' :%d", VISUAL_SELECTOR, visual_count)
        except Exception as exc:
            logger.exception("Unable to locate Power BI visuals")
            result["status"] = "failed"
            result["errors"].append(f"Unable to locate Power BI visuals: {exc}")
            return result

        if visual_count == 0:
            logger.warning("No Power BI visual containers found")
            result["status"] = "partial"
            result["errors"].append("No Power BI visual containers were found.")
            return result

        # PROCESS VISUALS
        for index in range(visual_count):
            locator = self.page.locator(VISUAL_SELECTOR).nth(index)

            try:
                if not await locator.is_visible():
                    logger.info("Skipping hidden visual | index=%d", index + 1)
                    result["skipped_visuals"].append({"index": index + 1, "reason": "hidden"})
                    continue

                visual = await self._inspect_visual(locator, index)

                # LOADING PLACEHOLDER
                if visual.get("is_loading_placeholder"):
                    logger.info("Skipping loading visual | index=%d | title=%s", index + 1, visual.get("title"))
                    result["skipped_visuals"].append({"index": index + 1, "reason": "loading_placeholder", "title": visual.get("title")})
                    continue

                # KPI / CARD — already stored in kpi_cards; do not treat as a chart.
                if visual.get("is_kpi_or_card"):
                    # Check if this KPI was already captured by _extract_kpi_cards
                    visual_title = str(visual.get("title") or "").casefold()
                    kpi_already_captured = any(
                        str(kpi.get("name") or "").casefold() == visual_title
                        for kpi in result["kpi_cards"]
                    )
                    
                    if not kpi_already_captured:
                        # Gap detected: KPI visual not captured by _extract_kpi_cards
                        # Extract KPI data from the visual inspection result
                        logger.info(
                            "KPI gap detected | index=%d | title=%s | extracting from visual inspection",
                            index + 1,
                            visual.get("title"),
                        )
                        
                        # Try to extract the KPI value from dom_content or accessible_text
                        kpi_value = None
                        dom_content = visual.get("dom_content", [])
                        
                        # Look for numeric values in dom_content
                        numeric_pattern = re.compile(r'[$€£¥%\d]')
                        for item in dom_content:
                            text = str(item.get("text", "") or "")
                            if text and numeric_pattern.search(text) and len(text) < 50:
                                kpi_value = text
                                break
                        
                        # If no value found in dom_content, try accessible_text
                        if not kpi_value:
                            accessible_text = str(visual.get("accessible_text", "") or "")
                            # Extract the first non-empty line
                            for line in accessible_text.split("\n"):
                                line = line.strip()
                                if line:
                                    kpi_value = line[:100]
                                    break
                        
                        # Add the KPI to kpi_cards if we found a value
                        if kpi_value:
                            result["kpi_cards"].append({
                                "name": visual.get("title"),
                                "value": kpi_value,
                                "previous_value": None,
                                "variance": None,
                                "confidence": visual.get("confidence", 0.5),
                            })
                            logger.info(
                                "KPI gap filled | index=%d | title=%s | value=%s",
                                index + 1,
                                visual.get("title"),
                                kpi_value,
                            )
                        else:
                            logger.warning(
                                "KPI gap could not be filled | index=%d | title=%s | no value found",
                                index + 1,
                                visual.get("title"),
                            )
                    
                    result["skipped_visuals"].append({"index": index + 1, "reason": "kpi_or_card", "title": visual.get("title")})
                    continue

                # BUTTON SLICER — keep selected options; do not treat as a chart.
                if visual.get("is_button"):
                    visual_title = str(visual.get("title") or "").casefold()
                    visual_available = set(visual.get("available_values") or [])
                    
                    # Check if this button group was already captured
                    # Match by name OR by available values (to handle name variations)
                    already = any(
                        str(item.get("name") or "").casefold() == visual_title
                        or (
                            visual_available
                            and set(item.get("available_values") or []) == visual_available
                        )
                        for item in result["button_groups"]
                    )
                    
                    if not already:
                        # Gap detected: button visual not captured by _extract_button_groups
                        logger.info(
                            "Button gap detected | index=%d | title=%s | adding from visual inspection",
                            index + 1,
                            visual.get("title"),
                        )
                        result["button_groups"].append({
                            "name": visual.get("title"),
                            "filter_type": "Buttons",
                            "selected_values": visual.get("selected_values") or [],
                            "available_values": visual.get("available_values") or [],
                            "options": visual.get("options") or [],
                            "buttons": visual.get("buttons") or [],
                            "confidence": visual.get("confidence"),
                        })
                    logger.info(
                        "Captured button visual | index=%d | title=%s | selected=%s | confidence=%s",
                        index + 1,
                        visual.get("title"),
                        visual.get("selected_values"),
                        visual.get("confidence"),
                    )
                    continue

                # SLICER / DROPDOWN
                if visual.get("is_slicer") or visual.get("is_dropdown"):
                    logger.info("Skipping slicer/dropdown from visual extraction | index=%d | title=%s", index + 1, visual.get("title"))
                    result["skipped_visuals"].append({"index": index + 1, "reason": "slicer_or_dropdown", "title": visual.get("title")})
                    continue

                # TABULAR VISUALS
                if visual.get("is_table") or visual.get("is_matrix"):
                    logger.info("Adding tabular visual for export | index=%d", index + 1)
                    result["table_visuals"].append(visual)
                    continue

                # NORMAL GRAPH / VISUAL
                logger.info("Adding DOM visual | index=%d | title=%s | type=%s", index + 1, visual.get("title"), visual.get("visual_type"))
                result["visuals"].append(visual)

            except Exception as exc:
                logger.exception("Visual extraction failed | index=%d", index + 1)
                result["status"] = "partial"
                result["errors"].append(f"Visual {index + 1}: {exc}")

        # EXPORT ALL CAPTURED TABLES AT ONCE
        if result["table_visuals"]:
            try:
                logger.info("Starting delegated table export | dashboard=%s | tables=%d", self.dashboard_name, len(result["table_visuals"]))
                result["table_exports"] = await export_table_visuals(
                    page=self.page,
                    table_visuals=result["table_visuals"],
                    dashboard_name=self.dashboard_name,
                )
                successful_exports = sum(1 for item in result["table_exports"] if item.get("status") == "downloaded")
                logger.info("Delegated table export completed | dashboard=%s | successful=%d | total=%d", self.dashboard_name, successful_exports, len(result["table_exports"]))
            except Exception as exc:
                logger.exception("Delegated table export failed | dashboard=%s", self.dashboard_name)
                result["status"] = "partial"
                result["errors"].append(f"Table export failed: {exc}")
        else:
            logger.info("No table or matrix visuals detected | dashboard=%s", self.dashboard_name)

        logger.info(
            "Dashboard DOM extraction completed | kpis=%d | buttons=%d | visuals=%d | table_visuals=%d | table_exports=%d | skipped=%d | errors=%d",
            len(result["kpi_cards"]),
            len(result["button_groups"]),
            len(result["visuals"]),
            len(result["table_visuals"]),
            len(result["table_exports"]),
            len(result["skipped_visuals"]),
            len(result["errors"]),
        )

        return result


async def extract_visual_data(page, **kwargs) -> dict[str, Any]:
    """Public convenience API for DOM KPI, visual, and table data extraction."""
    dashboard_name = kwargs.pop("dashboard_name", "Dashboard")
    if kwargs:
        logger.debug("Ignoring unsupported extract_visual_data kwargs: %s", list(kwargs.keys()))

    exporter = VisualDataExporter(page, dashboard_name=dashboard_name)
    return await exporter.extract_dashboard_data()