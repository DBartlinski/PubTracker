"""Dimensions-vs-PubTracker submission compliance.

Dimensions is treated as the true source; PubTracker is the user-submitted supplement
being audited. Only titles are shared between the two exports, so matching is
normalized-exact title first, then fuzzy title (gated by facility agreement).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from processors.compliance_calculator import get_station_numbers, load_vamc_reference
from processors.dashboard_data import UMBRELLA_STATION_NUMBERS
from processors.pubtracker_crossref import _normalize_title
from processors.pubtracker_processor import get_quarter_date_range, get_quarter_label

FY26_START = pd.Timestamp("2025-10-01")
FY26_END = pd.Timestamp("2026-09-30")
UNATTRIBUTED = "Unattributed (no VAMC match)"
# Dimensions `Publication Type` values that are not published journal items; unknown values are kept.
NON_PUBLICATION_TYPES = {"preprint", "chapter", "proceeding", "book", "monograph", "edited book", "seminar"}

PUBTRACKER_COLUMNS = ["Record ID", "Title", "Date Created", "POC Medical Center", "POC Medical Center Number"]


def build_station_lookup(reference: pd.DataFrame | None = None) -> dict[str, set[str]]:
    """Map every station number (incl. alternates) to the reference facility display names."""
    reference = load_vamc_reference() if reference is None else reference
    lookup: dict[str, set[str]] = {}
    for _, row in reference.iterrows():
        stations = get_station_numbers(row.get("station_no"), row.get("alt_station_nos"))
        if stations & UMBRELLA_STATION_NUMBERS:
            continue
        for station in stations:
            lookup.setdefault(station, set()).add(row["vamc_display"])
    return lookup


def _read_pubtracker_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, sheet_name=0, dtype=object)
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig")


def load_pubtracker_files(paths: list[str | Path], station_lookup: dict[str, set[str]]) -> pd.DataFrame:
    """Load PubTracker `publication` rows from one or more exports.

    `PubTracker Date` is the Publication Date (comparable to Dimensions), falling back to Date Created.
    """
    frames = [_read_pubtracker_file(Path(path)) for path in paths]
    raw = pd.concat(frames, ignore_index=True).drop_duplicates(subset="Record ID")
    type_column = "Submittion Type" if "Submittion Type" in raw.columns else "Submission Type"
    raw = raw[raw[type_column].fillna("").astype(str).str.strip().str.lower() == "publication"].copy()
    raw["_norm_title"] = raw["Title"].map(_normalize_title)
    raw = raw[raw["_norm_title"] != ""].reset_index(drop=True)
    raw["_facilities"] = raw["POC Medical Center Number"].map(
        lambda value: frozenset(station_lookup.get(str(value).strip().removesuffix(".0"), set()))
    )
    raw["Date Created"] = pd.to_datetime(raw["Date Created"], errors="coerce", format="mixed")
    raw["Publication Date"] = pd.to_datetime(raw["Publication Date"], errors="coerce", format="mixed")
    raw["PubTracker Date"] = raw["Publication Date"].fillna(raw["Date Created"])
    raw["PubTracker Date Source"] = np.where(raw["Publication Date"].notna(), "Publication Date", "Date Created")
    return raw[PUBTRACKER_COLUMNS + ["Publication Date", "PubTracker Date", "PubTracker Date Source", "_norm_title", "_facilities"]]


def quarter_options(publications: pd.DataFrame, fiscal_year: int = 26) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Selectable periods (whole year plus each FY quarter present in the Dimensions data)."""
    options = {f"Whole FY{fiscal_year}": (FY26_START, FY26_END)}
    present = set(publications["Fiscal Period"].dropna())
    for quarter in (1, 2, 3, 4):
        label = get_quarter_label(2000 + fiscal_year, quarter)
        if label in present:
            start, end = get_quarter_date_range(2000 + fiscal_year, quarter)
            options[label] = (pd.Timestamp(start), pd.Timestamp(end))
    return options


REASON_DOCUMENT_TYPE = "Conference abstract / correction"
REASON_PUBLICATION_TYPE = "Non-publication type"
REASON_UNDATED = "Year-only or missing date"
REASON_OUT_OF_RANGE = "Outside selected period"


