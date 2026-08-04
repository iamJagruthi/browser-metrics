"""
kpi_service.py

Service layer for KPI extraction.
"""

from extraction.kpi_extractor import extract_kpis


def detect_kpis(ocr_results):
    """
    Detect KPIs from OCR output.
    """

    try:
        return extract_kpis(ocr_results)

    except Exception as e:
        print(f"Error detecting KPIs: {e}")
        raise