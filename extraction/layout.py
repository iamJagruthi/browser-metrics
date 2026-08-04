"""
layout.py

Classifies OCR results into dashboard regions.
"""


def classify_regions(ocr_results, image_height, image_width):
    """
    Classify OCR results into dashboard regions.

    Returns
    -------
    dict
    """

    layout = {
        "top_left": [],
        "top_right": [],
        "left": [],
        "center": [],
        "bottom": []
    }

    for result in ocr_results:

        bbox = result["bbox"]

        xs = [point[0] for point in bbox]
        ys = [point[1] for point in bbox]

        x = sum(xs) / len(xs)
        y = sum(ys) / len(ys)

        if y < image_height * 0.20:

            if x < image_width * 0.50:
                layout["top_left"].append(result)
            else:
                layout["top_right"].append(result)

        elif x < image_width * 0.25:
            layout["left"].append(result)

        elif y > image_height * 0.70:
            layout["bottom"].append(result)

        else:
            layout["center"].append(result)

    return layout