from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from playwright.sync_api import BrowserContext, Page, sync_playwright

from processors.dimensions_processor import read_dimensions_df


BASE_URL = "https://va.dimensions.ai"
DEFAULT_ORG_ID = "grid.239186.7"
MAX_EXPORT_SIZE = 500


@dataclass(frozen=True)
class Batch:
    year: int
    count: int
    url: str


def merge_dimensions_csvs(csv_paths: list[Path], output_path: Path) -> tuple[int, int]:
    if not csv_paths:
        raise ValueError("No Dimensions CSV files were found to merge.")

    frames: list[pd.DataFrame] = []
    expected_columns: list[str] | None = None
    for csv_path in csv_paths:
        frame = read_dimensions_df(csv_path.read_bytes())
        columns = frame.columns.tolist()
        if "Publication ID" not in columns:
            raise ValueError(f"{csv_path.name} has no Publication ID column.")
        if expected_columns is None:
            expected_columns = columns
        elif columns != expected_columns:
            raise ValueError(f"{csv_path.name} has different columns from the first export.")
        if frame["Publication ID"].isna().any() or frame["Publication ID"].astype(str).str.strip().eq("").any():
            raise ValueError(f"{csv_path.name} contains a blank Publication ID.")
        frames.append(frame)

    merged = pd.concat(frames, ignore_index=True)
    source_count = len(merged)
    merged = merged.drop_duplicates(subset=["Publication ID"], keep="first")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, index=False, encoding="utf-8-sig")
    return source_count, len(merged)


class DimensionsExporter:
    def __init__(self, context: BrowserContext, output_dir: Path, org_id: str) -> None:
        self.context = context
        self.output_dir = output_dir
        self.org_id = org_id
        self.page = context.pages[0] if context.pages else context.new_page()

    @property
    def search_url(self) -> str:
        return f"{BASE_URL}/discover/publication?{urlencode({'or_facet_research_org': self.org_id})}"

    def wait_for_login(self) -> None:
        self.page.goto(self.search_url, wait_until="domcontentloaded")
        print("A browser window is open. Sign in to Dimensions there if prompted; this window will stay open.")
        while True:
            response = self.page.request.get(f"{BASE_URL}/exports")
            if response.ok and response.url.rstrip("/").endswith("/exports") and "Export center" in response.text():
                self.page.goto(self.search_url, wait_until="domcontentloaded")
                return
            print("Waiting for Dimensions sign-in...")
            time.sleep(3)

    def total_count(self, url: str | None = None) -> int:
        target = url or self.search_url
        response = self.page.request.get(target.replace("/discover/publication?", "/discover/publication/results.json?"))
        if response.status == 204:
            return 0
        if not response.ok:
            raise RuntimeError(f"Dimensions count request failed: HTTP {response.status}")
        return int(response.json()["count"])

    def discover_year_batches(self) -> list[Batch]:
        total = self.total_count()
        current_year = time.gmtime().tm_year
        batches: list[Batch] = []
        running_total = 0
        empty_years = 0

        for year in range(current_year + 1, 1899, -1):
            query = urlencode({"or_facet_research_org": self.org_id, "or_facet_year": year})
            url = f"{BASE_URL}/discover/publication?{query}"
            count = self.total_count(url)
            if count:
                empty_years = 0
                if count > MAX_EXPORT_SIZE:
                    raise RuntimeError(
                        f"Year {year} has {count:,} records, above the {MAX_EXPORT_SIZE}-record limit. "
                        "A finer date partition is required."
                    )
                batches.append(Batch(year=year, count=count, url=url))
                running_total += count
            elif batches:
                empty_years += 1
                if empty_years >= 10:
                    break

        if running_total != total:
            raise RuntimeError(
                f"Year batches total {running_total:,}, but the unfiltered result count is {total:,}. "
                "No exports were submitted."
            )
        return batches

    def submit_batch(self, batch: Batch) -> None:
        self.page.goto(batch.url, wait_until="domcontentloaded")
        self.page.get_by_text(f"{batch.count:,}", exact=True).first.wait_for(timeout=30_000)
        self.page.get_by_role("button", name="Show options").click()
        self.page.get_by_role("button", name="Save / Export").click()
        self.page.get_by_role("menuitem", name="Export results").click()
        dialog = self.page.get_by_role("dialog", name="Export results")
        format_button = dialog.get_by_role("button", name=re.compile(r"^File format:"))
        if "CSV" not in format_button.first.inner_text():
            format_button.first.click()
            self.page.get_by_role("option", name="CSV - Comma separated").click()
        email = dialog.get_by_role("checkbox", name="Send email when export is ready")
        if email.is_checked():
            email.uncheck()
        with self.page.expect_response(lambda response: "/exports/publication.json" in response.url) as response_info:
            dialog.get_by_role("button", name="Export").click()
        response = response_info.value
        if not response.ok:
            raise RuntimeError(f"Dimensions rejected the {batch.year} export: HTTP {response.status}")

    def submit_all(self, batches: list[Batch], manifest_path: Path) -> None:
        completed = set()
        if manifest_path.exists():
            completed = set(json.loads(manifest_path.read_text(encoding="utf-8")).get("submitted_years", []))

        for index, batch in enumerate(batches, 1):
            if batch.year in completed:
                print(f"[{index}/{len(batches)}] {batch.year}: already submitted")
                continue
            print(f"[{index}/{len(batches)}] {batch.year}: submitting {batch.count:,} records")
            self.submit_batch(batch)
            completed.add(batch.year)
            manifest_path.write_text(
                json.dumps({
                    "batches": [asdict(item) for item in batches],
                    "submitted_years": sorted(completed),
                    "completed": False,
                }, indent=2),
                encoding="utf-8",
            )
            time.sleep(1.1)

    def download_ready_exports(self, batches: list[Batch], wait_minutes: int) -> list[Path]:
        expected = {batch.year: batch for batch in batches}
        downloaded = {}
        for path in self.output_dir.glob("dimensions_*.csv"):
            match = re.fullmatch(r"dimensions_(\d{4})\.csv", path.name)
            if not match or int(match.group(1)) not in expected:
                continue
            year = int(match.group(1))
            if len(read_dimensions_df(path.read_bytes())) == expected[year].count:
                downloaded[year] = path
            else:
                path.unlink()
        deadline = time.monotonic() + wait_minutes * 60

        while expected.keys() - downloaded.keys():
            response = self.page.request.get(f"{BASE_URL}/exports.json")
            if not response.ok:
                raise RuntimeError(f"Could not read Export Center: HTTP {response.status}")
            jobs_by_year = {}
            for job in response.json().get("exports", []):
                source_url = job.get("source_url") or ""
                year_match = re.search(r"(?:\?|&)or_facet_year=(\d{4})(?:&|$)", source_url)
                if not year_match:
                    continue
                year = int(year_match.group(1))
                if year not in expected or year in jobs_by_year:
                    continue
                jobs_by_year[year] = job

            ready_urls = {
                year: job.get("download_url")
                for year, job in jobs_by_year.items()
                if job.get("download_url")
            }
            duplicate_urls = {
                url for url in ready_urls.values()
                if list(ready_urls.values()).count(url) > 1
            }
            if duplicate_urls:
                affected = sorted(year for year, url in ready_urls.items() if url in duplicate_urls)
                raise RuntimeError(
                    "Dimensions reused a ZIP URL for multiple years: "
                    f"{', '.join(map(str, affected))}. Resubmit those years before merging."
                )

            for year, download_url in ready_urls.items():
                if year in downloaded:
                    continue
                archive_path = self.output_dir / f"dimensions_{year}.csv.zip"
                download_response = self.page.request.get(download_url)
                if not download_response.ok:
                    raise RuntimeError(f"Could not download year {year}: HTTP {download_response.status}")
                archive_path.write_bytes(download_response.body())
                csv_path = self.output_dir / f"dimensions_{year}.csv"
                with zipfile.ZipFile(archive_path) as archive:
                    csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
                    if len(csv_names) != 1:
                        raise RuntimeError(f"Expected one CSV in {archive_path.name}; found {len(csv_names)}.")
                    csv_path.write_bytes(archive.read(csv_names[0]))
                archive_path.unlink()
                actual_count = len(read_dimensions_df(csv_path.read_bytes()))
                if actual_count != expected[year].count:
                    csv_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Year {year} downloaded {actual_count:,} rows; expected {expected[year].count:,}. "
                        "Dimensions returned the wrong export payload; resubmit this year."
                    )
                downloaded[year] = csv_path
                print(f"Downloaded {year}: {expected[year].count:,} records")

            remaining = expected.keys() - downloaded.keys()
            if not remaining:
                break
            if time.monotonic() >= deadline:
                years = ", ".join(str(year) for year in sorted(remaining, reverse=True))
                raise TimeoutError(f"Exports are still processing for: {years}. Rerun this command to resume.")
            print(f"Waiting for {len(remaining)} export(s) in Export Center...")
            self.page.wait_for_timeout(30_000)

        return [downloaded[batch.year] for batch in batches]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export and merge all VA Dimensions publications for an organization.")
    parser.add_argument("--org-id", default=DEFAULT_ORG_ID, help="Dimensions research organization GRID ID")
    parser.add_argument("--output-dir", type=Path, default=Path("output/dimensions_batches"))
    parser.add_argument("--wait-minutes", type=int, default=240, help="Maximum time to wait for export jobs")
    parser.add_argument("--merge-only", action="store_true", help="Only merge CSV files already in --output-dir")
    return parser.parse_args()


