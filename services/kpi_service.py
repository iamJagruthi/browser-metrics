"""
kpi_service.py

Service layer for KPI extraction.
"""

from extraction.kpi_extractor import extract_kpis


def detect_kpis(ocr_results):
    """
    Detect KPIs from OCR output.
    """

    return extract_kpis(ocr_results)