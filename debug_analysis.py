#!/usr/bin/env python3
"""
Debug analysis: Compare actual data files with manual output expectations
"""
import pandas as pd
from datetime import datetime
from collections import Counter

# Load files
pubtracker_file = "2026 PubTracker report as of May.csv"
dimensions_file = "Dimensions-for-Veterans-Affairs-Publication-2026-06-11_19-02-02.csv"
manual_output_file = "PubTracker compliance running figures 2026.csv"

print("=" * 80)
print("PUBTRACKER ANALYSIS")
print("=" * 80)

pt_df = pd.read_csv(pubtracker_file)
print(f"\nTotal PubTracker records: {len(pt_df)}")
print(f"\nColumn names: {list(pt_df.columns)}")

# Check for date column
date_cols = [c for c in pt_df.columns if 'date' in c.lower()]
print(f"\nDate columns found: {date_cols}")

# Look at actual date values
if 'Publication Date' in pt_df.columns:
    print(f"\nSample Publication Date values:")
    print(pt_df['Publication Date'].head(10))
    
    # Parse dates
    pt_df['_date_parsed'] = pd.to_datetime(pt_df['Publication Date'], errors='coerce')
    print(f"\nDates parsed: {pt_df['_date_parsed'].notna().sum()} out of {len(pt_df)}")
    
    # Group by month
    pt_df['_month'] = pt_df['_date_parsed'].dt.to_period('M')
    print(f"\nRecords by month:")
    print(pt_df['_month'].value_counts().sort_index())
    
    # Determine fiscal quarter
    def get_fy_quarter(date):
        if pd.isna(date):
            return None
        m = date.month
        y = date.year
        if m >= 10: return f"FY{y+1} Q1"
        if m <= 3:  return f"FY{y} Q2"
        if m <= 6:  return f"FY{y} Q3"
        return f"FY{y} Q4"
    
    pt_df['_quarter'] = pt_df['_date_parsed'].apply(get_fy_quarter)
    print(f"\nRecords by quarter:")
    print(pt_df['_quarter'].value_counts())

# Check submission types
print(f"\nSubmission type distribution:")
print(pt_df['Submittion Type'].value_counts())

# Check POC Medical Center
print(f"\nUnique POC Medical Center Numbers: {pt_df['POC Medical Center Number'].nunique()}")
print(f"\nTop centers by record count:")
print(pt_df['POC Medical Center Number'].value_counts().head(10))

print("\n" + "=" * 80)
print("DIMENSIONS ANALYSIS")
print("=" * 80)

# Skip metadata rows in Dimensions file
with open(dimensions_file, 'r', encoding='utf-8-sig', errors='replace') as f:
    lines = f.readlines()
    header_idx = None
    for i, line in enumerate(lines[:30]):
        if 'Rank' in line and 'Publication ID' in line and 'DOI' in line:
            header_idx = i
            break

print(f"\nMetadata rows to skip: {header_idx}")

dim_df = pd.read_csv(dimensions_file, skiprows=header_idx)
print(f"\nTotal Dimensions records: {len(dim_df)}")
print(f"\nColumn names: {list(dim_df.columns)}")

# Check date columns
date_cols = [c for c in dim_df.columns if 'date' in c.lower()]
print(f"\nDate columns found: {date_cols}")

# Check for data in each date column
for col in date_cols:
    non_null = dim_df[col].notna().sum()
    print(f"\n{col}: {non_null} non-null values")
    if non_null > 0:
        print(f"  Sample values: {dim_df[col].dropna().head(5).tolist()}")

# Parse all date columns
for col in date_cols:
    dim_df[f'{col}_parsed'] = pd.to_datetime(dim_df[col], errors='coerce')

# Check organization column
org_cols = [c for c in dim_df.columns if 'research organizations' in c.lower()]
print(f"\nOrganization columns: {org_cols}")
if org_cols:
    org_col = org_cols[0]
    print(f"\nSample organizations (first 5 records with data):")
    sample_orgs = dim_df[org_col].dropna().head(5)
    for i, org in enumerate(sample_orgs, 1):
        print(f"  {i}. {org[:100]}...")

print("\n" + "=" * 80)
print("MANUAL OUTPUT ANALYSIS")
print("=" * 80)

manual_df = pd.read_csv(manual_output_file)
print(f"\nTotal rows in manual output: {len(manual_df)}")
print(f"\nColumns: {list(manual_df.columns)}")

# Find rows with Dimensions data
rows_with_dim = manual_df[manual_df['FY26 Q2 Dimensions Count'] > 0]
print(f"\nRows with FY26 Q2 Dimensions count > 0: {len(rows_with_dim)}")
print(f"\nTotal Dimensions count in manual output: {manual_df['FY26 Q2 Dimensions Count'].sum()}")

# Show some examples
print(f"\nTop 10 VAMCs by Dimensions count:")
print(rows_with_dim.nlargest(10, 'FY26 Q2 Dimensions Count')[['VAMC', 'FY26 Q2 Dimensions Count']])

# Check which VAMCs appear in Dimensions
print(f"\nVAMCs with data in manual output:")
print(manual_df[manual_df['FY26 Q2 Dimensions Count'] > 0]['VAMC'].tolist()[:10])

print("\n" + "=" * 80)
print("ORGANIZATION MATCHING CHECK")
print("=" * 80)

# Load VAMC reference
vamc_ref = pd.read_csv("data/vamc_reference.csv")
print(f"\nTotal VAMCs in reference: {len(vamc_ref)}")

# Extract org names from Dimensions
if org_cols:
    org_col = org_cols[0]
    all_orgs = set()
    for org_list in dim_df[org_col].dropna():
        orgs = [o.strip() for o in str(org_list).split(';')]
        all_orgs.update(orgs)
    
    print(f"\nUnique organizations in Dimensions: {len(all_orgs)}")
    print(f"\nSample organizations from Dimensions:")
    for org in list(all_orgs)[:10]:
        print(f"  - {org}")
    
    # Check for VA matches
    va_orgs = [o for o in all_orgs if 'va' in o.lower()]
    print(f"\nOrganizations containing 'VA': {len(va_orgs)}")
    print("\nSample VA organizations:")
    for org in va_orgs[:10]:
        print(f"  - {org}")

print("\n" + "=" * 80)
