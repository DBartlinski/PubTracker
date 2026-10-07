import unittest

import pandas as pd

from processors.pubtracker_compliance import (
    REASON_UNDATED,
    UNATTRIBUTED,
    classify_pubtracker_rows,
    exclusion_reasons,
    facility_map,
    facility_rates,
    filter_fiscal_year,
    match_pubtracker_to_dimensions,
    match_to_pubtracker,
    matched_records_table,
    quarter_rates,
)


def pubs(rows):
    frame = pd.DataFrame(rows)
    frame["Canonical Date"] = pd.to_datetime(frame["Canonical Date"])
    return frame


def pubtracker(rows):
    frame = pd.DataFrame(rows)
    frame["_facilities"] = frame["_facilities"].map(frozenset)
    return frame


class ComplianceTests(unittest.TestCase):
    def test_fiscal_year_boundaries_and_exclusions(self):
        frame = pubs([
            {"Publication ID": "a", "Canonical Date": "2025-09-30", "Date Precision": "day", "SOP Eligible": True},
            {"Publication ID": "b", "Canonical Date": "2025-10-01", "Date Precision": "day", "SOP Eligible": True},
            {"Publication ID": "c", "Canonical Date": "2026-09-30", "Date Precision": "day", "SOP Eligible": True},
            {"Publication ID": "d", "Canonical Date": "2026-10-01", "Date Precision": "day", "SOP Eligible": True},
            {"Publication ID": "e", "Canonical Date": "2026-01-01", "Date Precision": "year", "SOP Eligible": True},
            {"Publication ID": "f", "Canonical Date": "2026-02-01", "Date Precision": "day", "SOP Eligible": False},
        ])
        scoped, stats = filter_fiscal_year(frame)
        self.assertEqual(sorted(scoped["Publication ID"]), ["b", "c"])
        self.assertEqual(stats["excluded_document_type"], 1)
        self.assertEqual(stats["excluded_undated_or_year_only"], 1)
        self.assertEqual(stats["excluded_out_of_range"], 2)

    def test_non_publication_types_are_excluded(self):
        rows = [
            {"Publication ID": pid, "Canonical Date": "2026-02-01", "Date Precision": "day",
             "SOP Eligible": True, "Publication Type": kind}
            for pid, kind in [("a", "Article"), ("b", "Preprint"), ("c", "Chapter"), ("d", "Proceeding"), ("e", None)]
        ]
        scoped, stats = filter_fiscal_year(pubs(rows))
        self.assertEqual(sorted(scoped["Publication ID"]), ["a", "e"])
        self.assertEqual(stats["excluded_publication_type"], 3)

    def test_exact_fuzzy_and_facility_gate(self):
        dimensions = pd.DataFrame([
            {"Publication ID": "p1", "Title": "Opioid Use among Veterans: a cohort study"},
            {"Publication ID": "p2", "Title": "Sleep apnea outcomes in older veterans"},
            {"Publication ID": "p3", "Title": "Sleep apnea outcomes in older veterans!"},
            {"Publication ID": "p4", "Title": "Entirely different topic"},
        ])
        facilities = {"p1": frozenset({"A"}), "p2": frozenset({"A"}), "p3": frozenset({"B"})}
        tracker = pubtracker([
            {"Record ID": "1", "Title": "Opioid use among veterans a cohort study", "POC Medical Center": "A",
             "_norm_title": "opioid use among veterans a cohort study", "_facilities": ["A"]},
            {"Record ID": "2", "Title": "Sleep apnea outcomes in older veteran", "POC Medical Center": "A",
             "_norm_title": "sleep apnea outcomes in older veteran", "_facilities": ["A"]},
        ])
        result = match_to_pubtracker(dimensions, facilities, tracker, threshold=90).set_index("Publication ID")
        self.assertEqual(result.loc["p1", "Match Type"], "Matched (exact)")
        self.assertEqual(result.loc["p2", "Match Type"], "Matched (fuzzy)")
        self.assertEqual(result.loc["p3", "Match Type"], "Missing")
        self.assertEqual(result.loc["p4", "Match Type"], "Missing")

        strict = match_to_pubtracker(dimensions, facilities, tracker, threshold=100).set_index("Publication ID")
        self.assertEqual(strict.loc["p2", "Match Type"], "Missing")

    def test_facility_rates_multi_facility_and_unattributed(self):
        results = pd.DataFrame({
            "Publication ID": ["p1", "p2", "p3"],
            "Match Type": ["Matched (exact)", "Missing", "Missing"],
        })
        facilities = {"p1": frozenset({"A", "B"}), "p2": frozenset({"A"})}
        rates = facility_rates(results, facilities).set_index("Facility")
        self.assertEqual(rates.loc["A", "Dimensions Records"], 2)
        self.assertEqual(rates.loc["A", "Submission Rate %"], 50.0)
        self.assertEqual(rates.loc["B", "Submission Rate %"], 100.0)
        self.assertEqual(rates.loc[UNATTRIBUTED, "Missing"], 1)

    def test_facility_map(self):
        matches = pd.DataFrame({"Publication ID": ["p1", "p1"], "Facility": ["A", "B"]})
        self.assertEqual(facility_map(matches)["p1"], frozenset({"A", "B"}))


