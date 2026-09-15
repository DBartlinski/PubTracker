from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from processors.compliance_calculator import (
    get_search_terms,
    get_station_numbers,
    load_vamc_reference,
)
from processors.dimensions_processor import EXCLUDED_DOC_TYPES, read_dimensions_df
from processors.ord_portfolio import tag_publications
from processors.pubtracker_processor import get_fy_quarter, get_quarter_label


REQUIRED_COLUMNS = {
    "Publication ID",
    "Title",
    "Document Type",
    "Research Organizations - standardized",
}
DATE_COLUMNS = (
    ("Publication date (print)", "print"),
    ("Publication date (online)", "online"),
    ("Publication date", "general"),
)
NUMERIC_COLUMNS = ("Times cited", "Recent citations", "RCR", "FCR")
UMBRELLA_STATION_NUMBERS = {"101"}


@dataclass(frozen=True)
class DashboardDataset:
    publications: pd.DataFrame
    facility_matches: pd.DataFrame
    source_columns: tuple[str, ...]


def split_values(value) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _date_precision(value) -> str | None:
    if pd.isna(value) or not str(value).strip():
        return None
    value = str(value).strip().split("T", 1)[0].split(" ", 1)[0]
    if len(value) == 4 and value.isdigit():
        return "year"
    if len(value) == 7 and value[4] in "-/":
        return "month"
    return "day"


def derive_publication_date(row: pd.Series) -> tuple[pd.Timestamp | pd.NaT, str | None, str | None]:
    for column, source in DATE_COLUMNS:
        value = row.get(column)
        if pd.isna(value) or not str(value).strip():
            continue
        parsed = pd.to_datetime(value, errors="coerce")
        if not pd.isna(parsed):
            return parsed, source, _date_precision(value)
    return pd.NaT, None, None


def prepare_publications(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"Dimensions data is missing required columns: {', '.join(missing)}")
    if frame["Publication ID"].isna().any() or frame["Publication ID"].astype(str).str.strip().eq("").any():
        raise ValueError("Dimensions data contains a blank Publication ID.")
    if frame["Publication ID"].duplicated().any():
        raise ValueError("Dimensions data contains duplicate Publication IDs.")

    result = frame.copy()
    result["Publication ID"] = result["Publication ID"].astype(str).str.strip()
    for column in NUMERIC_COLUMNS:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")

    derived_dates = result.apply(derive_publication_date, axis=1, result_type="expand")
    derived_dates.columns = ["Canonical Date", "Date Source", "Date Precision"]
    result = pd.concat([result, derived_dates], axis=1)
    result["Calendar Year"] = pd.to_numeric(result.get("PubYear"), errors="coerce").astype("Int64")
    missing_year = result["Calendar Year"].isna() & result["Canonical Date"].notna()
    result.loc[missing_year, "Calendar Year"] = result.loc[missing_year, "Canonical Date"].dt.year

    fiscal_values = result.apply(_derive_fiscal_period, axis=1, result_type="expand")
    fiscal_values.columns = ["Fiscal Year", "Fiscal Quarter", "Fiscal Period"]
    result = pd.concat([result, fiscal_values], axis=1)
    result["Fiscal Year"] = result["Fiscal Year"].astype("Int64")
    result["Fiscal Quarter"] = result["Fiscal Quarter"].astype("Int64")

    document_types = result["Document Type"].fillna("").astype(str).str.strip().str.lower()
    result["SOP Eligible"] = ~document_types.isin(EXCLUDED_DOC_TYPES)
    result["Organization Count"] = result["Research Organizations - standardized"].map(split_values).map(len)
    result["Author Count"] = result.get("Authors", pd.Series(index=result.index, dtype=object)).map(split_values).map(len)
    open_access = result.get("Open Access", pd.Series(index=result.index, dtype=object)).fillna("").astype(str)
    result["Is Open Access"] = open_access.str.strip().ne("") & ~open_access.str.contains("closed", case=False)
    doi = result.get("DOI", pd.Series(index=result.index, dtype=object)).fillna("").astype(str).str.strip()
    pmid = result.get("PMID", pd.Series(index=result.index, dtype=object)).fillna("").astype(str).str.strip().str.removesuffix(".0")
    result["DOI Link"] = doi.map(lambda value: f"https://doi.org/{value}" if value else "")
    result["PubMed Link"] = pmid.map(lambda value: f"https://pubmed.ncbi.nlm.nih.gov/{value}/" if value else "")
    return result


