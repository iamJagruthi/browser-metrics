"""
refresh_extractor.py
"""

import re


DATE_PATTERN = re.compile(
    r"\d{1,2}/\d{1,2}/\d{4}"
)

TIME_PATTERN = re.compile(
    r"\d{1,2}:\d{2}(:\d{2})?\s?(AM|PM)?",
    re.IGNORECASE
)


def extract_refresh_date(layout):

    for item in layout["top_right"]:

        text = item["text"]

        if "refresh" in text.lower():

            return text

        if DATE_PATTERN.search(text):

            return text

        if TIME_PATTERN.search(text):

            return text

    return None