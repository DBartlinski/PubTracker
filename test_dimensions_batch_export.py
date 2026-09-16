import tempfile
import unittest
from pathlib import Path

import pandas as pd

from dimensions_batch_export import merge_dimensions_csvs


class MergeDimensionsCsvsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_csv(self, name, rows, columns=None):
        path = self.root / name
        pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
        return path

    def test_merges_and_keeps_first_duplicate(self):
        first = self.write_csv("first.csv", [
            {"Rank": 1, "Publication ID": "pub.1", "DOI": "a", "Title": "First"},
            {"Rank": 2, "Publication ID": "pub.2", "DOI": "b", "Title": "Original"},
        ])
        second = self.write_csv("second.csv", [
            {"Rank": 1, "Publication ID": "pub.2", "DOI": "b", "Title": "Replacement"},
            {"Rank": 2, "Publication ID": "pub.3", "DOI": "c", "Title": "Third"},
        ])
        output = self.root / "merged.csv"

        source_count, unique_count = merge_dimensions_csvs([first, second], output)

        merged = pd.read_csv(output)
        self.assertEqual((source_count, unique_count), (4, 3))
        self.assertEqual(merged["Publication ID"].tolist(), ["pub.1", "pub.2", "pub.3"])
        self.assertEqual(merged.loc[merged["Publication ID"] == "pub.2", "Title"].item(), "Original")

    def test_rejects_different_columns(self):
        first = self.write_csv("first.csv", [[1, "pub.1", "a"]], ["Rank", "Publication ID", "DOI"])
        second = self.write_csv("second.csv", [[1, "pub.2", "Other"]], ["Rank", "Publication ID", "Title"])

        with self.assertRaisesRegex(ValueError, "different columns"):
            merge_dimensions_csvs([first, second], self.root / "merged.csv")

    def test_rejects_blank_publication_id(self):
        path = self.write_csv("blank.csv", [[1, "", "a"]], ["Rank", "Publication ID", "DOI"])

        with self.assertRaisesRegex(ValueError, "blank Publication ID"):
            merge_dimensions_csvs([path], self.root / "merged.csv")


if __name__ == "__main__":
    unittest.main()