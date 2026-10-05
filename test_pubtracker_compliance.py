import unittest

import pandas as pd

from processors.pubtracker_compliance import (
    UNATTRIBUTED,
    facility_map,
    facility_rates,
    filter_fiscal_year,
    match_to_pubtracker,
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


if __name__ == "__main__":
    unittest.main()
