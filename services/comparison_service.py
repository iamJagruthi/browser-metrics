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

    try:
        return comparison.compare_kpis(
            source_kpis,
            target_kpis
        )

    except Exception as e:
        print(f"Error comparing dashboard KPIs: {e}")
        raise