"""
Detailed validation of dimensions_va_2025_2026_filtered CSV
"""
import sys
from pathlib import Path
from datetime import datetime, date
import pandas as pd
from collections import Counter

project_root = Path.cwd()
sys.path.insert(0, str(project_root))

from processors.dimensions_processor import read_dimensions_df
from processors.dashboard_data import derive_publication_date

def validate_csv():
    print("=" * 80)
    print("DETAILED VALIDATION REPORT")
    print("CSV File: output/dimensions_va_2025_2026/dimensions_va_2025_2026_filtered_2025-10-01_to_2026-09-30.csv")
    print("=" * 80)
    print()
    
    print("[STEP 1] Loading CSV file...")
    try:
        csv_path = project_root / "output/dimensions_va_2025_2026/dimensions_va_2025_2026_filtered_2025-10-01_to_2026-09-30.csv"
        df = read_dimensions_df(csv_path)
        print(f"✓ Successfully loaded CSV with {len(df)} rows and {len(df.columns)} columns")
        print(f"  Columns: {list(df.columns)}")
    except Exception as e:
        print(f"✗ ERROR loading CSV: {e}")
        import traceback
        traceback.print_exc()
        return
    print()
    
    min_expected = datetime(2025, 10, 1).date()
    max_expected = datetime(2026, 9, 30).date()
    print(f"Expected date range: {min_expected} to {max_expected}")
    print()
    
    print("[STEP 2] Deriving publication dates...")
    try:
        derived_dates = []
        date_errors = []
        
        for idx, row in df.iterrows():
            try:
                derived_date = derive_publication_date(row)
                derived_dates.append(derived_date)
            except Exception as e:
                date_errors.append((idx, row.get('Publication ID', 'UNKNOWN'), str(e)))
                derived_dates.append(None)
        
        df['derived_date'] = derived_dates
        
        if date_errors:
            print(f"⚠ {len(date_errors)} rows had errors deriving dates")
            for idx, pub_id, err in date_errors[:5]:
                print(f"    Row {idx}, PubID: {pub_id}, Error: {err}")
        else:
            print(f"✓ Successfully derived dates for all {len(df)} rows")
    except Exception as e:
        print(f"✗ ERROR deriving dates: {e}")
        import traceback
        traceback.print_exc()
        return
    print()
    
    print("[STEP 3] Verifying date range (2025-10-01 to 2026-09-30)...")
    valid_dates = df['derived_date'].dropna()
    out_of_range = []
    
    for idx, derived_date in enumerate(df['derived_date']):
        if pd.notna(derived_date):
            if isinstance(derived_date, datetime):
                d = derived_date.date()
            else:
                d = derived_date
            
            if d < min_expected or d > max_expected:
                pub_id = df.iloc[idx].get('Publication ID', 'UNKNOWN')
                out_of_range.append({
                    'index': idx,
                    'publication_id': pub_id,
                    'date': d
                })
    
    if out_of_range:
        print(f"✗ VIOLATIONS FOUND: {len(out_of_range)} dates are outside the expected range")
        for violation in out_of_range[:10]:
            print(f"  Index: {violation['index']}, PubID: {violation['publication_id']}, Date: {violation['date']}")
        if len(out_of_range) > 10:
            print(f"  ... and {len(out_of_range) - 10} more violations")
    else:
        print(f"✓ All {len(valid_dates)} valid dates are within the expected range")
    print()
    
    print("[STEP 4] Checking for duplicate Publication IDs...")
    if 'Publication ID' in df.columns:
        pub_ids = df['Publication ID'].dropna()
        id_counts = pub_ids.value_counts()
        duplicates = id_counts[id_counts > 1]
        
        if len(duplicates) > 0:
            print(f"✗ DUPLICATES FOUND: {len(duplicates)} Publication IDs appear more than once")
            for pub_id, count in duplicates.head(10).items():
                matching_rows = df[df['Publication ID'] == pub_id]
                dates_str = ", ".join(str(d)[:10] for d in matching_rows['derived_date'].values)
                print(f"  PubID: {pub_id}, Count: {count}, Dates: {dates_str}")
            if len(duplicates) > 10:
                print(f"  ... and {len(duplicates) - 10} more duplicates")
        else:
            print(f"✓ No duplicate Publication IDs found (all {len(pub_ids)} unique)")
    else:
        print("⚠ Publication ID column not found")
    print()
    
    print("[STEP 5] Checking for missing/null values in critical fields...")
    critical_fields = ['Publication ID', 'Title']
    date_fields = [col for col in df.columns if 'date' in col.lower() or 'year' in col.lower()]
    critical_fields.extend(date_fields)
    critical_fields = list(set(critical_fields))
    
    has_nulls = False
    for field in critical_fields:
        if field in df.columns:
            null_count = df[field].isna().sum()
            if null_count > 0:
                print(f"  ✗ {field}: {null_count} missing values ({100*null_count/len(df):.2f}%)")
                has_nulls = True
    
    if not has_nulls:
        print(f"✓ No missing values found in critical fields")
    print()
    
    print("[STEP 6] STATISTICS")
    print("-" * 80)
    print(f"Total records: {len(df)}")
    print()
    
    print("DATE DISTRIBUTION:")
    valid_dates_list = df['derived_date'].dropna()
    if len(valid_dates_list) > 0:
        valid_dates_list = [d.date() if isinstance(d, datetime) else d for d in valid_dates_list]
        earliest = min(valid_dates_list)
        latest = max(valid_dates_list)
        print(f"  Earliest date: {earliest}")
        print(f"  Latest date: {latest}")
        print()
        print("  Records by month:")
        month_counts = Counter()
        for d in valid_dates_list:
            month_key = d.strftime('%Y-%m')
            month_counts[month_key] += 1
        
        for month in sorted(month_counts.keys()):
            count = month_counts[month]
            print(f"    {month}: {count}")
    print()
    
    print("NULL VALUES BY FIELD:")
    null_summary = []
    for col in df.columns:
        null_count = df[col].isna().sum()
        if null_count > 0:
            null_summary.append((col, null_count))
    
    if null_summary:
        null_summary.sort(key=lambda x: x[1], reverse=True)
        for col, count in null_summary[:10]:
            print(f"  {col}: {count} ({100*count/len(df):.2f}%)")
        if len(null_summary) > 10:
            print(f"  ... and {len(null_summary) - 10} more columns with nulls")
    else:
        print("  No columns have null values")
    print()
    
    print("SAMPLE RECORDS:")
    print()
    
    if len(df) > 0:
        df_sorted = df.dropna(subset=['derived_date']).copy()
        if len(df_sorted) > 0:
            df_sorted = df_sorted.sort_values('derived_date')
            
            print("  BEGINNING OF DATE RANGE (earliest records):")
            for idx, (_, row) in enumerate(df_sorted.head(3).iterrows()):
                pub_id = row.get('Publication ID', 'N/A')
                title = str(row.get('Title', 'N/A'))[:60]
                date = row.get('derived_date', 'N/A')
                print(f"    [{idx+1}] PubID: {pub_id}, Date: {date}, Title: {title}...")
            print()
            
            print("  MIDDLE OF DATE RANGE (records around midpoint):")
            mid_idx = len(df_sorted) // 2
            for idx, (_, row) in enumerate(df_sorted.iloc[mid_idx:mid_idx+3].iterrows()):
                pub_id = row.get('Publication ID', 'N/A')
                title = str(row.get('Title', 'N/A'))[:60]
                date = row.get('derived_date', 'N/A')
                print(f"    [{idx+1}] PubID: {pub_id}, Date: {date}, Title: {title}...")
            print()
            
            print("  END OF DATE RANGE (latest records):")
            for idx, (_, row) in enumerate(df_sorted.tail(3).iterrows()):
                pub_id = row.get('Publication ID', 'N/A')
                title = str(row.get('Title', 'N/A'))[:60]
                date = row.get('derived_date', 'N/A')
                print(f"    [{idx+1}] PubID: {pub_id}, Date: {date}, Title: {title}...")
    print()
    
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    
    all_pass = True
    
    if out_of_range:
        print(f"✗ DATE RANGE: {len(out_of_range)} records outside expected range")
        all_pass = False
    else:
        print(f"✓ DATE RANGE: All dates within 2025-10-01 to 2026-09-30")
    
    dup_count = len(duplicates) if 'Publication ID' in df.columns else 0
    if dup_count > 0:
        print(f"✗ DUPLICATES: {dup_count} duplicate Publication IDs found")
        all_pass = False
    else:
        print(f"✓ DUPLICATES: No duplicate Publication IDs")
    
    if has_nulls:
        print(f"✗ NULL VALUES: Found in critical fields")
        all_pass = False
    else:
        print(f"✓ NULL VALUES: No nulls in critical fields")
    
    if date_errors:
        print(f"✗ DATE DERIVATION: {len(date_errors)} errors deriving dates")
        all_pass = False
    else:
        print(f"✓ DATE DERIVATION: All dates successfully derived")
    
    print()
    if all_pass:
        print("✓ ALL VALIDATION CHECKS PASSED")
    else:
        print("✗ VALIDATION FAILURES DETECTED - SEE DETAILS ABOVE")
    
    print("=" * 80)

if __name__ == '__main__':
    validate_csv()
