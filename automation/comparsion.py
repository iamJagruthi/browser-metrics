"""
comparison.py

Compares two dashboard executions and determines which performs better.
"""


class DashboardComparison:
    """
    Compares two dashboard metric dictionaries.
    """

    def __init__(self):

        # True -> Lower value is better
        # False -> Higher value is better

        self.metrics = {
            "browser_launch_seconds": True,
            "page_load_seconds": True,
            "dashboard_render_seconds": True,
            "screenshot_seconds": True,
            "total_execution_seconds": True,
            "failed_requests": True,
            "console_messages": True,
            "page_errors": True,
            "total_requests": False,
            "total_responses": False,
        }

    def compare_metric(self, metric, value_a, value_b):
        """
        Compare a single metric.
        """

        if value_a == value_b:
            return "Equal"

        lower_is_better = self.metrics[metric]

        if lower_is_better:
            return (
                "Dashboard A"
                if value_a < value_b
                else "Dashboard B"
            )

        return (
            "Dashboard A"
            if value_a > value_b
            else "Dashboard B"
        )

    def compare(self, dashboard_a, dashboard_b):
        """
        Compare two dashboard metric dictionaries.
        """

        results = {}

        score_a = 0
        score_b = 0

        for metric in self.metrics:

            value_a = dashboard_a.get(metric, 0)
            value_b = dashboard_b.get(metric, 0)

            winner = self.compare_metric(
                metric,
                value_a,
                value_b
            )

            results[metric] = {
                "dashboard_a": value_a,
                "dashboard_b": value_b,
                "winner": winner
            }

            if winner == "Dashboard A":
                score_a += 1

            elif winner == "Dashboard B":
                score_b += 1

        if score_a > score_b:
            overall = dashboard_a["dashboard_name"]

        elif score_b > score_a:
            overall = dashboard_b["dashboard_name"]

        else:
            overall = "Tie"

        return {

            "dashboard_a": dashboard_a["dashboard_name"],
            "dashboard_b": dashboard_b["dashboard_name"],

            "score_a": score_a,
            "score_b": score_b,

            "overall_winner": overall,

            "results": results

        }