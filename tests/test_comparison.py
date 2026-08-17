"""
Test KPI comparison using comparison_service (live validation path).
"""

from extraction.kpi_extractor import extract_kpis
from extraction.ocr import extract_text
from services.comparison_service import compare_kpi_cards


SOURCE_IMAGE = "output/screenshots/example_source.png"
TARGET_IMAGE = "output/screenshots/example_target.png"


def main():
    print("=" * 60)
    print("POWER BI KPI VALIDATION")
    print("=" * 60)

    print("\nRunning OCR...")
    source_ocr = extract_text(SOURCE_IMAGE)
    target_ocr = extract_text(TARGET_IMAGE)

    print("Extracting KPIs...")
    source_kpis = extract_kpis(source_ocr)
    target_kpis = extract_kpis(target_ocr)
    print(f"Source KPIs : {len(source_kpis)}")
    print(f"Target KPIs : {len(target_kpis)}")

    results = compare_kpi_cards(
        {"kpi_cards": source_kpis},
        {"kpi_cards": target_kpis},
    )

    print("\n")
    print("=" * 60)
    print("KPI COMPARISON RESULTS")
    print("=" * 60)

    for result in results:
        print(f"\nKPI      : {result.get('kpi')}")
        print(f"Source   : {result.get('source')}")
        print(f"Target   : {result.get('target')}")
        print(f"Status   : {result.get('status')}")

    matches = sum(1 for item in results if item.get("status") == "Match")
    print("\n")
    print("=" * 60)
    print(f"Total KPIs      : {len(results)}")
    print(f"Matched         : {matches}")
    if results:
        print(f"Match Percentage: {round((matches / len(results)) * 100, 2)} %")
    print("=" * 60)


if __name__ == "__main__":
    main()
