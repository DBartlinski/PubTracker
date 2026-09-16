"""Extract deduped, sorted lists of category values from dimensions_filtered_3745.csv."""
import csv
from pathlib import Path

INPUT = Path("output/dimensions_filtered_3745.csv")
OUTPUT_DIR = Path("output")

COLUMNS = {
    "Fields of Research (ANZSRC 2020)": "fields_of_research.csv",
    "RCDC Categories": "rcdc_categories.csv",
    "HRCS HC Categories": "hrcs_hc_categories.csv",
}


def main():
    values = {col: set() for col in COLUMNS}

    with INPUT.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for col in COLUMNS:
                raw = row.get(col, "")
                if not raw:
                    continue
                for item in raw.split(";"):
                    item = item.strip()
                    if item:
                        values[col].add(item)

    for col, filename in COLUMNS.items():
        out_path = OUTPUT_DIR / filename
        sorted_values = sorted(values[col])
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([col])
            for v in sorted_values:
                writer.writerow([v])
        print(f"{col}: {len(sorted_values)} unique values -> {out_path}")


if __name__ == "__main__":
    main()
