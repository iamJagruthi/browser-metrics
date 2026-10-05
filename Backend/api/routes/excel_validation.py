"""Excel file validation route.

POST /api/excel-validate accepts two uploaded spreadsheet files (source and
target), inspects each workbook's sheets dynamically (no hardcoded sheet
names), and compares every shared sheet with the existing table comparison
engine (``services.table_comparison.compare_dataframes``).

Pure deterministic computation:

* No Playwright / browser launch.
* No Power BI / DOM extraction.
* No LLM / vision calls (files are never sent to any model).

Supported file types: ``.xlsx`` (openpyxl) and ``.csv`` (pandas).
``.xls`` requires the optional ``xlrd`` engine, which is not installed, so it
is rejected with an explicit unsupported-type error.

Excel comparisons are intentionaly NOT rendered into the dashboard Word
report template: that template's schema is dashboard-specific (pages, browser
metrics, screenshots) and cannot represent file-to-file comparisons cleanly.
"""

from __future__ import annotations

import io
import logging

import pandas as pd

from fastapi import APIRouter, File, HTTPException, UploadFile

from services.table_comparison import compare_dataframes


logger = logging.getLogger(__name__)

router = APIRouter(tags=["excel-validation"])

_SUPPORTED_SUFFIXES = {"xlsx", "csv"}

_ERRORS = {
    "no_source": "Missing source file.",
    "no_target": "Missing target file.",
    "unsupported_type": (
        "Unsupported file type. Upload .xlsx or .csv files "
        "(.xls requires the xlrd engine, which is not installed)."
    ),
    "unreadable": (
        "Workbook cannot be read. Ensure the file is a valid spreadsheet "
        "with at least one non-empty sheet."
    ),
    "no_sheets": (
        "No comparable sheets found: the source and target workbooks do not "
        "share any sheet names."
    ),
    "empty": "No comparable data found between the two workbooks.",
}


def _suffix(filename: str | None) -> str:
    name = (filename or "").strip()
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def _read_sheets(data: bytes, suffix: str) -> dict[str, pd.DataFrame]:
    """Read every sheet of an uploaded workbook into DataFrames.

    Returns a ``{sheet_name: DataFrame}`` mapping holding only non-empty
    sheets. CSV is treated as a single implicit ``"CSV"`` sheet.
    """
    if suffix == "csv":
        frame = pd.read_csv(io.BytesIO(data))
        return {"CSV": frame} if not frame.empty else {}

    workbook = pd.read_excel(
        io.BytesIO(data),
        sheet_name=None,
        engine="openpyxl",
    )
    return {name: frame for name, frame in workbook.items() if not frame.empty}


def _mismatch_rows(result: dict, limit: int = 50) -> list[dict]:
    """Lightweight mismatch details (keys + cell differences) for the UI."""
    rows = []
    for record in list(result.get("mismatched_records") or [])[:limit]:
        rows.append(
            {
                "keys": record.get("keys"),
                "differences": list(record.get("differences") or []),
            }
        )
    return rows


def _sheet_comparison(sheet_name: str, result: dict) -> dict:
    summary = result.get("summary") or {}
    return {
        "sheet": sheet_name,
        "status": result.get("status", "TABLE_NOT_COMPARED"),
        "comparison_confidence": result.get("comparison_confidence"),
        "key_strategy": result.get("key_strategy"),
        "source_row_count": len(result.get("source_rows") or []),
        "target_row_count": len(result.get("target_rows") or []),
        "matched_rows": summary.get("matched_rows", 0),
        "mismatched_rows": summary.get("mismatched_rows", 0),
        "missing_in_source_rows": summary.get("missing_in_source_rows", 0),
        "missing_in_target_rows": summary.get("missing_in_target_rows", 0),
        "mismatched_cells": summary.get("mismatched_cells", 0),
        "column_differences": list(result.get("column_differences") or []),
        "mismatch_details": _mismatch_rows(result),
    }


