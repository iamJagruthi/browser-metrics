"""
comparison.py

Compares two dashboard executions and determines which performs better.
"""
import re

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
    def compare_kpi_values(self, value_a, value_b):
        """
        Compare two KPI values.

        Returns
        -------
        str
            Match
            Near Match
            Mismatch
        """

        value_a = self.normalize_value(value_a)
        value_b = self.normalize_value(value_b)

            # Exact match
        if value_a == value_b:
            return "Match"

            # Try numeric comparison
        try:
            num_a = float(value_a.replace("%", ""))
            num_b = float(value_b.replace("%", ""))

            if num_a == num_b:
                return "Match"

            difference = abs(num_a - num_b)
            tolerance = max(abs(num_a), abs(num_b)) * 0.02

            if difference <= tolerance:
                return "Near Match"

        except ValueError:
            pass

        return "Mismatch"

    def calculate_match_percentage(
        self,
        matched,
        near_matched,
        total
    ):
        """
        Calculate the overall KPI match percentage.
        """

        if total == 0:
            return 0.0

        score = matched + (near_matched * 0.5)

        percentage = (score / total) * 100

        return round(percentage, 2)

    def normalize_value(self, value):
        """
        Normalize a KPI value before comparison.
        """

        if value is None:
            return ""

        value = str(value).strip().lower()

        # Remove commas
        value = value.replace(",", "")

        # Remove currency symbols
        value = re.sub(r"[$₹€£]", "", value)

        # Remove extra spaces
        value = " ".join(value.split())

        # Convert "18 %" -> "18%"
        value = value.replace(" %", "%")

        return value

    def compare_kpis(self, source_kpis, target_kpis):
        """
        Compare KPI lists from two dashboards.
        """

        results = []

        matched = 0
        near_matched = 0
        mismatched = 0

        source_lookup = {
            kpi.name.lower(): kpi
            for kpi in source_kpis
        }

        target_lookup = {
            kpi.name.lower(): kpi
            for kpi in target_kpis
        }

        all_names = sorted(
            set(source_lookup.keys()) |
            set(target_lookup.keys())
        )

        for name in all_names:

            source = source_lookup.get(name)
            target = target_lookup.get(name)

            if source is None or target is None:

                results.append({
                    "kpi": name,
                    "source": source.value if source else None,
                    "target": target.value if target else None,
                    "status": "Missing"
                })

                mismatched += 1
                continue

            status = self.compare_kpi_values(
                source.value,
                target.value
            )

            if status == "Match":
                matched += 1

            elif status == "Near Match":
                near_matched += 1

            else:
                mismatched += 1

            results.append({
                "kpi": source.name,
                "source": source.value,
                "target": target.value,
                "status": status
            })

        total = len(all_names)

        match_percentage = self.calculate_match_percentage(
            matched,
            near_matched,
            total
        )

        return {
            "total_kpis": total,
            "matched": matched,
            "near_matched": near_matched,
            "mismatched": mismatched,
            "match_percentage": match_percentage,
            "results": results
        }