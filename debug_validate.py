#!/usr/bin/env python3
"""
Validate: Run compliance calc with no Dimensions date filter, compare to manual output
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
from processors.pubtracker_processor import process_pubtracker
from processors.dimensions_processor import read_dimensions_df, process_dimensions
from processors.compliance_calculator import calculate_compliance

print("Loading files...")
pt_df = pd.read_csv("2026 PubTracker report as of May.csv")
dim_bytes = open("Dimensions-for-Veterans-Affairs-Publication-2026-06-11_19-02-02.csv", 'rb').read()
manual_df = pd.read_csv("PubTracker compliance running figures 2026.csv")

print(f"PubTracker: {len(pt_df)} rows")
dim_df = read_dimensions_df(dim_bytes)
print(f"Dimensions: {len(dim_df)} rows after header skip")

# Process PubTracker using Date Created (default)
pt_counts, pt_info = process_pubtracker(pt_df)
print(f"PubTracker counts: {pt_info}")
print(f"Quarters found: {list(pt_counts.keys())}")

# Process Dimensions (no date filter)
pub_list, date_info = process_dimensions(dim_df)
print(f"Dimensions pub_list: {len(pub_list)} records")

# Calculate compliance
result_df, report_text, all_quarters, diagnostics = calculate_compliance(pt_counts, pub_list)

# Compare to manual output
print("\n" + "=" * 80)
print("COMPARISON: APP OUTPUT vs MANUAL OUTPUT")
print("=" * 80)

total_row = result_df[result_df['VAMC'] == 'TOTAL'].iloc[0]
manual_total = manual_df[manual_df['VAMC'] == 'TOTAL'].iloc[0]

for q_key in all_quarters:
    fy, q = q_key
    label = f"FY{str(fy)[2:]} Q{q}"
    
    app_pt  = total_row.get(f'{label} PubTracker Count', 'N/A')
    app_dim = total_row.get(f'{label} Dimensions Count', 'N/A')
    app_pct = total_row.get(f'{label} % Entered', 'N/A')
    
    man_pt  = manual_total.get(f'{label} PubTracker Count', 'N/A')
    man_dim = manual_total.get(f'{label} Dimensions Count', 'N/A')
    man_pct = manual_total.get(f'FY26 Q2\n% Entered', manual_total.get(f'{label}\n% Entered', 'N/A'))
    
    print(f"\n{label}:")
    print(f"  PubTracker:  app={app_pt}   manual={man_pt}")
    print(f"  Dimensions:  app={app_dim}  manual={man_dim}")

# Also compare some specific VAMCs
print("\n\nSpot-checking VAMCs:")
vamc_checks = ['Philadelphia VA Medical Center', 'Minneapolis VA Health Care System; Minneapolis VA Medical Center',
               'VA Ann Arbor Healthcare System; Ann Arbor VA Medical Center',
               'Durham VA Medical Center; Durham VA Health Care System']
               
for vamc_name in vamc_checks:
    app_row = result_df[result_df['VAMC'] == vamc_name]
    man_row = manual_df[manual_df['VAMC'] == vamc_name]
    
    if not app_row.empty and not man_row.empty:
        for q_key in all_quarters:
            fy, q = q_key
            label = f"FY{str(fy)[2:]} Q{q}"
            app_pt = app_row.iloc[0].get(f'{label} PubTracker Count', '?')
            app_dim = app_row.iloc[0].get(f'{label} Dimensions Count', '?')
            man_pt = man_row.iloc[0].get(f'{label} PubTracker Count', '?')
            man_dim = man_row.iloc[0].get(f'{label} Dimensions Count', '?')
            print(f"\n  {vamc_name[:50]}")
            print(f"    PT: app={app_pt} manual={man_pt}  |  DIM: app={app_dim} manual={man_dim}")
    else:
        print(f"\n  {vamc_name[:50]}: not found in one of the outputs")
