"""
performance.py

Utility for measuring browser performance timings.
"""

import logging
import time


logger = logging.getLogger(__name__)


class PerformanceTimer:
    """
    Generic timer for measuring execution durations.
    """

    def __init__(self):
        self._timers = {}

    def start(self, name: str):
        """Start a named timer."""
        try:
            self._timers[name] = {
                "start": time.perf_counter(),
                "elapsed": None,
            }
        except Exception:
            logger.exception("Error starting timer | name=%s", name)

    def stop(self, name: str):
        """Stop a named timer."""
        try:
            if name not in self._timers:
                logger.warning(
                    "Timer stop requested for unknown name | name=%s",
                    name,
                )
                return 0.0

            elapsed = (
                time.perf_counter()
                - self._timers[name]["start"]
            )

            self._timers[name]["elapsed"] = elapsed

            logger.info(
                "Timer stopped | name=%s | elapsed=%.6f seconds | %.2f ms",
                name,
                elapsed,
                elapsed * 1000,
            )

            return elapsed

        except Exception:
            logger.exception(
                "Error stopping timer | name=%s",
                name,
            )
            return 0.0

    def get(self, name: str):
        """Get elapsed time for a timer."""
        try:
            timer = self._timers.get(name)

            if not timer:
                return 0.0

            return timer.get("elapsed") or 0.0

        except Exception:
            logger.exception("Error reading timer | name=%s", name)
            return 0.0

    def summary(self):
        """Returns all collected timings."""
        try:
            return {
                key: value["elapsed"]
                for key, value in self._timers.items()
            }
        except Exception:
            logger.exception("Error building timer summary")
            return {}

    def reset(self):
        """Clears all timers."""
        try:
            self._timers.clear()
        except Exception:
            logger.exception("Error resetting timers")
