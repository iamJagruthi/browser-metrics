"""
ai_validation_service.py

Integration layer between the validator and the hosted Data Science AI
validation application (Gemini-backed).

The hosted app owns the Gemini credentials; this project never holds or
calls Gemini directly. Screenshots from the DOM capture are uploaded to the
hosted service (batch/folder per side), a comparison job is started and
polled, and the returned artifacts are stored UNDER a separate ``ai_analysis``
key -- never merged into the DOM results.

Config
    AI_VALIDATION_SERVICE_URL
        Base URL of the hosted AI validation app (e.g. via ``.env``).
        When unset, every call returns a ``not_configured`` result and
        nothing is attempted.
    AI_VALIDATION_SOURCE_FOLDER / AI_VALIDATION_TARGET_FOLDER
        Folder identifiers accepted by the hosted upload endpoint
        (documented contract: "spartnash" / "trendence").

Hosted API contract (verified against the live service OpenAPI):
    POST /api/upload/{folder}      multipart form, field ``files`` (files[])
    POST /api/compare              start a comparison job
    GET  /api/compare/{job_id}     job status
    GET  /api/results              comparison result payload
    GET  /api/download             Excel workbook download

The result payload schema is not fully documented by the service, so the
raw payload is stored verbatim and only contract-known keys are summarised
(`pairs`, `image_stats`, token/cost counters, `workbook_available`,
`download_url`). A ``dashboard_name`` is surfaced ONLY if the hosted service
actually returns a key with that exact name; otherwise it stays absent and
the pipeline falls back to the DOM-derived name.
"""

import asyncio
import logging
import os
import time

import httpx

from utils.config import (
    AI_VALIDATION_SERVICE_URL,
    AI_VALIDATION_SOURCE_FOLDER,
    AI_VALIDATION_TARGET_FOLDER,
    SCREENSHOT_SOURCE_FOLDER,
    SCREENSHOT_TARGET_FOLDER,
    side_screenshot_dir,
)

logger = logging.getLogger(__name__)

_COMPARE_POLL_ATTEMPTS = int(os.getenv("AI_COMPARE_POLL_ATTEMPTS", "60"))
_COMPARE_POLL_INTERVAL_SECONDS = float(
    os.getenv("AI_COMPARE_POLL_INTERVAL_SECONDS", "5")
)
_INVOCATION_TIMEOUT_SECONDS = float(
    os.getenv("AI_INVOCATION_TIMEOUT_SECONDS", "600")
)

# Keys observed on GET /api/results from the live service. Copied verbatim
# when present; never synthesised.
_RESULTS_ALLOWLIST = (
    "total_llm_calls",
    "total_tokens",
    "total_prompt_tokens",
    "total_image_tokens",
    "total_input_tokens",
    "total_output_tokens",
    "total_input_cost_usd",
    "total_output_cost_usd",
    "total_cost_usd",
    "total_cost_inr",
    "workbook_available",
    "download_url",
)

_JOB_TERMINAL_STATUSES = {"completed", "done", "success", "failed", "error"}


