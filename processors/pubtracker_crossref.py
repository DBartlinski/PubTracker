"""Optional PubTracker corroboration check for Dimensions-based ORD funding tags.

PubTracker is a manually user-submitted system and only covers a subset of VA
publications, so it is never used to replace or lower the bar for the text-based
ORD funding evidence in `ord_portfolio.py` - only to corroborate it for the subset
of records that were also submitted to PubTracker. This module is intentionally
additive: callers can ignore it entirely (e.g. via a dashboard toggle left off) to
get the exact same ORD numbers as before this cross-reference existed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

PUBTRACKER_EXPORT_DIR = Path("PubTracker Export")


def _normalize_title(title) -> str:
    if not isinstance(title, str):
        return ""
    text = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    return re.sub(r"\s+", " ", text).strip()


def find_latest_export(directory: Path = PUBTRACKER_EXPORT_DIR) -> Path | None:
    """Return the most recently named PubTracker export .xlsx in `directory`, if any."""
    files = sorted(directory.glob("*.xlsx")) if directory.exists() else []
    return files[-1] if files else None


def load_pubtracker_submissions(path: Path | None = None) -> pd.DataFrame:
    """Load and normalize a PubTracker submission export for title-based cross-referencing.

    Returns an empty frame (safe no-op for callers) if no export file is found.
    """
    path = path or find_latest_export()
    columns = ["_norm_title", "PubTracker Reported Portfolio", "PubTracker VA Funded"]
    if path is None:
        return pd.DataFrame(columns=columns)

    raw = pd.read_excel(path, sheet_name=0)
    raw = raw[raw["Submittion Type"].astype(str).str.strip().str.lower() == "publication"].copy()
    raw["_norm_title"] = raw["Title"].map(_normalize_title)
    raw = raw[raw["_norm_title"] != ""]
    raw["PubTracker Reported Portfolio"] = raw["POC Primary Service"].fillna("").astype(str).str.strip()
    raw["PubTracker VA Funded"] = raw["VA Funded?"].astype(str).str.strip().str.lower().eq("yes")

    # One PubTracker row per normalized title is enough for a corroboration check.
    return raw[columns].drop_duplicates("_norm_title")


def crossref_ord_funding(publications: pd.DataFrame, pubtracker: pd.DataFrame) -> pd.DataFrame:
    """Return `publications` with PubTracker corroboration columns appended.

    Does not modify any existing column, including the Dimensions-based ORD tags.
    """
    result = publications.copy()
    result["_norm_title"] = result["Title"].map(_normalize_title)
    merged = result.merge(pubtracker, on="_norm_title", how="left")
    merged["PubTracker Match Found"] = merged["PubTracker Reported Portfolio"].notna()
    merged["PubTracker Reported Portfolio"] = merged["PubTracker Reported Portfolio"].fillna("")
    merged["PubTracker VA Funded"] = merged["PubTracker VA Funded"].fillna(False)
    return merged.drop(columns=["_norm_title"])
