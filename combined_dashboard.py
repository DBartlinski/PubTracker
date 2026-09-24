"""Combined multi-batch VA publications dashboard (2016-2019, 2020-2024, FY24-FY25).

Analyzes the deduplicated union of all three Dimensions batch exports to give an
overall picture of VA-affiliated research output: preprint vs. print, volume over
time, topics, active facilities, active authors, and ORD-funded vs. other VA
publications.

Run: streamlit run combined_dashboard.py
Data must first be built with: python build_combined_dashboard_data.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))

from processors.dashboard_data import split_values

# Set COMBINED_DASHBOARD_DATA_DIR to force a specific cache directory. Otherwise, prefer the
# full local cache (output/combined_dashboard) and fall back to the trimmed public cache
# (output/combined_dashboard_public) when the full one isn't present - e.g. on a Streamlit
# Community Cloud deployment, where only the trimmed cache is committed to git.
_DEFAULT_CACHE_DIRS = ["output/combined_dashboard", "output/combined_dashboard_public"]


def _resolve_cache_dir() -> Path:
    override = os.environ.get("COMBINED_DASHBOARD_DATA_DIR")
    if override:
        return Path(override)
    for candidate in _DEFAULT_CACHE_DIRS:
        if (Path(candidate) / "combined_publications.parquet").exists():
            return Path(candidate)
    return Path(_DEFAULT_CACHE_DIRS[0])


CACHE_DIR = _resolve_cache_dir()
PUBLICATIONS_PATH = CACHE_DIR / "combined_publications.parquet"
MATCHES_PATH = CACHE_DIR / "combined_facility_matches.parquet"

st.set_page_config(page_title="VA Publications - Combined Analysis", page_icon="🧭", layout="wide")
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap');
    html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
    h1, h2, h3 { font-family: 'IBM Plex Serif', serif; letter-spacing: 0; }
    [data-testid="stAppViewContainer"] { background: linear-gradient(180deg, #f5f7f4 0, #ffffff 260px); }
    [data-testid="stSidebar"] { background: #edf1ec; border-right: 1px solid #cdd6cf; }
    [data-testid="stMetric"] {
        background: #ffffff; border: 1px solid #d9dfda; border-top: 3px solid #236b56;
        padding: 12px 14px; border-radius: 4px;
    }
    .dashboard-kicker { color: #236b56; font-size: .78rem; font-weight: 600; text-transform: uppercase; }
    .dashboard-note { color: #52605a; font-size: .92rem; margin-bottom: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner="Loading combined publication dataset...")
def load_cached(pub_mtime: float, match_mtime: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    del pub_mtime, match_mtime
    publications = pd.read_parquet(PUBLICATIONS_PATH)
    matches = pd.read_parquet(MATCHES_PATH)
    return publications, matches


def reset_filters() -> None:
    for key in list(st.session_state):
        if key.startswith("cdash_"):
            del st.session_state[key]


def tokens(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame:
        return []
    values = {token for value in frame[column] for token in split_values(value)}
    return sorted(values, key=str.casefold)


def bar_chart(frame: pd.DataFrame, category: str, value: str, color: str = "#236b56") -> None:
    if frame.empty:
        st.info("No data is available for this chart under the current filters.")
        return
    st.bar_chart(frame.set_index(category)[value], color=color)


def apply_filters(publications: pd.DataFrame, matches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = pd.Series(True, index=publications.index)
    if not st.session_state.cdash_include_all:
        mask &= publications["SOP Eligible"]

    ord_status = st.session_state.cdash_ord_status
    if ord_status == "ORD-funded only":
        mask &= publications["Has ORD Funding Evidence"]
    elif ord_status == "Other VA publications only":
        mask &= ~publications["Has ORD Funding Evidence"]

    preprint_status = st.session_state.cdash_preprint_status
    if preprint_status == "Preprints only":
        mask &= publications["Is Preprint"]
    elif preprint_status == "Published only (exclude preprints)":
        mask &= ~publications["Is Preprint"]

    selections = {
        "Calendar Year": st.session_state.cdash_calendar_year,
        "Fiscal Year": st.session_state.cdash_fiscal_year,
        "Document Type": st.session_state.cdash_document_type,
        "Facility Match Status": st.session_state.cdash_match_status,
    }
    for column, selected in selections.items():
        if selected:
            mask &= publications[column].isin(selected)

    batches = st.session_state.cdash_batches
    if batches:
        selected_set = set(batches)
        mask &= publications["Source Batches"].map(lambda value: bool(selected_set & set(split_values(value))))

    selected_facilities = st.session_state.cdash_facility
    if selected_facilities:
        facility_ids = matches.loc[matches["Facility"].isin(selected_facilities), "Publication ID"]
        mask &= publications["Publication ID"].isin(facility_ids)

    query = st.session_state.cdash_search.strip()
    if query:
        search_columns = ["Title", "Authors", "DOI", "PMID", "Publication ID"]
        searchable = publications[search_columns].fillna("").astype(str).agg(" ".join, axis=1)
        mask &= searchable.str.contains(query, case=False, regex=False)

    filtered = publications.loc[mask].copy()
    filtered_matches = matches[matches["Publication ID"].isin(filtered["Publication ID"])].copy()
    if selected_facilities:
        filtered_matches = filtered_matches[filtered_matches["Facility"].isin(selected_facilities)]
    return filtered, filtered_matches


def render_filters(publications: pd.DataFrame, matches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with st.sidebar:
        st.header("Filters")
        if st.button("Reset filters", use_container_width=True):
            reset_filters()
            st.rerun()
        st.checkbox("Include SOP-excluded records", value=False, key="cdash_include_all")
        st.selectbox(
            "ORD funding status",
            ["All publications", "ORD-funded only", "Other VA publications only"],
            key="cdash_ord_status",
        )
        st.selectbox(
            "Preprint status",
            ["All publications", "Preprints only", "Published only (exclude preprints)"],
            key="cdash_preprint_status",
        )
        st.multiselect(
            "Batch export",
            tokens(publications, "Source Batches"),
            key="cdash_batches",
            help="A publication can appear in more than one batch when year ranges overlap.",
        )
        st.multiselect(
            "Calendar publication year",
            sorted(publications["Calendar Year"].dropna().astype(int).unique(), reverse=True),
            key="cdash_calendar_year",
        )
        st.multiselect(
            "VA fiscal year",
            sorted(publications["Fiscal Year"].dropna().astype(int).unique(), reverse=True),
            key="cdash_fiscal_year",
        )
        st.multiselect(
            "Facility",
            sorted(matches["Facility"].unique(), key=str.casefold),
            key="cdash_facility",
        )
        with st.expander("Advanced filters"):
            st.multiselect(
                "Document type",
                sorted(publications["Document Type"].dropna().unique(), key=str.casefold),
                key="cdash_document_type",
            )
            st.multiselect(
                "Facility match status",
                ["Single facility", "Multiple facilities", "Unmatched"],
                key="cdash_match_status",
            )
        st.text_input(
            "Search title, author, DOI, PMID, or ID",
            key="cdash_search",
            placeholder="Search records",
        )
        st.divider()
        st.caption(
            "Combines batch exports for 2016-2019, 2020-2024, and FY24-FY25, de-duplicated by "
            "Publication ID. ORD-funded status and facility matches are inferred (see ORD tab); "
            "treat all figures as estimates."
        )
    return apply_filters(publications, matches)


def explode_tokens(publications: pd.DataFrame, id_column: str, value_column: str, label: str) -> pd.DataFrame:
    rows = []
    for pub_id, value in publications[[id_column, value_column]].itertuples(index=False):
        for token in split_values(value):
            rows.append({id_column: pub_id, label: token})
    return pd.DataFrame(rows, columns=[id_column, label])


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

def render_overview(publications: pd.DataFrame, matches: pd.DataFrame) -> None:
    total = len(publications)
    ord_funded = int(publications["Has ORD Funding Evidence"].sum())
    preprints = int(publications["Is Preprint"].sum())
    active_facilities = matches["Facility"].nunique()
    author_tokens = {a for value in publications["Authors"] for a in split_values(value)}

    cols = st.columns(5)
    cols[0].metric("Publications", f"{total:,}")
    cols[1].metric("ORD-funded", f"{ord_funded:,}", f"{100 * ord_funded / total:.0f}%" if total else "0%")
    cols[2].metric("Preprints", f"{preprints:,}", f"{100 * preprints / total:.0f}%" if total else "0%")
    cols[3].metric("Active facilities", f"{active_facilities:,}")
    cols[4].metric("Active authors", f"{len(author_tokens):,}")

    left, right = st.columns([1.6, 1])
    with left:
        st.subheader("Publications by calendar year")
        trend = (
            publications.dropna(subset=["Calendar Year"])
            .groupby("Calendar Year")["Publication ID"].nunique().reset_index(name="Publications")
        )
        trend["Calendar Year"] = trend["Calendar Year"].astype(int)
        bar_chart(trend, "Calendar Year", "Publications")
    with right:
        st.subheader("Batch coverage")
        batch_long = explode_tokens(publications, "Publication ID", "Source Batches", "Batch")
        counts = batch_long["Batch"].value_counts().rename_axis("Batch").reset_index(name="Publications")
        bar_chart(counts, "Batch", "Publications", "#ca8a2c")

    left, right = st.columns(2)
    with left:
        st.subheader("ORD-funded vs. other VA publications")
        ord_frame = pd.DataFrame({
            "Status": ["ORD-funded", "Other VA publications"],
            "Publications": [ord_funded, total - ord_funded],
        })
        bar_chart(ord_frame, "Status", "Publications", "#5f6b85")
    with right:
        st.subheader("Preprint vs. published")
        preprint_frame = pd.DataFrame({
            "Status": ["Preprint", "Published"],
            "Publications": [preprints, total - preprints],
        })
        bar_chart(preprint_frame, "Status", "Publications", "#b4553d")


def render_trends(publications: pd.DataFrame) -> None:
    st.subheader("Publications over time")
    st.caption("Grouped by calendar publication year. Use the sidebar to compare ORD-funded vs. other, or preprint vs. published.")

    by_year = publications.dropna(subset=["Calendar Year"]).copy()
    by_year["Calendar Year"] = by_year["Calendar Year"].astype(int)

    left, right = st.columns(2)
    with left:
        st.markdown("**By ORD funding status**")
        grouped = (
            by_year.assign(Status=by_year["Has ORD Funding Evidence"].map({True: "ORD-funded", False: "Other VA"}))
            .groupby(["Calendar Year", "Status"])["Publication ID"].nunique()
            .unstack(fill_value=0)
        )
        if grouped.empty:
            st.info("No data is available for this chart under the current filters.")
        else:
            st.bar_chart(grouped)
    with right:
        st.markdown("**By preprint status**")
        grouped = (
            by_year.assign(Status=by_year["Is Preprint"].map({True: "Preprint", False: "Published"}))
            .groupby(["Calendar Year", "Status"])["Publication ID"].nunique()
            .unstack(fill_value=0)
        )
        if grouped.empty:
            st.info("No data is available for this chart under the current filters.")
        else:
            st.bar_chart(grouped)

    st.markdown("**By VA fiscal year**")
    by_fy = publications.dropna(subset=["Fiscal Year"]).copy()
    by_fy["Fiscal Year"] = by_fy["Fiscal Year"].astype(int).map(lambda value: f"FY{value}")
    fy_trend = by_fy.groupby("Fiscal Year")["Publication ID"].nunique().reset_index(name="Publications")
    bar_chart(fy_trend, "Fiscal Year", "Publications")


def render_preprints(publications: pd.DataFrame) -> None:
    st.subheader("Preprint vs. print analysis")
    st.caption("Based on Dimensions' 'Publication Type' field equal to 'Preprint'.")
    total = len(publications)
    preprints = int(publications["Is Preprint"].sum())
    cols = st.columns(3)
    cols[0].metric("Preprints", f"{preprints:,}")
    cols[1].metric("Published (non-preprint)", f"{total - preprints:,}")
    cols[2].metric("Preprint share", f"{100 * preprints / total:.1f}%" if total else "0%")

    ord_rows = publications[publications["Has ORD Funding Evidence"]]
    ord_total = len(ord_rows)
    ord_preprints = int(ord_rows["Is Preprint"].sum())
    st.markdown("**ORD-funded only**")
    ord_cols = st.columns(3)
    ord_cols[0].metric("ORD-funded preprints", f"{ord_preprints:,}")
    ord_cols[1].metric("ORD-funded published (non-preprint)", f"{ord_total - ord_preprints:,}")
    ord_cols[2].metric("ORD-funded preprint share", f"{100 * ord_preprints / ord_total:.1f}%" if ord_total else "0%")

    left, right = st.columns(2)
    with left:
        st.markdown("**Preprint share by calendar year**")
        by_year = publications.dropna(subset=["Calendar Year"]).copy()
        by_year["Calendar Year"] = by_year["Calendar Year"].astype(int)
        share = by_year.groupby("Calendar Year")["Is Preprint"].mean().mul(100).reset_index(name="Preprint %")
        ord_share = (
            by_year[by_year["Has ORD Funding Evidence"]]
            .groupby("Calendar Year")["Is Preprint"].mean().mul(100).reset_index(name="Preprint %")
        )
        share_by_year = share.rename(columns={"Preprint %": "All publications"}).merge(
            ord_share.rename(columns={"Preprint %": "ORD-funded"}), on="Calendar Year", how="left"
        ).set_index("Calendar Year")
        if share_by_year.empty:
            st.info("No data is available for this chart under the current filters.")
        else:
            st.line_chart(share_by_year)
    with right:
        st.markdown("**Preprint share: ORD-funded vs. other**")
        share_ord = (
            publications.assign(Status=publications["Has ORD Funding Evidence"].map({True: "ORD-funded", False: "Other VA"}))
            .groupby("Status")["Is Preprint"].mean().mul(100).reset_index(name="Preprint %")
        )
        bar_chart(share_ord, "Status", "Preprint %", "#5f6b85")

    st.markdown("**Top journals/sources publishing VA preprints**")
    left, right = st.columns(2)
    with left:
        st.caption("All publications")
        preprint_rows = publications[publications["Is Preprint"]]
        top_sources = (
            preprint_rows["Source title"].fillna("Unknown").value_counts().head(15)
            .rename_axis("Source").reset_index(name="Preprints")
        )
        bar_chart(top_sources, "Source", "Preprints", "#ca8a2c")
    with right:
        st.caption("ORD-funded only")
        ord_preprint_rows = ord_rows[ord_rows["Is Preprint"]]
        ord_top_sources = (
            ord_preprint_rows["Source title"].fillna("Unknown").value_counts().head(15)
            .rename_axis("Source").reset_index(name="Preprints")
        )
        bar_chart(ord_top_sources, "Source", "Preprints", "#5f6b85")


def render_topics(publications: pd.DataFrame) -> None:
    st.subheader("Research topics")
    topic_column = st.selectbox(
        "Topic taxonomy",
        [
            "RCDC Categories",
            "HRCS HC Categories",
            "Fields of Research (ANZSRC 2020)",
            "Broad Research Areas",
            "Health Research Areas",
        ],
    )
    top_n = st.slider("Top N topics", 5, 30, 15)
    topic_long = explode_tokens(publications, "Publication ID", topic_column, "Topic")
    if topic_long.empty:
        st.info("No data is available for this taxonomy under the current filters.")
        return
    topic_long = topic_long.merge(
        publications[["Publication ID", "Has ORD Funding Evidence"]], on="Publication ID", how="left"
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Overall top topics**")
        counts = topic_long["Topic"].value_counts().head(top_n).rename_axis("Topic").reset_index(name="Publications")
        bar_chart(counts, "Topic", "Publications")
    with right:
        st.markdown("**ORD-funded top topics**")
        ord_counts = (
            topic_long[topic_long["Has ORD Funding Evidence"]]["Topic"].value_counts().head(top_n)
            .rename_axis("Topic").reset_index(name="Publications")
        )
        bar_chart(ord_counts, "Topic", "Publications", "#5f6b85")


def render_facilities(publications: pd.DataFrame, matches: pd.DataFrame) -> None:
    st.subheader("Active facilities")
    st.caption("Matches are name-based evidence for review, not authoritative assignments. Station 101 umbrella terms are excluded.")
    if matches.empty:
        st.info("No facility matches are available under the current filters.")
        return

    active_facilities = matches["Facility"].nunique()
    st.metric("Active facilities", f"{active_facilities:,}")

    summary = matches.merge(
        publications[["Publication ID", "Has ORD Funding Evidence", "Is Preprint", "Calendar Year"]],
        on="Publication ID", how="left",
    )
    facility_summary = summary.groupby("Facility").agg(
        Publications=("Publication ID", "nunique"),
        ORD_Funded=("Has ORD Funding Evidence", "sum"),
        Preprints=("Is Preprint", "sum"),
    ).reset_index().sort_values("Publications", ascending=False)
    st.dataframe(facility_summary, use_container_width=True, hide_index=True, height=360)

    st.markdown("**Top facilities by publication volume**")
    bar_chart(facility_summary.head(15), "Facility", "Publications", "#ca8a2c")

    selected = st.selectbox("Facility drilldown - publications over time", facility_summary["Facility"].tolist())
    facility_trend = (
        summary[summary["Facility"] == selected].dropna(subset=["Calendar Year"])
        .assign(**{"Calendar Year": lambda d: d["Calendar Year"].astype(int)})
        .groupby("Calendar Year")["Publication ID"].nunique().reset_index(name="Publications")
    )
    bar_chart(facility_trend, "Calendar Year", "Publications")


def render_authors(publications: pd.DataFrame) -> None:
    st.subheader("Active authors")
    author_long = explode_tokens(publications, "Publication ID", "Authors", "Author")
    if author_long.empty:
        st.info("No author data is available under the current filters.")
        return
    author_long = author_long.merge(
        publications[["Publication ID", "Has ORD Funding Evidence", "Calendar Year"]], on="Publication ID", how="left"
    )
    total_authors = author_long["Author"].nunique()
    ord_authors = author_long.loc[author_long["Has ORD Funding Evidence"], "Author"].nunique()

    cols = st.columns(2)
    cols[0].metric("Active authors", f"{total_authors:,}")
    cols[1].metric("Authors with ORD-funded publications", f"{ord_authors:,}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Most prolific authors (overall)**")
        top_authors = author_long["Author"].value_counts().head(20).rename_axis("Author").reset_index(name="Publications")
        bar_chart(top_authors, "Author", "Publications")
    with right:
        st.markdown("**Active authors by calendar year**")
        by_year = author_long.dropna(subset=["Calendar Year"]).copy()
        by_year["Calendar Year"] = by_year["Calendar Year"].astype(int)
        trend = by_year.groupby("Calendar Year")["Author"].nunique().reset_index(name="Active authors")
        bar_chart(trend, "Calendar Year", "Active authors", "#ca8a2c")


def render_ord_vs_other(publications: pd.DataFrame) -> None:
    st.subheader("ORD-funded vs. other VA publications")
    st.caption(
        "ORD-funded is inferred from VA grant award prefixes and service names in the funding/acknowledgement "
        "text, or an Actively Managed Portfolio topic keyword paired with funding evidence (see "
        "processors/ord_portfolio.py). Treat as an estimate, not an authoritative VA source of truth."
    )
    total = len(publications)
    ord_funded = int(publications["Has ORD Funding Evidence"].sum())
    cols = st.columns(3)
    cols[0].metric("Publications", f"{total:,}")
    cols[1].metric("ORD-funded", f"{ord_funded:,}", f"{100 * ord_funded / total:.0f}%" if total else "0%")
    cols[2].metric("Other VA publications", f"{total - ord_funded:,}", f"{100 * (total - ord_funded) / total:.0f}%" if total else "0%")

    broad_long = explode_tokens(publications, "Publication ID", "ORD Broad Portfolios", "Broad Portfolio")
    left, right = st.columns(2)
    with left:
        st.markdown("**Broad Portfolio breakdown**")
        counts = broad_long["Broad Portfolio"].value_counts().rename_axis("Broad Portfolio").reset_index(name="Publications")
        bar_chart(counts, "Broad Portfolio", "Publications")
    with right:
        st.markdown("**ORD-funded vs. other, by calendar year**")
        by_year = publications.dropna(subset=["Calendar Year"]).copy()
        by_year["Calendar Year"] = by_year["Calendar Year"].astype(int)
        grouped = (
            by_year.assign(Status=by_year["Has ORD Funding Evidence"].map({True: "ORD-funded", False: "Other VA"}))
            .groupby(["Calendar Year", "Status"])["Publication ID"].nunique()
            .unstack(fill_value=0)
        )
        if grouped.empty:
            st.info("No data is available for this chart under the current filters.")
        else:
            st.bar_chart(grouped)


def render_records(publications: pd.DataFrame) -> None:
    st.subheader("Publication records")
    columns = [
        "Title", "Publication ID", "Canonical Date", "Calendar Year", "Fiscal Period",
        "Document Type", "Is Preprint", "Has ORD Funding Evidence", "Matched Facilities",
        "Source title", "Source Batches", "Times cited",
    ]
    records = publications[[column for column in columns if column in publications]].copy()
    if "Canonical Date" in records:
        records["Canonical Date"] = records["Canonical Date"].dt.strftime("%Y-%m-%d").fillna("")
    st.dataframe(records, use_container_width=True, hide_index=True, height=560)
    st.download_button(
        "Download filtered records",
        records.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"combined_dashboard_filtered_{len(records)}.csv",
        mime="text/csv",
    )


def main() -> None:
    st.markdown('<div class="dashboard-kicker">VA Publications - Combined Analysis</div>', unsafe_allow_html=True)
    st.title("2016-2025 Combined Dimensions Dashboard")
    st.markdown(
        '<div class="dashboard-note">Deduplicated union of the 2016-2019, 2020-2024, and FY24-FY25 batch '
        "exports, giving an overall picture of VA-affiliated research output: preprint vs. print, volume "
        "over time, topics, active facilities, active authors, and ORD-funded vs. other VA publications.</div>",
        unsafe_allow_html=True,
    )

    if not PUBLICATIONS_PATH.exists() or not MATCHES_PATH.exists():
        st.error(
            f"Combined dataset cache not found at `{CACHE_DIR}`. Run `python build_combined_dashboard_data.py` "
            "(add `--out-dir output/combined_dashboard_public --public` for a smaller committable cache) "
            "from the project root, then reload this page. If deploying, either commit the trimmed public "
            "cache or set the COMBINED_DASHBOARD_DATA_DIR environment variable to its location."
        )
        return

    publications, matches = load_cached(
        PUBLICATIONS_PATH.stat().st_mtime, MATCHES_PATH.stat().st_mtime
    )
    filtered, filtered_matches = render_filters(publications, matches)
    st.caption(f"Showing {len(filtered):,} of {len(publications):,} unique publications under the current filters.")

    tabs = st.tabs([
        "Overview", "Trends Over Time", "Preprint vs. Print", "Topics",
        "Facilities", "Authors", "ORD vs. Other", "Records",
    ])
    with tabs[0]:
        render_overview(filtered, filtered_matches)
    with tabs[1]:
        render_trends(filtered)
    with tabs[2]:
        render_preprints(filtered)
    with tabs[3]:
        render_topics(filtered)
    with tabs[4]:
        render_facilities(filtered, filtered_matches)
    with tabs[5]:
        render_authors(filtered)
    with tabs[6]:
        render_ord_vs_other(filtered)
    with tabs[7]:
        render_records(filtered)


if __name__ == "__main__":
    main()
