"""Run ORD portfolio tagging over the filtered Dimensions VA export and report coverage."""
import sys
from pathlib import Path

import pandas as pd

project_root = Path.cwd()
sys.path.insert(0, str(project_root))

from processors.dimensions_processor import read_dimensions_df
from processors.ord_portfolio import (
    AMP_KEYWORD_PATTERNS,
    BROAD_PORTFOLIO_NAMES,
    tag_publications,
)

SOURCE_CSV = project_root / "output/dimensions_va_2025_2026/dimensions_va_2025_2026_filtered_2025-10-01_to_2026-09-30.csv"
OUTPUT_CSV = project_root / "output/dimensions_va_2025_2026/dimensions_va_2025_2026_ord_tagged.csv"


def main() -> None:
    print(f"Loading {SOURCE_CSV.name} ...")
    df = read_dimensions_df(SOURCE_CSV.read_bytes())
    total = len(df)
    print(f"Loaded {total:,} records\n")

    print("Tagging records with ORD Broad Portfolio / Actively Managed Portfolio evidence...")
    tagged = tag_publications(df)

    tagged.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote tagged CSV -> {OUTPUT_CSV}\n")

    print("=" * 80)
    print("COVERAGE SUMMARY")
    print("=" * 80)

    with_evidence = tagged["Has ORD Funding Evidence"].sum()
    print(f"Records with any Broad Portfolio (VA funding) evidence: {with_evidence:,} / {total:,} "
          f"({100 * with_evidence / total:.1f}%)")
    print()

    print("Broad Portfolio breakdown (a record may count in more than one):")
    for code, name in BROAD_PORTFOLIO_NAMES.items():
        count = tagged["ORD Broad Portfolio Codes"].str.contains(rf"\b{code}\b", regex=True, na=False).sum()
        print(f"  {name:<55} ({code:<5}): {count:,} ({100 * count / total:.1f}%)")
    print()

    amp_tagged = tagged["ORD Actively Managed Portfolios"].str.strip().ne("")
    print(f"Records with any Actively Managed Portfolio keyword match: {amp_tagged.sum():,} / {total:,} "
          f"({100 * amp_tagged.sum() / total:.1f}%)")
    print("Actively Managed Portfolio breakdown (a record may count in more than one):")
    for name in AMP_KEYWORD_PATTERNS:
        count = tagged["ORD Actively Managed Portfolios"].str.contains(re_escape(name), regex=True, na=False).sum()
        print(f"  {name:<30}: {count:,} ({100 * count / total:.1f}%)")
    print()

    both = with_evidence & amp_tagged
    print(f"Records with BOTH a Broad Portfolio and an AMP tag: {int((tagged['Has ORD Funding Evidence'] & amp_tagged).sum()):,}")
    neither = (~tagged["Has ORD Funding Evidence"]) & (~amp_tagged)
    print(f"Records with NEITHER tag (no detectable ORD signal): {int(neither.sum()):,} ({100 * neither.sum() / total:.1f}%)")


def re_escape(value: str) -> str:
    import re
    return re.escape(value)


if __name__ == "__main__":
    main()
