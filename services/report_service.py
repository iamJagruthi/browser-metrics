"""
report_service.py

Service layer for report generation.
"""

from automation.report import generate_report


def build_report(results):
    """
    Generate validation report.
    """

    try:
        return generate_report(results)

    except Exception as e:
        print(f"Error building report: {e}")
        raise