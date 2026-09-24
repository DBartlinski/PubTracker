"""Combine multiple Dimensions batch-export merges (2016-2019, 2020-2024, FY24-25, ...)
into a single deduplicated dataset for the cross-batch analysis dashboard.

Reuses the enrichment pipeline from `processors/dashboard_data.py` (fiscal period
derivation, SOP eligibility, facility matching, ORD portfolio tagging) so the
combined dashboard stays consistent with the single-export dashboard, and adds:

- ``Source Batches``: which of the input batch exports contained this Publication ID
  (a publication can appear in more than one batch when year ranges overlap; it is
  de-duplicated to a single row but keeps a record of every batch it was seen in).
- ``Is Preprint``: True when Dimensions' own ``Publication Type`` is "Preprint".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from processors.dashboard_data import (
    DashboardDataset,
    add_facility_summary,
    build_facility_matches,
    prepare_publications,
)
from processors.dimensions_processor import read_dimensions_df
from processors.ord_portfolio import tag_publications

# Default set of batch exports to combine. Update paths here if new batches are added.
DEFAULT_SOURCE_BATCHES: tuple[tuple[str, str], ...] = (
    ("2016-2019", "output/dimensions_2016_2019_all/dimensions_merged.csv"),
    ("2020-2024", "output/dimensions_2020_2024_all/dimensions_merged.csv"),
    ("FY24-FY25", "output/dimensions_exports/dimensions_va_fy24_fy25/dimensions_va_fy24_fy25_merged.csv"),
)


@dataclass(frozen=True)
class CombinedDashboardDataset(DashboardDataset):
    batch_counts: dict[str, int] | None = None


def _read_batch(label: str, path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Batch '{label}' not found: {path}")
    frame = read_dimensions_df(path.read_bytes())
    frame["__source_batch"] = label
    return frame


def load_combined_publications(
    sources: tuple[tuple[str, str], ...] = DEFAULT_SOURCE_BATCHES,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Read, concatenate, and de-duplicate the batch exports by Publication ID.

    Returns the combined raw frame (one row per unique Publication ID, plus a
    'Source Batches' column) and a dict of raw row counts per input batch (before
    de-duplication) for reporting overlap.
    """
    frames = [_read_batch(label, path) for label, path in sources]
    raw_counts = {label: len(frame) for (label, _), frame in zip(sources, frames)}

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined["Publication ID"] = combined["Publication ID"].astype(str).str.strip()
    combined = combined[combined["Publication ID"].ne("")]

    source_map = (
        combined.groupby("Publication ID")["__source_batch"]
        .agg(lambda values: "; ".join(sorted(set(values))))
        .rename("Source Batches")
    )
    deduped = combined.drop_duplicates(subset="Publication ID", keep="first").drop(columns="__source_batch")
    deduped = deduped.merge(source_map, left_on="Publication ID", right_index=True, how="left")
    return deduped, raw_counts


def enrich_combined_publications(frame: pd.DataFrame) -> pd.DataFrame:
    result = prepare_publications(frame)
    result = tag_publications(result)
    publication_type = result.get("Publication Type", pd.Series(index=result.index, dtype=object))
    result["Is Preprint"] = publication_type.fillna("").astype(str).str.strip().str.casefold().eq("preprint")
    return result


def build_combined_dataset(
    sources: tuple[tuple[str, str], ...] = DEFAULT_SOURCE_BATCHES,
    reference: pd.DataFrame | None = None,
) -> CombinedDashboardDataset:
    raw, raw_counts = load_combined_publications(sources)
    source_columns = tuple(col for col in raw.columns if col != "Source Batches")
    publications = enrich_combined_publications(raw)
    matches = build_facility_matches(publications, reference)
    publications = add_facility_summary(publications, matches)
    return CombinedDashboardDataset(publications, matches, source_columns, raw_counts)
