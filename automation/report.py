"""
report.py

Generates a summary report for dashboard validation.
"""

from datetime import datetime
from pathlib import Path

from utils.config import OUTPUT_DIR


REPORT_DIR = OUTPUT_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def generate_report(metrics, comparison=None):
    """
    Generates a text report.

    Parameters
    ----------
    metrics : dict
        Metrics collected for a dashboard.

    comparison : dict, optional
        Comparison result from comparison.py
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_file = REPORT_DIR / f"ValidationReport_{timestamp}.txt"

    with open(report_file, "w", encoding="utf-8") as report:

        report.write("=" * 70 + "\n")
        report.write("BROWSER METRICS VALIDATION REPORT\n")
        report.write("=" * 70 + "\n\n")

        report.write("Dashboard Information\n")
        report.write("-" * 70 + "\n")
        report.write(f"Dashboard Name : {metrics.get('dashboard_name')}\n")
        report.write(f"Environment    : {metrics.get('environment')}\n")
        report.write(f"URL            : {metrics.get('dashboard_url')}\n")
        report.write(f"Timestamp      : {metrics.get('timestamp')}\n\n")

        report.write("Performance Metrics\n")
        report.write("-" * 70 + "\n")

        report.write(
            f"Browser Launch Time : {metrics.get('browser_launch_seconds')} sec\n"
        )

        report.write(
            f"Page Load Time      : {metrics.get('page_load_seconds')} sec\n"
        )

        report.write(
            f"Dashboard Render    : {metrics.get('dashboard_render_seconds')} sec\n"
        )

        report.write(
            f"Screenshot Time     : {metrics.get('screenshot_seconds')} sec\n"
        )

        report.write(
            f"Total Execution     : {metrics.get('total_execution_seconds')} sec\n\n"
        )

        report.write("Network Metrics\n")
        report.write("-" * 70 + "\n")

        report.write(
            f"HTTP Status      : {metrics.get('http_status')}\n"
        )

        report.write(
            f"Requests         : {metrics.get('total_requests')}\n"
        )

        report.write(
            f"Responses        : {metrics.get('total_responses')}\n"
        )

        report.write(
            f"Failed Requests  : {metrics.get('failed_requests')}\n"
        )

        report.write(
            f"Console Messages : {metrics.get('console_messages')}\n"
        )

        report.write(
            f"Page Errors      : {metrics.get('page_errors')}\n\n"
        )

        if comparison:

            report.write("Comparison Summary\n")
            report.write("-" * 70 + "\n")

            summary = comparison.get("Summary", {})

            report.write(
                f"Dashboard A Score : {summary.get('Dashboard A Score')}\n"
            )

            report.write(
                f"Dashboard B Score : {summary.get('Dashboard B Score')}\n"
            )

            report.write(
                f"Overall Winner    : {summary.get('Overall Winner')}\n"
            )

        report.write("\n")
        report.write("=" * 70 + "\n")
        report.write("End of Report\n")

    return report_file