def dimensions_set():
    return pubs([
        {"Publication ID": "d1", "Title": "Opioid use among veterans", "Canonical Date": "2026-02-15",
         "Date Precision": "day", "SOP Eligible": True, "Publication Type": "Article", "Fiscal Period": "FY26 Q2"},
        {"Publication ID": "d2", "Title": "Sleep apnea outcomes in older veterans", "Canonical Date": "2026-05-01",
         "Date Precision": "day", "SOP Eligible": True, "Publication Type": "Article", "Fiscal Period": "FY26 Q3"},
        {"Publication ID": "d3", "Title": "A preprint on hearing loss", "Canonical Date": "2026-03-01",
         "Date Precision": "day", "SOP Eligible": True, "Publication Type": "Preprint", "Fiscal Period": "FY26 Q2"},
        {"Publication ID": "d4", "Title": "Year only dated cohort", "Canonical Date": "2026-01-01",
         "Date Precision": "year", "SOP Eligible": True, "Publication Type": "Article", "Fiscal Period": "Unavailable"},
    ])


DIM_FACILITIES = {"d1": frozenset({"A"}), "d2": frozenset({"A"}), "d3": frozenset({"A"}), "d4": frozenset({"A"})}


def tracker_set():
    frame = pubtracker([
        {"Record ID": "1", "Title": "Opioid use among veterans", "POC Medical Center": "A",
         "Date Created": "2026-06-30", "Publication Date": "2025-12-01",
         "_norm_title": "opioid use among veterans", "_facilities": ["A"]},
        {"Record ID": "2", "Title": "Sleep apnea outcomes in older veteran", "POC Medical Center": "B",
         "Date Created": "2026-07-01", "Publication Date": None,
         "_norm_title": "sleep apnea outcomes in older veteran", "_facilities": ["B"]},
        {"Record ID": "3", "Title": "A preprint on hearing loss", "POC Medical Center": "A",
         "Date Created": "2026-04-01", "Publication Date": "2026-03-01",
         "_norm_title": "a preprint on hearing loss", "_facilities": ["A"]},
        {"Record ID": "4", "Title": "Year only dated cohort", "POC Medical Center": "A",
         "Date Created": "2026-02-01", "Publication Date": "2026-02-01",
         "_norm_title": "year only dated cohort", "_facilities": ["A"]},
    ])
    for column in ("Date Created", "Publication Date"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


class DimensionsToPubTrackerTests(unittest.TestCase):
    def setUp(self):
        self.dimensions = dimensions_set()
        self.tracker = tracker_set()
        self.scoped, self.stats = filter_fiscal_year(self.dimensions)
        self.results = match_to_pubtracker(self.scoped, DIM_FACILITIES, self.tracker)
        reasons = exclusion_reasons(self.dimensions)
        reverse = match_pubtracker_to_dimensions(self.tracker, self.dimensions, DIM_FACILITIES)
        self.pt_rows = classify_pubtracker_rows(
            reverse, dict(zip(self.dimensions["Publication ID"], reasons))
        ).set_index("Record ID")

    def test_exact_match_takes_dimensions_date(self):
        table = matched_records_table(self.results, self.scoped, self.tracker, DIM_FACILITIES).set_index("Publication ID")
        self.assertEqual(table.loc["d1", "Dimensions Date"], pd.Timestamp("2026-02-15"))
        self.assertEqual(table.loc["d1", "PubTracker Publication Date"], pd.Timestamp("2025-12-01"))
        self.assertEqual(table.loc["d1", "PubTracker Date Created"], pd.Timestamp("2026-06-30"))
        self.assertEqual(table.loc["d1", "Match Type"], "Matched (exact)")
        quarters = quarter_rates(self.results, self.scoped).set_index("Fiscal Period")
        self.assertEqual(quarters.loc["FY26 Q2", "In PubTracker"], 1)

    def test_fuzzy_match_rejected_when_facilities_disagree(self):
        result = self.results.set_index("Publication ID")
        self.assertEqual(result.loc["d2", "Match Type"], "Missing")
        self.assertEqual(self.pt_rows.loc["2", "Status"], "Exception")

    def test_year_only_date_excluded(self):
        self.assertNotIn("d4", set(self.scoped["Publication ID"]))
        self.assertEqual(self.stats["excluded_undated_or_year_only"], 1)
        self.assertEqual(self.pt_rows.loc["4", "Status"], "Matched but excluded")
        self.assertEqual(self.pt_rows.loc["4", "Exclusion Reason"], REASON_UNDATED)

    def test_pubtracker_record_matching_excluded_dimensions_record(self):
        self.assertEqual(self.pt_rows.loc["3", "Status"], "Matched but excluded")
        self.assertEqual(self.pt_rows.loc["3", "Dimensions Publication ID"], "d3")
        self.assertIn("Preprint", self.pt_rows.loc["3", "Exclusion Reason"])
        self.assertEqual(self.pt_rows.loc["1", "Status"], "Matched (eligible)")

    def test_unmatched_pubtracker_record_is_exception_with_original_dates(self):
        row = self.pt_rows.loc["2"]
        self.assertEqual(row["Dimensions Publication ID"], "")
        self.assertEqual(row["Date Created"], pd.Timestamp("2026-07-01"))
        self.assertTrue(pd.isna(row["Publication Date"]))

    def test_eligible_equals_found_plus_not_found(self):
        found = self.results["Match Type"].ne("Missing")
        self.assertEqual(len(self.results), self.stats["in_scope"])
        self.assertEqual(len(self.results), int(found.sum()) + int((~found).sum()))
        self.assertEqual((int(found.sum()), int((~found).sum())), (1, 1))


if __name__ == "__main__":
    unittest.main()
