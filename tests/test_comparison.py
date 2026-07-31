"""
Test complete KPI comparison pipeline.

Flow:
Screenshot A
    ↓
OCR
    ↓
KPIs

Screenshot B
    ↓
OCR
    ↓
KPIs

Comparison
"""

from extraction.ocr import extract_text
from extraction.kpi_extractor import extract_kpis
from automation.comparison import DashboardComparison


SOURCE_IMAGE = "output/screenshots/example_source.png"
TARGET_IMAGE = "output/screenshots/example_target.png"

print(SOURCE_IMAGE)
print(TARGET_IMAGE)

def main():

    print("=" * 60)
    print("POWER BI KPI VALIDATION")
    print("=" * 60)

    # -----------------------------
    # OCR
    # -----------------------------

    print("\nRunning OCR...")

    source_ocr = extract_text(SOURCE_IMAGE)
    target_ocr = extract_text(TARGET_IMAGE)

    # -----------------------------
    # KPI Extraction
    # -----------------------------

    print("Extracting KPIs...")

    source_kpis = extract_kpis(source_ocr)
    target_kpis = extract_kpis(target_ocr)

    print(f"Source KPIs : {len(source_kpis)}")
    print(f"Target KPIs : {len(target_kpis)}")

    # -----------------------------
    # Comparison
    # -----------------------------

    comparison = DashboardComparison()

    results = comparison.compare_kpis(
        source_kpis,
        target_kpis
    )

    # -----------------------------
    # Results
    # -----------------------------

    print("\n")
    print("=" * 60)
    print("KPI COMPARISON RESULTS")
    print("=" * 60)

    for result in results["results"]:

        print(f"\nKPI      : {result['kpi']}")
        print(f"Source   : {result['source']}")
        print(f"Target   : {result['target']}")
        print(f"Status   : {result['status']}")

    print("\n")
    print("=" * 60)

    print(f"Total KPIs      : {results['total_kpis']}")
    print(f"Matched         : {results['matched']}")
    print(f"Near Matched    : {results['near_matched']}")
    print(f"Mismatched      : {results['mismatched']}")
    print(f"Match Percentage: {results['match_percentage']} %")

    print("=" * 60)


if __name__ == "__main__":
    main()