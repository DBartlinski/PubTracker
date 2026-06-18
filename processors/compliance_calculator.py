import os
import re
import pandas as pd


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def load_vamc_reference():
    """Load the canonical VAMC reference list from data/vamc_reference.csv."""
    ref_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'vamc_reference.csv')
    df = pd.read_csv(ref_path, dtype=str)
    # Deduplicate – if the CSV was accidentally doubled, keep first occurrence (new rows with alt codes)
    df = df.drop_duplicates(subset='vamc_display', keep='first').reset_index(drop=True)
    # Normalise boolean column
    df['not_in_dimensions'] = df['not_in_dimensions'].str.strip().str.lower() == 'true'
    return df


# ---------------------------------------------------------------------------
# Helper: station numbers
# ---------------------------------------------------------------------------

def get_station_numbers(station_str, alt_station_str=None):
    """
    Parse station-number field(s) that may contain multiple values separated
    by commas or semicolons.  If alt_station_str is also provided (from the
    alt_station_nos column) its values are merged in.

    Returns a set of stripped strings (deduped).
    """
    results = set()
    for s in [station_str, alt_station_str]:
        if s and not pd.isna(s) and str(s).strip() not in ('', 'nan'):
            for part in re.split(r'[,;]', str(s)):
                p = part.strip()
                if p:
                    results.add(p)
    return results


# ---------------------------------------------------------------------------
# Helper: Dimensions search terms
# ---------------------------------------------------------------------------

def get_search_terms(vamc_display):
    """
    Extract clean search terms from a VAMC display name string.

    - Splits on ';' to get individual centre names
    - Strips the '(Not in VA Dimensions)' marker
    - Strips trailing parenthetical location notes, e.g. '(Togus, ME)',
      '(includes Brooklyn and Manhattan)', '(Wichita, KS)'
      while preserving mid-name parentheticals like '(Sonny)' in
      'G.V. (Sonny) Montgomery VA Medical Center'
    """
    if not vamc_display or pd.isna(vamc_display):
        return []

    parts = str(vamc_display).split(';')
    terms = []
    for part in parts:
        cleaned = part.strip()
        # Remove the not-in-dimensions annotation
        cleaned = re.sub(r'\s*\(Not in VA Dimensions\)\s*', '', cleaned, flags=re.IGNORECASE)
        # Remove a trailing parenthetical (location / AKA / includes info)
        cleaned = re.sub(r'\s+\([^()]+\)\s*$', '', cleaned).strip()
        if cleaned:
            terms.append(cleaned)
    return terms


# ---------------------------------------------------------------------------
# Counting helpers
# ---------------------------------------------------------------------------

def count_pubtracker_for_vamc(station_str, alt_station_str, quarter_station_counts):
    """Sum PubTracker submission counts across all station numbers (primary + alternate) for a VAMC."""
    return sum(
        quarter_station_counts.get(s, 0)
        for s in get_station_numbers(station_str, alt_station_str)
    )


def count_dimensions_for_vamc(vamc_display, not_in_dimensions, quarter_pub_list):
    """
    Count Dimensions publications attributed to a VAMC.

    Each publication is counted at most once per VAMC.
    Matching uses case-insensitive substring search: a publication is matched
    if any search term appears as a substring of any of its Research
    Organisation names, or vice-versa.

    Returns (count, list_of_matched_pub_ids) for diagnostic purposes.
    """
    if not_in_dimensions:
        return 0, []

    search_terms = get_search_terms(vamc_display)
    if not search_terms:
        return 0, []

    terms_lower = [t.lower() for t in search_terms]
    matched_ids = []

    for pub_id, orgs in quarter_pub_list:
        orgs_lower = [o.lower() for o in orgs]
        for term in terms_lower:
            if any(term in org or org in term for org in orgs_lower):
                matched_ids.append(pub_id)
                break  # count each publication only once per VAMC

    return len(matched_ids), matched_ids


# ---------------------------------------------------------------------------
# Main compliance calculation
# ---------------------------------------------------------------------------

