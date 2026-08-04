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
        try:
            self._timers[name] = {
                "start": time.perf_counter(),
                "elapsed": None
            }
        except Exception as e:
            print(f"Error starting timer '{name}': {e}")

    def stop(self, name: str):
        """
        Stop a named timer.
        """
        try:
            if name not in self._timers:
                return 0.0

            elapsed = round(
                time.perf_counter() - self._timers[name]["start"],
                3
            )

            self._timers[name]["elapsed"] = elapsed

            return elapsed

        except Exception as e:
            print(f"Error stopping timer '{name}': {e}")
            return 0.0

    def get(self, name: str):
        """
        Get elapsed time for a timer.
        """
        try:
            timer = self._timers.get(name)

            if not timer:
                return 0.0

            return timer.get("elapsed") or 0.0

        except Exception as e:
            print(f"Error getting timer '{name}': {e}")
            return 0.0

    def summary(self):
        """
        Returns all collected timings.
        """
        try:
            return {
                key: value["elapsed"]
                for key, value in self._timers.items()
            }
        except Exception as e:
            print(f"Error building timer summary: {e}")
            return {}

    def reset(self):
        """
        Clears all timers.
        """
        try:
            self._timers.clear()
        except Exception as e:
            print(f"Error resetting timers: {e}")