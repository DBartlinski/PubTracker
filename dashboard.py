from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

from processors.dashboard_data import DashboardDataset, load_dashboard_dataset, split_values
from processors.pubtracker_compliance import (
    UNATTRIBUTED,
    build_station_lookup,
    classify_pubtracker_rows,
    exclusion_reasons,
    facility_map,
    facility_rates,
    filter_fiscal_year,
    load_pubtracker_files,
    match_pubtracker_to_dimensions,
    match_to_pubtracker,
    matched_records_table,
    not_in_pubtracker_by_facility,
    quarter_options,
    quarter_rates,
    records_by_facility,
)


DATA_PATH = Path("output/dimensions_va_2025_2026/dimensions_va_2025_2026_filtered_2025-10-01_to_2026-09-30.csv")
PUBTRACKER_PATHS = [
    Path("PubTracker Export/submissionlist20261005132200-2025.xlsx"),
    Path("PubTracker Export/submissionlist20261005132200-2026.xlsx"),
]
COMPLIANCE_TAB_TITLE = "Dimensions-PubTracker Complience Oct 2026"
DIM_TO_PT_TAB_TITLE = "Dimensions to PubTracker (Build 01)"
BUILD_02_TAB_TITLE = "Not in PubTracker (Build 02)"
NOT_IN_PUBTRACKER = "Not in PubTracker"
ORD_NO_SIGNAL_LABEL = "No ORD signal detected"
DERIVED_EXPORT_COLUMNS = [
    "Canonical Date", "Date Source", "Date Precision", "Calendar Year",
    "Fiscal Year", "Fiscal Quarter", "Fiscal Period", "SOP Eligible",
    "Is Open Access", "Organization Count", "Author Count",
    "Matched Facilities", "Facility Match Count", "Facility Match Status",
    "ORD Broad Portfolio Codes", "ORD Broad Portfolios",
    "ORD Actively Managed Portfolios", "Has ORD Funding Evidence",
]


