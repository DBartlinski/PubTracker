import io
import sys
import os

import pandas as pd
import streamlit as st

# Ensure the project root is on sys.path so processors can be imported
sys.path.insert(0, os.path.dirname(__file__))

from processors.pubtracker_processor import process_pubtracker, get_quarter_label
from processors.dimensions_processor import read_dimensions_df, process_dimensions
from processors.compliance_calculator import calculate_compliance, load_vamc_reference

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title='PubTracker Compliance Report',
    page_icon='📊',
    layout='wide',
)

# ---------------------------------------------------------------------------
# Sidebar – instructions
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header('How to use')
    st.markdown(
        """
        **Step 1 – PubTracker export**  
        Download the PubTracker CSV (all publications for the current year).
        Save as CSV and upload below.

        **Step 2 – Dimensions export**  
        Download the Dimensions XLSX, open in Excel and save as CSV. Upload below.

        **Step 3 – Generate**  
        Click *Generate Compliance Report*. The app will:
        - Filter PubTracker to publications only
        - Exclude Conference Abstracts & Correction Erratum from Dimensions
        - Auto-detect VA fiscal year quarters from dates
        - Count submissions per VAMC (PubTracker by station no., Dimensions by org name)
        - Calculate % Entered (PubTracker ÷ Dimensions)

        **Step 4 – Download**  
        Download the compliance CSV and/or the summary report.
        """
    )
    st.divider()
    st.caption('VA Fiscal Year: Q1 Oct–Dec · Q2 Jan–Mar · Q3 Apr–Jun · Q4 Jul–Sep')

# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
st.title('📊 PubTracker Compliance Report Generator')

# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------
col_left, col_right = st.columns(2)

with col_left:
    st.subheader('PubTracker Data')
    pubtracker_file = st.file_uploader(
        'Upload PubTracker CSV export',
        type=['csv'],
        key='pubtracker_upload',
        help='Export from PubTracker – all submission types for the year.',
    )
    if pubtracker_file:
        st.success(f'✓  {pubtracker_file.name}')

with col_right:
    st.subheader('Dimensions Data')
    dimensions_file = st.file_uploader(
        'Upload Dimensions CSV export',
        type=['csv'],
        key='dimensions_upload',
        help=(
            'Export from VA Dimensions. The standard Dimensions export has two '
            'metadata rows above the column headers – the app handles this automatically.'
        ),
    )
    if dimensions_file:
        st.success(f'✓  {dimensions_file.name}')

# ---------------------------------------------------------------------------
# Generate button
# ---------------------------------------------------------------------------
st.divider()

# Options
with st.expander('⚙️  Options'):
    include_presentations = st.checkbox(
        'Include "presentation" type submissions (in addition to publications)',
        value=False,
        help='The SOP specifies publications only. Enable this if your PubTracker extract was not pre-filtered.',
    )

if not pubtracker_file or not dimensions_file:
    st.info('Upload both files above to enable the report generator.')
    st.stop()

