"""Build the slim JSON dataset consumed by docs/dashboard.html (static GitHub Pages dashboard).

Runs the existing dashboard pipeline (load + facility match + ORD tagging) against the
current FY26 filtered Dimensions export, then writes compact JSON files under docs/data/
containing only the columns the static page needs to render (no abstracts/funding text).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

project_root = Path.cwd()
sys.path.insert(0, str(project_root))

from processors.dashboard_data import load_dashboard_dataset, split_values
from processors.pubtracker_crossref import load_pubtracker_submissions, find_latest_export, _normalize_title
from processors.pubtracker_processor import process_pubtracker, get_quarter_label
from processors.dimensions_processor import process_dimensions_by_quarter
from processors.compliance_calculator import calculate_compliance, load_vamc_reference
from processors.ord_portfolio import tag_publications
from processors.pubtracker_compliance import (
    UNATTRIBUTED,
    build_station_lookup,
    facility_map,
    filter_fiscal_year,
    load_pubtracker_files,
    match_to_pubtracker,
    quarter_options,
)

PUBTRACKER_GAP_PATHS = [
    project_root / "PubTracker Export/submissionlist20261005132200-2025.xlsx",
    project_root / "PubTracker Export/submissionlist20261005132200-2026.xlsx",
]
GAP_MIN_THRESHOLD = 70
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


def build_compliance_payload() -> dict | None:
    """Precompute the compliance table + PubTracker corroboration counts server-side.

    Only aggregated counts are returned (no raw PubTracker titles/rows), since this
    payload is published to the public GitHub Pages site.
    """
    pt_path = find_latest_export()
    if pt_path is None:
        return None

    dim_raw = pd.read_csv(SOURCE_CSV)
    dim_raw = tag_publications(dim_raw)

    pt_submissions = load_pubtracker_submissions(pt_path)
    pubtracker_norm_titles = set(pt_submissions["_norm_title"]) if not pt_submissions.empty else set()

    # Only count confirmed ORD-funded Dimensions records: funding-text evidence, OR a title
    # match to a PubTracker submission (PubTracker submissions are ORD-funded by definition).
    if "Title" in dim_raw.columns:
        title_matched = dim_raw["Title"].map(_normalize_title).isin(pubtracker_norm_titles)
    else:
        title_matched = pd.Series(False, index=dim_raw.index)
    ord_funded_mask = dim_raw["Has ORD Funding Evidence"].fillna(False) | title_matched
    dim_raw = dim_raw[ord_funded_mask].copy()

    # Split by each record's own publication date instead of one flat pool applied
    # identically to every quarter, so quarter-over-quarter Dimensions counts differ.
    dim_pub_list, _ = process_dimensions_by_quarter(dim_raw)

    pt_raw = pd.read_excel(pt_path, sheet_name=0)
    pt_counts, _ = process_pubtracker(pt_raw)

    vamc_ref = load_vamc_reference()
    result_df, _, all_quarters, diagnostics = calculate_compliance(pt_counts, dim_pub_list, vamc_ref)
    quarter_labels = [get_quarter_label(fy, q) for fy, q in all_quarters] + ["FY Total"]
    not_in_dim_map = dict(zip(vamc_ref["vamc_display"].astype(str), vamc_ref["not_in_dimensions"]))

    pub_title_map = {}
    if "Publication ID" in dim_raw.columns and "Title" in dim_raw.columns:
        pub_title_map = dict(zip(dim_raw["Publication ID"].astype(str), dim_raw["Title"]))

    # Year-deduplicated pool (dim_count/matched_pub_ids consistent across quarters) for corroboration.
    fy_diag = diagnostics.get("FY_TOTAL", {})

    vamcs = []
    total_corroborated = 0
    total_matched = 0
    for _, row in result_df[result_df["VAMC"] != "TOTAL"].iterrows():
        vamc_name = row["VAMC"]
        # Strip the +/- prefix compliance_calculator adds - the JS renderer re-derives it from magnitude.
        per_quarter = {
            label: {
                "pt": int(row.get(f"{label} PubTracker Count", 0)),
                "dim": int(row.get(f"{label} Dimensions Count", 0)),
                "pct": str(row.get(f"{label} % Entered", "")).lstrip("+-"),
            }
            for label in quarter_labels
        }
        matched_ids = fy_diag.get(vamc_name, {}).get("matched_pub_ids", [])
        matched_titles = [pub_title_map.get(pid) for pid in matched_ids if pub_title_map.get(pid)]
        corroborated = sum(1 for t in matched_titles if _normalize_title(t) in pubtracker_norm_titles)
        total_corroborated += corroborated
        total_matched += len(matched_titles)
        vamcs.append({
            "vamc": vamc_name,
            "stationNo": row.get("Station No.", ""),
            "vaFunded": row.get("VA Funded", ""),
            "notInDim": bool(not_in_dim_map.get(vamc_name, False)),
            "perQuarter": per_quarter,
            "crossref": {"matched": len(matched_titles), "corroborated": corroborated},
        })

    total_row = result_df[result_df["VAMC"] == "TOTAL"]
    total = {}
    if not total_row.empty:
        t = total_row.iloc[0]
        total = {
            label: {
                "pt": int(t.get(f"{label} PubTracker Count", 0)),
                "dim": int(t.get(f"{label} Dimensions Count", 0)),
                "pct": str(t.get(f"{label} % Entered", "")).lstrip("+-"),
            }
            for label in quarter_labels
        }

    return {
        "generatedFrom": {"dimensions": SOURCE_CSV.name, "pubtracker": pt_path.name},
        "quarters": quarter_labels,
        "vamcs": vamcs,
        "total": total,
        "crossrefSummary": {"matched": total_matched, "corroborated": total_corroborated},
    }


def build_pubtracker_gap_payload(publications: pd.DataFrame, facility_matches: pd.DataFrame) -> dict | None:
    """Dimensions FY26 records with their best PubTracker title-match score, for the static slider.

    Each record carries its best facility-compatible match score against ALL PubTracker rows (0 below
    the minimum threshold, 100 = exact), so the page can apply any threshold. PubTracker's own date is
    not used: the Dimensions publication date decides which period a record belongs to.
    Only Dimensions data and scores are written (no PubTracker titles or submitter data), since
    this is published to the public GitHub Pages site.
    """
    if not all(path.exists() for path in PUBTRACKER_GAP_PATHS):
        return None

    pubtracker = load_pubtracker_files(PUBTRACKER_GAP_PATHS, build_station_lookup())
    scoped, _ = filter_fiscal_year(publications)
    pub_facilities = facility_map(facility_matches)

    results = match_to_pubtracker(scoped, pub_facilities, pubtracker, GAP_MIN_THRESHOLD)
    scores = dict(zip(results["Publication ID"], (results["Match Score"] * 10).apply(math.floor) / 10))
    periods = {
        label: {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")}
        for label, (start, end) in quarter_options(scoped).items()
    }

    facility_names = sorted({name for names in pub_facilities.values() for name in names})
    facility_index = {name: i for i, name in enumerate(facility_names)}
    ordered = scoped.sort_values("Canonical Date", ascending=False)
    records = []
    for row in ordered.to_dict("records"):
        pub_id = row["Publication ID"]
        doi = str(row.get("DOI Link") or "").removeprefix("https://doi.org/")
        pmid = str(row.get("PubMed Link") or "").removeprefix("https://pubmed.ncbi.nlm.nih.gov/").strip("/")
        journal = row.get("Source title")
        records.append([
            pub_id,
            row["Canonical Date"].strftime("%Y-%m-%d"),
            str(row.get("Title") or ""),
            journal if isinstance(journal, str) else "",
            doi,
            pmid,
            sorted(facility_index[name] for name in pub_facilities.get(pub_id, ())),
            scores.get(pub_id, 0),
        ])
    return {
        "minThreshold": GAP_MIN_THRESHOLD,
        "defaultThreshold": 90,
        "pubtrackerRows": len(pubtracker),
        "unattributedLabel": UNATTRIBUTED,
        "periods": periods,
        "facilities": facility_names,
        # [id, date, title, journal, doi, pmid, facilityIdx[], bestMatchScore]
        "records": records,
    }


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def build_not_in_pubtracker_payload(publications: pd.DataFrame, facility_matches: pd.DataFrame) -> dict | None:
    """Build 02 data: eligible FY26 Dimensions records, found/not found at the fixed 90% threshold, with funding codes.

    Public output, so only Dimensions fields and a found flag are written (no PubTracker titles, dates or IDs).
    """
    if not all(path.exists() for path in PUBTRACKER_GAP_PATHS):
        return None

    pubtracker = load_pubtracker_files(PUBTRACKER_GAP_PATHS, build_station_lookup())
    scoped, _ = filter_fiscal_year(publications)
    pub_facilities = facility_map(facility_matches)
    results = match_to_pubtracker(scoped, pub_facilities, pubtracker, 90.0)
    found = dict(zip(results["Publication ID"], results["Match Type"].ne("Missing")))

    facility_names = sorted({name for names in pub_facilities.values() for name in names})
    facility_index = {name: i for i, name in enumerate(facility_names)}
    records = []
    for row in scoped.sort_values("Canonical Date", ascending=False).to_dict("records"):
        pub_id = row["Publication ID"]
        records.append([
            pub_id,
            row["Canonical Date"].strftime("%Y-%m-%d"),
            _text(row.get("Fiscal Period")),
            _text(row.get("Title")),
            _text(row.get("Source title")),
            _text(row.get("DOI Link")).removeprefix("https://doi.org/"),
            _text(row.get("PubMed Link")).removeprefix("https://pubmed.ncbi.nlm.nih.gov/").strip("/"),
            sorted(facility_index[name] for name in pub_facilities.get(pub_id, ())),
            int(bool(found.get(pub_id))),
            int(bool(row.get("Has ORD Funding Evidence"))),
            _text(row.get("ORD Broad Portfolio Codes")),
            _text(row.get("ORD Broad Portfolios")),
            _text(row.get("Funder")),
            _text(row.get("Supporting Grants")),
        ])
    periods = {
        label: {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")}
        for label, (start, end) in quarter_options(scoped).items()
    }
    return {
        "threshold": 90,
        "unattributedLabel": UNATTRIBUTED,
        "periods": periods,
        "facilities": facility_names,
        # [id, date, fiscalPeriod, title, journal, doi, pmid, facilityIdx[], inPubTracker, ordFunded,
        #  vaGrantCodes, ordPortfolio, funders, grantNumbers]
        "records": records,
    }


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

    compliance_payload = build_compliance_payload()
    compliance_path = OUTPUT_DIR / "compliance.json"
    if compliance_payload is None:
        compliance_path.write_text("null", encoding="utf-8")
        print("No PubTracker export found in 'PubTracker Export/' - wrote empty compliance.json")
    else:
        compliance_path.write_text(json.dumps(compliance_payload, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote {compliance_path} ({compliance_path.stat().st_size / 1024:.1f} KB, {len(compliance_payload['vamcs']):,} VAMCs)")

    gap_payload = build_pubtracker_gap_payload(dataset.publications, dataset.facility_matches)
    gap_path = OUTPUT_DIR / "pubtracker_gap.json"
    if gap_payload is None:
        gap_path.write_text("null", encoding="utf-8")
        print("PubTracker exports for the gap report not found - wrote empty pubtracker_gap.json")
    else:
        gap_path.write_text(json.dumps(gap_payload, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote {gap_path} ({gap_path.stat().st_size / 1_048_576:.2f} MB, {len(gap_payload['periods'])} periods)")

    build02_payload = build_not_in_pubtracker_payload(dataset.publications, dataset.facility_matches)
    build02_path = OUTPUT_DIR / "not_in_pubtracker.json"
    build02_path.write_text(
        json.dumps(build02_payload, separators=(",", ":")) if build02_payload else "null", encoding="utf-8"
    )
    print(f"Wrote {build02_path} ({build02_path.stat().st_size / 1_048_576:.2f} MB)")


if __name__ == "__main__":
    main()
