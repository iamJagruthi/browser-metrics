"""
models.py

Data models used by the extraction module.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class KPI:
    """
    Represents a single KPI extracted
    from a dashboard.
    """

    name: str
    value: str
    confidence: float = 1.0
    bbox: List = None

@dataclass
class DashboardMetadata:
    title: str | None = None
    refresh_date: str | None = None

    kpis: list[KPI] = field(default_factory=list)

    filters: list = field(default_factory=list)

    visuals: list = field(default_factory=list)