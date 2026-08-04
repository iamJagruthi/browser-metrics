"""
title_extractor.py
"""


def extract_title(layout):

    if not layout["top_left"]:
        return None

    title = max(
        layout["top_left"],
        key=lambda item: len(item["text"])
    )

    return title["text"]