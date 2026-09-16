#!/usr/bin/env python3
"""
Debug: Show exact quarter distribution in both files
"""
import pandas as pd
import io

def get_fy_quarter(date):
    if pd.isna(date):
        return None
    m = date.month
    y = date.year
    if m >= 10: return f"FY{y+1} Q1"
    if m <= 3:  return f"FY{y} Q2"
    if m <= 6:  return f"FY{y} Q3"
    return f"FY{y} Q4"

print("=" * 80)
print("PUBTRACKER QUARTERS")
print("=" * 80)

pt_df = pd.read_csv("2026 PubTracker report as of May.csv")
pt_df['PublDate'] = pd.to_datetime(pt_df['Publication Date'], errors='coerce')
pt_df['_quarter'] = pt_df['PublDate'].apply(get_fy_quarter)

print("\nQuarters in PubTracker (by Publication Date):")
q_dist = pt_df['_quarter'].value_counts().sort_index()
for quarter, count in q_dist.items():
    if pd.notna(quarter):
        print(f"  {quarter}: {count} records")

print("\n" + "=" * 80)
print("DIMENSIONS QUARTERS")
print("=" * 80)

# Read Dimensions file with proper header skip
with open("Dimensions-for-Veterans-Affairs-Publication-2026-06-11_19-02-02.csv", 'r', encoding='utf-8-sig', errors='replace') as f:
    lines = f.readlines()

header_idx = None
for i, line in enumerate(lines[:20]):
    if 'Rank' in line and 'Publication ID' in line and 'DOI' in line:
        header_idx = i
        break

remaining = ''.join(lines[header_idx:])
dim_df = pd.read_csv(io.StringIO(remaining))

# Check each date column
for date_col in ['Publication date', 'Publication date (online)', 'Publication date (print)']:
    if date_col in dim_df.columns:
        print(f"\nQuarters in Dimensions (by '{date_col}'):")
        dim_df[f'{date_col}_parsed'] = pd.to_datetime(dim_df[date_col], errors='coerce')
        dim_df[f'{date_col}_quarter'] = dim_df[f'{date_col}_parsed'].apply(get_fy_quarter)
        
        q_dist = dim_df[f'{date_col}_quarter'].value_counts().sort_index()
        for quarter, count in q_dist.items():
            if pd.notna(quarter):
                print(f"  {quarter}: {count} records")
        
        # Show date range
        min_date = dim_df[f'{date_col}_parsed'].min()
        max_date = dim_df[f'{date_col}_parsed'].max()
        if pd.notna(min_date):
            print(f"  Date range: {min_date.date()} to {max_date.date()}")

print("\n" + "=" * 80)
print("MANUAL OUTPUT EXPECTATIONS")
print("=" * 80)

manual_df = pd.read_csv("PubTracker compliance running figures 2026.csv")
print(f"\nManual output shows FY26 Q2 compliance")
print(f"  Total PubTracker Q2: {manual_df[manual_df['VAMC'] == 'TOTAL']['FY26 Q2 PubTracker Count'].values[0]}")
print(f"  Total Dimensions Q2: {manual_df[manual_df['VAMC'] == 'TOTAL']['FY26 Q2 Dimensions Count'].values[0]}")

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)
print("\n⚠️  The files DON'T OVERLAP:")
print("   - PubTracker has Q2 (Jan-Mar 2026) publications")
print("   - Dimensions has Q3-Q4 (Jun-Dec 2026) publications")
print("\nTo get matching data, you need EITHER:")
print("   1. A Q2 Dimensions file (Jan-Mar 2026)")
print("   2. A Q3+ PubTracker file (Apr-Dec 2026)")