def exclusion_reasons(
    publications: pd.DataFrame,
    start: pd.Timestamp = FY26_START,
    end: pd.Timestamp = FY26_END,
) -> pd.Series:
    """First failing eligibility rule per record ('' = eligible and dated within [start, end])."""
    sop_eligible = publications["SOP Eligible"].astype(bool)
    if "Publication Type" in publications.columns:
        publication_type = publications["Publication Type"].fillna("").astype(str).str.strip()
        is_publication = ~publication_type.str.lower().isin(NON_PUBLICATION_TYPES)
    else:
        publication_type = pd.Series("", index=publications.index)
        is_publication = pd.Series(True, index=publications.index)
    dated = publications["Canonical Date"].notna() & publications["Date Precision"].ne("year")
    in_range = publications["Canonical Date"].between(start, end)
    reasons = pd.Series("", index=publications.index, dtype=object)
    reasons[~in_range] = REASON_OUT_OF_RANGE
    reasons[~dated] = REASON_UNDATED
    reasons[~is_publication] = REASON_PUBLICATION_TYPE + ": " + publication_type[~is_publication]
    reasons[~sop_eligible] = REASON_DOCUMENT_TYPE
    return reasons


def filter_fiscal_year(
    publications: pd.DataFrame,
    start: pd.Timestamp = FY26_START,
    end: pd.Timestamp = FY26_END,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Keep published-item records dated within [start, end]; year-only dates cannot be placed."""
    reasons = exclusion_reasons(publications, start, end)
    stats = {
        "source_records": len(publications),
        "excluded_document_type": int(reasons.eq(REASON_DOCUMENT_TYPE).sum()),
        "excluded_publication_type": int(reasons.str.startswith(REASON_PUBLICATION_TYPE).sum()),
        "excluded_undated_or_year_only": int(reasons.eq(REASON_UNDATED).sum()),
        "excluded_out_of_range": int(reasons.eq(REASON_OUT_OF_RANGE).sum()),
    }
    scoped = publications[reasons.eq("")].copy()
    stats["in_scope"] = len(scoped)
    return scoped, stats


def facility_map(matches: pd.DataFrame) -> dict[str, frozenset[str]]:
    return {
        pub_id: frozenset(group)
        for pub_id, group in matches.groupby("Publication ID")["Facility"]
    }


def _best_matches(
    query_titles: list[str],
    query_facilities: list[frozenset[str]],
    target_titles: list[str],
    target_facilities: list[frozenset[str]],
    threshold: float,
    chunk_size: int = 500,
) -> dict[int, tuple[str, float, int]]:
    """Exact normalized-title match, else best fuzzy match whose facilities overlap (or one side has none)."""
    exact_index: dict[str, int] = {}
    for position, title in enumerate(target_titles):
        exact_index.setdefault(title, position)

    results: dict[int, tuple[str, float, int]] = {}
    pending = []
    for i, title in enumerate(query_titles):
        if not title:
            continue
        if title in exact_index:
            results[i] = ("Matched (exact)", 100.0, exact_index[title])
        else:
            pending.append(i)

    if not target_titles:
        return results
    for offset in range(0, len(pending), chunk_size):
        chunk = pending[offset:offset + chunk_size]
        scores = process.cdist(
            [query_titles[i] for i in chunk],
            target_titles,
            scorer=fuzz.ratio,
            dtype=np.float32,
            score_cutoff=threshold,
            workers=-1,
        )
        for row, i in enumerate(chunk):
            candidates = np.flatnonzero(scores[row] >= threshold)
            if candidates.size == 0:
                continue
            own = query_facilities[i]
            for position in candidates[np.argsort(-scores[row][candidates], kind="stable")]:
                theirs = target_facilities[position]
                if not own or not theirs or own & theirs:
                    results[i] = ("Matched (fuzzy)", float(scores[row][position]), int(position))
                    break
    return results


def match_to_pubtracker(
    publications: pd.DataFrame,
    pub_facilities: dict[str, frozenset[str]],
    pubtracker: pd.DataFrame,
    threshold: float = 90.0,
) -> pd.DataFrame:
    """Tag each Dimensions record Matched (exact) / Matched (fuzzy) / Missing."""
    pub_ids = publications["Publication ID"].tolist()
    results = _best_matches(
        publications["Title"].map(_normalize_title).tolist(),
        [pub_facilities.get(pub_id, frozenset()) for pub_id in pub_ids],
        pubtracker["_norm_title"].tolist(),
        pubtracker["_facilities"].tolist(),
        threshold,
    )

    rows = []
    for i, pub_id in enumerate(pub_ids):
        match_type, score, position = results.get(i, ("Missing", 0.0, -1))
        found = position >= 0
        rows.append({
            "Publication ID": pub_id,
            "Match Type": match_type,
            "Match Score": score,
            "PubTracker Record ID": pubtracker["Record ID"].iloc[position] if found else "",
            "PubTracker Title": pubtracker["Title"].iloc[position] if found else "",
            "PubTracker Facility": pubtracker["POC Medical Center"].iloc[position] if found else "",
        })
    return pd.DataFrame(rows)


def facility_rates(
    results: pd.DataFrame,
    pub_facilities: dict[str, frozenset[str]],
) -> pd.DataFrame:
    """Per-facility Dimensions total, found in PubTracker, missing, and submission rate (%)."""
    rows = []
    for pub_id, match_type in zip(results["Publication ID"], results["Match Type"]):
        for facility in pub_facilities.get(pub_id) or (UNATTRIBUTED,):
            rows.append((facility, match_type != "Missing"))
    pairs = pd.DataFrame(rows, columns=["Facility", "Found"])
    if pairs.empty:
        return pd.DataFrame(columns=["Facility", "Dimensions Records", "In PubTracker", "Missing", "Submission Rate %"])
    summary = pairs.groupby("Facility").agg(
        **{"Dimensions Records": ("Found", "size"), "In PubTracker": ("Found", "sum")}
    ).reset_index()
    summary["Missing"] = summary["Dimensions Records"] - summary["In PubTracker"]
    summary["Submission Rate %"] = (summary["In PubTracker"] / summary["Dimensions Records"] * 100).round(1)
    return summary.sort_values(["Missing", "Dimensions Records"], ascending=False).reset_index(drop=True)


def quarter_rates(results: pd.DataFrame, scoped: pd.DataFrame) -> pd.DataFrame:
    """Submission rate per fiscal period, assigned by the Dimensions date only."""
    frame = results[["Publication ID", "Match Type"]].merge(
        scoped[["Publication ID", "Fiscal Period"]], on="Publication ID", how="left"
    )
    frame["Found"] = frame["Match Type"].ne("Missing")
    summary = frame.groupby("Fiscal Period").agg(
        **{"Dimensions Records": ("Found", "size"), "In PubTracker": ("Found", "sum")}
    ).reset_index()
    summary["Not in PubTracker"] = summary["Dimensions Records"] - summary["In PubTracker"]
    summary["Submission Rate %"] = (summary["In PubTracker"] / summary["Dimensions Records"] * 100).round(1)
    return summary.sort_values("Fiscal Period").reset_index(drop=True)


FACILITY_RECORD_COLUMNS = [
    "Dimensions Date", "Fiscal Period", "Facility", "Title", "Journal", "Document Type",
    "ORD Funded", "VA Grant Codes", "ORD Portfolio", "Funders", "Grant Numbers",
    "DOI", "PubMed", "Dimensions URL", "Publication ID",
]
MATCH_COLUMNS = ["Match Type", "Match Score", "PubTracker Record ID"]


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def records_by_facility(
    results: pd.DataFrame,
    scoped: pd.DataFrame,
    pub_facilities: dict[str, frozenset[str]],
    in_pubtracker: bool = False,
) -> pd.DataFrame:
    """One row per (Dimensions record, facility) found / not found in PubTracker, newest Dimensions date first."""
    found = results["Match Type"].ne("Missing")
    selected = results[found if in_pubtracker else ~found].set_index("Publication ID")
    records = scoped[scoped["Publication ID"].isin(selected.index)]
    rows = []
    for row in records.to_dict("records"):
        pub_id = row["Publication ID"]
        base = {
            "Dimensions Date": row["Canonical Date"],
            "Fiscal Period": _text(row.get("Fiscal Period")),
            "Title": _text(row.get("Title")),
            "Journal": _text(row.get("Source title")),
            "Document Type": _text(row.get("Document Type")),
            "ORD Funded": bool(row.get("Has ORD Funding Evidence", False)),
            "VA Grant Codes": _text(row.get("ORD Broad Portfolio Codes")),
            "ORD Portfolio": _text(row.get("ORD Broad Portfolios")),
            "Funders": _text(row.get("Funder")),
            "Grant Numbers": _text(row.get("Supporting Grants")),
            "DOI": _text(row.get("DOI Link")),
            "PubMed": _text(row.get("PubMed Link")),
            "Dimensions URL": _text(row.get("Dimensions for Veterans Affairs URL")),
            "Publication ID": pub_id,
        }
        if in_pubtracker:
            match = selected.loc[pub_id]
            base.update({column: match[column] for column in MATCH_COLUMNS})
        for facility in sorted(pub_facilities.get(pub_id) or (UNATTRIBUTED,)):
            rows.append({**base, "Facility": facility})
    columns = FACILITY_RECORD_COLUMNS + (MATCH_COLUMNS if in_pubtracker else [])
    frame = pd.DataFrame(rows, columns=columns)
    return frame.sort_values(["Dimensions Date", "Facility"], ascending=[False, True]).reset_index(drop=True)


def not_in_pubtracker_by_facility(
    results: pd.DataFrame,
    scoped: pd.DataFrame,
    pub_facilities: dict[str, frozenset[str]],
) -> pd.DataFrame:
    return records_by_facility(results, scoped, pub_facilities, in_pubtracker=False)


def matched_records_table(
    results: pd.DataFrame,
    scoped: pd.DataFrame,
    pubtracker: pd.DataFrame,
    pub_facilities: dict[str, frozenset[str]],
) -> pd.DataFrame:
    """Matched records with the Dimensions date as the published date; PubTracker dates kept for audit."""
    matched = results[results["Match Type"].ne("Missing")]
    dims = scoped[["Publication ID", "Title", "Canonical Date"]].rename(columns={"Canonical Date": "Dimensions Date"})
    pt = pubtracker[["Record ID", "Date Created", "Publication Date"]].drop_duplicates("Record ID").rename(columns={
        "Record ID": "PubTracker Record ID",
        "Date Created": "PubTracker Date Created",
        "Publication Date": "PubTracker Publication Date",
    })
    table = matched[["Publication ID", "PubTracker Record ID", "Match Type", "Match Score"]].merge(
        dims, on="Publication ID", how="left"
    ).merge(pt, on="PubTracker Record ID", how="left")
    table["Facilities"] = table["Publication ID"].map(
        lambda pub_id: "; ".join(sorted(pub_facilities.get(pub_id, ()))) or UNATTRIBUTED
    )
    return table[[
        "Publication ID", "Title", "Dimensions Date", "PubTracker Record ID", "PubTracker Date Created",
        "PubTracker Publication Date", "Match Type", "Match Score", "Facilities",
    ]].reset_index(drop=True)


def match_pubtracker_to_dimensions(
    pubtracker: pd.DataFrame,
    publications: pd.DataFrame,
    pub_facilities: dict[str, frozenset[str]],
    threshold: float = 90.0,
) -> pd.DataFrame:
    """Match every PubTracker row against the full prepared Dimensions set (not just eligible records)."""
    pub_ids = publications["Publication ID"].tolist()
    results = _best_matches(
        pubtracker["_norm_title"].tolist(),
        pubtracker["_facilities"].tolist(),
        publications["Title"].map(_normalize_title).tolist(),
        [pub_facilities.get(pub_id, frozenset()) for pub_id in pub_ids],
        threshold,
    )
    rows = []
    for i in range(len(pubtracker)):
        match_type, score, position = results.get(i, ("", 0.0, -1))
        rows.append({
            "Dimensions Publication ID": pub_ids[position] if position >= 0 else "",
            "Match Type": match_type,
            "Match Score": score,
        })
    matches = pd.DataFrame(rows, index=pubtracker.index)
    columns = ["Record ID", "Title", "Date Created", "Publication Date", "POC Medical Center"]
    return pd.concat([pubtracker[columns], matches], axis=1).reset_index(drop=True)


def classify_pubtracker_rows(reverse: pd.DataFrame, reasons_by_id: dict[str, str]) -> pd.DataFrame:
    """Label each PubTracker row Matched (eligible) / Matched but excluded / Exception."""
    frame = reverse.copy()
    matched = frame["Dimensions Publication ID"].ne("")
    frame["Exclusion Reason"] = frame["Dimensions Publication ID"].map(reasons_by_id).fillna("").where(matched, "")
    frame["Status"] = np.select(
        [~matched, frame["Exclusion Reason"].ne("")],
        ["Exception", "Matched but excluded"],
        default="Matched (eligible)",
    )
    return frame
