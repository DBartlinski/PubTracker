# Repeatable VA Dimensions Export

Run `run_dimensions_export.bat` to export every publication under the Veterans Health Administration research-organization filter.

The utility opens a visible Chromium window. Sign in to VA Dimensions in that window when prompted. It then:

1. Confirms the unfiltered publication count.
2. Splits the result into disjoint publication-year batches.
3. Refuses to continue if any batch exceeds Dimensions' 500-record limit or the batch counts do not equal the full result count.
4. Submits full-record CSV exports and waits for them in Export Center.
5. Validates every downloaded batch against its expected count.
6. Merges all columns and deduplicates by `Publication ID`.

The final file is `output/dimensions_batches/dimensions_merged.csv`.

An interrupted run can be resumed by running the batch file again. After a run completes, the next invocation archives that run and starts a fresh export. Browser login state is retained locally in `.dimensions-browser-profile`, which is excluded from Git.

## Publications dashboard

Run `run_dashboard.bat` to open the local Streamlit dashboard. It reads the latest `dimensions_merged.csv` and provides:

- VA fiscal-year and quarter filters
- Calendar year, document type, open access, journal, research area, and country filters
- Record search and filtered CSV download
- VAMC facility summaries with the organization name and search term that produced each match
- Journal, citation, RCR/FCR, and research-area views

The dashboard preserves all source records but defaults to SOP-eligible publications. Conference abstracts and correction errata can be restored with the sidebar toggle.

Facility attribution is a transparent first-pass name match against `data/vamc_reference.csv`. The generic station 101 VHA/VA Central Office row is excluded because it would match every record. A publication may map to multiple local facilities, and unmatched records remain visible. These matches are evidence for review, not final compliance determinations.

Fiscal periods use publication date in this order: print, online, then general date. Records with only a year cannot be assigned reliably across the October fiscal-year boundary and are labeled unavailable.