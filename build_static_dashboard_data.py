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
from processors.pubtracker_crossref import load_pubtracker_submissions, find_latest_export, _normalize_title
from processors.pubtracker_processor import process_pubtracker, get_quarter_label
from processors.dimensions_processor import process_dimensions
from processors.compliance_calculator import calculate_compliance, load_vamc_reference
from processors.ord_portfolio import tag_publications

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

    dim_pub_list, _ = process_dimensions(dim_raw)

    pt_raw = pd.read_excel(pt_path, sheet_name=0)
    pt_counts, _ = process_pubtracker(pt_raw)

    vamc_ref = load_vamc_reference()
    result_df, _, all_quarters, diagnostics = calculate_compliance(pt_counts, dim_pub_list, vamc_ref)
    quarter_labels = [get_quarter_label(fy, q) for fy, q in all_quarters]
    not_in_dim_map = dict(zip(vamc_ref["vamc_display"].astype(str), vamc_ref["not_in_dimensions"]))

    pub_title_map = {}
    if "Publication ID" in dim_raw.columns and "Title" in dim_raw.columns:
        pub_title_map = dict(zip(dim_raw["Publication ID"].astype(str), dim_raw["Title"]))

    # Dimensions matches are the same set across quarters (pre-filtered per SOP) - use the first.
    quarter_diag = diagnostics.get(all_quarters[0], {}) if all_quarters else {}

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
        matched_ids = quarter_diag.get(vamc_name, {}).get("matched_pub_ids", [])
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


if __name__ == "__main__":
    main()
