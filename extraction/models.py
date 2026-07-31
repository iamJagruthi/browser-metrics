"""
models.py

Data models used by the extraction module.
"""

from dataclasses import dataclass
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