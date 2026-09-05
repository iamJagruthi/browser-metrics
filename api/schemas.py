"""Pydantic request/response models for HTTP APIs.

Jagruthi — shared schemas for validation and probe endpoints.
"""

from pydantic import BaseModel, Field


class ValidateRequest(BaseModel):
    source_url: str = Field(..., min_length=1, description="Source dashboard URL")
    target_url: str = Field(..., min_length=1, description="Target dashboard URL")

