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
from datetime import datetime, timezone
from typing import Any

from services.table_exporter import export_table_visuals


logger = logging.getLogger(__name__)


# ============================================================================
# Shared browser-side visual-type classifier.
#
# This is injected verbatim into every page.evaluate() call that needs to
# tell visuals apart (KPI extraction, button-group extraction, generic
# visual inspection) so all three stay in sync instead of drifting, which
# was the root cause of charts/KPIs being misread before.
#
# Detection is tiered, most reliable first:
#   1. dom_class_token   - Power BI's visual host element carries a two-word
#                          class "visual <internalType>" (e.g.
#                          "visual clusteredColumnChart", "visual card",
#                          "visual kpi"). This is the actual internal visual
#                          type name Power BI itself uses and is by far the
#                          most reliable signal when present.
#   2. data_visual_type  - the data-visual-type attribute, set on many
#                          embedded/Fabric report renders.
#   3. aria_roledescription - accessibility role, present on most visuals.
#   4. keyword_match     - regex over the old combined title/class/role
#                          string (the previous approach), kept as a net.
#   5. structural_*       - retained for diagnostics only; not allowed to classify
#                          textual matched at all (custom/AppSource visuals
#                          with obfuscated GUID class names).
#
# `classifyOrGuess(node, typeSource)` is the single entry point every
# extraction function should call: it runs the tiered classifier first and
# falls back to the structural guess only if that comes back empty. Every
# eval script below is built by concatenating this constant in, so a fix or
# a new visual-type pattern here automatically applies everywhere.
# ============================================================================
_TYPE_CLASSIFIER_JS = r"""
                    const PBI_TYPE_MAP = [
                        [/^card$/, 'kpi_card', 'Card', 'card'],
                        [/^kpi$/, 'kpi_card', 'KPI', 'kpi'],
                        [/multirowcard/, 'kpi_card', 'Multi-Row Card', 'multiRowCard'],
                        [/gauge/, 'chart', 'Gauge', 'gauge'],
                        [/hundredpercentstackedcolumnchart/, 'chart', '100% Stacked Column Chart', 'column'],
                        [/stackedcolumnchart/, 'chart', 'Stacked Column Chart', 'column'],
                        [/clusteredcolumnchart/, 'chart', 'Clustered Column Chart', 'column'],
                        [/^columnchart$/, 'chart', 'Column Chart', 'column'],
                        [/hundredpercentstackedbarchart/, 'chart', '100% Stacked Bar Chart', 'bar'],
                        [/stackedbarchart/, 'chart', 'Stacked Bar Chart', 'bar'],
                        [/clusteredbarchart/, 'chart', 'Clustered Bar Chart', 'bar'],
                        [/^barchart$/, 'chart', 'Bar Chart', 'bar'],
                        [/linestackedcolumncombochart/, 'chart', 'Line and Stacked Column Chart', 'combo'],
                        [/lineclusteredcolumncombochart/, 'chart', 'Line and Clustered Column Chart', 'combo'],
                        [/combochart/, 'chart', 'Combo Chart', 'combo'],
                        [/linechart/, 'chart', 'Line Chart', 'line'],
                        [/stackedareachart/, 'chart', 'Stacked Area Chart', 'area'],
                        [/areachart/, 'chart', 'Area Chart', 'area'],
                        [/donutchart/, 'chart', 'Donut Chart', 'pie'],
                        [/piechart/, 'chart', 'Pie Chart', 'pie'],
                        [/treemap/, 'chart', 'Treemap', 'treemap'],
                        [/waterfallchart/, 'chart', 'Waterfall Chart', 'waterfall'],
                        [/scatterchart|bubblechart/, 'chart', 'Scatter Chart', 'scatter'],
                        [/ribbonchart/, 'chart', 'Ribbon Chart', 'ribbon'],
                        [/funnel/, 'chart', 'Funnel Chart', 'funnel'],
                        [/histogram/, 'chart', 'Histogram', 'histogram'],
                        [/boxplot|violinplot/, 'chart', 'Box/Violin Plot', 'statistical'],
                        [/radarchart|polarchart/, 'chart', 'Radar Chart', 'radar'],
                        [/ganttchart/, 'chart', 'Gantt Chart', 'gantt'],
                        [/sankey/, 'chart', 'Sankey Diagram', 'sankey'],
                        [/wordcloud/, 'chart', 'Word Cloud', 'wordcloud'],
                        [/arcdiagram/, 'chart', 'Arc Diagram', 'arc'],
                        [/orgchart/, 'chart', 'Org Chart', 'org'],
                        [/decompositiontree/, 'chart', 'Decomposition Tree', 'decomposition_tree'],
                        [/keydrivers|keyinfluencers/, 'chart', 'Key Influencers', 'key_influencers'],
                        [/qnavisual/, 'other', 'Q&A Visual', 'qna'],
                        [/paginatedreport|rdlvisual/, 'other', 'Paginated Report', 'paginated'],
                        [/smartnarrative/, 'other', 'Smart Narrative', 'narrative'],
                        [/filledmap|shapemap|azuremap|choropleth/, 'map', 'Filled Map', 'map'],
                        [/\bmap\b/, 'map', 'Map', 'map'],
                        [/pivottable|^matrix$/, 'matrix', 'Matrix', 'matrix'],
                        [/tableex|^table$/, 'table', 'Table', 'table'],
                        [/buttonslicer|chicletslicer/, 'slicer', 'Button Slicer', 'button_slicer'],
                        [/slicer/, 'slicer', 'Slicer', 'slicer'],
                        [/textbox/, 'other', 'Textbox', 'textbox'],
                        [/^image$/, 'other', 'Image', 'image'],
                        [/basicshape|^shape$/, 'other', 'Shape', 'shape'],
                        [/actionbutton|^button$/, 'other', 'Button', 'button'],
                    ];

                    // Shared keyword net used as a fallback signal (and, for
                    // custom/obfuscated visuals, alongside structural checks)
                    // across all three extraction paths. Previously each
                    // function kept its own copy of this regex, and one of
                    // them was missing it entirely, causing a hard crash.
                    const CHART_TOKENS = /columnchart|barchart|linechart|areachart|piechart|donutchart|scatterchart|bubblechart|waterfall|ribbonchart|funnel|gauge|treemap|filledmap|shapemap|azuremap|\bmap\b|combochart|stackedcolumn|stackedbar|stackedarea|clusteredcolumn|clusteredbar|decompositiontree|keydrivers|keyinfluencers|qnavisual|paginatedreport|sankey|wordcloud|arcdiagram|radarchart|polarchart|ganttchart|histogram|boxplot|violinplot|smartnarrative|orgchart|hundredpercent/i;

                    const extractTypeToken = node => {
                        // Power BI's visual host element carries a two-token class:
                        // "visual <internalType>", e.g. class="visual clusteredColumnChart".
                        // Search the node itself plus its shallow descendants for that pattern.
                        const candidates = [node, ...node.querySelectorAll('[class]')].slice(0, 60);
                        for (const el of candidates) {
                            const raw = typeof el.className === 'string'
                                ? el.className
                                : (el.className && el.className.baseVal) || '';
                            const tokens = raw.split(/\s+/).filter(Boolean);
                            const visualIdx = tokens.indexOf('visual');
                            if (visualIdx !== -1 && tokens.length > visualIdx + 1) {
                                return tokens[visualIdx + 1];
                            }
                        }
                        return '';
                    };

                    const classifyVisualType = (node, typeSource) => {
                        const explicitAttr = String(node.getAttribute('data-visual-type') || '').trim().toLowerCase();
                        const ariaRole = String(node.getAttribute('aria-roledescription') || '').trim().toLowerCase();
                        const classToken = extractTypeToken(node).toLowerCase();

                        const tiers = [
                            { value: classToken, method: 'dom_class_token', weight: 0.95 },
                            { value: explicitAttr, method: 'data_visual_type', weight: 0.9 },
                            { value: ariaRole, method: 'aria_roledescription', weight: 0.85 },
                        ];

                        for (const tier of tiers) {
                            if (!tier.value) continue;
                            for (const [regex, category, subtype, family] of PBI_TYPE_MAP) {
                                if (regex.test(tier.value)) {
                                    return {
                                        category, subtype, family,
                                        detection_method: tier.method,
                                        confidence: tier.weight,
                                        raw_type: tier.value,
                                    };
                                }
                            }
                        }

                        const lower = String(typeSource || '').toLowerCase();
                        for (const [regex, category, subtype, family] of PBI_TYPE_MAP) {
                            if (regex.test(lower)) {
                                return {
                                    category, subtype, family,
                                    detection_method: 'keyword_match',
                                    confidence: 0.6,
                                    raw_type: lower,
                                };
                            }
                        }

                        return null;
                    };

                    // Structural SVG/canvas guessing intentionally stays disabled for
                    // classification. It caused false positives on real Power BI DOMs
                    // (for example, detecting a Pie Chart that was not present).
                    //
                    // Power BI visuals can contain SVG paths/arcs/canvas elements for
                    // icons, overlays, accessibility layers and internal rendering.
                    // Therefore chart family/subtype is accepted only from explicit
                    // Power BI metadata or the conservative keyword tier.
                    const guessChartSubtypeByStructure = node => null;

                    // Single entry point. Explicit/tiered Power BI metadata is the
                    // source of truth; structural guessing is deliberately non-
                    // classifying so it can never steal a matrix/table into a chart.
                    const classifyOrGuess = (node, typeSource) => {
                        return classifyVisualType(node, typeSource);
                    };
"""


