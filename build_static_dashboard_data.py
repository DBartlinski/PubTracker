"""Build the slim JSON dataset consumed by docs/dashboard.html (static GitHub Pages dashboard).

Runs the existing dashboard pipeline (load + facility match + ORD tagging) against the
current FY26 filtered Dimensions export, then writes compact JSON files under docs/data/
containing only the columns the static page needs to render (no abstracts/funding text).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

project_root = Path.cwd()
sys.path.insert(0, str(project_root))

from processors.dashboard_data import load_dashboard_dataset, split_values
from processors.pubtracker_crossref import load_pubtracker_submissions

SOURCE_CSV = project_root / "output/dimensions_va_2025_2026/dimensions_va_2025_2026_filtered_2025-10-01_to_2026-09-30.csv"
OUTPUT_DIR = project_root / "docs/data"

PUBLICATION_COLUMNS = {
    "Publication ID": "id",
    "Title": "title",
    "Authors": "authors",
    "Source title": "journal",
    "Document Type": "docType",
    "Canonical Date": "date",
    "Fiscal Year": "fiscalYear",
    "Fiscal Quarter": "fiscalQuarter",
    "Fiscal Period": "fiscalPeriod",
    "SOP Eligible": "sopEligible",
    "Is Open Access": "openAccess",
    "Times cited": "citations",
    "RCR": "rcr",
    "FCR": "fcr",
    "DOI Link": "doiLink",
    "PubMed Link": "pubmedLink",
    "Dimensions for Veterans Affairs URL": "dimensionsLink",
    "Matched Facilities": "facilities",
    "Facility Match Count": "facilityMatchCount",
    "Facility Match Status": "facilityMatchStatus",
    "Broad Research Areas": "researchAreas",
    "ORD Broad Portfolios": "ordBroad",
    "ORD Actively Managed Portfolios": "ordAmp",
    "Has ORD Funding Evidence": "hasOrdEvidence",
}

MATCH_COLUMNS = {
    "Publication ID": "pubId",
    "Facility": "facility",
    "Station Numbers": "stationNumbers",
    "Matched Organization": "matchedOrg",
    "Search Term": "searchTerm",
    "Match Direction": "matchDirection",
    "Match Strength": "matchStrength",
}


def _clean_records(frame: pd.DataFrame, column_map: dict[str, str]) -> list[dict]:
    slim = frame[list(column_map)].rename(columns=column_map)
    for column in slim.columns:
        if pd.api.types.is_datetime64_any_dtype(slim[column]):
            slim[column] = slim[column].dt.strftime("%Y-%m-%d")
    for column in ("fiscalYear", "fiscalQuarter"):
        if column in slim.columns:
            slim[column] = slim[column].astype("Int64")
    # Cast to object first so assigning None doesn't get silently coerced back to NaN
    # by pandas' float-column semantics (json.dumps would otherwise emit invalid "NaN").
    slim = slim.astype(object).where(pd.notna(slim), None)
    records = slim.to_dict(orient="records")
    for record in records:
        for key in ("researchAreas", "facilities"):
            if key in record and record[key]:
                record[key] = split_values(record[key])
        for key in ("ordBroad", "ordAmp"):
            if key in record and record[key]:
                record[key] = split_values(record[key])
    return records


def main() -> None:
    print(f"Loading dashboard dataset from {SOURCE_CSV.name} ...")
    dataset = load_dashboard_dataset(str(SOURCE_CSV))
    print(f"Publications: {len(dataset.publications):,} | Facility matches: {len(dataset.facility_matches):,}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    publications = _clean_records(dataset.publications, PUBLICATION_COLUMNS)
    matches = _clean_records(dataset.facility_matches, MATCH_COLUMNS)

    pub_path = OUTPUT_DIR / "publications.json"
    match_path = OUTPUT_DIR / "facility_matches.json"
    pub_path.write_text(json.dumps(publications, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    match_path.write_text(json.dumps(matches, separators=(",", ":"), allow_nan=False), encoding="utf-8")

    meta = {
        "generatedFrom": SOURCE_CSV.name,
        "publicationCount": len(publications),
        "facilityMatchCount": len(matches),
    }
    (OUTPUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"Wrote {pub_path} ({pub_path.stat().st_size / 1_048_576:.2f} MB)")
    print(f"Wrote {match_path} ({match_path.stat().st_size / 1_048_576:.2f} MB)")

    pubtracker = load_pubtracker_submissions()
    crossref_path = OUTPUT_DIR / "pubtracker_crossref.json"
    if pubtracker.empty:
        crossref_path.write_text("[]", encoding="utf-8")
        print("No PubTracker export found in 'PubTracker Export/' - wrote empty pubtracker_crossref.json")
    else:
        crossref_records = pubtracker.rename(columns={
            "_norm_title": "normTitle",
            "PubTracker Reported Portfolio": "reportedPortfolio",
            "PubTracker VA Funded": "vaFunded",
        }).to_dict(orient="records")
        crossref_path.write_text(json.dumps(crossref_records, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote {crossref_path} ({crossref_path.stat().st_size / 1_048_576:.2f} MB, {len(crossref_records):,} submissions)")


if __name__ == "__main__":
    main()
