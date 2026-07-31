"""
ocr_service.py

Service layer for OCR extraction.
"""

from extraction.ocr import extract_text


def extract_dashboard_text(image_path):
    """
    Extract OCR text from dashboard screenshot.
    """

    return extract_text(image_path)