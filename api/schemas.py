"""Pydantic request/response models for HTTP APIs.

Jagruthi — shared schemas for validation and probe endpoints.
"""

from pydantic import BaseModel, Field


class ValidateRequest(BaseModel):
    source_url: str = Field(..., min_length=1, description="Source dashboard URL")
    target_url: str = Field(..., min_length=1, description="Target dashboard URL")


class ProbeRequest(BaseModel):
    """Source URL required; target URL optional for single-dashboard probes."""

    source_url: str = Field(..., min_length=1, description="Primary dashboard URL")
    target_url: str | None = Field(default=None, description="Optional comparison dashboard URL")
