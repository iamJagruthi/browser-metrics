"""
ocr_service.py

Service layer for OCR extraction.
"""

from extraction.ocr import extract_text


def extract_dashboard_text(image_path):
    """
    Extract OCR text from dashboard screenshot.
    """

    try:
        return extract_text(image_path)

    except Exception as e:
        print(f"Error extracting text from '{image_path}': {e}")
        raise