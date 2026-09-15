import unittest

import pandas as pd

from processors.dashboard_data import (
    add_facility_summary,
    build_facility_matches,
    prepare_publications,
    split_values,
)


class DashboardDataTests(unittest.TestCase):
    def publication_frame(self):
        return pd.DataFrame([
            {
                "Publication ID": "pub.1",
                "Title": "October paper",
                "Document Type": "Article",
                "Publication date (print)": "2025-10-12",
                "Publication date (online)": "2025-09-01",
                "Publication date": "2025-10-12",
                "PubYear": 2025,
                "Research Organizations - standardized": "James J. Peters VA Medical Center; University A",
                "Authors": "One, A.; Two, B.",
            },
            {
                "Publication ID": "pub.2",
                "Title": "Year only",
                "Document Type": "Conference Abstract",
                "Publication date (print)": "",
                "Publication date (online)": "2024",
                "Publication date": "2024",
                "PubYear": 2024,
                "Research Organizations - standardized": "Tiny VA Clinic",
                "Authors": "Three, C.",
            },
            {
                "Publication ID": "pub.3",
                "Title": "Unmatched",
                "Document Type": "Review",
                "Publication date (print)": "2023-02",
                "Publication date (online)": "",
                "Publication date": "",
                "PubYear": 2023,
                "Research Organizations - standardized": "University B",
                "Authors": "",
            },
        ])

    def reference_frame(self):
        return pd.DataFrame([
            {
                "vamc_display": "VA Central Office; Veterans Health Administration",
                "station_no": "101",
                "alt_station_nos": "101",
                "not_in_dimensions": False,
            },
            {
                "vamc_display": "James J. Peters VA Medical Center",
                "station_no": "526",
                "alt_station_nos": "",
                "not_in_dimensions": False,
            },
            {
                "vamc_display": "Tiny VA Clinic North Campus",
                "station_no": "999",
                "alt_station_nos": "999A",
                "not_in_dimensions": False,
            },
        ])

    def test_split_values_ignores_blanks(self):
        self.assertEqual(split_values("A; B; ; C"), ["A", "B", "C"])
        self.assertEqual(split_values(None), [])

    def test_dates_fiscal_periods_and_sop_flags(self):
        publications = prepare_publications(self.publication_frame())

        self.assertEqual(publications.loc[0, "Date Source"], "print")
        self.assertEqual(publications.loc[0, "Fiscal Period"], "FY26 Q1")
        self.assertEqual(publications.loc[1, "Fiscal Period"], "Unavailable")
        self.assertEqual(publications.loc[2, "Fiscal Period"], "FY23 Q2")
        self.assertEqual(publications["SOP Eligible"].tolist(), [True, False, True])
        self.assertEqual(publications["Author Count"].tolist(), [2, 1, 0])
        self.assertEqual(publications["DOI Link"].tolist(), ["", "", ""])

    def test_facility_matches_include_strong_and_weak_evidence(self):
        publications = prepare_publications(self.publication_frame())
        matches = build_facility_matches(publications, self.reference_frame())

        strong = matches[matches["Publication ID"] == "pub.1"].iloc[0]
        weak = matches[matches["Publication ID"] == "pub.2"].iloc[0]
        self.assertEqual(strong["Match Strength"], "strong")
        self.assertEqual(strong["Matched Organization"], "James J. Peters VA Medical Center")
        self.assertEqual(weak["Match Strength"], "weak")
        self.assertEqual(weak["Station Numbers"], "999; 999A")
        self.assertNotIn("VA Central Office", matches["Facility"].tolist())

    def test_facility_summary_preserves_unmatched_and_distinct_counts(self):
        publications = prepare_publications(self.publication_frame())
        matches = build_facility_matches(publications, self.reference_frame())
        duplicate = matches.iloc[[0]].copy()
        matches = pd.concat([matches, duplicate], ignore_index=True).drop_duplicates(
            ["Publication ID", "Facility"]
        )
        summary = add_facility_summary(publications, matches)

        self.assertEqual(summary.loc[0, "Facility Match Count"], 1)
        self.assertEqual(summary.loc[2, "Facility Match Status"], "Unmatched")

    def test_rejects_duplicate_publication_ids(self):
        frame = self.publication_frame()
        frame.loc[1, "Publication ID"] = "pub.1"
        with self.assertRaisesRegex(ValueError, "duplicate Publication IDs"):
            prepare_publications(frame)

    def test_real_merged_dataset_reconciles_when_available(self):
        from pathlib import Path

        from processors.dashboard_data import load_dashboard_dataset

        path = Path("output/dimensions_batches/dimensions_merged.csv")
        if not path.exists():
            self.skipTest("Generated Dimensions merge is not available")
        dataset = load_dashboard_dataset(path)
        self.assertEqual(len(dataset.publications), 4061)
        self.assertEqual(len(dataset.source_columns), 60)
        self.assertEqual(dataset.publications["Publication ID"].nunique(), 4061)
        self.assertFalse(dataset.publications["Publication ID"].isna().any())


if __name__ == "__main__":
    unittest.main()