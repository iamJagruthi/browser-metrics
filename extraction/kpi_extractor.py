# clean_value()
# is_value()
# is_label()
# extract_kpis()
import re
from .models import KPI

def clean_value(value):
    """
    Cleans an OCR extracted KPI value.

    Parameters
    ----------
    value : str

    Returns
    -------
    str
        Normalized KPI value.
    """

    if value is None:
        return ""

    value = str(value).strip()

    # Remove multiple spaces
    value = re.sub(r"\s+", " ", value)

    # Remove spaces around commas
    value = value.replace(" ,", ",")
    value = value.replace(", ", ",")

    # Remove spaces around decimal points
    value = value.replace(" .", ".")
    value = value.replace(". ", ".")

    return value

def is_value(text):
    """
    Determines whether OCR text represents
    a KPI value.

    Parameters
    ----------
    text : str

    Returns
    -------
    bool
    """

    if not text:
        return False

    text = clean_value(text)

    # Currency
    if re.search(r"[₹$€£]", text):
        return True

    # Percentage
    if "%" in text:
        return True

    # Numbers
    if re.fullmatch(
        r"[-+]?\d[\d,]*\.?\d*",
        text
    ):
        return True

    # Numbers with suffix
    if re.fullmatch(
        r"[-+]?\d[\d,]*\.?\d*\s?(K|M|B|T)",
        text,
        re.IGNORECASE,
    ):
        return True

    # Time values
    if re.fullmatch(
        r"\d{1,2}:\d{2}(:\d{2})?",
        text
    ):
        return True

    return False

def is_label(text):
    """
    Determines whether OCR text represents
    a KPI label.

    Parameters
    ----------
    text : str

    Returns
    -------
    bool
    """

    if not text:
        return False

    text = clean_value(text)

    # Ignore values
    if is_value(text):
        return False

    # Ignore very short strings
    if len(text) < 2:
        return False

    # Ignore strings without letters
    if not re.search(r"[A-Za-z]", text):
        return False

    # Ignore separators/symbols
    if re.fullmatch(r"[-_=:/\\|.]+", text):
        return False

    return True

from .models import KPI

def extract_kpis(ocr_results):
    """
    Extract KPI label/value pairs from OCR output.

    Parameters
    ----------
    ocr_results : list

    Returns
    -------
    list[KPI]
    """

    kpis = []

    current_label = None

    for result in ocr_results:

        text = clean_value(result["text"])

        if not text:
            continue

        # --------------------------
        # Label
        # --------------------------

        if is_label(text):
            current_label = text
            continue

        # --------------------------
        # Value
        # --------------------------

        if is_value(text):

            if current_label:

                kpis.append(
                    KPI(
                        name=current_label,
                        value=text,
                        confidence=result["confidence"],
                        bbox=result["bbox"],
                    )
                )

                current_label = None

    return kpis