def archive_completed_run(output_dir: Path) -> None:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("completed"):
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = output_dir.with_name(f"{output_dir.name}_{timestamp}")
    shutil.move(str(output_dir), str(archive_path))
    print(f"Archived the previous completed run to {archive_path}")


def main() -> int:
    args = parse_args()
    if not args.merge_only:
        archive_completed_run(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    merged_path = args.output_dir / "dimensions_merged.csv"

    if args.merge_only:
        csv_paths = sorted(path for path in args.output_dir.glob("*.csv") if path != merged_path)
        source_count, unique_count = merge_dimensions_csvs(csv_paths, merged_path)
        print(f"Merged {source_count:,} rows into {unique_count:,} unique publications: {merged_path}")
        return 0

    profile_dir = Path(".dimensions-browser-profile").resolve()
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            accept_downloads=True,
        )
        try:
            exporter = DimensionsExporter(context, args.output_dir, args.org_id)
            exporter.wait_for_login()
            batches = exporter.discover_year_batches()
            total = sum(batch.count for batch in batches)
            print(f"Discovered {len(batches)} year batches covering {total:,} records.")
            manifest = args.output_dir / "manifest.json"
            exporter.submit_all(batches, manifest)
            print("Exports submitted. Waiting for Dimensions to prepare them; rerun this command to resume downloads.")
            downloaded = exporter.download_ready_exports(batches, args.wait_minutes)
            if downloaded:
                source_count, unique_count = merge_dimensions_csvs(downloaded, merged_path)
                if unique_count != total:
                    raise RuntimeError(
                        f"Merged CSV has {unique_count:,} unique publications; expected {total:,}."
                    )
                manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
                manifest_data.update({
                    "completed": True,
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "unique_count": unique_count,
                })
                manifest.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
                print(f"Merged {source_count:,} rows into {unique_count:,} unique publications: {merged_path}")
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())