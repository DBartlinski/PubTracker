"""Build and cache the combined multi-batch Dimensions dashboard dataset.

Combines the 2016-2019, 2020-2024, and FY24-FY25 batch-export merges (see
`processors/combined_dashboard_data.py`), runs the full enrichment pipeline
(fiscal periods, SOP eligibility, facility matching, ORD portfolio tagging,
preprint flagging), and writes the result to Parquet so `combined_dashboard.py`
can load it quickly without re-processing ~150k rows on every run.

Usage:
    python build_combined_dashboard_data.py [--out-dir output/combined_dashboard]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from processors.combined_dashboard_data import DEFAULT_SOURCE_BATCHES, build_combined_dataset

# Columns combined_dashboard.py actually reads. A --public build drops everything else
# (raw Abstract/Funding/Acknowledgements/MeSH/affiliation text), shrinking the cache from
# ~300MB to a size that fits in a git repo for sharing the app on Streamlit Community Cloud.
PUBLIC_COLUMNS = [
    "Publication ID", "Title", "Authors", "DOI", "PMID", "Source title", "Document Type",
    "Canonical Date", "Calendar Year", "Fiscal Year", "Fiscal Quarter", "Fiscal Period",
    "SOP Eligible", "Is Preprint", "Is Open Access", "Times cited",
    "Matched Facilities", "Facility Match Count", "Facility Match Status",
    "ORD Broad Portfolio Codes", "ORD Broad Portfolios", "ORD Actively Managed Portfolios",
    "ORD Actively Managed Portfolios (Topic Only, Unconfirmed)", "Has ORD Funding Evidence",
    "RCDC Categories", "HRCS HC Categories", "Fields of Research (ANZSRC 2020)",
    "Broad Research Areas", "Health Research Areas", "Source Batches",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="output/combined_dashboard")
    parser.add_argument(
        "--public", action="store_true",
        help="Drop raw text columns (Abstract/Funding/Acknowledgements/etc.) not used by the "
             "dashboard, for a much smaller cache suitable for committing to a public repo.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading and combining batch exports:")
    for label, path in DEFAULT_SOURCE_BATCHES:
        print(f"  - {label}: {path}")
    dataset = build_combined_dataset()

    publications = dataset.publications
    source_columns = dataset.source_columns
    if args.public:
        keep = [column for column in PUBLIC_COLUMNS if column in publications.columns]
        publications = publications[keep].copy()
        source_columns = tuple()

    publications_path = out_dir / "combined_publications.parquet"
    matches_path = out_dir / "combined_facility_matches.parquet"
    meta_path = out_dir / "meta.json"

    publications.to_parquet(publications_path, index=False)
    dataset.facility_matches.to_parquet(matches_path, index=False)
    meta = {
        "public": args.public,
        "source_batches": dict(DEFAULT_SOURCE_BATCHES),
        "raw_row_counts": dataset.batch_counts,
        "unique_publications": len(publications),
        "facility_match_rows": len(dataset.facility_matches),
        "source_columns": list(source_columns),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\nCombined dataset: {len(publications):,} unique publications")
    print(f"Raw rows per batch (before de-dup): {dataset.batch_counts}")
    print(f"Facility match rows: {len(dataset.facility_matches):,}")
    print(f"Wrote:\n  {publications_path}\n  {matches_path}\n  {meta_path}")


if __name__ == "__main__":
    main()
