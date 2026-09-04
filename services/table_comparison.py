"""Pandas-based comparison of Power BI table/matrix visuals from DOM extraction.

Features:
- Robust Tabular visual & CSV export detection
- Fallback DOM parsing when file downloads fail
- Multi-tier pairing (Title first, Index position fallback)
- DataFrame conversion and row/column diff reporting across unaligned shapes
- Standardized execution state tracking (TABLE_DETECTED -> TABLE_COMPARED)
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from utils.config import TABLE_COMPARE_KEY_COLUMNS, TABLE_COMPARE_KEY_STRATEGY

logger = logging.getLogger(__name__)

def _display_value(value: Any) -> str:
    """
    Preserve the exact displayed value for strict validation.

    No:
    - numeric normalization
    - currency removal
    - comma removal
    - case normalization
    - whitespace collapsing

    Only Python/Pandas missing values are represented as an empty string.
    """
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    return str(value)

def _values_match(
    source_value: Any,
    target_value: Any,
) -> bool:
    """
    Strict rendered-value comparison.

    Formatting differences are intentional mismatches.
    """
    return _display_value(source_value) == _display_value(target_value)


def _visual_key(visual: dict[str, Any]) -> str:
    return " ".join(str(visual.get("title") or visual.get("id") or "").casefold().split())


def is_tabular_visual(visual: dict[str, Any]) -> bool:
    """
    Return True only when there is actual evidence that this visual
    represents table/matrix data.

    NOTE:
    scrollable/horizontally_scrollable is intentionally NOT sufficient
    by itself here. Scrollability can still be used by table_exporter
    as an export fallback signal.
    """
    try:
        if visual.get("is_slicer"):
            return False

        visual_type = str(visual.get("visual_type", "")).strip()

        # Explicit non-tabular visual types should never become tables
        # merely because their container is scrollable.
        if re.search(
            r"slicer|dropdown|button|image|textbox|text box|"
            r"chart|graph|map|gauge",
            visual_type,
            re.IGNORECASE,
        ):
            return False

        data = visual.get("data") or {}

        if data.get("collection_method") == "slicer_skipped":
            return False

        rows = data.get("rows") or []
        columns = data.get("columns") or []

        # Explicit tabular signal from the extractor.
        if visual.get("is_tabular"):
            return True

        # Explicit table/matrix metadata.
        if re.search(r"table|matrix|pivot", visual_type, re.IGNORECASE):
            return True

        # Actual extracted tabular structure.
        if columns and rows:
            return True

        if rows and any(len(row) > 1 for row in rows):
            return True

        # Columns alone can represent a valid empty table/matrix.
        if columns:
            return True

        return False

    except Exception:
        logger.exception(
            "Unable to classify visual as tabular | visual=%s",
            visual.get("title"),
        )
        return False

def _has_exported_data(visual: dict[str, Any]) -> bool:
    """
    Return True only when a successful export contains actual
    comparable tabular content.
    """
    if visual.get("status") != "downloaded":
        return False

    data = visual.get("data") or {}

    rows = data.get("rows") or []
    columns = data.get("columns") or []

    if not rows:
        return False

    if not columns:
        return False

    # Reject exports that contain only Power BI metadata/filter text.
    metadata_only = all(
        isinstance(value, str)
        and value.strip().lower().startswith("applied filters:")
        for row in rows
        for value in row
    )

    if metadata_only:
        return False

    return True

def visual_to_dataframe(visual: dict[str, Any]) -> pd.DataFrame:
    try:
        data = visual.get("data") or {}
        columns = [str(c) for c in data.get("columns", [])]
        rows = data.get("rows", [])

        if columns or rows:
            width = len(columns) if columns else max((len(r) for r in rows), default=0)
            if width > 0:
                gen_cols = columns or [f"Column {i+1}" for i in range(width)]
                norm = [
                    [str(v) if v is not None else "" for v in r] + [""] * max(0, width - len(r))
                    for r in rows
                ]
                return pd.DataFrame([r[:width] for r in norm], columns=gen_cols)

        accessible_text = visual.get("accessible_text", "")
        if accessible_text:
            lines = [line.strip() for line in accessible_text.split("\n") if line.strip()]
            if lines:
                return pd.DataFrame({"DOM_Content": lines})

        return pd.DataFrame()
    except Exception:
        logger.exception("Failed to convert visual to DataFrame | visual=%s", visual.get("title"))
        return pd.DataFrame()


def _columns_are_unique_key(
    df: pd.DataFrame,
    key_columns: list[str],
) -> bool:
    """
    Return True only when the proposed key columns are:

    - present
    - non-null
    - non-empty
    - unique
    """
    if df.empty or not key_columns:
        return False

    if not all(column in df.columns for column in key_columns):
        return False

    subset = df[key_columns].copy()

    # Check actual Pandas nulls BEFORE string conversion.
    if subset.isna().any().any():
        return False

    # Empty string should not be considered a reliable key.
    for column in key_columns:
        if subset[column].map(
            lambda value: _display_value(value) == ""
        ).any():
            return False

    # Exact value uniqueness.
    normalized = subset.map(_display_value)

    return not normalized.duplicated(keep=False).any()


def determine_key_strategy(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
) -> tuple[list[str], str, bool, str | None]:
    """Choose row-matching columns using configured strategy or safe automatic fallbacks."""
    warning: str | None = None
    strategy = TABLE_COMPARE_KEY_STRATEGY.casefold()

    if strategy == "configured" and TABLE_COMPARE_KEY_COLUMNS:
        keys = [column for column in TABLE_COMPARE_KEY_COLUMNS if column in source_df.columns and column in target_df.columns]
        if keys and _columns_are_unique_key(source_df, keys) and _columns_are_unique_key(target_df, keys):
            return keys, "configured", True, None
        warning = "Configured key columns are missing or not unique in both tables."
        return keys or list(TABLE_COMPARE_KEY_COLUMNS), "configured", False, warning

    if strategy == "first_column":
        if len(source_df.columns) and source_df.columns[0] in target_df.columns:
            keys = [source_df.columns[0]]
            reliable = _columns_are_unique_key(source_df, keys) and _columns_are_unique_key(target_df, keys)
            if not reliable:
                warning = "First column is not a unique key in both tables."
            return keys, "first_column", reliable, warning

    if strategy == "all_columns":
        keys = [str(column) for column in source_df.columns if column in target_df.columns]
        reliable = keys and _columns_are_unique_key(source_df, keys) and _columns_are_unique_key(target_df, keys)
        if not reliable:
            warning = "All common columns do not form a unique key in both tables."
        return keys, "all_columns", bool(reliable), warning

    if strategy == "row_index":
        return [], "row_index", False, "Row index matching was explicitly configured; keys are not reliable."

    # Auto strategy
    if TABLE_COMPARE_KEY_COLUMNS:
        keys = [column for column in TABLE_COMPARE_KEY_COLUMNS if column in source_df.columns and column in target_df.columns]
        if keys and _columns_are_unique_key(source_df, keys) and _columns_are_unique_key(target_df, keys):
            return keys, "configured", True, None

    if len(source_df.columns) and source_df.columns[0] in target_df.columns:
        keys = [source_df.columns[0]]
        if _columns_are_unique_key(source_df, keys) and _columns_are_unique_key(target_df, keys):
            return keys, "first_column", True, None

    keys = [str(column) for column in source_df.columns if column in target_df.columns]
    if keys and _columns_are_unique_key(source_df, keys) and _columns_are_unique_key(target_df, keys):
        return keys, "all_columns", True, None

    warning = "No reliable unique key could be determined; comparison uses row position."
    return [], "row_index", False, warning


def _record_key_values(row: pd.Series, key_columns: list[str], row_number: int) -> dict[str, str]:
    if key_columns:
        return {column: str(row.get(column, "")) for column in key_columns}
    return {"row_number": str(row_number)}


def compare_dataframes(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    visual_title: str,
) -> dict[str, Any]:
    """Compare two extracted tables and classify rows and cell-level differences even with shape mismatches."""
    try:
        key_columns, key_strategy, key_reliable, key_warning = determine_key_strategy(source_df, target_df)
        source_only_columns = [str(column) for column in source_df.columns if column not in target_df.columns]
        target_only_columns = [str(column) for column in target_df.columns if column not in source_df.columns]
        
        column_differences = [
            {"visual": visual_title, "column": column, "presence": "Source only"}
            for column in source_only_columns
        ] + [
            {"visual": visual_title, "column": column, "presence": "Target only"}
            for column in target_only_columns
        ]

        matched_records: list[dict[str, Any]] = []
        mismatched_records: list[dict[str, Any]] = []
        missing_in_source: list[dict[str, Any]] = []
        missing_in_target: list[dict[str, Any]] = []

        if key_reliable and key_columns:
            common_value_columns = [
                str(column)
                for column in source_df.columns
                if column in target_df.columns and column not in key_columns
            ]
            source_named = source_df.copy()
            target_named = target_df.copy()
            for column in common_value_columns:
                source_named = source_named.rename(columns={column: f"{column}__src"})
                target_named = target_named.rename(columns={column: f"{column}__tgt"})

            merged = source_named.merge(
                target_named,
                on=key_columns,
                how="outer",
                indicator=True,
            )

            for _, row in merged.iterrows():
                key_values = _record_key_values(row, key_columns, 0)
                if row["_merge"] == "left_only":
                    missing_in_target.append(
                        {
                            "visual": visual_title,
                            "key_strategy": key_strategy,
                            "keys": key_values,
                            "row": {column: str(row.get(column, "")) for column in source_df.columns},
                        }
                    )
                    continue
                if row["_merge"] == "right_only":
                    missing_in_source.append(
                        {
                            "visual": visual_title,
                            "key_strategy": key_strategy,
                            "keys": key_values,
                            "row": {column: str(row.get(column, "")) for column in target_df.columns},
                        }
                    )
                    continue

                cell_diffs = []
                for column in common_value_columns:
                    source_value = _display_value(
                        row.get(f"{column}__src", "")
                    )

                    target_value = _display_value(
                        row.get(f"{column}__tgt", "")
                    )

                    if not _values_match(source_value, target_value):
                        cell_diffs.append(
                            {
                                "column": column,
                                "source_value": source_value,
                                "target_value": target_value,
                            }
                        )

                record = {
                    "visual": visual_title,
                    "key_strategy": key_strategy,
                    "keys": key_values,
                    "source_row": {
                        column: str(row.get(column if column in key_columns else f"{column}__src", ""))
                        for column in source_df.columns
                    },
                    "target_row": {
                        column: str(row.get(column if column in key_columns else f"{column}__tgt", ""))
                        for column in target_df.columns
                    },
                }
                if cell_diffs:
                    mismatched_records.append({**record, "differences": cell_diffs})
                else:
                    matched_records.append(record)
        else:
            # Fallback when key strategy is row_index or keys are unavailable.
            #
            # This can produce cascade mismatches when one side has an inserted
            # or missing row, so log it explicitly for diagnosis.
            logger.warning(
                "Using row-position comparison | visual=%s | "
                "source_rows=%s | target_rows=%s | warning=%s",
                visual_title,
                len(source_df),
                len(target_df),
                key_warning,
            )

            max_rows = max(len(source_df), len(target_df))
            shared_columns = [str(column) for column in source_df.columns if column in target_df.columns]
            
            for row_number in range(max_rows):
                has_source = row_number < len(source_df)
                has_target = row_number < len(target_df)
                key_values = {"row_number": str(row_number + 1)}

                if has_source and not has_target:
                    source_row = source_df.iloc[row_number]
                    missing_in_target.append(
                        {
                            "visual": visual_title,
                            "key_strategy": key_strategy,
                            "keys": key_values,
                            "row": {column: str(source_row.get(column, "")) for column in source_df.columns},
                        }
                    )
                    continue

                if has_target and not has_source:
                    target_row = target_df.iloc[row_number]
                    missing_in_source.append(
                        {
                            "visual": visual_title,
                            "key_strategy": key_strategy,
                            "keys": key_values,
                            "row": {column: str(target_row.get(column, "")) for column in target_df.columns},
                        }
                    )
                    continue

                source_row = source_df.iloc[row_number]
                target_row = target_df.iloc[row_number]

                cell_diffs = []
                for column in shared_columns:
                    source_value = _display_value(
                        source_row.get(column, "")
                    )

                    target_value = _display_value(
                        target_row.get(column, "")
                    )

                    if not _values_match(source_value, target_value):
                        cell_diffs.append(
                            {
                                "column": column,
                                "source_value": source_value,
                                "target_value": target_value,
                            }
                        )

                record = {
                    "visual": visual_title,
                    "key_strategy": key_strategy,
                    "keys": key_values,
                    "source_row": {column: str(source_row.get(column, "")) for column in source_df.columns},
                    "target_row": {column: str(target_row.get(column, "")) for column in target_df.columns},
                }
                if cell_diffs:
                    mismatched_records.append({**record, "differences": cell_diffs})
                else:
                    matched_records.append(record)

        comparison_confidence = (
            "high"
            if key_reliable
            else "medium"
            if len(source_df) == len(target_df)
            else "low"
        )

        mismatched_cells = sum(len(item.get("differences", [])) for item in mismatched_records)
        shape_mismatch = bool(source_only_columns or target_only_columns or len(source_df) != len(target_df))
        status = "TABLE_MATCHED"
        if missing_in_source or missing_in_target or mismatched_records or column_differences or shape_mismatch:
            status = "TABLE_MISMATCHED"

        return {
            "visual": visual_title,
            "status": status,
            "shape_mismatch": shape_mismatch,
            "key_strategy": key_strategy,
            "key_columns": key_columns,
            "key_reliable": key_reliable,
            "key_warning": key_warning,
            "source_only_columns": source_only_columns,
            "target_only_columns": target_only_columns,
            "column_differences": column_differences,
            "matched_records": matched_records,
            "mismatched_records": mismatched_records,
            "missing_in_source": missing_in_source,
            "missing_in_target": missing_in_target,
            "source_rows": source_df.values.tolist(),
            "source_columns": [str(column) for column in source_df.columns],
            "target_rows": target_df.values.tolist(),
            "target_columns": [str(column) for column in target_df.columns],
            "comparison_confidence": comparison_confidence,
            "summary": {
                "matched_rows": len(matched_records),
                "mismatched_rows": len(mismatched_records),
                "missing_in_source_rows": len(missing_in_source),
                "missing_in_target_rows": len(missing_in_target),
                "source_row_count": len(source_df),
                "target_row_count": len(target_df),
                "source_column_count": len(source_df.columns),
                "target_column_count": len(target_df.columns),
                "mismatched_cells": mismatched_cells,
            },
        }
    except Exception:
        logger.exception("Table comparison failed | visual=%s", visual_title)
        return {
            "visual": visual_title,
            "status": "TABLE_NOT_COMPARED",
            "key_strategy": "unknown",
            "key_columns": [],
            "key_reliable": False,
            "key_warning": "Comparison failed due to an unexpected error.",
            "source_only_columns": [],
            "target_only_columns": [],
            "column_differences": [],
            "matched_records": [],
            "mismatched_records": [],
            "missing_in_source": [],
            "missing_in_target": [],
            "source_rows": [],
            "source_columns": [],
            "target_rows": [],
            "target_columns": [],
            "summary": {},
        }


def _get_export_data(dash_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Build the list of comparable table/matrix visuals.

    Priority:
    1. Successful exported data
    2. DOM-extracted table/matrix data

    Export fallback remains supported, but a failed export is never
    treated as valid comparison data merely because the visual is
    scrollable.
    """
    visual_data = dash_dict.get("visual_data") or dash_dict

    table_exports = visual_data.get("table_exports", []) or []
    table_visuals = visual_data.get("table_visuals", []) or []
    general_visuals = visual_data.get("visuals", []) or []

    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # ---------------------------------------------------------
    # 1. Successful exports
    # ---------------------------------------------------------
    #
    # Keep exported data only when:
    #
    # A) The visual is known to be tabular
    # OR
    # B) The exporter returned actual structured data and this was
    #    an export fallback candidate.
    #
    for item in table_exports:
        if not _has_exported_data(item):
            continue

        if not is_tabular_visual(item):
            # Export fallback:
            # The DOM classification may be unavailable, but the export
            # contains structured rows/columns.
            #
            # Only allow this when the exporter itself marks the visual
            # as tabular or the visual has no explicit chart/image/text type.
            visual_type = str(item.get("visual_type", "")).strip()

            if visual_type and re.search(
                r"chart|graph|image|textbox|text box|map|gauge|slicer",
                visual_type,
                re.IGNORECASE,
            ):
                logger.debug(
                    "Skipping non-tabular exported visual | title=%s | type=%s",
                    item.get("title"),
                    visual_type,
                )
                continue

        key = _visual_key(item)

        if key and key in seen_keys:
            continue

        if key:
            seen_keys.add(key)

        merged.append(item)

    # ---------------------------------------------------------
    # 2. DOM table/matrix candidates
    # ---------------------------------------------------------
    #
    # Prefer table_visuals.
    #
    # If that list is empty, inspect general visuals as a fallback.
    #
    dom_pool = [
        *table_visuals,
        *general_visuals,
    ]

    for item in dom_pool:
        if not is_tabular_visual(item):
            continue

        key = _visual_key(item)

        if key and key in seen_keys:
            continue

        if key:
            seen_keys.add(key)

        merged.append(item)

    return merged
