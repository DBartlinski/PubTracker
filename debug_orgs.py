#!/usr/bin/env python3
"""
Debug: Check what organizations are in the Dimensions file and if they match VAMCs
"""
import pandas as pd
import io

dimensions_file = "Dimensions-for-Veterans-Affairs-Publication-2026-06-11_19-02-02.csv"

# Read with proper header skip
with open(dimensions_file, 'r', encoding='utf-8-sig', errors='replace') as f:
    lines = f.readlines()

# Find the actual header row
header_idx = None
for i, line in enumerate(lines[:20]):
    if 'Rank' in line and 'Publication ID' in line and 'DOI' in line:
        header_idx = i
        break

print(f"Header found at line index: {header_idx}")
print(f"\nHeader line content:")
print(lines[header_idx][:200])

# Read the CSV correctly
remaining = ''.join(lines[header_idx:])
df = pd.read_csv(io.StringIO(remaining))

print(f"\n✓ Successfully parsed {len(df)} records")
print(f"\nColumn names:")
for i, col in enumerate(df.columns):
    print(f"  {i}: {col}")

# Find the organization column
org_cols = [c for c in df.columns if 'research organizations' in c.lower()]
if org_cols:
    org_col = org_cols[0]
    print(f"\n✓ Found organization column: '{org_col}'")
    
    # Get all unique organizations
    all_orgs = set()
    org_counts = {}
    for org_list in df[org_col].dropna():
        orgs = [o.strip() for o in str(org_list).split(';') if o.strip()]
        for org in orgs:
            all_orgs.add(org)
            org_counts[org] = org_counts.get(org, 0) + 1
    
    print(f"\n✓ Found {len(all_orgs)} unique organizations")
    print(f"\nTop 20 organizations by frequency:")
    sorted_orgs = sorted(org_counts.items(), key=lambda x: x[1], reverse=True)
    for org, count in sorted_orgs[:20]:
        print(f"  {count:4d}x  {org[:70]}")
    
    # Check for VA matches
    va_orgs = [org for org in all_orgs if 'va' in org.lower() or 'veterans' in org.lower()]
    print(f"\n✓ Found {len(va_orgs)} VA-related organizations:")
    for org in sorted(va_orgs)[:20]:
        print(f"  - {org}")
else:
    print(f"\n✗ Organization column not found!")
    print(f"Available columns with 'research' or 'organization' in name:")
    for col in df.columns:
        if 'research' in col.lower() or 'organization' in col.lower():
            print(f"  - {col}")

# Check date columns
date_cols = [c for c in df.columns if 'date' in c.lower()]
print(f"\n✓ Found {len(date_cols)} date columns:")
for col in date_cols:
    non_null = df[col].notna().sum()
    print(f"  - {col}: {non_null} records have data")
    if non_null > 0:
        print(f"    Sample: {df[col].dropna().head(3).tolist()}")

# Check if any have Q2 dates (Jan-Mar)
if org_cols and date_cols:
    org_col = org_cols[0]
    q2_count = 0
    
    for date_col in date_cols:
        df[f'{date_col}_parsed'] = pd.to_datetime(df[date_col], errors='coerce')
        
        # Check for Q2 dates (months 1-3)
        df[f'{date_col}_month'] = df[f'{date_col}_parsed'].dt.month
        q2_in_col = df[df[f'{date_col}_month'].isin([1, 2, 3])].shape[0]
        print(f"\n  {date_col}: {q2_in_col} records in Q2 months (Jan-Mar)")

print("\n" + "=" * 80)
