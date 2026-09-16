"""Combine three category CSV files into one for Excel import."""
import csv
from pathlib import Path
from itertools import zip_longest

OUTPUT_DIR = Path("output")

FILES = [
    ("output/fields_of_research.csv", "Fields of Research (ANZSRC 2020)"),
    ("output/rcdc_categories.csv", "RCDC Categories"),
    ("output/hrcs_hc_categories.csv", "HRCS HC Categories"),
]


def main():
    categories = {}
    for filepath, header in FILES:
        values = []
        with Path(filepath).open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            for row in reader:
                if row:
                    values.append(row[0])
        categories[header] = values

    out_path = OUTPUT_DIR / "all_categories_combined.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        headers = [h for _, h in FILES]
        writer.writerow(headers)
        
        lists = [categories[h] for _, h in FILES]
        for row in zip_longest(*lists, fillvalue=""):
            writer.writerow(row)

    print(f"Combined file created: {out_path}")


if __name__ == "__main__":
    main()
