"""Pandas-based comparison of Power BI table/matrix visuals from DOM extraction.

Jagruthi — features:
- Tabular visual detection (excludes slicers/button filters)
- DataFrame conversion and row/column diff reporting
- Configurable key strategies for matched-row comparison
- build_table_comparisons() for Excel/report integration
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from utils.config import TABLE_COMPARE_KEY_COLUMNS, TABLE_COMPARE_KEY_STRATEGY


logger = logging.getLogger(__name__)


def _visual_key(visual: dict[str, Any]) -> str:
    return " ".join(str(visual.get("title") or visual.get("id") or "").casefold().split())


def is_tabular_visual(visual: dict[str, Any]) -> bool:
    """Return True when a visual contains scrollable table/matrix data."""
    try:
        if visual.get("is_slicer"):
            return False
        data = visual.get("data", {})
        if data.get("collection_method") == "slicer_skipped":
            return False
        rows = data.get("rows", [])
        columns = data.get("columns", [])
        if not rows and not columns:
            return False
        visual_type = str(visual.get("visual_type", ""))
        if re.search(r"slicer|dropdown|button", visual_type, re.IGNORECASE):
            return False
        if rows and all(len(row) <= 1 for row in rows) and not columns:
            return False
        if visual.get("scrollable") or visual.get("horizontally_scrollable"):
            return True
        if columns and rows:
            return True
        if rows and max(len(row) for row in rows) > 1:
            return True
        return bool(columns)
    except Exception:
        logger.exception("Unable to classify visual as tabular | visual=%s", visual.get("title"))
        return False


def visual_to_dataframe(visual: dict[str, Any]) -> pd.DataFrame:
    """Convert an extracted visual table into a DataFrame without altering cell text."""
    try:
        data = visual.get("data", {})
        columns = [str(column) for column in data.get("columns", [])]
        rows = data.get("rows", [])
        if not rows and not columns:
            return pd.DataFrame()

        if columns:
            width = len(columns)
            normalized = [
                [str(value) if value is not None else "" for value in row]
                + [""] * max(0, width - len(row))
                for row in rows
            ]
            normalized = [row[:width] for row in normalized]
            return pd.DataFrame(normalized, columns=columns)

        width = max(len(row) for row in rows)
        generated_columns = [f"Column {index}" for index in range(1, width + 1)]
        normalized = [
            [str(value) if value is not None else "" for value in row]
            + [""] * max(0, width - len(row))
            for row in rows
        ]
        normalized = [row[:width] for row in normalized]
        return pd.DataFrame(normalized, columns=generated_columns)
    except Exception:
        logger.exception("Failed to convert visual to DataFrame | visual=%s", visual.get("title"))
        return pd.DataFrame()


def _columns_are_unique_key(df: pd.DataFrame, key_columns: list[str]) -> bool:
    if df.empty or not key_columns:
        return False
    if not all(column in df.columns for column in key_columns):
        return False
    subset = df[key_columns].astype(str)
    if subset.isna().any().any():
        return False
    return not subset.duplicated(keep=False).any()


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

    # auto
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
    """Compare two extracted tables and classify rows and cell-level differences."""
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
                    source_value = str(row.get(f"{column}__src", ""))
                    target_value = str(row.get(f"{column}__tgt", ""))
                    if source_value != target_value:
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
            max_rows = max(len(source_df), len(target_df))
            shared_columns = [str(column) for column in source_df.columns if column in target_df.columns]
            for row_number in range(max_rows):
                source_row = source_df.iloc[row_number] if row_number < len(source_df) else None
                target_row = target_df.iloc[row_number] if row_number < len(target_df) else None
                key_values = {"row_number": str(row_number + 1)}

                if source_row is None:
                    missing_in_source.append(
                        {
                            "visual": visual_title,
                            "key_strategy": key_strategy,
                            "keys": key_values,
                            "row": {column: str(target_row.get(column, "")) for column in target_df.columns},
                        }
                    )
                    continue
                if target_row is None:
                    missing_in_target.append(
                        {
                            "visual": visual_title,
                            "key_strategy": key_strategy,
                            "keys": key_values,
                            "row": {column: str(source_row.get(column, "")) for column in source_df.columns},
                        }
                    )
                    continue

                cell_diffs = []
                for column in shared_columns:
                    source_value = str(source_row.get(column, ""))
                    target_value = str(target_row.get(column, ""))
                    if source_value != target_value:
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

        mismatched_cells = sum(len(item.get("differences", [])) for item in mismatched_records)
        status = "Match"
        if missing_in_source or missing_in_target or mismatched_records or column_differences:
            status = "Mismatch"

        return {
            "visual": visual_title,
            "status": status,
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
            "summary": {
                "matched_rows": len(matched_records),
                "mismatched_rows": len(mismatched_records),
                "missing_in_source_rows": len(missing_in_source),
                "missing_in_target_rows": len(missing_in_target),
                "source_column_count": len(source_df.columns),
                "target_column_count": len(target_df.columns),
                "mismatched_cells": mismatched_cells,
            },
        }
    except Exception:
        logger.exception("Table comparison failed | visual=%s", visual_title)
        return {
            "visual": visual_title,
            "status": "Error",
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


def compare_visual_tables(
    source_visual: dict[str, Any],
    target_visual: dict[str, Any],
) -> dict[str, Any]:
    title = source_visual.get("title") or target_visual.get("title") or "Table"
    source_df = visual_to_dataframe(source_visual)
    target_df = visual_to_dataframe(target_visual)
    if source_df.empty and target_df.empty:
        return {
            "visual": title,
            "status": "No table data captured",
            "key_strategy": "none",
            "key_columns": [],
            "key_reliable": False,
            "key_warning": "No rows were captured for this visual.",
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
    return compare_dataframes(source_df, target_df, title)


def build_table_comparisons(visual_data: dict[str, Any] | None) -> dict[str, Any]:
    """Build table/matrix comparisons for all tabular visuals in source and target runs."""
    visual_data = visual_data or {}
    try:
        source_visuals = [
            visual for visual in visual_data.get("Source", {}).get("visuals", [])
            if is_tabular_visual(visual)
        ]
        target_visuals = [
            visual for visual in visual_data.get("Target", {}).get("visuals", [])
            if is_tabular_visual(visual)
        ]
        source_map = {_visual_key(visual): visual for visual in source_visuals if _visual_key(visual)}
        target_map = {_visual_key(visual): visual for visual in target_visuals if _visual_key(visual)}

        comparisons: list[dict[str, Any]] = []
        for key in sorted(set(source_map) | set(target_map)):
            source_visual = source_map.get(key)
            target_visual = target_map.get(key)
            title = (source_visual or target_visual or {}).get("title", key)
            if not source_visual:
                comparisons.append(
                    {
                        "visual": title,
                        "status": "Missing in Source",
                        "key_strategy": "none",
                        "key_columns": [],
                        "key_reliable": False,
                        "key_warning": "Visual exists only in target.",
                        "source_only_columns": [],
                        "target_only_columns": list(target_visual.get("data", {}).get("columns", [])),
                        "column_differences": [],
                        "matched_records": [],
                        "mismatched_records": [],
                        "missing_in_source": [],
                        "missing_in_target": [],
                        "source_rows": [],
                        "source_columns": [],
                        "target_rows": target_visual.get("data", {}).get("rows", []),
                        "target_columns": [str(column) for column in target_visual.get("data", {}).get("columns", [])],
                        "summary": {"target_rows": len(target_visual.get("data", {}).get("rows", []))},
                    }
                )
                continue
            if not target_visual:
                comparisons.append(
                    {
                        "visual": title,
                        "status": "Missing in Target",
                        "key_strategy": "none",
                        "key_columns": [],
                        "key_reliable": False,
                        "key_warning": "Visual exists only in source.",
                        "source_only_columns": list(source_visual.get("data", {}).get("columns", [])),
                        "target_only_columns": [],
                        "column_differences": [],
                        "matched_records": [],
                        "mismatched_records": [],
                        "missing_in_source": [],
                        "missing_in_target": [],
                        "source_rows": source_visual.get("data", {}).get("rows", []),
                        "source_columns": [str(column) for column in source_visual.get("data", {}).get("columns", [])],
                        "target_rows": [],
                        "target_columns": [],
                        "summary": {"source_rows": len(source_visual.get("data", {}).get("rows", []))},
                    }
                )
                continue
            comparisons.append(compare_visual_tables(source_visual, target_visual))

        match_count = sum(1 for item in comparisons if item.get("status") == "Match")
        overall_status = "MATCH" if comparisons and match_count == len(comparisons) else "MISMATCH"
        logger.info(
            "Table comparisons built | tables=%d | matches=%d | status=%s",
            len(comparisons),
            match_count,
            overall_status,
        )
        return {
            "tables": comparisons,
            "summary": {
                "table_count": len(comparisons),
                "match_count": match_count,
                "overall_status": overall_status if comparisons else "NOT_COMPARED",
                "source_tabular_visuals": len(source_visuals),
                "target_tabular_visuals": len(target_visuals),
            },
        }
    except Exception:
        logger.exception("Failed to build table comparisons")
        return {
            "tables": [],
            "summary": {
                "table_count": 0,
                "match_count": 0,
                "overall_status": "ERROR",
                "source_tabular_visuals": 0,
                "target_tabular_visuals": 0,
            },
        }
