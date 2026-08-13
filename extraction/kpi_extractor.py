import re
from .models import KPI
from math import sqrt


def clean_value(value):

    if value is None:
        return ""

    value = str(value).strip()

    value = re.sub(r"\s+", " ", value)

    value = value.replace(" ,", ",")
    value = value.replace(", ", ",")

    value = value.replace(" .", ".")
    value = value.replace(". ", ".")

    return value

def get_center(bbox):

    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]

    return (
        sum(xs) / len(xs),
        sum(ys) / len(ys)
    )


def get_size(bbox):

    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]

    return (
        max(xs) - min(xs),
        max(ys) - min(ys)
    )

REFRESH_PATTERN = re.compile(
    r"(refresh|updated|loaded|snapshot)",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
)

TIME_PATTERN = re.compile(
    r"\d{1,2}:\d{2}(:\d{2})?\s?(AM|PM)?",
    re.IGNORECASE,
)

IGNORE_PATTERN = re.compile(
    r"(share|export|monitor|subscribe|file|home|help)",
    re.IGNORECASE,
)

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

def classify_text(text):

    text = clean_value(text)

    if not text:
        return "UNKNOWN"

    if IGNORE_PATTERN.search(text):
        return "IGNORE"

    if REFRESH_PATTERN.search(text):
        return "REFRESH"

    if DATE_PATTERN.search(text):
        return "DATE"

    if TIME_PATTERN.search(text):
        return "DATE"

    if is_value(text):
        return "VALUE"

    if is_label(text):
        return "LABEL"

    return "UNKNOWN"

def build_blocks(ocr_results):

    blocks = []

    for result in ocr_results:

        text = clean_value(result["text"])

        if not text:
            continue

        blocks.append({

            "text": text,

            "type": classify_text(text),

            "bbox": result["bbox"],

            "center": get_center(result["bbox"]),

            "size": get_size(result["bbox"]),

            "confidence": result["confidence"]

        })

    return blocks

def is_filter_label(block):

    _, y = block["center"]

    # Filters usually appear in top portion
    # return y < 250

def find_refresh_value(label, blocks):

    lx, ly = label["center"]

    best = None
    score = float("inf")

    for block in blocks:

        if block["type"] != "DATE":
            continue

        vx, vy = block["center"]

        if abs(vy - ly) > 40:
            continue

        if vx < lx:
            continue

        distance = vx - lx

        if distance < score:

            score = distance
            best = block

    return best
def find_filter_value(label, blocks):

    lx, ly = label["center"]

    best = None
    score = float("inf")

    for block in blocks:

        if block["type"] not in ("LABEL", "VALUE", "DATE"):
            continue

        vx, vy = block["center"]

        # Below filter

        if vy < ly:
            continue

        # Same column

        if abs(vx - lx) > 80:
            continue

        distance = vy - ly

        if distance < score:

            score = distance
            best = block

    return best

def find_nearest_value(label, blocks):

    lx, ly = label["center"]

    best = None
    score = float("inf")

    for block in blocks:

        if block["type"] != "VALUE":
            continue

        vx, vy = block["center"]

        dx = vx - lx
        dy = vy - ly

        if dx < -20:
            continue

        if abs(dy) > 120:
            continue

        distance = sqrt(dx**2 + dy**2)

        if distance < score:

            score = distance
            best = block

    return best

def extract_kpis(ocr_results):

    blocks = build_blocks(ocr_results)

    kpis = []

    for block in blocks:

        if block["type"] == "IGNORE":
            continue

        if block["type"] not in ("LABEL", "REFRESH"):
            continue

        # ----------------------------
        # Refresh Date
        # ----------------------------

        if block["type"] == "REFRESH":

            value = find_refresh_value(
                block,
                blocks
            )

        # ----------------------------
        # Filters
        # ----------------------------

        elif is_filter_label(block):

            value = find_filter_value(
                block,
                blocks
            )

        # ----------------------------
        # KPI Cards
        # ----------------------------

        else:

            value = find_nearest_value(
                block,
                blocks
            )

        if value is None:
            continue

        kpis.append(

            KPI(

                name=block["text"],

                value=value["text"],

                confidence=min(
                    block["confidence"],
                    value["confidence"]
                ),

                bbox=block["bbox"]

            )

        )

    return kpis