# ----------------------------------------------------------------------------
# KPI card extraction.
#
# Fix notes:
# - The previous version referenced `CHART_TOKENS` inside this script without
#   ever defining it (it lived only as a *local* const in the other two
#   eval scripts). That's a ReferenceError in the browser, which meant every
#   single call to `page.evaluate()` here threw, was caught by the outer
#   try/except in `_extract_kpi_cards`, and silently returned `[]`. In other
#   words: KPI extraction has not been returning any cards at all.
# - `parseKpiParts` was built by concatenating a non-raw Python string with a
#   raw one; the "last year" / variance regexes lived in the raw segment but
#   were written with doubled backslashes (`\\s`, `\\d`, `\\(`, ...), which a
#   raw string passes through literally, so the JS regex ended up matching
#   literal backslash characters instead of whitespace/digits/parens - i.e.
#   it could never match real KPI comparison text. Fixed to single backslashes.
# - Now calls the shared `classifyOrGuess` as the primary signal for
#   excluding charts/tables/matrices/slicers/maps, with the old keyword nets
#   kept as a fallback.
# ----------------------------------------------------------------------------
_KPI_EXTRACTION_JS = r"""(debug) => {
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

                    const noise =
                        /^(more options|focus mode|drill down|drill up|expand|see more)$/i;
""" + _TYPE_CLASSIFIER_JS + r"""
                    // Do not classify a visual as a chart solely from canvas/SVG
                    // structure. Those heuristics caused false positives in the
                    // dashboard under test.
                    const looksLikeChartByStructure = el => false;

                    const extractMultiRowCardRows = visual => {
                        // Best-effort: multi-row card DOM varies by theme/version, so
                        // this pairs a label-ish node with a value-ish node structurally
                        // rather than relying on one fixed selector.
                        const tileNodes = visual.querySelectorAll('[class*="card" i]:not([class*="cardHost" i])');
                        const rows = [];
                        const seen = new Set();
                        for (const tile of tileNodes) {
                            const captionEl = tile.querySelector('[class*="caption" i], [class*="label" i]');
                            const valueEl = tile.querySelector('[class*="title" i], [class*="value" i]');
                            const label = getText(captionEl);
                            const value = getText(valueEl);
                            if (!label && !value) continue;
                            const key = label.toLowerCase() + '|' + value.toLowerCase();
                            if (seen.has(key)) continue;
                            seen.add(key);
                            rows.push({ label: label || null, value: value || null });
                        }
                        return rows;
                    };

                    const chromeButton =
                        /^(more options|focus mode|scroll up|scroll down|scroll left|scroll right|search)$/i;

                    const parseKpiParts = (title, rawValue) => {
                        const text = clean(rawValue);
                        let value = text;
                        let previous_value = null;
                        let variance = null;

                        const lastYear = text.match(/last\s*year\s*:?\s*([^\n]+)/i);
                        if (lastYear) {
                            previous_value = clean(lastYear[1].replace(/\([^)]*\)/g, ''));
                            value = clean(text.slice(0, lastYear.index));
                        }
                        const varMatch = text.match(/\(([+-]?\d+(?:\.\d+)?%?)\)/);
                        if (varMatch) variance = varMatch[1];
                        if (title && value) {
                            value = clean(value.replace(title, ''));
                        }
                        return { value, previous_value, variance };
                    };

                    const kpiConfidence = ({ title, value, previous_value, usedCallout }) => {
                        let score = 0.45;
                        if (title && !/^KPI Card /i.test(title)) score += 0.2;
                        if (usedCallout) score += 0.25;
                        else if (/[$€£¥%]|\d/.test(value || '')) score += 0.1;
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

                        // Tier 1: explicit Power BI KPI/Card metadata.
                        // Tier 2: conservative DOM fallback for dashboards where
                        // the card/kpi token is not exposed on the visual container.
                        const cls = classifyOrGuess(visual, typeSource);

                        const explicitKpiSignal =
                            Boolean(cls && cls.category === 'kpi_card') ||
                            /(^|[\s_-])(card|kpi|multirowcard)([\s_-]|$)|callout/i.test(typeSource);

                        // Strong negative evidence wins over the fallback.
                        const hasTableEvidence = Boolean(
                            visual.querySelector(
                                'table, thead, tbody, tr, td, th, ' +
                                '[role="grid"], [role="table"], [role="gridcell"], ' +
                                '[class*="matrix" i], [class*="pivot" i], ' +
                                '[class*="bodyCell" i], [class*="headerCell" i], ' +
                                '[class*="rowCell" i]'
                            )
                        );

                        const hasSlicerEvidence =
                            /slicer|dropdown/i.test(typeSource) ||
                            Boolean(
                                visual.querySelector(
                                    '.slicerContainer, [class*="slicer" i], ' +
                                    '[aria-label*="Slicer" i], [role="listbox"]'
                                )
                            );

                        const hasExplicitChartEvidence =
                            Boolean(cls && (cls.category === 'chart' || cls.category === 'map')) ||
                            CHART_TOKENS.test(typeSource);

                        if (
                            (cls && ['table', 'matrix', 'slicer', 'map'].includes(cls.category)) ||
                            hasTableEvidence ||
                            hasSlicerEvidence ||
                            hasExplicitChartEvidence ||
                            looksLikeChartByStructure(visual)
                        ) {
                            continue;
                        }

                        const buttonNodes = [...visual.querySelectorAll(
                            '[role="button"], button, .buttonSlicerVisual, [class*="buttonSlicer" i]'
                        )].filter(el => {
                            const label = clean(el.innerText || el.getAttribute('aria-label'));
                            return label && !chromeButton.test(label);
                        });

                        const isButtonSlicer =
                            (cls && cls.family === 'button_slicer')
                            || /buttonslicer|chicletslicer/i.test(typeSource)
                            || (buttonNodes.length >= 2 && /slicer|button/i.test(typeSource));

                        if (isButtonSlicer) {
                            continue;
                        }

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

                        if (!value) {
                            const allNodes = [...visual.querySelectorAll('span, div, text, p')];
                            const numericRegex = /[$€£¥₹%\d]/;

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

                        if (!value) {
                            const svgTexts = [...visual.querySelectorAll('svg text, [role="graphics-symbol"]')];
                            const numericRegex = /[$€£¥₹%\\d]/;

                            for (const t of svgTexts) {
                                const tVal = clean(t.textContent || t.getAttribute('aria-label'));
                                if (
                                    tVal &&
                                    tVal !== title &&
                                    numericRegex.test(tVal) &&
                                    !noise.test(tVal) &&
                                    tVal.length <= 50
                                ) {
                                    value = tVal;
                                    break;
                                }
                            }
                        }

                        if (!value) {
                            let allText = clean(visual.innerText || visual.textContent || "");
                            if (title) {
                                allText = clean(allText.replace(title, ""));
                            }

                            // Last resort only: bounded text fallback. Reject long
                            // containers because they are usually whole visual text,
                            // not a KPI value.
                            if (allText && allText.length <= 100) {
                                value = allText;
                            }
                        }

                        if (!value) {
                            continue;
                        }

                        // Conservative fallback for KPI visuals whose DOM does not
                        // expose an explicit card/kpi token. This restores support
                        // for the real dashboard without accepting every unknown
                        // numeric visual as a KPI.
                        if (!explicitKpiSignal) {
                            const compactVisualText = clean(
                                visual.innerText || visual.textContent || ''
                            );

                            const valueLike =
                                /(?:[$€£¥₹]\s*)?[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMBT])?/i
                                    .test(value);

                            const compactLabel =
                                Boolean(title) &&
                                title.length <= 80 &&
                                !/^visual\s+\d+$/i.test(title);

                            const compactContainer =
                                compactVisualText.length > 0 &&
                                compactVisualText.length <= 180;

                            if (!valueLike || !compactLabel || !compactContainer) {
                                continue;
                            }
                        }

                        if (value.length > 100) {
                            value = value.substring(0, 100).trim() + "...";
                        }

                        const finalTitle = title || `KPI Card ${cards.length + 1}`;
                        const parts = parseKpiParts(title, value);
                        const usedCallout = Boolean(valueNode);

                        const card = {
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
                        };

                        if (debug && cls) {
                            card.type_detection = {
                                method: cls.detection_method,
                                confidence: cls.confidence,
                                raw_type: cls.raw_type,
                                family: cls.family,
                            };
                        }

                        cards.push(card);
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


# ----------------------------------------------------------------------------
# Button-group (button-slicer) extraction.
#
# Fix notes: now shares CHART_TOKENS/classifyOrGuess from _TYPE_CLASSIFIER_JS
# instead of keeping its own private copy, and uses the classifier as an
# extra, more reliable early-exit for chart/table/matrix/kpi/map visuals
# before falling back to the original keyword + structural checks.
# ----------------------------------------------------------------------------
_BUTTON_GROUP_JS = r"""(debug) => {
                    const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
                    const chrome = /^(more options|focus mode|scroll up|scroll down|scroll left|scroll right|search)$/i;
""" + _TYPE_CLASSIFIER_JS + r"""
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

                        // Chart legends and data points in complex visuals (combo
                        // charts, treemaps, decomposition trees, etc.) often render
                        // as role="button" elements too. Rule those visual families
                        // out before looking at individual button-like nodes.
                        const visualCls = classifyOrGuess(visual, typeSource);
                        if (visualCls && ['chart', 'table', 'matrix', 'kpi_card', 'map'].includes(visualCls.category)) {
                            continue;
                        }

                        if (CHART_TOKENS.test(typeSource)) {
                            continue;
                        }

                        const buttonNodes = [...visual.querySelectorAll(
                            '[role="button"], button, .buttonSlicerVisual, [class*="buttonSlicer" i]'
                        )].filter(el => {
                            const label = clean(el.innerText || el.getAttribute('aria-label'));
                            return label && !chrome.test(label);
                        });

                        const looksLikeButtonSlicer =
                            (visualCls && visualCls.family === 'button_slicer')
                            || /buttonslicer|chicletslicer|slicer/i.test(typeSource)
                            || buttonNodes.length >= 2;

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
                        let confidence = 0.55;
                        if (options.length >= 2) confidence += 0.2;
                        if (selected_values.length) confidence += 0.2;
                        if (selected_values.length > 0 && selected_values.length < options.length) confidence += 0.05;

                        const group = {
                            name,
                            filter_type: 'Buttons',
                            selected_values,
                            available_values,
                            options,
                            buttons: options.map(o => ({ label: o.label, selected: o.selected })),
                            confidence: Math.min(0.99, Math.round(confidence * 100) / 100),
                        };

                        if (debug && visualCls) {
                            group.type_detection = {
                                method: visualCls.detection_method,
                                confidence: visualCls.confidence,
                                raw_type: visualCls.raw_type,
                                family: visualCls.family,
                            };
                        }

                        results.push(group);
                    }
                    return results;
                }"""


# ----------------------------------------------------------------------------
# Generic visual inspection.
#
# Fix notes: now shares CHART_TOKENS/classifyOrGuess from _TYPE_CLASSIFIER_JS
# instead of a private copy. `cls` (the classifier result) is computed once,
# right after `typeSource`, and is used to strengthen isChart / isKpiOrCard /
# isTable / isMatrix / isSlicer / isButtonSlicer, plus a new `is_map` flag.
# The existing structural heuristics for tables/matrices are left intact
# (they're specific to what the table exporter needs) - classifier output is
# additive, not a replacement.
# ----------------------------------------------------------------------------
_VISUAL_INSPECTION_JS = r"""(node, { index, debug }) => {
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

                    const visualType = clean(
                        node.getAttribute('data-visual-type')
                    ).toLowerCase();

                    const ariaRoleDescription = clean(
                        node.getAttribute('aria-roledescription')
                    ).toLowerCase();

                    const typeAttributes = [
                        node.getAttribute('data-visual-type'),
                        node.getAttribute('aria-roledescription'),
                        node.getAttribute('role'),
                        typeof node.className === 'string'
                            ? node.className
                            : ''
                    ].filter(Boolean);

                    const typeSource = typeAttributes.join(' ');
""" + _TYPE_CLASSIFIER_JS + r"""
                    // Shared classifier result, computed once and reused below
                    // to strengthen every is_* determination.
                    const cls = classifyOrGuess(node, typeSource);

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

                    const isActionButton = /actionbutton|bookmark|navigation|weburl/i.test(typeSource);

                    const isButtonSlicer =
                        (cls && cls.family === 'button_slicer')
                        || /buttonslicer|chicletslicer/i.test(typeSource)
                        || Boolean(node.querySelector('.buttonSlicerVisual, [class*="buttonSlicer" i]'))
                        || (buttonNodes.length >= 2 && /slicer|button/i.test(typeSource));

                    const isButton = isButtonSlicer && !isActionButton;

                    const isImage =
                        visualType === 'image' ||
                        visualType === 'img' ||
                        ariaRoleDescription === 'image' ||
                        Boolean(node.querySelector('img, image, svg[class*="image" i]'));

                    const isShape =
                        /shape|basicShape|textbox|line/i.test(typeSource) ||
                        visualType === 'shape' ||
                        visualType === 'textbox';

                    const rawText = clean(node.innerText || node.getAttribute('aria-label') || '');
                    const isNavigationOrBookmarkText = /click here to|bookmark|page navigation|web url|open the document/i.test(rawText);

                    const isNonDataElement = (isActionButton || isImage || isShape || isNavigationOrBookmarkText) && !isButtonSlicer;

                    const isDropdown =
                        /dropdown/i.test(typeSource) ||
                        Boolean(node.querySelector('.dropdown, [class*="dropdown" i]'));

                    const isSlicer =
                        (
                            /slicer/i.test(typeSource) ||
                            node.matches('.slicerContainer, [class*="slicer" i], [aria-label*="Slicer" i], [data-visual-type*="slicer" i]') ||
                            Boolean(node.querySelector('.slicerContainer, [class*="slicer" i], [aria-label*="Slicer" i]')) ||
                            isDropdown ||
                            (cls && cls.category === 'slicer' && cls.family !== 'button_slicer')
                        ) && !isButton;

                    // Chart classification is intentionally conservative.
                    // Canvas/SVG counts are NOT sufficient evidence because they
                    // previously created a non-existent Pie Chart false positive.
                    const explicitChartFromClassifier = Boolean(cls && cls.category === 'chart');
                    const explicitChartFromKeywords = CHART_TOKENS.test(typeSource);

                    const isMap =
                        Boolean(cls && cls.category === 'map') ||
                        /filledmap|shapemap|azuremap|choropleth/i.test(typeSource);

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

                    const hasTableElement = Boolean(node.querySelector('table, thead, tbody, tr, td, th'));
                    const hasGrid = Boolean(node.querySelector('[role="grid"], [role="table"], [role="row"], [role="gridcell"], [role="columnheader"], [role="rowheader"]'));
                    const hasPowerBITabularClass = /table|matrix|pivot|tabular|grid|bodycells|headercells|rowcells/i.test(classSource);

                    const hasPowerBITabularStructure = Boolean(
                        node.querySelector(
                            '.mid-viewport, [class*="table" i], [class*="matrix" i], [class*="pivot" i], [class*="grid" i], [class*="bodyCell" i], [class*="headerCell" i], [class*="rowCell" i]'
                        )
                    );

                    const isTable = visualType === 'table' || ariaRoleDescription === 'table' || /\btable\b/i.test(typeSource) || /\btable\b/i.test(classSource) || (cls && cls.family === 'table');
                    const isMatrix = visualType === 'matrix' || ariaRoleDescription === 'matrix' || /\bmatrix\b/i.test(typeSource) || /\bmatrix\b/i.test(classSource) || (cls && cls.family === 'matrix');

                    // IMPORTANT: this is the proven working table/matrix
                    // detection logic. Its selectors and evidence checks are kept
                    // intact. We only resolve chart/KPI priority around it.
                    const explicitKpiOrCard =
                        (/card|kpi|callout|multirowcard/i.test(typeSource) ||
                         (cls && cls.category === 'kpi_card'))
                        && !isButton && !isSlicer;

                    // Preserve strong tabular evidence before chart routing.
                    const hasStrongTabularEvidence =
                        isTable ||
                        isMatrix ||
                        hasGrid ||
                        hasTableElement ||
                        hasPowerBITabularStructure ||
                        hasPowerBITabularClass;

                    const isChart =
                        (explicitChartFromClassifier || explicitChartFromKeywords)
                        && !isButton
                        && !isSlicer
                        && !hasStrongTabularEvidence;

                    const isKpiOrCard =
                        explicitKpiOrCard && !isChart;

                    const isTabular = Boolean(
                        isTable ||
                        isMatrix ||
                        (
                            (hasGrid || hasTableElement || hasPowerBITabularStructure || hasPowerBITabularClass)
                            && !isSlicer && !isKpiOrCard && !isButton && !isDropdown
                        )
                    );

                    const titleSelectors = ['.visualTitle', '[class*="visualTitle" i]', '[data-visual-title]', '[class*="title" i]'];
                    let title = '';
                    for (const selector of titleSelectors) {
                        const titleNode = node.querySelector(selector);
                        const candidate = getText(titleNode);
                        if (candidate) {
                            title = candidate;
                            break;
                        }
                    }

                    if (!title) title = clean(node.getAttribute('aria-label'));
                    if (!title) title = clean(node.getAttribute('title'));

                    const canScrollY = element => element.scrollHeight > element.clientHeight + 2;
                    const canScrollX = element => element.scrollWidth > element.clientWidth + 2;

                    const grid = node.querySelector('[role="grid"], [role="table"], .mid-viewport, [class*="scrollRegion" i]');
                    const scrollable = Boolean(grid && canScrollY(grid)) || [...node.querySelectorAll('*')].some(element => {
                        const style = getComputedStyle(element);
                        return canScrollY(element) && /(auto|scroll|hidden)/i.test(style.overflowY);
                    });

                    const horizontallyScrollable = Boolean(grid && canScrollX(grid)) || [...node.querySelectorAll('*')].some(element => {
                        const style = getComputedStyle(element);
                        return canScrollX(element) && /(auto|scroll|hidden)/i.test(style.overflowX);
                    });

                    const svgText = unique([...node.querySelectorAll('svg text')].map(e => clean(e.textContent)));
                    const ariaLabels = unique([...node.querySelectorAll('[aria-label]')].map(e => clean(e.getAttribute('aria-label'))));
                    const titles = unique([...node.querySelectorAll('[title]')].map(e => clean(e.getAttribute('title'))));
                    const accessibleText = clean(node.innerText);
                    const rect = node.getBoundingClientRect();
                    const loadingText = clean(node.innerText);

                    const isLoadingPlaceholder = /\bvisuals?\s+are\s+loading\b/i.test(loadingText) || /^loading(\.{3}|…)?$/i.test(loadingText);
                    const buttonLabels = buttonNodes.map(el => clean(el.innerText || el.getAttribute('aria-label'))).filter(Boolean);
                    const selectedValues = buttonNodes.filter(isSelected).map(el => clean(el.innerText || el.getAttribute('aria-label'))).filter(Boolean);

                    let confidence = 0.4;
                    if (title && !/^Visual \d+$/i.test(title)) confidence += 0.2;
                    const knownType = clean(node.getAttribute('data-visual-type') || node.getAttribute('aria-roledescription'));
                    if (knownType && knownType !== 'unknown') confidence += 0.15;
                    if ((accessibleText || '').length > 20) confidence += 0.1;
                    if (isButton && selectedValues.length) confidence = Math.max(confidence, 0.75);
                    if (cls && cls.detection_method === 'dom_class_token') confidence = Math.max(confidence, cls.confidence);
                    confidence = Math.min(0.99, Math.round(confidence * 100) / 100);

                    const result = {
                        id: node.getAttribute('data-visual-id') || node.id || `visual-${index + 1}`,
                        index: index,
                        title: title || `Visual ${index + 1}`,
                        visual_type: visualType || ariaRoleDescription || 'unknown',
                        aria_role: ariaRoleDescription,
                        type_source: clean(typeSource),
                        accessible_text: accessibleText,
                        accessible_text_length: accessibleText.length,
                        svg_text: svgText,
                        aria_labels: ariaLabels,
                        titles: titles,
                        position: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        },
                        is_non_data_element: Boolean(isNonDataElement),
                        is_button: Boolean(isButton),
                        is_dropdown: Boolean(isDropdown),
                        is_kpi_or_card: Boolean(isKpiOrCard),
                        is_chart: Boolean(isChart),
                        is_map: Boolean(isMap),
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

                    if (debug && cls) {
                        result.type_detection = {
                            method: cls.detection_method,
                            confidence: cls.confidence,
                            raw_type: cls.raw_type,
                            family: cls.family,
                            category: cls.category,
                        };
                    }

                    return result;
                }"""


class VisualDataExporter:
    """Extract KPI and visual information directly from the Power BI DOM."""

    def __init__(self, page, dashboard_name: str = "Dashboard", debug_type_detection: bool = False):
        self.page = page
        self.dashboard_name = dashboard_name
        # When true, every extracted visual/KPI carries its raw detection
        # tier + raw class/attribute token (a `type_detection` field), and a
        # summary of detection-method counts is logged. Turn this on when
        # tuning detection against a dashboard whose visuals keep landing in
        # the wrong bucket.
        self.debug_type_detection = debug_type_detection

    async def _extract_kpi_cards(self) -> list[dict[str, Any]]:
        """Extract KPI/card values directly from the DOM."""
        try:
            logger.info("Starting DOM KPI extraction")

            if self.page.is_closed():
                logger.error("Page was already closed before KPI extraction.")
                return []

            try:
                visual_count = await self.page.locator(
                    ".visualContainer, [data-visual-container]"
                ).count()
            except Exception as e:
                logger.error(f"Failed to count visual containers due to closed target: {e}")
                return []
            logger.info(
                "DOM KPI extraction | visual containers detected=%d",
                visual_count,
            )

            cards = await self.page.evaluate(_KPI_EXTRACTION_JS, self.debug_type_detection)

            raw_count = cards.get("raw_count", 0)
            unique_cards = cards.get("unique_cards", [])

            logger.info(
                "DOM KPI extraction | raw KPI candidates=%d | unique KPIs=%d",
                raw_count,
                len(unique_cards),
            )

            if self.debug_type_detection and unique_cards:
                self._log_detection_summary("kpi_cards", unique_cards)

            return unique_cards

        except Exception:
            logger.exception("Unable to extract DOM KPI cards")
            return []

    async def _extract_button_groups(self) -> list[dict[str, Any]]:
        """Read button slicers and option states."""
        try:
            groups = await self.page.evaluate(_BUTTON_GROUP_JS, self.debug_type_detection)
            logger.info("Button group extraction completed | groups=%d", len(groups or []))
            if self.debug_type_detection and groups:
                self._log_detection_summary("button_groups", groups)
            return groups or []
        except Exception:
            logger.exception("Unable to extract button groups")
            return []

    async def _inspect_visual(
        self,
        locator,
        index: int,
    ) -> dict[str, Any]:
        """Inspect one Power BI visual and extract DOM metadata."""
        try:
            metadata = await locator.evaluate(
                _VISUAL_INSPECTION_JS,
                {"index": index, "debug": self.debug_type_detection},
            )

            return metadata

        except Exception as exc:
            logger.exception("Visual inspection failed | dashboard=%s | index=%d", self.dashboard_name, index + 1)
            return {
                "id": f"visual-{index + 1}",
                "index": index,
                "title": f"Visual {index + 1}",
                "visual_type": "unknown",
                "is_non_data_element": False,
                "is_button": False,
                "is_dropdown": False,
                "is_kpi_or_card": False,
                "is_chart": False,
                "is_map": False,
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
                "type_detection": None,
                "inspection_error": str(exc),
            }

    @staticmethod
    def _log_detection_summary(label: str, items: list[dict[str, Any]]) -> None:
        """Log a count of detection methods used, for debug_type_detection tuning."""
        method_counts: dict[str, int] = {}
        for item in items:
            info = item.get("type_detection") or {}
            method = info.get("method", "heuristic_only")
            method_counts[method] = method_counts.get(method, 0) + 1
        logger.info("DOM extraction detection summary | %s=%s", label, method_counts)

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

        try:
            result["kpi_cards"] = await self._extract_kpi_cards()
        except Exception as exc:
            result["status"] = "partial"
            result["errors"].append(f"KPI extraction failed: {exc}")

        try:
            result["button_groups"] = await self._extract_button_groups()
        except Exception as exc:
            result["status"] = "partial"
            result["errors"].append(f"Button extraction failed: {exc}")

        try:
            visual_count = await self.page.locator(VISUAL_SELECTOR).count()
        except Exception as exc:
            result["status"] = "failed"
            result["errors"].append(f"Unable to locate Power BI visuals: {exc}")
            return result

        if visual_count == 0:
            result["status"] = "partial"
            result["errors"].append("No Power BI visual containers were found.")
            return result

        for index in range(visual_count):
            locator = self.page.locator(VISUAL_SELECTOR).nth(index)

            try:
                if not await locator.is_visible():
                    result["skipped_visuals"].append({"index": index + 1, "reason": "hidden"})
                    continue

                visual = await self._inspect_visual(locator, index)

                if visual.get("is_non_data_element"):
                    result["skipped_visuals"].append({
                        "index": index + 1,
                        "reason": "non_data_element",
                        "title": visual.get("title")
                    })
                    continue

                if visual.get("is_kpi_or_card"):
                    # KPI values are extracted only by _extract_kpi_cards().
                    # Do not perform a second extraction here; the old second path
                    # used different selectors and caused duplicate KPI records.
                    continue

                if visual.get("is_button"):
                    visual_title = str(visual.get("title") or "").casefold()
                    visual_available = set(visual.get("available_values") or [])

                    already = any(
                        str(item.get("name") or "").casefold() == visual_title
                        or (visual_available and set(item.get("available_values") or []) == visual_available)
                        for item in result["button_groups"]
                    )

                    if not already:
                        result["button_groups"].append({
                            "name": visual.get("title"),
                            "filter_type": "Buttons",
                            "selected_values": visual.get("selected_values") or [],
                            "available_values": visual.get("available_values") or [],
                            "options": visual.get("options") or [],
                            "buttons": visual.get("buttons") or [],
                            "confidence": visual.get("confidence"),
                        })
                    continue

                if visual.get("is_slicer") or visual.get("is_dropdown"):
                    result["skipped_visuals"].append({"index": index + 1, "reason": "slicer_or_dropdown", "title": visual.get("title")})
                    continue

                is_exportable_table = (
                    (visual.get("is_table") or visual.get("is_matrix") or visual.get("is_tabular"))
                    and not visual.get("is_button")
                    and not visual.get("is_non_data_element")
                )

                if is_exportable_table:
                    raw_title = str(visual.get("title") or "").lower()
                    if not ("click here to" in raw_title or "bookmark" in raw_title):
                        result["table_visuals"].append(visual)
                    continue

                result["visuals"].append(visual)

            except Exception as exc:
                result["status"] = "partial"
                result["errors"].append(f"Visual {index + 1}: {exc}")

        if result["table_visuals"]:
            try:
                result["table_exports"] = await export_table_visuals(
                    page=self.page,
                    table_visuals=result["table_visuals"],
                    dashboard_name=self.dashboard_name,
                )
            except Exception as exc:
                result["status"] = "partial"
                result["errors"].append(f"Table export failed: {exc}")

        if self.debug_type_detection:
            combined = result["kpi_cards"] + result["visuals"] + result["button_groups"]
            if combined:
                self._log_detection_summary("all_visuals", combined)

        return result


async def extract_visual_data(page, **kwargs) -> dict[str, Any]:
    dashboard_name = kwargs.pop("dashboard_name", "Dashboard")
    debug_type_detection = kwargs.pop("debug_type_detection", False)
    if kwargs:
        logger.debug("Ignoring unsupported extract_visual_data kwargs: %s", list(kwargs.keys()))

    exporter = VisualDataExporter(
        page,
        dashboard_name=dashboard_name,
        debug_type_detection=debug_type_detection,
    )
    return await exporter.extract_dashboard_data()