def calculate_compliance(pt_counts, dim_pub_list, vamc_ref=None):
    """
    Merge PubTracker and Dimensions counts and produce the compliance table.

    Parameters
    ----------
    pt_counts    : dict  {(fy_year, q): {station_no_str: count}}
    dim_pub_list : list  [(pub_id, [org_name, ...])]  – all Dimensions records
                   (assumed to be pre-filtered by the user to the quarter of interest)
    vamc_ref     : DataFrame or None (loaded from file if None)

    Returns
    -------
    result_df   : DataFrame  – compliance table ready for download
    report_text : str        – human-readable summary report
    all_quarters: list       – sorted [(fy_year, q), ...] from PubTracker
    diagnostics : dict       – per-quarter per-vamc diagnostic info
    """
    if vamc_ref is None:
        vamc_ref = load_vamc_reference()

    all_quarters = sorted(pt_counts.keys())

    rows = []
    diagnostics = {q: {} for q in all_quarters}

    for _, ref_row in vamc_ref.iterrows():
        vamc_display = str(ref_row['vamc_display'])
        station_no = str(ref_row.get('station_no', '')) if not pd.isna(ref_row.get('station_no', '')) else ''
        alt_station_no = str(ref_row.get('alt_station_nos', '')) if 'alt_station_nos' in ref_row and not pd.isna(ref_row.get('alt_station_nos', '')) else ''
        va_funded = str(ref_row.get('va_funded', '')) if not pd.isna(ref_row.get('va_funded', '')) else ''
        not_in_dim = bool(ref_row['not_in_dimensions'])

        row = {
            'VAMC': vamc_display,
            'Station No.': station_no,
            'VA Funded': va_funded if va_funded != 'nan' else '',
        }

        # Pre-compute Dimensions count once (same pool used for all quarters)
        dim_count, matched_ids = count_dimensions_for_vamc(vamc_display, not_in_dim, dim_pub_list)

        for quarter_key in all_quarters:
            fy_year, q = quarter_key
            label = f"FY{str(fy_year)[2:]} Q{q}"

            # PubTracker count (uses both primary and alternate station numbers)
            pt_q = pt_counts.get(quarter_key, {})
            pt_count = count_pubtracker_for_vamc(station_no, alt_station_no, pt_q)

            # Store diagnostics
            diagnostics[quarter_key][vamc_display] = {
                'pt_count': pt_count,
                'dim_count': dim_count,
                'matched_pub_ids': matched_ids,
            }

            # Percentage
            if not_in_dim:
                pct = '100%'
            elif pt_count == 0 and dim_count == 0:
                pct = '100%'
            elif dim_count == 0:
                pct = ''
            else:
                pct = f"{round(pt_count / dim_count * 100)}%"

            row[f'{label} PubTracker Count'] = pt_count
            row[f'{label} Dimensions Count'] = dim_count
            row[f'{label} % Entered'] = pct

        rows.append(row)

    # TOTAL row
    total_row = {'VAMC': 'TOTAL', 'Station No.': '', 'VA Funded': ''}
    for quarter_key in all_quarters:
        fy_year, q = quarter_key
        label = f"FY{str(fy_year)[2:]} Q{q}"
        total_pt = sum(r.get(f'{label} PubTracker Count', 0) for r in rows)
        total_dim = sum(r.get(f'{label} Dimensions Count', 0) for r in rows)
        total_pct = f"{round(total_pt / total_dim * 100)}%" if total_dim > 0 else ''
        total_row[f'{label} PubTracker Count'] = total_pt
        total_row[f'{label} Dimensions Count'] = total_dim
        total_row[f'{label} % Entered'] = total_pct
    rows.append(total_row)

    result_df = pd.DataFrame(rows)
    report_text = _generate_report(result_df, all_quarters, pt_counts)

    return result_df, report_text, all_quarters, diagnostics


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def _generate_report(result_df, quarters, pt_counts):
    lines = [
        '=' * 70,
        'PUBTRACKER COMPLIANCE REPORT',
        '=' * 70,
    ]

    data_rows = result_df[result_df['VAMC'] != 'TOTAL']
    total_rows = result_df[result_df['VAMC'] == 'TOTAL']

    for (fy_year, q) in quarters:
        label = f"FY{str(fy_year)[2:]} Q{q}"
        pt_col  = f'{label} PubTracker Count'
        dim_col = f'{label} Dimensions Count'
        pct_col = f'{label} % Entered'

        lines += ['', f'{label} SUMMARY', '-' * 40]

        if not total_rows.empty:
            t = total_rows.iloc[0]
            lines.append(f"  Total PubTracker submissions : {t[pt_col]}")
            lines.append(f"  Total Dimensions publications: {t[dim_col]}")
            lines.append(f"  Overall % Entered            : {t[pct_col]}")

        # Top 10 by PubTracker count
        lines.append(f'\nTop 10 VAMCs by PubTracker submissions:')
        top10 = data_rows.nlargest(10, pt_col)
        for _, row in top10.iterrows():
            name = row['VAMC'][:52]
            lines.append(f"  {name:<52} PT:{row[pt_col]:>5}  DIM:{row[dim_col]:>5}  {str(row[pct_col]):>6}")

        # Zero PubTracker submissions (with Dimensions data present)
        zero_with_dim = data_rows[(data_rows[pt_col] == 0) & (data_rows[dim_col] > 0)]
        if not zero_with_dim.empty:
            lines.append(f'\nVAMCs with 0 PubTracker submissions but Dimensions data exists:')
            for _, row in zero_with_dim.iterrows():
                lines.append(f"  {row['VAMC'][:60]}  (DIM: {row[dim_col]})")

        # Data quality flags: PubTracker > 1.5× Dimensions
        high = data_rows[(data_rows[pt_col] > data_rows[dim_col] * 1.5) & (data_rows[dim_col] > 0)]
        if not high.empty:
            lines.append(f'\nData quality – PubTracker > 1.5× Dimensions (review recommended):')
            for _, row in high.iterrows():
                lines.append(f"  {row['VAMC'][:52]}  PT:{row[pt_col]}  DIM:{row[dim_col]}  {row[pct_col]}")

        # Unmatched station numbers in PubTracker
        pt_q = pt_counts.get((fy_year, q), {})
        if pt_q:
            ref = load_vamc_reference()
            known_stations = set()
            for _, r in ref.iterrows():
                known_stations.update(
                    get_station_numbers(
                        str(r.get('station_no', '')),
                        str(r.get('alt_station_nos', '')) if 'alt_station_nos' in r else None,
                    )
                )
            unmatched = {s: c for s, c in pt_q.items() if s not in known_stations and s != 'nan'}
            if unmatched:
                lines.append(f'\nPubTracker station numbers not in VAMC reference (submissions unattributed):')
                for s, c in sorted(unmatched.items(), key=lambda x: -x[1]):
                    lines.append(f"  Station {s}: {c} submission(s)")

    lines += ['', '=' * 70]
    return '\n'.join(lines)
