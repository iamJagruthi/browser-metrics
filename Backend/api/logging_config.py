"""Central logging configuration for the API and services.

Jagruthi — consistent log format across server routes and service layers.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once at application startup."""
    root = logging.getLogger()
    if root.handlers:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.setLevel(log_level)
    root.addHandler(handler)
