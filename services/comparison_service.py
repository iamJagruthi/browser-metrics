"""
comparison_service.py

Service layer for KPI comparison.
"""

from automation.comparison import DashboardComparison


comparison = DashboardComparison()


def compare_dashboard_kpis(
    source_kpis,
    target_kpis
):
    """
    Compare KPI lists.
    """

    return comparison.compare_kpis(
        source_kpis,
        target_kpis
    )