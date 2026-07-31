"""
ocr.py

Extracts text from dashboard screenshots using EasyOCR.
"""

from pathlib import Path

import easyocr

# --------------------------------------------------
# Initialize OCR Reader
# --------------------------------------------------

_reader = easyocr.Reader(
    ["en"],
    gpu=False,
)


def extract_text(image_path):
    """
    Perform OCR on a screenshot.

    Parameters
    ----------
    image_path : str | Path

    Returns
    -------
    list[dict]
        OCR results containing text,
        confidence and bounding box.
    """

    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Screenshot not found: {image_path}"
        )

    results = _reader.readtext(str(image_path))

    output = []

    for bbox, text, confidence in results:

        output.append(
            {
                "text": text.strip(),
                "confidence": round(float(confidence), 3),
                "bbox": bbox,
            }
        )

    return output