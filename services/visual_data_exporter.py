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
import inspect
from datetime import datetime, timezone
from typing import Any

from services.table_exporter import export_table_visuals


logger = logging.getLogger(__name__)

VISUAL_SELECTOR = ".visualContainer, [data-visual-container]"


class VisualDataExporter:
    """Extract KPI and visual information directly from the Power BI DOM."""

    def __init__(self, page, dashboard_name: str = "Dashboard",):
        self.page = page
        self.dashboard_name = dashboard_name

    async def _extract_kpi_cards(self) -> list[dict[str, Any]]:
        """
        Extract KPI/card values directly from the DOM.

        This stays separate from graph/visual extraction.
        """
        try:
            logger.info("Starting DOM KPI extraction")

            # Useful diagnostic: how many Power BI visual containers exist?
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

                        // Skip visuals that should not be treated as KPIs.
                        if (
                            /slicer|dropdown|button|table|matrix|legend|axis|tooltip/i
                                .test(typeSource)
                        ) {
                            continue;
                        }

                        const explicitCard =
                            /card|kpi|callout|multirowcard/i.test(typeSource);

                        const titleNode = visual.querySelector(
                            '.visualTitle, [class*="visualTitle" i], [data-visual-title]'
                        );

                        const title =
                            getText(titleNode) ||
                            getText(visual.querySelector('[title]'));

                        if (!title || noise.test(title)) {
                            continue;
                        }

                        const valueSelectors = [
                            '[class*="calloutValue" i]',
                            '[class*="callout-value" i]',
                            '[class*="value-label" i]',
                            '[class*="dataLabel" i]',
                            '[class*="cardValue" i]',
                            '[class*="kpiValue" i]'
                        ];

                        let valueNode = null;

                        // First priority:
                        // Look for known KPI/card value elements.
                        for (const selector of valueSelectors) {
                            const candidate =
                                visual.querySelector(selector);

                            if (candidate && getText(candidate)) {
                                valueNode = candidate;
                                break;
                            }
                        }

                        // Fallback only when this visual looks explicitly
                        // like a KPI/card visual.
                        if (!valueNode && explicitCard) {
                            const candidates = [
                                ...visual.querySelectorAll(
                                    '[class*="value" i], [class*="metric" i]'
                                )
                            ].filter(element => {
                                const text = getText(element);

                                return (
                                    text &&
                                    text !== title &&
                                    text.length <= 150
                                );
                            });

                            valueNode = candidates[0] || null;
                        }

                        const value = getText(valueNode);

                        if (!value) {
                            continue;
                        }

                        cards.push({
                            name: title,
                            value,
                            previous_value: null,
                            variance: null,
                            extraction_source: 'dom'
                        });
                    }

                    // Remove duplicate name/value pairs.
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

            if raw_count > len(unique_cards):
                logger.debug(
                    "DOM KPI extraction | removed duplicate KPI entries=%d",
                    raw_count - len(unique_cards),
                )

            # Debug only: avoids filling normal logs with every KPI.
            for card in unique_cards:
                logger.debug(
                    "DOM KPI detected | name=%r | value=%r",
                    card.get("name"),
                    card.get("value"),
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

    async def _inspect_visual(
        self,
        locator,
        index: int,
    ) -> dict[str, Any]:
        """
        Inspect one Power BI visual and extract DOM-based metadata/content.

        Responsibilities:
        - Identify visual type and title.
        - Detect KPI/card visuals.
        - Detect slicers.
        - Detect table/matrix/tabular visuals.
        - Preserve scrollability metadata.
        - Extract DOM-visible graph content.
        - Do NOT compare source and target.
        - Do NOT export table data here.
        - Do NOT call AI/LLM.
        """

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


                    // ------------------------------------------
                    // VISUAL TYPE DETECTION
                    // ------------------------------------------

                    const isKpiOrCard =
                        /card|kpi|callout|multirowcard/i
                            .test(typeSource);


                    const isSlicer =
                        /slicer/i.test(typeSource) ||

                        node.matches(
                            '.slicerContainer, ' +
                            '[class*="slicer" i], ' +
                            '[aria-label*="Slicer" i], ' +
                            '[data-visual-type*="slicer" i]'
                        ) ||

                        Boolean(
                            node.querySelector(
                                '.slicerContainer, ' +
                                '[class*="slicer" i], ' +
                                '[aria-label*="Slicer" i]'
                            )
                        );


                    // ------------------------------------------
                    // TABLE / MATRIX DETECTION
                    // ------------------------------------------

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


                    // ------------------------------------------
                    // POWER BI TABULAR DOM SIGNALS
                    // ------------------------------------------

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


                    // ------------------------------------------
                    // EXPLICIT TYPE DETECTION
                    // ------------------------------------------

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


                    // ------------------------------------------
                    // FINAL TABULAR DECISION
                    // ------------------------------------------

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
                                !isKpiOrCard
                            )
                        );
                    // ------------------------------------------
                    // TITLE EXTRACTION
                    // ------------------------------------------

                    const titleSelectors = [
                        '.visualTitle',
                        '[class*="visualTitle" i]',
                        '[data-visual-title]',
                        '[class*="title" i]'
                    ];


                    let title = '';

                    for (const selector of titleSelectors) {

                        const titleNode =
                            node.querySelector(selector);

                        const candidate =
                            getText(titleNode);

                        if (candidate) {
                            title = candidate;
                            break;
                        }
                    }


                    if (!title) {

                        const labelled =
                            clean(
                                node.getAttribute(
                                    'aria-label'
                                )
                            );

                        if (labelled) {
                            title = labelled;
                        }
                    }


                    if (!title) {

                        const titled =
                            clean(
                                node.getAttribute(
                                    'title'
                                )
                            );

                        if (titled) {
                            title = titled;
                        }
                    }


                    // ------------------------------------------
                    // SCROLL DETECTION
                    // ------------------------------------------

                    const canScrollY = element =>
                        element.scrollHeight >
                        element.clientHeight + 2;


                    const canScrollX = element =>
                        element.scrollWidth >
                        element.clientWidth + 2;


                    const grid = node.querySelector(
                        '[role="grid"], ' +
                        '[role="table"], ' +
                        '.mid-viewport, ' +
                        '[class*="scrollRegion" i]'
                    );


                    const scrollable =
                        Boolean(
                            grid &&
                            canScrollY(grid)
                        ) ||

                        [...node.querySelectorAll('*')]
                            .some(element => {

                                const style =
                                    getComputedStyle(element);

                                return (
                                    canScrollY(element) &&
                                    /(auto|scroll|hidden)/i
                                        .test(
                                            style.overflowY
                                        )
                                );
                            });


                    const horizontallyScrollable =
                        Boolean(
                            grid &&
                            canScrollX(grid)
                        ) ||

                        [...node.querySelectorAll('*')]
                            .some(element => {

                                const style =
                                    getComputedStyle(element);

                                return (
                                    canScrollX(element) &&
                                    /(auto|scroll|hidden)/i
                                        .test(
                                            style.overflowX
                                        )
                                );
                            });


                    // ------------------------------------------
                    // GRAPH / VISUAL CONTENT EXTRACTION
                    // ------------------------------------------
                    //
                    // Works generically for visuals where Power BI
                    // exposes labels/data through:
                    //
                    // - SVG text
                    // - aria-label
                    // - title
                    // - graphics symbols
                    // - canvas accessibility layers
                    //
                    // This does NOT assume a specific chart type.
                    //
                    // Therefore it can preserve information from:
                    //
                    // - bar charts
                    // - column charts
                    // - line charts
                    // - area charts
                    // - pie/donut charts
                    // - scatter plots
                    // - heatmaps
                    // - histograms
                    // - box plots
                    // - combo charts
                    // ------------------------------------------

                    const contentSelectors = [
                        'svg text',
                        '[aria-label]',
                        '[title]',
                        '[role="img"]',
                        '[role="graphics-symbol"]',
                        '[role="graphics-document"]',
                        '[role="listitem"]'
                    ];


                    const elements = [
                        ...node.querySelectorAll(
                            contentSelectors.join(',')
                        )
                    ];


                    const domContent = [];

                    const seenContent = new Set();


                    for (const element of elements) {

                        if (!element || !element.isConnected) {
                            continue;
                        }


                        const text =
                            getText(element) ||

                            clean(
                                element.getAttribute(
                                    'aria-label'
                                )
                            ) ||

                            clean(
                                element.getAttribute(
                                    'title'
                                )
                            );


                        if (!text) {
                            continue;
                        }


                        const item = {
                            tag:
                                clean(
                                    element.tagName
                                ).toLowerCase(),

                            role:
                                clean(
                                    element.getAttribute(
                                        'role'
                                    )
                                ),

                            aria_label:
                                clean(
                                    element.getAttribute(
                                        'aria-label'
                                    )
                                ),

                            title:
                                clean(
                                    element.getAttribute(
                                        'title'
                                    )
                                ),

                            text
                        };


                        const key = [
                            item.tag,
                            item.role,
                            item.aria_label,
                            item.title,
                            item.text
                        ].join('|');


                        if (seenContent.has(key)) {
                            continue;
                        }


                        seenContent.add(key);

                        domContent.push(item);
                    }


                    // ------------------------------------------
                    // SVG TEXT
                    // ------------------------------------------

                    const svgText = unique(
                        [
                            ...node.querySelectorAll(
                                'svg text'
                            )
                        ].map(
                            element =>
                                clean(
                                    element.textContent
                                )
                        )
                    );


                    // ------------------------------------------
                    // ARIA LABELS
                    // ------------------------------------------

                    const ariaLabels = unique(
                        [
                            ...node.querySelectorAll(
                                '[aria-label]'
                            )
                        ].map(
                            element =>
                                clean(
                                    element.getAttribute(
                                        'aria-label'
                                    )
                                )
                        )
                    );


                    // ------------------------------------------
                    // TITLE ATTRIBUTES
                    // ------------------------------------------

                    const titles = unique(
                        [
                            ...node.querySelectorAll(
                                '[title]'
                            )
                        ].map(
                            element =>
                                clean(
                                    element.getAttribute(
                                        'title'
                                    )
                                )
                        )
                    );


                    // ------------------------------------------
                    // ACCESSIBLE / VISIBLE TEXT
                    // ------------------------------------------

                    const accessibleText =
                        clean(node.innerText);


                    // ------------------------------------------
                    // POSITION
                    // ------------------------------------------

                    const rect =
                        node.getBoundingClientRect();


                    // ------------------------------------------
                    // LOADING DETECTION
                    // ------------------------------------------

                    const loadingText =
                        clean(node.innerText);


                    const isLoadingPlaceholder =
                        /\bvisuals?\s+are\s+loading\b/i
                            .test(loadingText) ||

                        /^loading(\.{3}|…)?$/i
                            .test(loadingText);


                    // ------------------------------------------
                    // FINAL METADATA
                    // ------------------------------------------

                    return {

                        id:
                            node.getAttribute(
                                'data-visual-id'
                            ) ||

                            node.id ||

                            `visual-${index + 1}`,


                        index: index,


                        title:
                            title ||
                            `Visual ${index + 1}`,


                        visual_type:
                            clean(
                                node.getAttribute(
                                    'data-visual-type'
                                )
                            ) ||

                            clean(
                                node.getAttribute(
                                    'aria-roledescription'
                                )
                            ) ||

                            'unknown',


                        aria_role:
                            clean(
                                node.getAttribute(
                                    'aria-roledescription'
                                )
                            ),


                        type_source:
                            clean(typeSource),


                        accessible_text:
                            accessibleText,
                        "accessible_text_length": 
                            accessibleText.length,
                            

                        // DOM graph/visual data
                        dom_content:
                            domContent,


                        svg_text:
                            svgText,


                        aria_labels:
                            ariaLabels,


                        titles,


                        // Position metadata
                        position: {
                            x:
                                Math.round(rect.x),

                            y:
                                Math.round(rect.y),

                            width:
                                Math.round(rect.width),

                            height:
                                Math.round(rect.height)
                        },


                        // Visual classification
                        is_kpi_or_card:
                            Boolean(isKpiOrCard),


                        is_slicer:
                            Boolean(isSlicer),


                        is_tabular:
                            Boolean(isTabular),


                        is_table:
                            Boolean(isTable),


                        is_matrix:
                            Boolean(isMatrix),


                        // Preserve scroll metadata
                        scrollable:
                            Boolean(scrollable),


                        horizontally_scrollable:
                            Boolean(
                                horizontallyScrollable
                            ),


                        is_loading_placeholder:
                            Boolean(
                                isLoadingPlaceholder
                            )
                    };

                }""",
                index,
            )

            logger.debug(
                "Visual inspection completed | "
                "dashboard=%s | index=%d | "
                "title=%s | type=%s | "
                "kpi=%s | slicer=%s | "
                "tabular=%s | dom_items=%d",
                self.dashboard_name,
                index + 1,
                metadata.get("title"),
                metadata.get("visual_type"),
                metadata.get("is_kpi_or_card"),
                metadata.get("is_slicer"),
                metadata.get("is_tabular"),
                len(metadata.get("dom_content", [])),
            )

            return metadata

        except Exception as exc:

            logger.exception(
                "Visual inspection failed | "
                "dashboard=%s | index=%d | error=%s",
                self.dashboard_name,
                index + 1,
                exc,
            )

            return {
                "id": f"visual-{index + 1}",
                "index": index,
                "title": f"Visual {index + 1}",
                "visual_type": "unknown",
                "aria_role": "",
                "type_source": "",
                "accessible_text": "",
                "dom_content": [],
                "svg_text": [],
                "aria_labels": [],
                "titles": [],
                "position": {
                    "x": 0,
                    "y": 0,
                    "width": 0,
                    "height": 0,
                },
                "is_kpi_or_card": False,
                "is_slicer": False,
                "is_tabular": False,
                "is_table": False,
                "is_matrix": False,
                "scrollable": False,
                "horizontally_scrollable": False,
                "is_loading_placeholder": False,
                "inspection_error": str(exc),
            }
        
    async def _extract_table_data(
        self,
        visual: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        """
        Delegate a single identified table/matrix visual to table_exporter.

        VisualDataExporter:
        - identifies the table/matrix

        table_exporter:
        - exports the actual data

        No AI/LLM is used here.
        """

        table_result: dict[str, Any] = {
            "visual_id": visual.get("id"),
            "index": index,
            "title": visual.get("title"),
            "visual_type": visual.get("visual_type"),
            "is_table": visual.get("is_table", False),
            "is_matrix": visual.get("is_matrix", False),
            "is_tabular": visual.get("is_tabular", False),
            "scrollable": visual.get("scrollable", False),
            "horizontally_scrollable": visual.get(
                "horizontally_scrollable",
                False,
            ),
            "status": "not_attempted",
            "data": None,
            "error": None,
        }

        try:
            logger.info(
                "Delegating table visual to table_exporter | "
                "dashboard=%s | index=%d | title=%s",
                self.dashboard_name,
                index + 1,
                visual.get("title"),
            )

            exported_tables = await export_table_visuals(
                page=self.page,
                table_visuals=[visual],
                dashboard_name=self.dashboard_name,
            )

            if not exported_tables:
                logger.warning(
                    "Table exporter returned no results | "
                    "dashboard=%s | title=%s",
                    self.dashboard_name,
                    visual.get("title"),
                )

                table_result["status"] = "no_data"

                return table_result

            exported = exported_tables[0]

            table_result["status"] = exported.get(
                "status",
                "unknown",
            )

            table_result["data"] = exported.get(
                "data"
            )

            table_result["error"] = exported.get(
                "error"
            )

            table_result["file_path"] = exported.get(
                "file_path"
            )

            table_result["validation_data_type"] = (
                exported.get("validation_data_type")
            )

            table_result["validation_option"] = (
                exported.get("validation_option")
            )

            table_result["validation_note"] = (
                exported.get("validation_note")
            )

            logger.info(
                "Table export completed | "
                "dashboard=%s | title=%s | status=%s",
                self.dashboard_name,
                visual.get("title"),
                table_result["status"],
            )

            return table_result

        except Exception as exc:

            logger.exception(
                "Table exporter failed | "
                "dashboard=%s | index=%d | title=%s",
                self.dashboard_name,
                index + 1,
                visual.get("title"),
            )

            table_result["status"] = "failed"
            table_result["error"] = str(exc)

            return table_result

    async def extract_dashboard_data(self) -> dict[str, Any]:
        """
        Extract dashboard data using DOM inspection.

        Responsibilities:
        - Extract KPI/card values from the DOM.
        - Extract graph/visual information from the DOM.
        - Detect tables and matrices.
        - Delegate table/matrix extraction to table_exporter.

        This function does NOT:
        - Compare source and target dashboards.
        - Call Gemini or any LLM.
        - Scroll tables manually.
        """

        result: dict[str, Any] = {
            "status": "success",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "kpi_cards": [],
            "visuals": [],
            "table_visuals": [],
            "table_exports": [],
            "skipped_visuals": [],
            "errors": [],
        }

        logger.info(
            "Starting dashboard DOM extraction"
        )

        # --------------------------------------------------
        # KPI EXTRACTION
        # --------------------------------------------------
        try:
            logger.info(
                "Starting KPI extraction"
            )

            result["kpi_cards"] = (
                await self._extract_kpi_cards()
            )

            logger.info(
                "KPI extraction completed | kpis=%d",
                len(result["kpi_cards"]),
            )

        except Exception as exc:
            logger.exception(
                "KPI extraction failed"
            )

            result["status"] = "partial"

            result["errors"].append(
                f"KPI extraction failed: {exc}"
            )

        # --------------------------------------------------
        # LOCATE VISUALS
        # --------------------------------------------------
        try:
            visual_count = (
                await self.page.locator(
                    VISUAL_SELECTOR
                ).count()
            )

            logger.info(
                "Power BI visual containers found | count=%d",
                visual_count,
            )

        except Exception as exc:
            logger.exception(
                "Unable to locate Power BI visuals"
            )

            result["status"] = "failed"

            result["errors"].append(
                f"Unable to locate Power BI visuals: {exc}"
            )

            return result

        # --------------------------------------------------
        # NO VISUALS
        # --------------------------------------------------
        if visual_count == 0:

            logger.warning(
                "No Power BI visual containers found"
            )

            result["status"] = "partial"

            result["errors"].append(
                "No Power BI visual containers were found."
            )

            return result

        # --------------------------------------------------
        # PROCESS VISUALS
        # --------------------------------------------------
        for index in range(visual_count):

            locator = (
                self.page
                .locator(VISUAL_SELECTOR)
                .nth(index)
            )

            try:

                # ------------------------------------------
                # VISIBILITY CHECK
                # ------------------------------------------
                if not await locator.is_visible():

                    logger.debug(
                        "Skipping hidden visual | index=%d",
                        index + 1,
                    )

                    result["skipped_visuals"].append(
                        {
                            "index": index + 1,
                            "reason": "hidden",
                        }
                    )

                    continue

                # ------------------------------------------
                # DOM INSPECTION
                # ------------------------------------------
                logger.debug(
                    "Inspecting visual | index=%d",
                    index + 1,
                )

                visual = await self._inspect_visual(
                    locator,
                    index,
                )

                logger.debug(
                    "Visual inspected | "
                    "index=%d | title=%s | type=%s",
                    index + 1,
                    visual.get("title"),
                    visual.get("visual_type"),
                )

                # ------------------------------------------
                # LOADING PLACEHOLDER
                # ------------------------------------------
                if visual.get(
                    "is_loading_placeholder"
                ):

                    logger.info(
                        "Skipping loading visual | "
                        "index=%d | title=%s",
                        index + 1,
                        visual.get("title"),
                    )

                    result["skipped_visuals"].append(
                        {
                            "index": index + 1,
                            "reason": "loading_placeholder",
                            "title": visual.get("title"),
                        }
                    )

                    continue

                # ------------------------------------------
                # KPI / CARD
                # ------------------------------------------
                #
                # KPI extraction is already handled by
                # _extract_kpi_cards().
                #
                # Do not add KPI visuals to graph visuals.
                #
                # ------------------------------------------

                if visual.get("is_kpi_or_card"):

                    logger.debug(
                        "Skipping KPI/card visual from "
                        "visual extraction | index=%d | title=%s",
                        index + 1,
                        visual.get("title"),
                    )

                    result["skipped_visuals"].append(
                        {
                            "index": index + 1,
                            "reason": "kpi_or_card",
                            "title": visual.get("title"),
                        }
                    )

                    continue

                # ------------------------------------------
                # SLICER
                # ------------------------------------------

                if visual.get("is_slicer"):

                    logger.debug(
                        "Skipping slicer from visual extraction | "
                        "index=%d | title=%s",
                        index + 1,
                        visual.get("title"),
                    )

                    result["skipped_visuals"].append(
                        {
                            "index": index + 1,
                            "reason": "slicer",
                            "title": visual.get("title"),
                        }
                    )

                    continue

                # ---------------------------------------------------------
                # TABLE / MATRIX EXPORT
                # ---------------------------------------------------------

                if result["table_visuals"]:

                    try:

                        logger.info(
                            "Starting delegated table export | "
                            "dashboard=%s | tables=%d",
                            self.dashboard_name,
                            len(result["table_visuals"]),
                        )

                        result["table_exports"] = (
                            await export_table_visuals(
                                page=self.page,
                                table_visuals=result["table_visuals"],
                                dashboard_name=self.dashboard_name,
                            )
                        )

                        successful_exports = sum(
                            1
                            for item in result["table_exports"]
                            if item.get("status") == "downloaded"
                        )

                        logger.info(
                            "Delegated table export completed | "
                            "dashboard=%s | successful=%d | total=%d",
                            self.dashboard_name,
                            successful_exports,
                            len(result["table_exports"]),
                        )

                    except Exception as exc:

                        logger.exception(
                            "Delegated table export failed | dashboard=%s",
                            self.dashboard_name,
                        )

                        result["status"] = "partial"

                        result["errors"].append(
                            f"Table export failed: {exc}"
                        )

                else:

                    logger.info(
                        "No table or matrix visuals detected | dashboard=%s",
                        self.dashboard_name,
                    )

                # ------------------------------------------
                # NORMAL GRAPH / VISUAL
                # ------------------------------------------

                logger.debug(
                    "Adding DOM visual | "
                    "index=%d | title=%s | type=%s",
                    index + 1,
                    visual.get("title"),
                    visual.get("visual_type"),
                )

                result["visuals"].append(
                    visual
                )

            except Exception as exc:

                logger.exception(
                    "Visual extraction failed | index=%d",
                    index + 1,
                )

                result["status"] = "partial"

                result["errors"].append(
                    f"Visual {index + 1}: {exc}"
                )

        # --------------------------------------------------
        # FINAL LOG
        # --------------------------------------------------

        logger.info(
            "Dashboard DOM extraction completed | "
            "kpis=%d | visuals=%d | table_visuals=%d | "
            "table_exports=%d | skipped=%d | errors=%d",
            len(result["kpi_cards"]),
            len(result["visuals"]),
            len(result["table_visuals"]),
            len(result["table_exports"]),
            len(result["skipped_visuals"]),
            len(result["errors"]),
        )

        return result


async def extract_visual_data(
    page,
    **kwargs,
) -> dict[str, Any]:
    """
    Public convenience API for DOM KPI, visual,
    and table data extraction.
    """

    dashboard_name = kwargs.pop(
        "dashboard_name",
        "Dashboard",
    )

    if kwargs:
        logger.debug(
            "Ignoring unsupported extract_visual_data kwargs: %s",
            list(kwargs.keys()),
        )

    exporter = VisualDataExporter(
        page,
        dashboard_name=dashboard_name,
    )

    return await exporter.extract_dashboard_data()