def _get_visual_index(visual: dict[str, Any]) -> Any:
    """
    Return the visual index without treating 0 as a missing value.
    """
    if visual.get("visual_index") is not None:
        return visual.get("visual_index")

    return visual.get("index")

def pair_source_and_target_tables(
    source_exports: list[dict[str, Any]],
    target_exports: list[dict[str, Any]],
) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    """
    Pair source and target table/matrix visuals.

    Priority:
    1. Normalized title
    2. Visual index

    Index is only a fallback and is logged because visual order can
    change after migration.
    """
    pairs: list[
        tuple[dict[str, Any] | None, dict[str, Any] | None]
    ] = []

    target_remaining = list(target_exports)

    # ---------------------------------------------------------
    # 1. Match by title
    # ---------------------------------------------------------
    for source_visual in source_exports:
        source_key = _visual_key(source_visual)

        match = None

        if source_key:
            for target_visual in target_remaining:
                if _visual_key(target_visual) == source_key:
                    match = target_visual
                    break

        if match is not None:
            pairs.append((source_visual, match))
            target_remaining.remove(match)
        else:
            pairs.append((source_visual, None))

    # ---------------------------------------------------------
    # 2. Match remaining source visuals by index
    # ---------------------------------------------------------
    final_pairs: list[
        tuple[dict[str, Any] | None, dict[str, Any] | None]
    ] = []

    for source_visual, target_visual in pairs:

        if target_visual is None and target_remaining:

            source_index = _get_visual_index(source_visual)

            if source_index is not None:

                for candidate in list(target_remaining):

                    candidate_index = _get_visual_index(candidate)

                    if candidate_index == source_index:

                        logger.info(
                            "Table paired by visual index fallback | "
                            "source=%s | target=%s | index=%s",
                            source_visual.get("title"),
                            candidate.get("title"),
                            source_index,
                        )

                        target_visual = candidate
                        target_remaining.remove(candidate)
                        break

        final_pairs.append((source_visual, target_visual))

    # ---------------------------------------------------------
    # 3. Remaining target visuals
    # ---------------------------------------------------------
    for target_visual in target_remaining:
        final_pairs.append((None, target_visual))

    return final_pairs