@router.post("/api/excel-validate")
async def excel_validate(
    source_file: UploadFile | None = File(default=None),
    target_file: UploadFile | None = File(default=None),
) -> dict:
    """Compare two uploaded spreadsheet files reusing the table comparison engine."""
    if source_file is None or not (source_file.filename or "").strip():
        raise HTTPException(status_code=400, detail=_ERRORS["no_source"])
    if target_file is None or not (target_file.filename or "").strip():
        raise HTTPException(status_code=400, detail=_ERRORS["no_target"])

    source_name = source_file.filename
    target_name = target_file.filename
    source_suffix = _suffix(source_name)
    target_suffix = _suffix(target_name)

    if (
        source_suffix not in _SUPPORTED_SUFFIXES
        or target_suffix not in _SUPPORTED_SUFFIXES
    ):
        raise HTTPException(status_code=400, detail=_ERRORS["unsupported_type"])

    try:
        source_bytes = await source_file.read()
        target_bytes = await target_file.read()
    except Exception:
        logger.exception("Failed to read uploaded files")
        raise HTTPException(
            status_code=500,
            detail="Failed to read the uploaded files.",
        )

    try:
        source_sheets = _read_sheets(source_bytes, source_suffix)
        target_sheets = _read_sheets(target_bytes, target_suffix)
    except Exception:
        logger.exception(
            "Workbook read failed | source=%s | target=%s",
            source_name,
            target_name,
        )
        raise HTTPException(status_code=400, detail=_ERRORS["unreadable"])

    if not source_sheets or not target_sheets:
        raise HTTPException(status_code=422, detail=_ERRORS["empty"])

    shared_sheets = sorted(set(source_sheets) & set(target_sheets))
    if not shared_sheets:
        raise HTTPException(status_code=422, detail=_ERRORS["no_sheets"])

    sheet_comparisons: list[dict] = []
    total_checks = 0
    matched_count = 0
    mismatch_count = 0
    mismatched_cells_total = 0
    column_difference_count = 0

    for sheet in shared_sheets:
        try:
            result = compare_dataframes(
                source_sheets[sheet],
                target_sheets[sheet],
                visual_title=sheet,
            )
        except Exception:
            logger.exception("Excel sheet comparison failed | sheet=%s", sheet)
            result = {
                "status": "TABLE_NOT_COMPARED",
                "visual": sheet,
                "comparison_confidence": None,
                "key_strategy": "unknown",
                "column_differences": [],
                "mismatched_records": [],
                "summary": {},
                "source_rows": [],
                "target_rows": [],
            }

        comparison = _sheet_comparison(sheet, result)
        sheet_comparisons.append(comparison)

        summary = result.get("summary") or {}
        checks = (
            summary.get("matched_rows", 0)
            + summary.get("mismatched_rows", 0)
            + summary.get("missing_in_source_rows", 0)
            + summary.get("missing_in_target_rows", 0)
        )
        matched = summary.get("matched_rows", 0)
        total_checks += checks
        matched_count += matched
        mismatch_count += checks - matched
        mismatched_cells_total += summary.get("mismatched_cells", 0)
        column_difference_count += len(result.get("column_differences") or [])

    if total_checks == 0:
        raise HTTPException(status_code=422, detail=_ERRORS["empty"])

    if mismatch_count == 0:
        overall_status = "matched"
    elif matched_count > 0 or any(
        item["status"] != "TABLE_NOT_COMPARED" for item in sheet_comparisons
    ):
        overall_status = "mismatched"
    else:
        overall_status = "not_compared"

    return {
        "mode": "excel",
        "status": overall_status,
        "source_filename": source_name,
        "target_filename": target_name,
        "sheets_compared": shared_sheets,
        "summary": {
            "sheet_count": len(sheet_comparisons),
            "total_checks": total_checks,
            "matched_count": matched_count,
            "mismatch_count": mismatch_count,
            "mismatched_cells": mismatched_cells_total,
            "column_difference_count": column_difference_count,
        },
        "sheet_comparisons": sheet_comparisons,
        "word_report_note": (
            "Excel comparisons are not rendered into the dashboard Word "
            "report template."
        ),
    }