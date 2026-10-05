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
    facility_map,
    facility_rates,
    filter_fiscal_year,
    filter_pubtracker_period,
    load_pubtracker_files,
    match_to_pubtracker,
    quarter_options,
)


DATA_PATH = Path("output/dimensions_va_2025_2026/dimensions_va_2025_2026_filtered_2025-10-01_to_2026-09-30.csv")
PUBTRACKER_PATHS = [
    Path("PubTracker Export/submissionlist20261005132200-2025.xlsx"),
    Path("PubTracker Export/submissionlist20261005132200-2026.xlsx"),
]
COMPLIANCE_TAB_TITLE = "Dimensions-PubTracker Complience Oct 2026"
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
    pubtracker_all = cached_pubtracker(tuple(str(path) for path in PUBTRACKER_PATHS), pt_mtimes)
    scoped, stats = filter_fiscal_year(dataset.publications)

    options = quarter_options(scoped)
    period = st.radio("Period", list(options), horizontal=True, key="compliance_period")
    start, end = options[period]
    scoped = scoped[scoped["Canonical Date"].between(start, end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
    pubtracker = filter_pubtracker_period(pubtracker_all, start, end)

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
        f"{stats['source_records']:,} source records: excluded {stats['excluded_document_type']:,} non-scientific document types, "
        f"{stats['excluded_undated_or_year_only']:,} with no exact date, {stats['excluded_out_of_range']:,} outside Oct 1, 2025 - Sep 30, 2026. "
        f"PubTracker: {len(pubtracker):,} of {len(pubtracker_all):,} publication submissions have a publication date "
        f"(Date Created if blank) in {start:%Y-%m-%d} to {end:%Y-%m-%d}. A record with several facilities counts toward each."
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

overview_tab, records_tab, facilities_tab, ord_tab, impact_tab, compliance_tab = st.tabs([
    "Overview", "Records", "Facilities", "ORD Portfolios", "Research impact", COMPLIANCE_TAB_TITLE,
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