st.set_page_config(page_title="VA Publications Dashboard", page_icon="📚", layout="wide")
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap');
    html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
    h1, h2, h3 { font-family: 'IBM Plex Serif', serif; letter-spacing: 0; }
    /* Follows Streamlit's resolved theme (auto/light/dark) via its CSS variables, so this
       adapts to the visitor's browser/OS color-scheme preference automatically. */
    [data-testid="stAppViewContainer"] { background: var(--background-color); }
    [data-testid="stSidebar"] {
        background: var(--secondary-background-color);
        border-right: 1px solid rgba(128, 128, 128, 0.3);
    }
    [data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.3); border-top: 3px solid #2f9c7c;
        padding: 12px 14px; border-radius: 4px;
    }
    .dashboard-kicker { color: #2f9c7c; font-size: .78rem; font-weight: 600; text-transform: uppercase; }
    .dashboard-note { color: var(--text-color); opacity: .75; font-size: .92rem; margin-bottom: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner="Preparing publication and facility records...")
def cached_dataset(path: str, modified_time: float) -> DashboardDataset:
    del modified_time
    return load_dashboard_dataset(path)


def reset_filters() -> None:
    for key in list(st.session_state):
        if key.startswith("dash_filter_"):
            del st.session_state[key]


def tokens(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame:
        return []
    values = {token for value in frame[column] for token in split_values(value)}
    return sorted(values, key=str.casefold)


def apply_filters(publications: pd.DataFrame, matches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = pd.Series(True, index=publications.index)
    if not st.session_state.dash_filter_include_all:
        mask &= publications["SOP Eligible"]

    selections = {
        "Fiscal Year": st.session_state.dash_filter_fiscal_year,
        "Fiscal Quarter": st.session_state.dash_filter_fiscal_quarter,
        "Calendar Year": st.session_state.dash_filter_calendar_year,
        "Facility Match Status": st.session_state.dash_filter_match_status,
        "Document Type": st.session_state.dash_filter_document_type,
        "Open Access": st.session_state.dash_filter_open_access,
        "Source title": st.session_state.dash_filter_journal,
    }
    for column, selected in selections.items():
        if selected:
            mask &= publications[column].isin(selected)

    selected_facilities = st.session_state.dash_filter_facility
    if selected_facilities:
        facility_ids = matches.loc[matches["Facility"].isin(selected_facilities), "Publication ID"]
        mask &= publications["Publication ID"].isin(facility_ids)

    for column, selected in (
        ("Broad Research Areas", st.session_state.dash_filter_research_area),
        ("Country of standardized research organization", st.session_state.dash_filter_country),
        ("ORD Broad Portfolios", st.session_state.dash_filter_ord_broad),
        ("ORD Actively Managed Portfolios", st.session_state.dash_filter_ord_amp),
    ):
        if selected:
            selected_set = set(selected)
            mask &= publications[column].map(lambda value: bool(selected_set & set(split_values(value))))

    query = st.session_state.dash_filter_search.strip()
    if query:
        search_columns = ["Title", "Authors", "DOI", "PMID", "Publication ID"]
        searchable = publications[search_columns].fillna("").astype(str).agg(" ".join, axis=1)
        mask &= searchable.str.contains(query, case=False, regex=False)

    filtered = publications.loc[mask].copy()
    filtered_matches = matches[matches["Publication ID"].isin(filtered["Publication ID"])].copy()
    if selected_facilities:
        filtered_matches = filtered_matches[filtered_matches["Facility"].isin(selected_facilities)]
    return filtered, filtered_matches


def render_filters(dataset: DashboardDataset) -> tuple[pd.DataFrame, pd.DataFrame]:
    publications, matches = dataset.publications, dataset.facility_matches
    with st.sidebar:
        st.header("Filters")
        if st.button("Reset filters", use_container_width=True):
            reset_filters()
            st.rerun()
        st.checkbox("Include SOP-excluded records", value=False, key="dash_filter_include_all")
        st.multiselect(
            "VA fiscal year",
            sorted(publications["Fiscal Year"].dropna().astype(int).unique(), reverse=True),
            key="dash_filter_fiscal_year",
        )
        st.multiselect("Fiscal quarter", [1, 2, 3, 4], key="dash_filter_fiscal_quarter")
        st.multiselect(
            "Calendar publication year",
            sorted(publications["Calendar Year"].dropna().astype(int).unique(), reverse=True),
            key="dash_filter_calendar_year",
        )
        st.multiselect(
            "Facility",
            sorted(matches["Facility"].unique(), key=str.casefold),
            key="dash_filter_facility",
        )
        st.multiselect(
            "Facility match status",
            ["Single facility", "Multiple facilities", "Unmatched"],
            key="dash_filter_match_status",
        )
        with st.expander("Advanced filters"):
            st.multiselect(
                "Document type",
                sorted(publications["Document Type"].dropna().unique(), key=str.casefold),
                key="dash_filter_document_type",
            )
            st.multiselect(
                "Open access status",
                sorted(publications["Open Access"].dropna().unique(), key=str.casefold),
                key="dash_filter_open_access",
            )
            st.multiselect(
                "Journal / source",
                sorted(publications["Source title"].dropna().unique(), key=str.casefold),
                key="dash_filter_journal",
            )
            st.multiselect(
                "Broad research area",
                tokens(publications, "Broad Research Areas"),
                key="dash_filter_research_area",
            )
            st.multiselect(
                "Organization country",
                tokens(publications, "Country of standardized research organization"),
                key="dash_filter_country",
            )
            st.multiselect(
                "ORD Broad Portfolio",
                tokens(publications, "ORD Broad Portfolios"),
                key="dash_filter_ord_broad",
            )
            st.multiselect(
                "ORD Actively Managed Portfolio",
                tokens(publications, "ORD Actively Managed Portfolios"),
                key="dash_filter_ord_amp",
            )
        st.text_input(
            "Search title, author, DOI, PMID, or ID",
            key="dash_filter_search",
            placeholder="Search records",
        )
        st.divider()
        st.caption("Fiscal periods use print date, then online date, then general publication date. Year-only dates remain unassigned.")
    return apply_filters(publications, matches)


def bar_chart(frame: pd.DataFrame, category: str, value: str, color: str = "#236b56") -> None:
    if frame.empty:
        st.info("No data is available for this chart under the current filters.")
        return
    st.bar_chart(frame.set_index(category)[value], color=color)


def render_overview(publications: pd.DataFrame, matches: pd.DataFrame) -> None:
    matched = publications["Facility Match Count"].gt(0).sum()
    open_access_rate = publications["Is Open Access"].mean() * 100 if len(publications) else 0
    metric_columns = st.columns(4)
    metric_columns[0].metric("Publications", f"{len(publications):,}")
    metric_columns[1].metric("Mapped to a VAMC", f"{matched:,}")
    metric_columns[2].metric("Unmatched", f"{len(publications) - matched:,}")
    metric_columns[3].metric("Open access", f"{open_access_rate:.0f}%")

    left, right = st.columns([1.6, 1])
    with left:
        st.subheader("VA fiscal-year trend")
        trend = (
            publications.dropna(subset=["Fiscal Year"])
            .groupby("Fiscal Year")["Publication ID"].nunique().reset_index(name="Publications")
        )
        trend["Fiscal Year"] = trend["Fiscal Year"].astype(int).map(lambda value: f"FY {value}")
        bar_chart(trend, "Fiscal Year", "Publications")
    with right:
        st.subheader("Document types")
        types = publications["Document Type"].fillna("Unknown").value_counts().head(10).rename_axis("Type").reset_index(name="Publications")
        bar_chart(types, "Type", "Publications", "#b4553d")

    left, right = st.columns(2)
    with left:
        st.subheader("Top facilities")
        facility_counts = (
            matches.groupby("Facility")["Publication ID"].nunique()
            .sort_values(ascending=False).head(12).rename("Publications").reset_index()
        )
        bar_chart(facility_counts, "Facility", "Publications", "#ca8a2c")
    with right:
        st.subheader("Fiscal-period coverage")
        coverage = publications["Fiscal Period"].eq("Unavailable").value_counts()
        coverage_frame = pd.DataFrame({
            "Status": ["Assigned", "Unavailable"],
            "Publications": [int(coverage.get(False, 0)), int(coverage.get(True, 0))],
        })
        bar_chart(coverage_frame, "Status", "Publications", "#5f6b85")


def render_records(publications: pd.DataFrame, source_columns: tuple[str, ...]) -> None:
    st.subheader("Publication records")
    columns = [
        "Title", "Publication ID", "Canonical Date", "Fiscal Period", "Document Type",
        "Matched Facilities", "Source title", "Open Access", "Times cited", "DOI Link",
        "PubMed Link", "Dimensions for Veterans Affairs URL",
    ]
    records = publications[[column for column in columns if column in publications]].copy()
    records["Canonical Date"] = records["Canonical Date"].dt.strftime("%Y-%m-%d").fillna("")
    st.dataframe(
        records,
        use_container_width=True,
        hide_index=True,
        height=620,
        column_config={
            "DOI Link": st.column_config.LinkColumn("DOI"),
            "PubMed Link": st.column_config.LinkColumn("PubMed"),
            "Dimensions for Veterans Affairs URL": st.column_config.LinkColumn("Dimensions"),
            "Times cited": st.column_config.NumberColumn("Citations", format="%d"),
        },
    )
    export_columns = list(source_columns) + [column for column in DERIVED_EXPORT_COLUMNS if column in publications]
    export = publications[export_columns].copy()
    st.download_button(
        "Download filtered records",
        export.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"dimensions_filtered_{len(export)}.csv",
        mime="text/csv",
    )


def render_facilities(publications: pd.DataFrame, matches: pd.DataFrame) -> None:
    st.subheader("Facility attribution")
    st.caption("Matches are name-based evidence for review, not authoritative assignments. Station 101 umbrella terms are excluded.")
    if matches.empty:
        st.info("No facility matches are available under the current filters.")
        return
    summary = matches.groupby(["Facility", "Station Numbers"]).agg(
        Publications=("Publication ID", "nunique"),
        Strong=("Match Strength", lambda values: (values == "strong").sum()),
        Weak=("Match Strength", lambda values: (values == "weak").sum()),
    ).reset_index().sort_values("Publications", ascending=False)
    st.dataframe(summary, use_container_width=True, hide_index=True, height=360)

    selected = st.selectbox("Facility drilldown", summary["Facility"].tolist())
    evidence = matches[matches["Facility"] == selected].merge(
        publications[["Publication ID", "Title", "Fiscal Period", "Document Type"]],
        on="Publication ID",
        how="left",
    )
    evidence = evidence[[
        "Title", "Publication ID", "Fiscal Period", "Document Type", "Matched Organization",
        "Search Term", "Match Direction", "Match Strength", "Station Numbers",
    ]]
    st.dataframe(evidence, use_container_width=True, hide_index=True, height=440)


def explode_tokens(publications: pd.DataFrame, id_column: str, value_column: str, label: str) -> pd.DataFrame:
    rows = []
    for pub_id, value in publications[[id_column, value_column]].itertuples(index=False):
        pub_tokens = split_values(value)
        if not pub_tokens:
            rows.append({id_column: pub_id, label: ORD_NO_SIGNAL_LABEL})
        else:
            rows.extend({id_column: pub_id, label: token} for token in pub_tokens)
    return pd.DataFrame(rows, columns=[id_column, label])


def render_pubtracker_crossref(publications: pd.DataFrame) -> None:
    use_pubtracker = st.checkbox(
        "Cross-reference against PubTracker submissions (experimental, off by default)",
        value=False,
        key="dash_use_pubtracker_crossref",
        help=(
            "Adds a corroboration check for the subset of publications also manually submitted to PubTracker. "
            "PubTracker only covers user-submitted records and is not comprehensive, so turning this on never "
            "changes the ORD numbers above - it only adds an extra section below. Leave it off to keep the "
            "Dimensions-only view (the default, unaffected by this feature)."
        ),
    )
    if not use_pubtracker:
        return

    from processors.pubtracker_crossref import crossref_ord_funding, load_pubtracker_submissions

    pubtracker_df = load_pubtracker_submissions()
    if pubtracker_df.empty:
        st.info("No PubTracker export file found in 'PubTracker Export/'. Add one there to enable this cross-reference.")
        return

    crossref = crossref_ord_funding(publications, pubtracker_df)
    matched = crossref[crossref["PubTracker Match Found"]]
    st.subheader("PubTracker corroboration (experimental)")
    st.caption(
        f"{len(matched):,} of {len(publications):,} filtered publications were also found in the PubTracker "
        "submission export (matched by normalized title). This is a partial, user-submitted dataset - absence "
        "from PubTracker does NOT mean a publication isn't ORD-funded, it may simply not have been submitted. "
        "Use this only to spot-check agreement, not as a replacement for the Broad Portfolio funding-evidence "
        "numbers above."
    )
    if matched.empty:
        st.info("No filtered publications matched a PubTracker submission by title.")
        return

    agree = matched["Has ORD Funding Evidence"] & matched["PubTracker VA Funded"]
    disagree = matched["Has ORD Funding Evidence"] != matched["PubTracker VA Funded"]
    cols = st.columns(3)
    cols[0].metric("Matched to PubTracker", f"{len(matched):,}")
    cols[1].metric("Funding evidence agrees", f"{int(agree.sum()):,}")
    cols[2].metric("Funding evidence disagrees", f"{int(disagree.sum()):,}")
    if disagree.any():
        st.dataframe(
            matched.loc[disagree, [
                "Publication ID", "Title", "Has ORD Funding Evidence", "ORD Broad Portfolios",
                "PubTracker Reported Portfolio", "PubTracker VA Funded",
            ]],
            use_container_width=True, hide_index=True, height=300,
        )


def render_ord_portfolios(publications: pd.DataFrame, matches: pd.DataFrame) -> None:
    st.subheader("ORD portfolio attribution")
    st.caption(
        "Dimensions has no dedicated ORD field, so Broad Portfolio tags are inferred from VA grant award "
        "prefixes and service names in the funding/acknowledgement text. Actively Managed Portfolio tags are "
        "inferred from topic keywords in the title/abstract/MeSH terms, but a topic match alone is not funding "
        "evidence, so an Actively Managed tag is only counted here once the record also carries ORD funding "
        "evidence (a Broad Portfolio grant/service, or the portfolio's own name in the funding text). "
        "Topic-only matches with no funding evidence are excluded from these totals. Treat all figures as "
        "estimates, not an authoritative VA source of truth; PubTracker's own service field is not used as a "
        "cross-check because it only covers user-submitted records and is not comprehensive."
    )

    total = len(publications)
    with_broad = publications["Has ORD Funding Evidence"].sum() if total else 0
    with_amp = publications["ORD Actively Managed Portfolios"].str.strip().ne("").sum() if total else 0
    with_neither = int(((~publications["Has ORD Funding Evidence"]) & publications["ORD Actively Managed Portfolios"].str.strip().eq("")).sum()) if total else 0
    with_any_ord = total - with_neither

    metric_columns = st.columns(5)
    metric_columns[0].metric("Publications", f"{total:,}")
    metric_columns[1].metric("Total ORD-funded (unique)", f"{with_any_ord:,}", f"{100 * with_any_ord / total:.0f}%" if total else "0%")
    metric_columns[2].metric("With Broad Portfolio evidence", f"{with_broad:,}", f"{100 * with_broad / total:.0f}%" if total else "0%")
    metric_columns[3].metric("With Actively Managed tag", f"{with_amp:,}", f"{100 * with_amp / total:.0f}%" if total else "0%")
    metric_columns[4].metric(ORD_NO_SIGNAL_LABEL, f"{with_neither:,}", f"{100 * with_neither / total:.0f}%" if total else "0%")

    render_pubtracker_crossref(publications)

    broad_long = explode_tokens(publications, "Publication ID", "ORD Broad Portfolios", "Broad Portfolio")
    amp_long = explode_tokens(publications, "Publication ID", "ORD Actively Managed Portfolios", "Actively Managed Portfolio")

    left, right = st.columns(2)
    with left:
        st.subheader("Broad Portfolio (VA funding service)")
        counts = broad_long["Broad Portfolio"].value_counts().rename_axis("Broad Portfolio").reset_index(name="Publications")
        bar_chart(counts, "Broad Portfolio", "Publications")
    with right:
        st.subheader("Actively Managed Portfolio (topic)")
        counts = amp_long["Actively Managed Portfolio"].value_counts().rename_axis("Actively Managed Portfolio").reset_index(name="Publications")
        bar_chart(counts, "Actively Managed Portfolio", "Publications", "#b4553d")

    st.subheader("Broad Portfolio by fiscal quarter")
    fiscal_long = broad_long.merge(publications[["Publication ID", "Fiscal Period"]], on="Publication ID", how="left")
    pivot = (
        fiscal_long[fiscal_long["Broad Portfolio"] != ORD_NO_SIGNAL_LABEL]
        .groupby(["Fiscal Period", "Broad Portfolio"])["Publication ID"].nunique()
        .unstack(fill_value=0)
    )
    if pivot.empty:
        st.info("No Broad Portfolio evidence is available for this selection.")
    else:
        st.bar_chart(pivot)

    st.subheader("Broad Portfolio by facility")
    if matches.empty:
        st.info("No facility matches are available under the current filters.")
    else:
        facility_long = broad_long[broad_long["Broad Portfolio"] != ORD_NO_SIGNAL_LABEL].merge(
            matches[["Publication ID", "Facility"]], on="Publication ID", how="inner"
        )
        facility_summary = (
            facility_long.groupby(["Facility", "Broad Portfolio"])["Publication ID"].nunique()
            .reset_index(name="Publications")
            .sort_values("Publications", ascending=False)
        )
        st.dataframe(facility_summary, use_container_width=True, hide_index=True, height=360)


def render_impact(publications: pd.DataFrame) -> None:
    st.subheader("Research impact")
    st.caption("Citation, RCR, and FCR values vary with publication age and research field; use them for context, not rankings alone.")
    metrics = st.columns(4)
    metrics[0].metric("Median citations", f"{publications['Times cited'].median():.0f}" if len(publications) else "0")
    metrics[1].metric("Mean RCR", f"{publications['RCR'].mean():.2f}" if publications["RCR"].notna().any() else "N/A")
    metrics[2].metric("Mean FCR", f"{publications['FCR'].mean():.2f}" if publications["FCR"].notna().any() else "N/A")
    metrics[3].metric("Unique journals", f"{publications['Source title'].nunique():,}")

    left, right = st.columns(2)
    with left:
        st.subheader("Top journals")
        journals = publications["Source title"].fillna("Unknown").value_counts().head(15).rename_axis("Journal").reset_index(name="Publications")
        bar_chart(journals, "Journal", "Publications")
    with right:
        st.subheader("Broad research areas")
        areas = pd.Series(
            [area for value in publications["Broad Research Areas"] for area in split_values(value)],
            dtype="object",
        ).value_counts().head(15).rename_axis("Research area").reset_index(name="Publications")
        bar_chart(areas, "Research area", "Publications", "#b4553d")

    st.subheader("Citation distribution")
    cited = publications["Times cited"].dropna().clip(upper=100)
    if cited.empty:
        st.info("Citation metrics are unavailable for the current records.")
    else:
        bins = pd.cut(cited, bins=[-1, 0, 2, 5, 10, 25, 50, 100], labels=["0", "1–2", "3–5", "6–10", "11–25", "26–50", "51–100+"])
        distribution = bins.value_counts(sort=False).rename_axis("Citations").reset_index(name="Publications")
        bar_chart(distribution, "Citations", "Publications", "#5f6b85")


st.markdown('<div class="dashboard-kicker">VA research publications</div>', unsafe_allow_html=True)
st.title("Dimensions Records Dashboard")
st.markdown(
    '<div class="dashboard-note">Explore publication records, fiscal timing, facility attribution, and research impact before PubTracker reconciliation.</div>',
    unsafe_allow_html=True,
)

@st.cache_data(show_spinner="Loading PubTracker submissions...")
def cached_pubtracker(paths: tuple[str, ...], modified_times: tuple[float, ...]) -> pd.DataFrame:
    del modified_times
    return load_pubtracker_files(list(paths), build_station_lookup())


@st.cache_data(show_spinner="Matching Dimensions records to PubTracker...")
def cached_match(threshold: float, cache_key: str, _scoped, _pub_facilities, _pubtracker) -> pd.DataFrame:
    del cache_key
    return match_to_pubtracker(_scoped, _pub_facilities, _pubtracker, threshold)


def render_pubtracker_compliance(dataset: DashboardDataset) -> None:
    st.subheader(COMPLIANCE_TAB_TITLE)
    st.caption(
        "Dimensions is treated as the true source; PubTracker is the user-submitted supplement being audited. "
        "Records are matched by title only (exact, then fuzzy), so treat results as evidence for review."
    )
    missing_files = [path for path in PUBTRACKER_PATHS if not path.exists()]
    if missing_files:
        st.error(f"PubTracker export not found: {', '.join(str(path) for path in missing_files)}")
        return

    pt_mtimes = tuple(path.stat().st_mtime for path in PUBTRACKER_PATHS)
    pubtracker = cached_pubtracker(tuple(str(path) for path in PUBTRACKER_PATHS), pt_mtimes)
    scoped, stats = filter_fiscal_year(dataset.publications)

    options = quarter_options(scoped)
    period = st.radio("Period", list(options), horizontal=True, key="compliance_period")
    start, end = options[period]
    scoped = scoped[scoped["Canonical Date"].between(start, end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()

    threshold = st.slider(
        "Fuzzy title match threshold (%)", min_value=70, max_value=100, value=90, step=1,
        key="compliance_threshold",
        help="Titles not matched exactly are accepted when similarity is at least this value and the facilities agree.",
    )
    if scoped.empty:
        st.info("No Dimensions records fall in the selected period.")
        return

    pub_facilities = facility_map(dataset.facility_matches)
    cache_key = f"{DATA_PATH.stat().st_mtime}|{pt_mtimes}|{period}"
    results = cached_match(float(threshold), cache_key, scoped, pub_facilities, pubtracker)

    found = results["Match Type"].ne("Missing")
    metric_columns = st.columns(5)
    metric_columns[0].metric(f"Dimensions records ({period})", f"{len(results):,}")
    metric_columns[1].metric("Found in PubTracker", f"{int(found.sum()):,}")
    metric_columns[2].metric("  exact / fuzzy", f"{int(results['Match Type'].eq('Matched (exact)').sum()):,} / {int(results['Match Type'].eq('Matched (fuzzy)').sum()):,}")
    metric_columns[3].metric("Missing from PubTracker", f"{int((~found).sum()):,}")
    metric_columns[4].metric("Overall submission rate", f"{found.mean() * 100:.1f}%")
    st.caption(
        f"{stats['source_records']:,} source records: excluded {stats['excluded_document_type']:,} conference abstracts/corrections, "
        f"{stats['excluded_publication_type']:,} preprints, chapters, proceedings or books, "
        f"{stats['excluded_undated_or_year_only']:,} with no exact date, {stats['excluded_out_of_range']:,} outside Oct 1, 2025 - Sep 30, 2026. "
        f"All {len(pubtracker):,} PubTracker publication submissions are compared with the Dimensions records dated "
        f"{start:%Y-%m-%d} to {end:%Y-%m-%d}; the Dimensions publication date decides the period, so PubTracker's own "
        "date is not used. A record with several facilities counts toward each."
    )

    rates = facility_rates(results, pub_facilities)
    st.subheader("Submission rate by facility")
    st.dataframe(
        rates, use_container_width=True, hide_index=True, height=420,
        column_config={"Submission Rate %": st.column_config.ProgressColumn("Submission Rate %", min_value=0, max_value=100, format="%.1f%%")},
    )
    st.download_button(
        "Download facility rates", rates.to_csv(index=False).encode("utf-8-sig"),
        file_name="dimensions_pubtracker_facility_rates.csv", mime="text/csv",
    )
    st.subheader("Most missing records")
    bar_chart(rates.head(20), "Facility", "Missing", "#b4553d")

    st.subheader("Missing records by facility")
    selected = st.selectbox("Facility", rates["Facility"].tolist(), key="compliance_facility")
    missing_ids = set(results.loc[~found, "Publication ID"])
    in_facility = scoped["Publication ID"].map(
        lambda pub_id: selected in pub_facilities[pub_id] if pub_facilities.get(pub_id) else selected == UNATTRIBUTED
    )
    columns = ["Title", "Canonical Date", "Document Type", "Source title", "Matched Facilities", "DOI Link", "PubMed Link", "Publication ID"]
    missing = scoped[in_facility & scoped["Publication ID"].isin(missing_ids)][[c for c in columns if c in scoped]].copy()
    missing["Canonical Date"] = missing["Canonical Date"].dt.strftime("%Y-%m-%d")
    st.caption(f"{len(missing):,} Dimensions records for this facility were not found in PubTracker.")
    st.dataframe(
        missing, use_container_width=True, hide_index=True, height=420,
        column_config={"DOI Link": st.column_config.LinkColumn("DOI"), "PubMed Link": st.column_config.LinkColumn("PubMed")},
    )

    all_missing = scoped[scoped["Publication ID"].isin(missing_ids)][[c for c in columns if c in scoped]].copy()
    all_missing["Canonical Date"] = all_missing["Canonical Date"].dt.strftime("%Y-%m-%d")
    st.download_button(
        "Download all missing records", all_missing.to_csv(index=False).encode("utf-8-sig"),
        file_name="dimensions_missing_from_pubtracker.csv", mime="text/csv",
    )
    fuzzy = results[results["Match Type"].eq("Matched (fuzzy)")].merge(
        scoped[["Publication ID", "Title"]], on="Publication ID"
    )[["Title", "PubTracker Title", "Match Score", "PubTracker Facility", "PubTracker Record ID", "Publication ID"]]
    with st.expander(f"Review fuzzy matches ({len(fuzzy):,})"):
        st.dataframe(fuzzy.sort_values("Match Score"), use_container_width=True, hide_index=True, height=360)


@st.cache_data(show_spinner="Checking every PubTracker record against Dimensions...")
def cached_reverse_match(threshold: float, cache_key: str, _pubtracker, _publications, _pub_facilities) -> pd.DataFrame:
    del cache_key
    return match_pubtracker_to_dimensions(_pubtracker, _publications, _pub_facilities, threshold)


def _format_dates(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = frame.copy()
    for column in columns:
        frame[column] = pd.to_datetime(frame[column]).dt.strftime("%Y-%m-%d").fillna("")
    return frame


def _csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def render_dimensions_to_pubtracker(dataset: DashboardDataset) -> None:
    st.subheader(DIM_TO_PT_TAB_TITLE)
    st.caption(
        "Starts from every eligible Dimensions record (the authoritative source) and checks whether it also "
        "appears in PubTracker. For matched records the Dimensions date is the published date and decides the "
        "fiscal period; PubTracker's dates are shown only for audit. Matching is by title only (PubTracker has "
        "no DOI or PMID). Sidebar filters do not apply to this tab."
    )
    missing_files = [path for path in PUBTRACKER_PATHS if not path.exists()]
    if missing_files:
        st.error(f"PubTracker export not found: {', '.join(str(path) for path in missing_files)}")
        return

    publications = dataset.publications
    pt_mtimes = tuple(path.stat().st_mtime for path in PUBTRACKER_PATHS)
    pubtracker = cached_pubtracker(tuple(str(path) for path in PUBTRACKER_PATHS), pt_mtimes)
    pub_facilities = facility_map(dataset.facility_matches)

    options = quarter_options(publications)
    period = st.radio("Period", list(options), horizontal=True, key="d2p_period")
    start, end = options[period]
    end = end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    threshold = st.slider(
        "Fuzzy title match threshold (%)", min_value=70, max_value=100, value=90, step=1, key="d2p_threshold",
        help="Titles not matched exactly are accepted when similarity is at least this value and the facilities agree.",
    )

    scoped, stats = filter_fiscal_year(publications, start, end)
    reasons = exclusion_reasons(publications, start, end)
    reasons_by_id = dict(zip(publications["Publication ID"], reasons))

    data_key = f"{DATA_PATH.stat().st_mtime}|{pt_mtimes}"
    results = cached_match(float(threshold), f"{data_key}|d2p|{period}", scoped, pub_facilities, pubtracker)
    reverse = cached_reverse_match(float(threshold), data_key, pubtracker, publications, pub_facilities)
    pt_rows = classify_pubtracker_rows(reverse, reasons_by_id)

    found = results["Match Type"].ne("Missing")
    exact = int(results["Match Type"].eq("Matched (exact)").sum())
    fuzzy_count = int(results["Match Type"].eq("Matched (fuzzy)").sum())
    exceptions = pt_rows[pt_rows["Status"].eq("Exception")]
    excluded = pt_rows[pt_rows["Status"].eq("Matched but excluded")]

    row1 = st.columns(4)
    row1[0].metric(f"Eligible Dimensions ({period})", f"{len(results):,}")
    row1[1].metric("Found in PubTracker", f"{int(found.sum()):,}", f"{exact:,} exact / {fuzzy_count:,} fuzzy", delta_color="off")
    row1[2].metric(NOT_IN_PUBTRACKER, f"{int((~found).sum()):,}")
    row1[3].metric("Overall submission rate", f"{found.mean() * 100:.1f}%" if len(results) else "N/A")
    row2 = st.columns(4)
    row2[0].metric("PubTracker publication rows", f"{len(pt_rows):,}")
    row2[1].metric("Matched to eligible Dimensions", f"{int(pt_rows['Status'].eq('Matched (eligible)').sum()):,}")
    row2[2].metric("Matched but excluded", f"{len(excluded):,}")
    row2[3].metric("PubTracker exceptions", f"{len(exceptions):,}")
    st.caption(
        f"{stats['source_records']:,} source records: excluded {stats['excluded_document_type']:,} conference abstracts/corrections, "
        f"{stats['excluded_publication_type']:,} preprints, chapters, proceedings, books, monographs or seminars, "
        f"{stats['excluded_undated_or_year_only']:,} with a year-only or missing date (never replaced by PubTracker's date), "
        f"{stats['excluded_out_of_range']:,} outside {start:%Y-%m-%d} to {end:%Y-%m-%d}. "
        f"Eligible {len(results):,} = found {int(found.sum()):,} + not in PubTracker {int((~found).sum()):,}. "
        "Exceptions are PubTracker rows with no match anywhere in the prepared Dimensions set; rows matching an "
        "excluded Dimensions record are listed separately. A record with several facilities counts toward each."
    )
    if scoped.empty:
        st.info("No eligible Dimensions records fall in the selected period.")
        return

    left, right = st.columns([1.6, 1])
    with left:
        st.subheader("Submission rate by facility")
        rates = facility_rates(results, pub_facilities).rename(columns={"Missing": NOT_IN_PUBTRACKER})
        st.dataframe(
            rates, use_container_width=True, hide_index=True, height=420,
            column_config={"Submission Rate %": st.column_config.ProgressColumn("Submission Rate %", min_value=0, max_value=100, format="%.1f%%")},
        )
        st.download_button("Download facility rates", _csv(rates), file_name="dimensions_to_pubtracker_facility_rates.csv", mime="text/csv", key="d2p_dl_rates")
    with right:
        st.subheader("Submission rate by fiscal quarter")
        st.caption("Quarter assigned by the Dimensions date.")
        quarters = quarter_rates(results, scoped)
        st.dataframe(quarters, use_container_width=True, hide_index=True)
        bar_chart(quarters, "Fiscal Period", "Submission Rate %")

    st.subheader("Records not in PubTracker by facility")
    selected = st.selectbox("Facility", rates["Facility"].tolist(), key="d2p_facility")
    missing_ids = set(results.loc[~found, "Publication ID"])
    in_facility = scoped["Publication ID"].map(
        lambda pub_id: selected in pub_facilities[pub_id] if pub_facilities.get(pub_id) else selected == UNATTRIBUTED
    )
    columns = ["Title", "Canonical Date", "Document Type", "Publication Type", "Source title", "Matched Facilities", "DOI Link", "PubMed Link", "Publication ID"]
    columns = [column for column in columns if column in scoped]
    is_missing = scoped["Publication ID"].isin(missing_ids)
    not_found = scoped[is_missing]
    facility_missing = _format_dates(scoped[is_missing & in_facility][columns], ["Canonical Date"])
    st.caption(f"{len(facility_missing):,} eligible Dimensions records for this facility were not found in PubTracker.")
    st.dataframe(
        facility_missing, use_container_width=True, hide_index=True, height=380,
        column_config={"DOI Link": st.column_config.LinkColumn("DOI"), "PubMed Link": st.column_config.LinkColumn("PubMed")},
    )
    download_cols = st.columns(2)
    download_cols[0].download_button(
        "Download this facility's records", _csv(facility_missing),
        file_name=f"not_in_pubtracker_{selected[:40].replace(' ', '_')}.csv", mime="text/csv", key="d2p_dl_facility",
    )
    download_cols[1].download_button(
        "Download all records not in PubTracker", _csv(_format_dates(not_found[columns], ["Canonical Date"])),
        file_name="dimensions_not_in_pubtracker.csv", mime="text/csv", key="d2p_dl_all_missing",
    )

    st.subheader("Matched records (Dimensions date replaces PubTracker date)")
    matched = _format_dates(
        matched_records_table(results, scoped, pubtracker, pub_facilities),
        ["Dimensions Date", "PubTracker Date Created", "PubTracker Publication Date"],
    )
    st.dataframe(matched, use_container_width=True, hide_index=True, height=380)
    st.download_button("Download matched records", _csv(matched), file_name="dimensions_pubtracker_matched.csv", mime="text/csv", key="d2p_dl_matched")

    fuzzy = results[results["Match Type"].eq("Matched (fuzzy)")].merge(
        scoped[["Publication ID", "Title"]], on="Publication ID"
    )[["Title", "PubTracker Title", "Match Score", "PubTracker Facility", "PubTracker Record ID", "Publication ID"]]
    with st.expander(f"Review fuzzy matches ({len(fuzzy):,})"):
        st.dataframe(fuzzy.sort_values("Match Score"), use_container_width=True, hide_index=True, height=360)

    pt_columns = ["Record ID", "Title", "Date Created", "Publication Date", "POC Medical Center"]
    with st.expander(f"PubTracker exceptions: no Dimensions match ({len(exceptions):,})"):
        coverage_start, coverage_end = publications["Canonical Date"].min(), publications["Canonical Date"].max()
        pt_date = exceptions["Publication Date"].fillna(exceptions["Date Created"])
        exceptions = exceptions.assign(**{"PubTracker Date In Dimensions Coverage": pt_date.between(coverage_start, coverage_end)})
        inside = int(exceptions["PubTracker Date In Dimensions Coverage"].sum())
        st.caption(
            f"The Dimensions file covers {coverage_start:%Y-%m-%d} to {coverage_end:%Y-%m-%d}. {len(exceptions) - inside:,} exceptions "
            f"have a PubTracker date outside that window and cannot match; {inside:,} fall inside it and need review."
        )
        exception_table = _format_dates(
            exceptions[pt_columns + ["PubTracker Date In Dimensions Coverage"]], ["Date Created", "Publication Date"]
        )
        st.dataframe(exception_table, use_container_width=True, hide_index=True, height=360)
        st.download_button("Download exceptions", _csv(exception_table), file_name="pubtracker_exceptions.csv", mime="text/csv", key="d2p_dl_exceptions")
    with st.expander(f"PubTracker rows matched to an excluded Dimensions record ({len(excluded):,})"):
        excluded_table = _format_dates(
            excluded[pt_columns + ["Dimensions Publication ID", "Match Type", "Match Score", "Exclusion Reason"]],
            ["Date Created", "Publication Date"],
        )
        st.dataframe(excluded_table, use_container_width=True, hide_index=True, height=360)
        st.download_button("Download matched-but-excluded", _csv(excluded_table), file_name="pubtracker_matched_but_excluded.csv", mime="text/csv", key="d2p_dl_excluded")


def render_not_in_pubtracker_simple(dataset: DashboardDataset) -> None:
    st.subheader("Dimensions publications not in PubTracker")
    st.caption(
        "Journal publications in Dimensions with an exact publication date in the chosen period that were not "
        "found in PubTracker (matched by title). Sorted by the Dimensions publication date; PubTracker's "
        "submission and publication dates are not used. A publication linked to several facilities is listed under each."
    )
    missing_files = [path for path in PUBTRACKER_PATHS if not path.exists()]
    if missing_files:
        st.error(f"PubTracker export not found: {', '.join(str(path) for path in missing_files)}")
        return

    pt_mtimes = tuple(path.stat().st_mtime for path in PUBTRACKER_PATHS)
    pubtracker = cached_pubtracker(tuple(str(path) for path in PUBTRACKER_PATHS), pt_mtimes)
    pub_facilities = facility_map(dataset.facility_matches)

    options = quarter_options(dataset.publications)
    period = st.radio("Period", list(options), horizontal=True, key="b02_period")
    start, end = options[period]
    scoped, _ = filter_fiscal_year(dataset.publications, start, end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    if scoped.empty:
        st.info("No eligible Dimensions publications fall in the selected period.")
        return
    # Same key as Build 01 so both tabs share one cached match.
    results = cached_match(90.0, f"{DATA_PATH.stat().st_mtime}|{pt_mtimes}|d2p|{period}", scoped, pub_facilities, pubtracker)
    not_found = int(results["Match Type"].eq("Missing").sum())
    entered = len(results) - not_found

    cols = st.columns(4)
    cols[0].metric(f"Dimensions publications ({period})", f"{len(results):,}")
    cols[1].metric("Entered in PubTracker", f"{entered:,}")
    cols[2].metric("Not in PubTracker", f"{not_found:,}")
    cols[3].metric("Compliance %", f"{entered / len(results) * 100:.1f}%", help="Entered in PubTracker ÷ Dimensions publications.")

    listing = not_in_pubtracker_by_facility(results, scoped, pub_facilities)
    entered_listing = records_by_facility(results, scoped, pub_facilities, in_pubtracker=True)
    summary = facility_rates(results, pub_facilities).rename(columns={
        "Dimensions Records": "Dimensions publications",
        "In PubTracker": "Entered in PubTracker",
        "Missing": "Not in PubTracker",
        "Submission Rate %": "Compliance %",
    })[["Facility", "Not in PubTracker", "Entered in PubTracker", "Dimensions publications", "Compliance %"]]

    st.subheader("Compliance by facility")
    st.caption("Click one or more facilities to drill into their publications below.")
    facility_event = st.dataframe(
        summary, use_container_width=True, hide_index=True, height=420,
        on_select="rerun", selection_mode="multi-row", key="b02_facility_table",
        column_config={"Compliance %": st.column_config.ProgressColumn("Compliance %", min_value=0, max_value=100, format="%.1f%%")},
    )
    st.download_button(
        "Download facility compliance", _csv(summary), file_name="pubtracker_compliance_by_facility.csv",
        mime="text/csv", key="b02_dl_summary",
    )

    st.subheader("Publication drill-down")
    st.caption(
        "Each row is one Dimensions publication at one facility, so a multi-facility publication appears once per "
        "facility. Dates and fiscal quarters come from Dimensions. Funding columns come from Dimensions: "
        "**VA Grant Codes** and **ORD Portfolio** are VA award prefixes (CX, BX, RX, HX, etc.) found in the funding text, "
        "**Funders** and **Grant Numbers** are the funders and awards Dimensions lists. Blank means Dimensions has none. "
        "Click a row to see its full details."
    )
    clicked = summary.iloc[facility_event.selection.rows]["Facility"].tolist() if facility_event.selection.rows else []
    filter_cols = st.columns([2, 1, 1.4, 1.4, 1.6])
    chosen = filter_cols[0].multiselect(
        "Facility", summary["Facility"].tolist(), default=clicked, key=f"b02_facility_{'|'.join(clicked)}",
        placeholder="All facilities",
    )
    quarters = filter_cols[1].multiselect(
        "Fiscal quarter", sorted(scoped["Fiscal Period"].dropna().unique()), key="b02_quarter", placeholder="All",
    )
    funding = filter_cols[2].selectbox(
        "Funding", ["All", "ORD-funded (VA grant evidence)", "Any grant listed", "No funding listed"], key="b02_funding",
    )
    portfolios = filter_cols[3].multiselect(
        "ORD portfolio", tokens(scoped, "ORD Broad Portfolios"), key="b02_portfolio", placeholder="All",
    )
    query = filter_cols[4].text_input("Search", key="b02_search", placeholder="Title, journal, funder, grant")
    filters = {"facilities": chosen, "quarters": quarters, "funding": funding, "portfolios": portfolios, "query": query}

    missing_view = _filter_facility_records(listing, filters)
    entered_view = _filter_facility_records(entered_listing, filters)
    missing_tab, entered_tab = st.tabs([
        f"Not in PubTracker ({missing_view['Publication ID'].nunique():,} publications)",
        f"In PubTracker ({entered_view['Publication ID'].nunique():,} publications)",
    ])
    with missing_tab:
        _render_facility_records(missing_view, "b02_missing", "dimensions_not_in_pubtracker_by_facility.csv", pub_facilities)
    with entered_tab:
        _render_facility_records(entered_view, "b02_entered", "dimensions_in_pubtracker_by_facility.csv", pub_facilities)


def _filter_facility_records(frame: pd.DataFrame, filters: dict) -> pd.DataFrame:
    mask = pd.Series(True, index=frame.index)
    if filters["facilities"]:
        mask &= frame["Facility"].isin(filters["facilities"])
    if filters["quarters"]:
        mask &= frame["Fiscal Period"].isin(filters["quarters"])
    if filters["funding"] == "ORD-funded (VA grant evidence)":
        mask &= frame["ORD Funded"]
    elif filters["funding"] == "Any grant listed":
        mask &= frame["Grant Numbers"].ne("") | frame["VA Grant Codes"].ne("")
    elif filters["funding"] == "No funding listed":
        mask &= frame["Grant Numbers"].eq("") & frame["VA Grant Codes"].eq("") & frame["Funders"].eq("")
    if filters["portfolios"]:
        wanted = set(filters["portfolios"])
        mask &= frame["ORD Portfolio"].map(lambda value: bool(wanted & set(split_values(value))))
    query = filters["query"].strip()
    if query:
        searchable = frame[["Title", "Journal", "Funders", "Grant Numbers", "VA Grant Codes"]].agg(" ".join, axis=1)
        mask &= searchable.str.contains(query, case=False, regex=False)
    return frame[mask].reset_index(drop=True)


def _render_facility_records(frame: pd.DataFrame, key: str, file_name: str, pub_facilities: dict) -> None:
    unique = frame["Publication ID"].nunique()
    ord_funded = frame.drop_duplicates("Publication ID")["ORD Funded"].sum()
    st.caption(
        f"{unique:,} publications ({len(frame):,} facility rows); {ord_funded:,} with VA/ORD grant evidence. "
        "Newest Dimensions publication date first."
    )
    shown = _format_dates(frame, ["Dimensions Date"])
    event = st.dataframe(
        shown, use_container_width=True, hide_index=True, height=440,
        on_select="rerun", selection_mode="single-row", key=f"{key}_table",
        column_config={
            "ORD Funded": st.column_config.CheckboxColumn("ORD Funded"),
            "DOI": st.column_config.LinkColumn("DOI", display_text="DOI"),
            "PubMed": st.column_config.LinkColumn("PubMed", display_text="PubMed"),
            "Dimensions URL": st.column_config.LinkColumn("Dimensions", display_text="Open"),
            "Match Score": st.column_config.NumberColumn("Match Score", format="%.0f"),
        },
    )
    st.download_button("Download this list", _csv(shown), file_name=file_name, mime="text/csv", key=f"{key}_dl")
    if not event.selection.rows:
        return
    record = shown.iloc[event.selection.rows[0]]
    with st.container(border=True):
        st.markdown(f"**{record['Title']}**")
        left, right = st.columns(2)
        left.markdown(
            f"**Dimensions date:** {record['Dimensions Date']} ({record['Fiscal Period']})  \n"
            f"**Journal:** {record['Journal'] or '-'}  \n"
            f"**Document type:** {record['Document Type'] or '-'}  \n"
            f"**All facilities:** {'; '.join(sorted(pub_facilities.get(record['Publication ID'], ()))) or UNATTRIBUTED}"
        )
        right.markdown(
            f"**ORD funded:** {'Yes' if record['ORD Funded'] else 'No evidence'}  \n"
            f"**VA grant codes:** {record['VA Grant Codes'] or '-'}  \n"
            f"**ORD portfolio:** {record['ORD Portfolio'] or '-'}  \n"
            f"**Funders:** {record['Funders'] or '-'}  \n"
            f"**Grant numbers:** {record['Grant Numbers'] or '-'}"
        )
        if "Match Type" in record:
            st.markdown(
                f"**PubTracker match:** {record['Match Type']}, score {record['Match Score']:.0f}, "
                f"Record ID {record['PubTracker Record ID']}"
            )
        links = [f"[{label}]({record[column]})" for label, column in (("DOI", "DOI"), ("PubMed", "PubMed"), ("Dimensions", "Dimensions URL")) if record[column]]
        if links:
            st.markdown(" · ".join(links))


if not DATA_PATH.exists():
    st.error("The merged Dimensions file is missing. Run run_dimensions_export.bat first.")
    st.stop()

try:
    dataset = cached_dataset(str(DATA_PATH), DATA_PATH.stat().st_mtime)
except Exception as error:
    st.error(f"Could not prepare the Dimensions dashboard: {error}")
    st.stop()

filtered_publications, filtered_matches = render_filters(dataset)
st.caption(f"Showing {len(filtered_publications):,} of {len(dataset.publications):,} source publications")
if filtered_publications.empty:
    st.warning("No publications match the current filters. Reset or broaden the filters to continue.")
    st.stop()

overview_tab, records_tab, facilities_tab, ord_tab, impact_tab, compliance_tab, d2p_tab, b02_tab = st.tabs([
    "Overview", "Records", "Facilities", "ORD Portfolios", "Research impact", COMPLIANCE_TAB_TITLE,
    DIM_TO_PT_TAB_TITLE, BUILD_02_TAB_TITLE,
])
with overview_tab:
    render_overview(filtered_publications, filtered_matches)
with records_tab:
    render_records(filtered_publications, dataset.source_columns)
with facilities_tab:
    render_facilities(filtered_publications, filtered_matches)
with ord_tab:
    render_ord_portfolios(filtered_publications, filtered_matches)
with impact_tab:
    render_impact(filtered_publications)
with compliance_tab:
    render_pubtracker_compliance(dataset)
with d2p_tab:
    render_dimensions_to_pubtracker(dataset)
with b02_tab:
    render_not_in_pubtracker_simple(dataset)