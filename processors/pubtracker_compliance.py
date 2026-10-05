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
    publication_date = pd.to_datetime(raw["Publication Date"], errors="coerce", format="mixed")
    raw["PubTracker Date"] = publication_date.fillna(raw["Date Created"])
    raw["PubTracker Date Source"] = np.where(publication_date.notna(), "Publication Date", "Date Created")
    return raw[PUBTRACKER_COLUMNS + ["PubTracker Date", "PubTracker Date Source", "_norm_title", "_facilities"]]


def filter_pubtracker_period(pubtracker: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Keep PubTracker rows whose PubTracker Date falls within [start, end] (inclusive of the end day)."""
    dates = pubtracker["PubTracker Date"]
    return pubtracker[dates.between(start, end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].reset_index(drop=True)


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


def filter_fiscal_year(
    publications: pd.DataFrame,
    start: pd.Timestamp = FY26_START,
    end: pd.Timestamp = FY26_END,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Keep SOP-eligible records dated within [start, end]; year-only dates cannot be placed."""
    eligible = publications["SOP Eligible"].astype(bool)
    dated = publications["Canonical Date"].notna() & publications["Date Precision"].ne("year")
    in_range = publications["Canonical Date"].between(start, end)
    stats = {
        "source_records": len(publications),
        "excluded_document_type": int((~eligible).sum()),
        "excluded_undated_or_year_only": int((eligible & ~dated).sum()),
        "excluded_out_of_range": int((eligible & dated & ~in_range).sum()),
    }
    scoped = publications[eligible & dated & in_range].copy()
    stats["in_scope"] = len(scoped)
    return scoped, stats


def facility_map(matches: pd.DataFrame) -> dict[str, frozenset[str]]:
    return {
        pub_id: frozenset(group)
        for pub_id, group in matches.groupby("Publication ID")["Facility"]
    }


def match_to_pubtracker(
    publications: pd.DataFrame,
    pub_facilities: dict[str, frozenset[str]],
    pubtracker: pd.DataFrame,
    threshold: float = 90.0,
) -> pd.DataFrame:
    """Tag each Dimensions record Matched (exact) / Matched (fuzzy) / Missing."""
    pt_titles = pubtracker["_norm_title"].tolist()
    exact_index: dict[str, int] = {}
    for position, title in enumerate(pt_titles):
        exact_index.setdefault(title, position)

    pub_ids = publications["Publication ID"].tolist()
    pub_titles = publications["Title"].map(_normalize_title).tolist()
    results: dict[int, tuple[str, float, int]] = {}

    pending = []
    for i, title in enumerate(pub_titles):
        if not title:
            continue
        if title in exact_index:
            results[i] = ("Matched (exact)", 100.0, exact_index[title])
        else:
            pending.append(i)

    if pending and pt_titles:
        scores = process.cdist(
            [pub_titles[i] for i in pending],
            pt_titles,
            scorer=fuzz.ratio,
            dtype=np.uint8,
            score_cutoff=int(round(threshold)),
            workers=-1,
        )
        pt_facilities = pubtracker["_facilities"].tolist()
        for row, i in enumerate(pending):
            candidates = np.flatnonzero(scores[row] >= int(round(threshold)))
            if candidates.size == 0:
                continue
            own = pub_facilities.get(pub_ids[i], frozenset())
            for position in candidates[np.argsort(-scores[row][candidates], kind="stable")]:
                theirs = pt_facilities[position]
                if not own or not theirs or own & theirs:
                    results[i] = ("Matched (fuzzy)", float(scores[row][position]), int(position))
                    break

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
