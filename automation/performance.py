"""
performance.py

Utility for measuring browser performance timings.
"""

import time


class PerformanceTimer:
    """
    Generic timer for measuring execution durations.
    """

    def __init__(self):
        self._timers = {}

    def start(self, name: str):
        """
        Start a named timer.
        """
        self._timers[name] = {
            "start": time.perf_counter(),
            "elapsed": None
        }

    def stop(self, name: str):
        """
        Stop a named timer.
        """
        if name not in self._timers:
            return 0.0

        elapsed = round(
            time.perf_counter() - self._timers[name]["start"],
            3
        )

        self._timers[name]["elapsed"] = elapsed

        return elapsed

    def get(self, name: str):
        """
        Get elapsed time for a timer.
        """
        timer = self._timers.get(name)

        if not timer:
            return 0.0

        return timer.get("elapsed") or 0.0

    def summary(self):
        """
        Returns all collected timings.
        """

        return {
            key: value["elapsed"]
            for key, value in self._timers.items()
        }

    def reset(self):
        """
        Clears all timers.
        """
        self._timers.clear()