def _scan_dashboard_name(payload) -> str | None:
    """Return the first ``dashboard_name`` string found anywhere in a payload.

    Key-name driven only, so it never invents field names; it simply surfaces
    a dashboard name if (and only if) the hosted service returns one.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if (
                str(key).casefold() == "dashboard_name"
                and isinstance(value, str)
                and value.strip()
            ):
                return value.strip()
        for value in payload.values():
            found = _scan_dashboard_name(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _scan_dashboard_name(item)
            if found:
                return found
    return None


async def _upload_folder(
    client: httpx.AsyncClient,
    folder_id: str,
    screenshot_files: list,
) -> int:
    if not screenshot_files:
        return 0
    files = [
        ("files", (path.name, path.read_bytes(), "image/png"))
        for path in screenshot_files
    ]
    response = await client.post(f"/api/upload/{folder_id}", files=files)
    response.raise_for_status()
    return len(screenshot_files)


async def _start_and_wait_for_compare(client: httpx.AsyncClient) -> tuple[str | None, dict | None]:
    compare_response = await client.post("/api/compare")
    compare_response.raise_for_status()
    compare_payload = compare_response.json() or {}
    job_id = compare_payload.get("job_id") if isinstance(compare_payload, dict) else None

    last_status = None
    if isinstance(job_id, str) and job_id:
        for _ in range(_COMPARE_POLL_ATTEMPTS):
            try:
                status_response = await client.get(f"/api/compare/{job_id}")
                if status_response.status_code != 200:
                    break
                last_status = status_response.json() or {}
                if (
                    isinstance(last_status, dict)
                    and str(last_status.get("status", "")).casefold()
                    in _JOB_TERMINAL_STATUSES
                ):
                    break
            except Exception:
                logger.exception("AI compare status poll failed | job_id=%s", job_id)
                break
            await asyncio.sleep(_COMPARE_POLL_INTERVAL_SECONDS)
    return job_id, last_status


async def run_ai_validation(
    run_id: str,
    screenshot_dir,  # Path | None
    source_name: str | None = None,
    target_name: str | None = None,
) -> dict:
    """Run the hosted AI validation pass against a completed DOM capture.

    Uploads the persistence side folders (source/target), starts a
    comparison job, polls it, then stores the raw results under ``ai_analysis``.
    Never raises API errors into the capture flow: failures become a
    structured ``failed`` result so DOM validation still completes.
    """
    started = time.perf_counter()
    baseline = {
        "run_id": run_id,
        "source_name": source_name,
        "target_name": target_name,
        "source_folder": SCREENSHOT_SOURCE_FOLDER,
        "target_folder": SCREENSHOT_TARGET_FOLDER,
    }

    if not AI_VALIDATION_SERVICE_URL:
        return {
            **baseline,
            "status": "not_configured",
            "reason": "AI_VALIDATION_SERVICE_URL is not configured",
            "duration_seconds": time.perf_counter() - started,
        }

    async def _invoke() -> dict:
        source_files = sorted(
            side_screenshot_dir(screenshot_dir, "source").glob("*.png")
        ) if screenshot_dir else []
        target_files = sorted(
            side_screenshot_dir(screenshot_dir, "target").glob("*.png")
        ) if screenshot_dir else []

        if not source_files or not target_files:
            return {
                **baseline,
                "status": "failed",
                "reason": "Screenshot side folders are missing or empty for the hosted AI service",
                "uploaded": {"source": len(source_files), "target": len(target_files)},
                "duration_seconds": time.perf_counter() - started,
            }

        timeout = httpx.Timeout(_INVOCATION_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(
            base_url=AI_VALIDATION_SERVICE_URL,
            timeout=timeout,
        ) as client:
            uploaded_source = await _upload_folder(
                client, AI_VALIDATION_SOURCE_FOLDER, source_files
            )
            uploaded_target = await _upload_folder(
                client, AI_VALIDATION_TARGET_FOLDER, target_files
            )

            job_id, compare_status = await _start_and_wait_for_compare(client)

            results_response = await client.get("/api/results")
            results_response.raise_for_status()
            results = results_response.json() or {}

        summary = {key: results[key] for key in _RESULTS_ALLOWLIST if key in results}
        pairs = results.get("pairs") if isinstance(results, dict) else None
        image_stats = results.get("image_stats") if isinstance(results, dict) else None
        dashboard_name = _scan_dashboard_name(results)

        return {
            **baseline,
            "status": "completed",
            "uploaded": {"source": uploaded_source, "target": uploaded_target},
            "job_id": job_id,
            "compare_status_payload": compare_status,
            "results": results,
            "pairs_count": len(pairs) if isinstance(pairs, list) else None,
            "image_stats_count": (
                len(image_stats) if isinstance(image_stats, list) else None
            ),
            **summary,
            **({"dashboard_name": dashboard_name} if dashboard_name else {}),
            "duration_seconds": time.perf_counter() - started,
        }

    try:
        return await asyncio.wait_for(_invoke(), timeout=_INVOCATION_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - never break DOM capture
        logger.exception("AI validation invocation failed | run_id=%s", run_id)
        return {
            **baseline,
            "status": "failed",
            "reason": f"AI validation failed: {exc}",
            "duration_seconds": time.perf_counter() - started,
        }


def describe_screenshot_contract() -> str:
    """Human-readable summary of the artifact layout for the hosted service."""
    return (
        "Screenshots are stored per side under "
        f"output/screenshots/<run_id>/{SCREENSHOT_SOURCE_FOLDER}/ and "
        f"output/screenshots/<run_id>/{SCREENSHOT_TARGET_FOLDER}/. "
        "They are uploaded in batch to the hosted service "
        f"(/api/upload/{AI_VALIDATION_SOURCE_FOLDER}, "
        f"/api/upload/{AI_VALIDATION_TARGET_FOLDER}). "
        "DOM results stay in the capture; AI results are stored separately "
        "under ai_analysis."
    )