import pandas as pd
from datetime import datetime


def get_fy_quarter(date):
    """Return (fy_year, quarter) for a given date using VA fiscal year."""
    month = date.month
    year = date.year
    if month >= 10:       # Oct–Dec → FY Q1 of next year
        return year + 1, 1
    elif month <= 3:      # Jan–Mar → FY Q2
        return year, 2
    elif month <= 6:      # Apr–Jun → FY Q3
        return year, 3
    else:                 # Jul–Sep → FY Q4
        return year, 4


def get_quarter_label(fy_year, quarter):
    return f"FY{str(fy_year)[2:]} Q{quarter}"


def get_quarter_date_range(fy_year, quarter):
    """Return (start_date, end_date) for the given VA fiscal year quarter."""
    if quarter == 1:
        return datetime(fy_year - 1, 10, 1), datetime(fy_year - 1, 12, 31)
    elif quarter == 2:
        return datetime(fy_year, 1, 1), datetime(fy_year, 3, 31)
    elif quarter == 3:
        return datetime(fy_year, 4, 1), datetime(fy_year, 6, 30)
    else:
        return datetime(fy_year, 7, 1), datetime(fy_year, 9, 30)


def process_pubtracker(df, include_presentations=False):
    """
    Process a PubTracker DataFrame.

    Filters to publication-type rows only (and optionally presentations), groups
    by fiscal year quarter using the 'Date Created' column, and counts
    submissions per POC Medical Center Number.

    Returns:
        dict: {(fy_year, quarter): {station_no_str: count}}
        dict: info – {'excluded_types': Counter, 'total_kept': int}
    """
    from collections import Counter

    # Handle the source system typo "Submittion Type"
    type_col = next(
        (c for c in df.columns if 'submission' in c.lower() or 'submittion' in c.lower()),
        None,
    )
    if type_col is None:
        raise ValueError(
            "Could not find a submission type column in the PubTracker file. "
            "Expected 'Submittion Type' or 'Submission Type'."
        )

    allowed = {'publication'}
    if include_presentations:
        allowed.add('presentation')

    mask = df[type_col].str.strip().str.lower().isin(allowed)
    excluded = Counter(df.loc[~mask, type_col].str.strip().str.lower().tolist())

    df = df[mask].copy()

    # Parse Date Created
    df['_date'] = pd.to_datetime(df['Date Created'], errors='coerce')
    df = df.dropna(subset=['_date'])

    info = {'excluded_types': excluded, 'total_kept': len(df)}

    if df.empty:
        return {}, info

    # Assign fiscal quarter
    df['_fy_quarter'] = df['_date'].apply(get_fy_quarter)

    # Count by quarter and station number
    result = {}
    for quarter_key, group in df.groupby('_fy_quarter'):
        counts = (
            group['POC Medical Center Number']
            .astype(str)
            .str.strip()
            .value_counts()
            .to_dict()
        )
        result[quarter_key] = counts

    return result, info
