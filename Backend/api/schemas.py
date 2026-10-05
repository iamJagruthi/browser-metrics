"""Pydantic request/response models for HTTP APIs.

Jagruthi — shared schemas for validation and probe endpoints.
"""

from pydantic import BaseModel, Field


class ValidateRequest(BaseModel):
    run_id: str | None = Field(
        default=None,
        description=(
            "Run_id of a previously captured browser-metrics run. When "
            "provided, the validation report is rebuilt from the persisted "
            "capture artifacts without launching another browser."
        ),
    )
    source_url: str = Field(
        default="",
        description=(
            "Source dashboard URL (required when run_id is not provided)."
        ),
    )
    target_url: str = Field(
        default="",
        description=(
            "Target dashboard URL (required when run_id is not provided)."
        ),
    )


class BrowserMetricsRequest(BaseModel):
    source_url: str = Field(..., min_length=1, description="Source dashboard URL")
    target_url: str = Field(..., min_length=1, description="Target dashboard URL")