def _derive_fiscal_period(row: pd.Series) -> tuple[int | None, int | None, str]:
    date = row["Canonical Date"]
    if pd.isna(date) or row["Date Precision"] == "year":
        return None, None, "Unavailable"
    fiscal_year, quarter = get_fy_quarter(date)
    return fiscal_year, quarter, get_quarter_label(fiscal_year, quarter)


def build_facility_matches(
    publications: pd.DataFrame,
    reference: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if reference is None:
        reference = load_vamc_reference()

    facilities = []
    for _, facility in reference.iterrows():
        if bool(facility.get("not_in_dimensions", False)):
            continue
        station_numbers = get_station_numbers(
            facility.get("station_no"), facility.get("alt_station_nos")
        )
        if station_numbers & UMBRELLA_STATION_NUMBERS:
            continue
        facilities.append({
            "facility": facility["vamc_display"],
            "station_numbers": "; ".join(sorted(station_numbers)),
            "terms": get_search_terms(facility["vamc_display"]),
        })

    matches = []
    for _, publication in publications.iterrows():
        organizations = split_values(publication["Research Organizations - standardized"])
        for facility in facilities:
            evidence = _best_facility_evidence(facility["terms"], organizations)
            if evidence is None:
                continue
            matches.append({
                "Publication ID": publication["Publication ID"],
                "Facility": facility["facility"],
                "Station Numbers": facility["station_numbers"],
                "Matched Organization": evidence["organization"],
                "Search Term": evidence["term"],
                "Match Direction": evidence["direction"],
                "Match Strength": evidence["strength"],
            })

    columns = [
        "Publication ID", "Facility", "Station Numbers", "Matched Organization",
        "Search Term", "Match Direction", "Match Strength",
    ]
    return pd.DataFrame(matches, columns=columns).drop_duplicates(
        subset=["Publication ID", "Facility"], keep="first"
    )


def _best_facility_evidence(terms: list[str], organizations: list[str]) -> dict | None:
    evidence = []
    for term in terms:
        term_lower = term.casefold()
        for organization in organizations:
            organization_lower = organization.casefold()
            if term_lower in organization_lower:
                evidence.append({
                    "organization": organization,
                    "term": term,
                    "direction": "facility term in organization",
                    "strength": "strong",
                    "score": (2, len(term)),
                })
            elif organization_lower in term_lower:
                evidence.append({
                    "organization": organization,
                    "term": term,
                    "direction": "organization in facility term",
                    "strength": "weak",
                    "score": (1, len(organization)),
                })
    if not evidence:
        return None
    best = max(evidence, key=lambda item: item["score"])
    best.pop("score")
    return best


def add_facility_summary(publications: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    result = publications.copy()
    if matches.empty:
        result["Matched Facilities"] = ""
        result["Facility Match Count"] = 0
        result["Facility Match Status"] = "Unmatched"
        return result

    grouped = matches.groupby("Publication ID").agg(
        **{
            "Matched Facilities": ("Facility", lambda values: "; ".join(sorted(set(values)))),
            "Facility Match Count": ("Facility", "nunique"),
        }
    )
    result = result.merge(grouped, left_on="Publication ID", right_index=True, how="left")
    result["Matched Facilities"] = result["Matched Facilities"].fillna("")
    result["Facility Match Count"] = result["Facility Match Count"].fillna(0).astype(int)
    result["Facility Match Status"] = result["Facility Match Count"].map(
        lambda count: "Unmatched" if count == 0 else "Single facility" if count == 1 else "Multiple facilities"
    )
    return result


def load_dashboard_dataset(
    csv_path: str | Path,
    reference: pd.DataFrame | None = None,
) -> DashboardDataset:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(path)
    source = read_dimensions_df(path.read_bytes())
    source_columns = tuple(source.columns)
    publications = prepare_publications(source)
    matches = build_facility_matches(publications, reference)
    publications = add_facility_summary(publications, matches)
    publications = tag_publications(publications)
    return DashboardDataset(publications, matches, source_columns)