def build_table_comparisons(visual_data: dict[str, Any] | None) -> dict[str, Any]:
    """Build structured table/matrix comparisons with explicit state tracking and diffs."""
    visual_data = visual_data or {}
    try:
        source_dict = visual_data.get("Source", {})
        target_dict = visual_data.get("Target", {})

        source_exports = _get_export_data(source_dict)
        target_exports = _get_export_data(target_dict)

        paired_list = pair_source_and_target_tables(source_exports, target_exports)

        comparisons: list[dict[str, Any]] = []
        source_detected = len(source_exports)
        target_detected = len(target_exports)
        paired_count = sum(1 for s, t in paired_list if s and t)
        compared_count = 0
        match_count = 0
        mismatch_count = 0

        for source_visual, target_visual in paired_list:
            source_name = source_visual.get("title") if source_visual else "N/A"
            target_name = target_visual.get("title") if target_visual else "N/A"

            if not source_visual:
                comparisons.append({
                    "source_table": "N/A",
                    "target_table": target_name,
                    "status": "TABLE_NOT_COMPARED",
                    "reason": "Missing in Source",
                    "source_row_count": 0,
                    "target_row_count": len((target_visual.get("data") or {}).get("rows", [])),
                    "matched_row_count": 0,
                    "missing_columns_in_target": [],
                    "extra_columns_in_target": list((target_visual.get("data") or {}).get("columns", [])),
                    "missing_rows_in_target": [],
                    "extra_rows_in_target": (target_visual.get("data") or {}).get("rows", []),
                    "cell_mismatches": [],
                })
                mismatch_count += 1
                continue

            if not target_visual:
                comparisons.append({
                    "source_table": source_name,
                    "target_table": "N/A",
                    "status": "TABLE_NOT_COMPARED",
                    "reason": "Missing in Target",
                    "source_row_count": len((source_visual.get("data") or {}).get("rows", [])),
                    "target_row_count": 0,
                    "matched_row_count": 0,
                    "missing_columns_in_target": list((source_visual.get("data") or {}).get("columns", [])),
                    "extra_columns_in_target": [],
                    "missing_rows_in_target": (source_visual.get("data") or {}).get("rows", []),
                    "extra_rows_in_target": [],
                    "cell_mismatches": [],
                })
                mismatch_count += 1
                continue

            # Run DataFrame Comparison
            compared_count += 1
            source_df = visual_to_dataframe(source_visual)
            target_df = visual_to_dataframe(target_visual)
            diff_res = compare_dataframes(source_df, target_df, source_name)

            table_status = diff_res.get("status", "TABLE_MISMATCHED")
            if table_status == "TABLE_MATCHED":
                match_count += 1
            else:
                mismatch_count += 1

            cell_mismatches = []
            for rec in diff_res.get("mismatched_records", []):
                for d in rec.get("differences", []):
                    cell_mismatches.append({
                        "row_identifier": rec.get("keys", {}),
                        "column": d.get("column"),
                        "source_value": d.get("source_value"),
                        "target_value": d.get("target_value"),
                    })

            comparisons.append({
                "source_table": source_name,
                "target_table": target_name,
                "status": table_status,
                "source_row_count": len(source_df),
                "target_row_count": len(target_df),
                "matched_row_count": diff_res.get("summary", {}).get("matched_rows", 0),
                "missing_columns_in_target": diff_res.get("source_only_columns", []),
                "extra_columns_in_target": diff_res.get("target_only_columns", []),
                "missing_rows_in_target": [
                    r.get("keys") for r in diff_res.get("missing_in_target", [])
                ],
                "extra_rows_in_target": [
                    r.get("keys") for r in diff_res.get("missing_in_source", [])
                ],
                "cell_mismatches": cell_mismatches[:50],  # Cap diffs to keep API light
            })

        overall_status = "MATCH" if comparisons and match_count == len(comparisons) else "MISMATCH"

        return {
            "tables": {
                "source_table_count": source_detected,
                "target_table_count": target_detected,
                "paired_table_count": paired_count,
                "compared_table_count": compared_count,
                "match_count": match_count,
                "mismatch_count": mismatch_count,
                "overall_status": overall_status if comparisons else "NOT_COMPARED",
                "comparisons": comparisons,
            }
        }
    except Exception:
        logger.exception("Failed to build table comparisons")
        return {
            "tables": {
                "source_table_count": 0,
                "target_table_count": 0,
                "paired_table_count": 0,
                "compared_table_count": 0,
                "match_count": 0,
                "mismatch_count": 0,
                "overall_status": "ERROR",
                "comparisons": [],
            }
        }