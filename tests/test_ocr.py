from pathlib import Path

from ..extraction.ocr import extract_text
from ..extraction.kpi_extractor import extract_kpis

image_path = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "screenshots"
    / "HR_Usage_Dashbord.png"
)

ocr_results = extract_text(image_path)

kpis = extract_kpis(ocr_results)

print("\n OCR OUTPUT\n")
print("\nDetected KPIs\n")

for kpi in kpis:
    print(kpi)