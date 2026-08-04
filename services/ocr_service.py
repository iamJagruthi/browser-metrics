"""
ocr_service.py

Service layer for OCR extraction.
"""
from PIL import Image

from extraction.ocr import extract_text
from extraction.layout import classify_regions
from extraction.title_extractor import extract_title
from extraction.refresh_extractor import extract_refresh_date
from extraction.ocr import extract_text


def extract_dashboard_text(image_path):
    image = Image.open(image_path)

<<<<<<< Updated upstream
    try:
        return extract_text(image_path)

    except Exception as e:
        print(f"Error extracting text from '{image_path}': {e}")
        raise
=======
    width, height = image.size

    ocr_results = extract_text(image_path)

    layout = classify_regions(
        ocr_results,
        height,
        width
    )

    return {
        "ocr": ocr_results,
        "layout": layout,
        "title": extract_title(layout),
        "refresh_date": extract_refresh_date(layout)
    }
>>>>>>> Stashed changes
