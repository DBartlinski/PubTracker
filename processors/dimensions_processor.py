import pandas as pd
import io

from processors.pubtracker_processor import get_fy_quarter

# Document types to exclude per the SOP
EXCLUDED_DOC_TYPES = {'conference abstract', 'correction erratum'}


def _parse_pub_date(date_str):
    """
    Parse a Dimensions publication date string.
    Handles YYYY-MM-DD, YYYY-MM, YYYY, MM/DD/YYYY, and DD/MM/YYYY formats.
    Returns a pandas Timestamp or NaT.
    """
    if pd.isna(date_str) or str(date_str).strip() == '':
        return pd.NaT
    s = str(date_str).strip()
    
    # Try common formats in order
    for fmt in ('%Y-%m-%d', '%Y-%m', '%Y', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return pd.to_datetime(s, format=fmt)
        except ValueError:
            continue
    
    # Fallback: let pandas try to infer the format
    try:
        return pd.to_datetime(s, infer_datetime_format=True)
    except:
        return pd.NaT


def read_dimensions_df(raw_bytes):
    """
    Read Dimensions CSV bytes, automatically skipping the metadata header rows
    that Dimensions prepends to every export.

    The export always contains a copyright/metadata row before the real column
    headers.  This function locates the actual header row (the one containing
    'Rank', 'Publication ID', and 'DOI') regardless of how many lines precede
    it, then returns a DataFrame starting from that row.

    Handles UTF-8 BOM (common in Excel-saved CSVs) via 'utf-8-sig' decoding.
    """
    # utf-8-sig strips the BOM automatically if present
    content = raw_bytes.decode('utf-8-sig', errors='replace')
    lines = content.split('\n')

    # Find the actual header row: look for a line containing all three key tokens
    header_idx = None
    for i, line in enumerate(lines[:20]):
        stripped = line.strip('\r').strip()
        if 'Rank' in stripped and 'Publication ID' in stripped and 'DOI' in stripped:
            header_idx = i
            break

    if header_idx is None:
        # No Dimensions metadata prefix found – try reading the file directly
        df = pd.read_csv(io.StringIO(content))
        return df

    # Re-join from the header row onward and parse as a fresh CSV
    remaining = '\n'.join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(remaining))
    return df


def process_dimensions(df):
    """
    Process a Dimensions DataFrame (already read with header rows skipped).

    Per the SOP the user pre-filters the Dimensions export to the quarter of
    interest before uploading, so this function does NOT filter by date.
    It only excludes the disallowed document types and returns a flat list of
    (publication_id, [org_names]) tuples for every remaining row.

    The caller is responsible for assigning these publications to the correct
    fiscal-year quarter (inferred from the PubTracker data).

    Returns:
        list: [(pub_id_str, [org_name_str, ...])]
        dict: date_range_info – {'min_date': ..., 'max_date': ..., 'count': ...}
    """
    if 'Document Type' in df.columns:
        df = df[
            ~df['Document Type'].str.strip().str.lower().isin(EXCLUDED_DOC_TYPES)
        ].copy()

    org_col = next(
        (c for c in df.columns if 'research organizations' in c.lower() and 'standardized' in c.lower()),
        None,
    )
    if org_col is None:
        raise ValueError(
            "Could not find 'Research Organizations - standardized' column in Dimensions file. "
            "Ensure the file is a standard Dimensions XLSX/CSV export."
        )

    pub_id_col = 'Publication ID' if 'Publication ID' in df.columns else df.columns[1]

    # Find publication date columns (try print, online, and generic variants)
    pub_date_cols = [c for c in df.columns if 'publication date' in c.lower()]
    pub_date_print = next((c for c in pub_date_cols if 'print' in c.lower()), None)
    pub_date_online = next((c for c in pub_date_cols if 'online' in c.lower()), None)
    pub_date_generic = next(
        (c for c in pub_date_cols
         if 'online' not in c.lower() and 'print' not in c.lower()),
        None,
    )
    
    # Use whichever is available in priority order: generic > print > online
    pub_date_col = pub_date_generic or pub_date_print or pub_date_online

    # Helper: get the best available date from any of the columns
    def get_row_date(row):
        if pub_date_print:
            d = _parse_pub_date(row.get(pub_date_print))
            if not pd.isna(d):
                return d
        if pub_date_online:
            d = _parse_pub_date(row.get(pub_date_online))
            if not pd.isna(d):
                return d
        if pub_date_col:
            d = _parse_pub_date(row.get(pub_date_col))
            if not pd.isna(d):
                return d
        return pd.NaT

    # Collect date range info for UI display (informational only)
    date_info = {'min_date': None, 'max_date': None, 'count': len(df)}
    if pub_date_col or pub_date_print or pub_date_online:
        dates = df.apply(get_row_date, axis=1).dropna()
        if not dates.empty:
            date_info['min_date'] = dates.min()
            date_info['max_date'] = dates.max()

    pub_list = []
    for _, row in df.iterrows():
        pub_id = str(row.get(pub_id_col, ''))
        orgs_raw = str(row.get(org_col, ''))
        orgs = [o.strip() for o in orgs_raw.split(';') if o.strip() and orgs_raw != 'nan']
        pub_list.append((pub_id, orgs))

    return pub_list, date_info