if st.button('Generate Compliance Report', type='primary', width='stretch'):

    with st.spinner('Processing…'):

        errors = []

        # ── PubTracker ──────────────────────────────────────────────────────
        try:
            pt_raw = pd.read_csv(pubtracker_file)
            pt_counts, pt_info = process_pubtracker(pt_raw, include_presentations=include_presentations)
        except Exception as exc:
            errors.append(f'PubTracker processing error: {exc}')
            pt_counts, pt_info = {}, {}
            pt_raw = pd.DataFrame()

        # ── Dimensions ──────────────────────────────────────────────────────
        try:
            dimensions_file.seek(0)
            dim_raw = read_dimensions_df(dimensions_file.read())
            dim_pub_list, dim_date_info = process_dimensions(dim_raw)
        except Exception as exc:
            errors.append(f'Dimensions processing error: {exc}')
            dim_pub_list, dim_date_info = [], {}
            dim_raw = pd.DataFrame()

        # ── Compliance calculation ───────────────────────────────────────────
        if not errors:
            try:
                vamc_ref = load_vamc_reference()
                result_df, report_text, all_quarters, diagnostics = calculate_compliance(
                    pt_counts, dim_pub_list, vamc_ref
                )
            except Exception as exc:
                errors.append(f'Compliance calculation error: {exc}')
                result_df, report_text, all_quarters, diagnostics = None, '', [], {}

    # ── Show errors ─────────────────────────────────────────────────────────
    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    if not all_quarters:
        st.warning(
            'No matching fiscal-year quarters were found in the uploaded data. '
            'Check that the files contain valid dates.'
        )
        st.stop()

    st.success('✅  Report generated successfully!')

    quarter_labels = [get_quarter_label(fy, q) for fy, q in all_quarters]
    st.info(f"Quarters detected from PubTracker: **{', '.join(quarter_labels)}**  |  Rows kept: **{pt_info.get('total_kept', '?')}**")

    # Warn about excluded types
    excluded = pt_info.get('excluded_types', {})
    if excluded:
        exc_str = ', '.join(f'{v} "{k}"' for k, v in excluded.items())
        st.warning(f"Excluded from PubTracker (non-publication types): {exc_str}. Enable in Options if these should be counted.")

    # Date range banner for Dimensions
    if dim_date_info.get('min_date') and dim_date_info.get('max_date'):
        mn = dim_date_info['min_date'].strftime('%b %d, %Y')
        mx = dim_date_info['max_date'].strftime('%b %d, %Y')
        st.info(
            f"Dimensions file contains **{dim_date_info['count']}** publications "
            f"with publication dates ranging **{mn} – {mx}**. "
            "Ensure this matches the quarter(s) above (pre-filter in Dimensions per SOP)."
        )

    # ── Summary metrics ──────────────────────────────────────────────────────
    st.subheader('Summary')
    metric_cols = st.columns(len(all_quarters) * 3)
    for idx, (fy_year, q) in enumerate(all_quarters):
        label = get_quarter_label(fy_year, q)
        total_row = result_df[result_df['VAMC'] == 'TOTAL']
        if total_row.empty:
            continue
        t = total_row.iloc[0]
        base = idx * 3
        metric_cols[base].metric(f'{label}\nPubTracker', t[f'{label} PubTracker Count'])
        metric_cols[base + 1].metric(f'{label}\nDimensions', t[f'{label} Dimensions Count'])
        metric_cols[base + 2].metric(f'{label}\n% Entered', t[f'{label} % Entered'])

    # ── Results table ────────────────────────────────────────────────────────
    st.subheader('Compliance Table')
    
    # Apply styling to highlight compliance percentages
    def style_compliance(val):
        """Color cells based on compliance: green for positive (+), red for negative (-)."""
        if isinstance(val, str) and val.startswith('+'):
            return 'background-color: #d4edda; color: #155724; font-weight: 600'
        elif isinstance(val, str) and val.startswith('-'):
            return 'background-color: #f8d7da; color: #721c24; font-weight: 600'
        return ''
    
    styled_df = result_df.style.applymap(style_compliance, subset=[col for col in result_df.columns if '% Entered' in col])
    st.dataframe(styled_df, width='stretch', height=560, hide_index=True)

    # ── Downloads ────────────────────────────────────────────────────────────
    st.subheader('Download Results')
    dl_col1, dl_col2 = st.columns(2)

    csv_buffer = io.StringIO()
    result_df.to_csv(csv_buffer, index=False)
    filename_stem = '_'.join(quarter_labels).replace(' ', '')

    with dl_col1:
        st.download_button(
            '📥  Download Compliance CSV',
            data=csv_buffer.getvalue(),
            file_name=f'pubtracker_compliance_{filename_stem}.csv',
            mime='text/csv',
            width='stretch',
        )

    with dl_col2:
        st.download_button(
            '📄  Download Summary Report',
            data=report_text,
            file_name=f'compliance_report_{filename_stem}.txt',
            mime='text/plain',
            width='stretch',
        )

    # ── Diagnostics expander ─────────────────────────────────────────────────
    with st.expander('🔍  Diagnostics – Dimensions matching details'):
        st.caption(
            'Shows which Dimensions publication IDs were matched to each VAMC. '
            'Use this to verify the matching logic or investigate unexpected counts.'
        )
        for (fy_year, q) in all_quarters:
            label = get_quarter_label(fy_year, q)
            st.markdown(f'**{label}**')
            quarter_diag = diagnostics.get((fy_year, q), {})

            diag_rows = []
            for vamc_name, info in quarter_diag.items():
                diag_rows.append({
                    'VAMC': vamc_name,
                    'PT Count': info['pt_count'],
                    'DIM Count': info['dim_count'],
                    'Matched Pub IDs (sample)': ', '.join(info['matched_pub_ids'][:5])
                    + ('…' if len(info['matched_pub_ids']) > 5 else ''),
                })
            if diag_rows:
                st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True)

    # ── Data preview expanders ────────────────────────────────────────────────
    with st.expander('👁  Preview – PubTracker raw data'):
        st.caption(f'{len(pt_raw)} total rows loaded')
        st.dataframe(pt_raw.head(50), use_container_width=True, hide_index=True)

    with st.expander('👁  Preview – Dimensions raw data'):
        st.caption(f'{len(dim_raw)} total rows loaded (after header skip)')
        st.dataframe(dim_raw.head(50), use_container_width=True, hide_index=True)
