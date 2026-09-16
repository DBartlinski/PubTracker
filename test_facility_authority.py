import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from facility_authority import (
    EXPORT_COLUMNS,
    export_authority_csv,
    import_vamc_reference,
    initialize_database,
    normalize_name,
)


class FacilityAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        initialize_database(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_normalize_name_preserves_meaning_but_removes_formatting(self):
        self.assertEqual(
            normalize_name("James J. Peters VA Medical Center"),
            "james j peters va medical center",
        )

    def test_import_splits_names_and_station_numbers_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "reference.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=[
                        "vamc_display",
                        "station_no",
                        "va_funded",
                        "not_in_dimensions",
                        "alt_station_nos",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "vamc_display": "VA NY Harbor Healthcare System; Manhattan VA Medical Center",
                        "station_no": "527",
                        "va_funded": "Y",
                        "not_in_dimensions": "False",
                        "alt_station_nos": "527; 630; 630A4",
                    }
                )

            summary = import_vamc_reference(
                self.connection, csv_path, retrieved_at="2026-09-14"
            )
            repeated_summary = import_vamc_reference(
                self.connection, csv_path, retrieved_at="2026-09-14"
            )

        self.assertEqual(summary.facilities_created, 1)
        self.assertEqual(summary.names_created, 2)
        self.assertEqual(summary.identifiers_created, 3)
        self.assertEqual(summary.identifier_conflicts, [])
        self.assertEqual(repeated_summary.facilities_created, 0)
        self.assertEqual(repeated_summary.names_created, 0)
        self.assertEqual(repeated_summary.identifiers_created, 0)
        names = self.connection.execute(
            "SELECT name FROM facility_name ORDER BY id"
        ).fetchall()
        self.assertEqual(
            [row["name"] for row in names],
            ["VA NY Harbor Healthcare System", "Manhattan VA Medical Center"],
        )
        evidence_links = self.connection.execute(
            "SELECT COUNT(*) AS count FROM alias_evidence"
        ).fetchone()["count"]
        self.assertEqual(evidence_links, 2)
        evidence_count = self.connection.execute(
            "SELECT COUNT(*) AS count FROM evidence"
        ).fetchone()["count"]
        self.assertEqual(evidence_count, 1)

    def test_identifier_collision_is_reported_without_reassignment(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "reference.csv"
            csv_path.write_text(
                "vamc_display,station_no,va_funded,not_in_dimensions,alt_station_nos\n"
                "First VA,100,,False,200\n"
                "Second VA,200,,False,200\n",
                encoding="utf-8",
            )
            summary = import_vamc_reference(self.connection, csv_path)

        self.assertEqual(len(summary.identifier_conflicts), 1)
        owner = self.connection.execute(
            """
            SELECT facility.canonical_name
            FROM facility_identifier
            JOIN facility ON facility.id = facility_identifier.facility_id
            WHERE facility_identifier.value = '200'
            """
        ).fetchone()["canonical_name"]
        self.assertEqual(owner, "First VA")

    def test_compound_primary_stations_and_unkeyed_rows_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "reference.csv"
            csv_path.write_text(
                "vamc_display,station_no,va_funded,not_in_dimensions,alt_station_nos\n"
                '"VA Palo Alto Health Care System","640, 640MPD",Y,False,"640; 640MPD"\n'
                "VA Sunshine Healthcare Network,,,False,\n",
                encoding="utf-8",
            )
            summary = import_vamc_reference(self.connection, csv_path)

        self.assertEqual(summary.facilities_created, 1)
        self.assertEqual(summary.identifiers_created, 2)
        self.assertEqual(len(summary.rows_skipped), 1)
        authority_key = self.connection.execute(
            "SELECT authority_key FROM facility"
        ).fetchone()["authority_key"]
        self.assertEqual(authority_key, "va-station:640")

    def test_export_writes_one_row_per_alias_identifier_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "reference.csv"
            csv_path.write_text(
                "vamc_display,station_no,va_funded,not_in_dimensions,alt_station_nos\n"
                '"VA NY Harbor Healthcare System; Manhattan VA Medical Center",527,Y,False,"527; 630"\n',
                encoding="utf-8",
            )
            import_vamc_reference(
                self.connection, csv_path, retrieved_at="2026-09-14"
            )
            export_path = Path(directory) / "authority.csv"
            exported_rows = export_authority_csv(self.connection, export_path)
            with export_path.open("r", encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))

        self.assertEqual(exported_rows, 4)
        self.assertEqual(list(rows[0]), EXPORT_COLUMNS)
        self.assertEqual({row["alias"] for row in rows}, {
            "VA NY Harbor Healthcare System",
            "Manhattan VA Medical Center",
        })
        self.assertEqual({row["identifier_value"] for row in rows}, {"527", "630"})
        self.assertTrue(all(row["alias_evidence_count"] == "1" for row in rows))


if __name__ == "__main__":
    unittest.main()