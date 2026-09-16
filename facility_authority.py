"""Evidence-backed authority data for VA research facilities."""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS facility (
    id INTEGER PRIMARY KEY,
    authority_key TEXT NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL,
    facility_kind TEXT NOT NULL DEFAULT 'campus',
    research_active_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (research_active_status IN ('yes', 'no', 'unknown')),
    city TEXT,
    state_code TEXT,
    country_code TEXT NOT NULL DEFAULT 'US',
    lifecycle_status TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active', 'inactive', 'historical', 'unknown')),
    valid_from TEXT,
    valid_to TEXT,
    notes TEXT,
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE TABLE IF NOT EXISTS facility_identifier (
    id INTEGER PRIMARY KEY,
    facility_id INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    value TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    valid_from TEXT,
    valid_to TEXT,
    source_name TEXT NOT NULL,
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    UNIQUE (namespace, value)
);

CREATE TABLE IF NOT EXISTS facility_name (
    id INTEGER PRIMARY KEY,
    facility_id INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    name_kind TEXT NOT NULL
        CHECK (name_kind IN (
            'canonical', 'former', 'short', 'acronym', 'campus', 'colloquial',
            'misspelling', 'dimensions_standardized', 'pubmed_observed', 'source_observed'
        )),
    valid_from TEXT,
    valid_to TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    UNIQUE (facility_id, name, name_kind)
);

CREATE INDEX IF NOT EXISTS idx_facility_name_normalized
    ON facility_name(normalized_name);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_record_id TEXT,
    source_url TEXT,
    source_file TEXT,
    retrieved_at TEXT NOT NULL,
    observed_text TEXT,
    notes TEXT,
    CHECK (source_url IS NOT NULL OR source_file IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_source_record
    ON evidence(source_name, source_record_id, source_file, retrieved_at);

CREATE TABLE IF NOT EXISTS alias_evidence (
    facility_name_id INTEGER NOT NULL REFERENCES facility_name(id) ON DELETE CASCADE,
    evidence_id INTEGER NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    PRIMARY KEY (facility_name_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS facility_relationship (
    id INTEGER PRIMARY KEY,
    subject_facility_id INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL
        CHECK (relationship_type IN (
            'parent_system', 'campus_of', 'predecessor_of', 'successor_of',
            'renamed_to', 'related_research_center'
        )),
    object_facility_id INTEGER NOT NULL REFERENCES facility(id) ON DELETE CASCADE,
    valid_from TEXT,
    valid_to TEXT,
    evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    CHECK (subject_facility_id <> object_facility_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    UNIQUE (subject_facility_id, relationship_type, object_facility_id, valid_from)
);

CREATE TABLE IF NOT EXISTS match_candidate (
    id INTEGER PRIMARY KEY,
    input_text TEXT NOT NULL,
    normalized_input TEXT NOT NULL,
    proposed_facility_id INTEGER REFERENCES facility(id) ON DELETE SET NULL,
    match_method TEXT NOT NULL,
    score REAL CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
    reason_codes TEXT,
    competing_candidates TEXT,
    disposition TEXT NOT NULL DEFAULT 'pending'
        CHECK (disposition IN ('pending', 'approved', 'rejected', 'abstained')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open an authority database with foreign-key validation enabled."""
    connection = sqlite3.connect(Path(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create or validate the version-one authority schema."""
    with connection:
        connection.executescript(SCHEMA_SQL)
        versions = connection.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
        if versions and versions[-1]["version"] > SCHEMA_VERSION:
            raise RuntimeError("Database schema is newer than this application")
        connection.execute(
            "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )


def normalize_name(value: str) -> str:
    """Create a conservative comparison key without changing source text."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _split_values(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", value or "") if part.strip()]


def _display_names(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def _canonical_name(value: str) -> str:
    first_name = _display_names(value)[0]
    first_name = re.sub(
        r"\s*\(Not in VA Dimensions\)\s*$", "", first_name, flags=re.IGNORECASE
    )
    first_name = re.sub(
        r"\s+\((?:includes\s+[^()]+|[^(),]+,\s*[A-Z]{2})\)\s*$",
        "",
        first_name,
        flags=re.IGNORECASE,
    )
    return first_name.strip()


@dataclass
class ImportSummary:
    facilities_created: int = 0
    names_created: int = 0
    identifiers_created: int = 0
    identifier_conflicts: list[str] = field(default_factory=list)
    rows_skipped: list[str] = field(default_factory=list)


EXPORT_COLUMNS = [
    "facility_id",
    "authority_key",
    "canonical_name",
    "facility_kind",
    "research_active_status",
    "city",
    "state_code",
    "country_code",
    "lifecycle_status",
    "facility_valid_from",
    "facility_valid_to",
    "alias",
    "normalized_alias",
    "alias_kind",
    "alias_review_status",
    "alias_confidence",
    "alias_valid_from",
    "alias_valid_to",
    "identifier_namespace",
    "identifier_value",
    "identifier_is_primary",
    "identifier_valid_from",
    "identifier_valid_to",
    "identifier_source",
    "alias_evidence_count",
]


def import_vamc_reference(
    connection: sqlite3.Connection,
    csv_path: str | Path,
    *,
    retrieved_at: str | None = None,
) -> ImportSummary:
    """Import the legacy VAMC CSV as reviewable seed data with provenance."""
    source_path = Path(csv_path).resolve()
    retrieval_date = retrieved_at or date.today().isoformat()
    summary = ImportSummary()

    with source_path.open("r", encoding="utf-8-sig", newline="") as source_file:
        rows = list(csv.DictReader(source_file))

    required_columns = {"vamc_display", "station_no", "alt_station_nos"}
    missing_columns = required_columns.difference(rows[0] if rows else {})
    if missing_columns:
        raise ValueError(
            f"Reference CSV is missing required columns: {', '.join(sorted(missing_columns))}"
        )

    with connection:
        for row_number, row in enumerate(rows, start=2):
            display_value = (row["vamc_display"] or "").strip()
            station_values = _split_values(row["station_no"] or "")
            if not display_value:
                raise ValueError(f"Row {row_number} must include vamc_display")
            if not station_values:
                summary.rows_skipped.append(f"row {row_number}: {display_value} (no station number)")
                continue
            primary_station = station_values[0]

            authority_key = f"va-station:{primary_station.casefold()}"
            canonical_name = _canonical_name(display_value)
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO facility(
                    authority_key, canonical_name, research_active_status, notes
                ) VALUES (?, ?, 'unknown', ?)
                """,
                (
                    authority_key,
                    canonical_name,
                    "Imported from the legacy VAMC reference; requires source verification.",
                ),
            )
            summary.facilities_created += cursor.rowcount
            facility_id = connection.execute(
                "SELECT id FROM facility WHERE authority_key = ?", (authority_key,)
            ).fetchone()["id"]

            connection.execute(
                """
                INSERT OR IGNORE INTO evidence(
                    source_name, source_record_id, source_file, retrieved_at, observed_text
                ) VALUES ('legacy_vamc_reference', ?, ?, ?, ?)
                """,
                (str(row_number), str(source_path), retrieval_date, display_value),
            )
            evidence_id = connection.execute(
                """
                SELECT id FROM evidence
                WHERE source_name = 'legacy_vamc_reference'
                    AND source_record_id = ? AND source_file = ? AND retrieved_at = ?
                """,
                (str(row_number), str(source_path), retrieval_date),
            ).fetchone()["id"]

            observed_names = _display_names(display_value)
            if canonical_name not in observed_names:
                observed_names.insert(0, canonical_name)
            for position, observed_name in enumerate(observed_names):
                name_kind = "canonical" if position == 0 else "source_observed"
                name_cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO facility_name(
                        facility_id, name, normalized_name, name_kind,
                        review_status, confidence
                    ) VALUES (?, ?, ?, ?, 'pending', NULL)
                    """,
                    (facility_id, observed_name, normalize_name(observed_name), name_kind),
                )
                summary.names_created += name_cursor.rowcount
                facility_name_id = connection.execute(
                    """
                    SELECT id FROM facility_name
                    WHERE facility_id = ? AND name = ? AND name_kind = ?
                    """,
                    (facility_id, observed_name, name_kind),
                ).fetchone()["id"]
                connection.execute(
                    "INSERT OR IGNORE INTO alias_evidence VALUES (?, ?)",
                    (facility_name_id, evidence_id),
                )

            station_values.extend(_split_values(row.get("alt_station_nos", "")))
            for station in dict.fromkeys(station_values):
                try:
                    identifier_cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO facility_identifier(
                            facility_id, namespace, value, is_primary, source_name
                        ) VALUES (?, 'va_station', ?, ?, 'legacy_vamc_reference')
                        """,
                        (facility_id, station, int(station == primary_station)),
                    )
                    summary.identifiers_created += identifier_cursor.rowcount
                    owner = connection.execute(
                        """
                        SELECT facility_id FROM facility_identifier
                        WHERE namespace = 'va_station' AND value = ?
                        """,
                        (station,),
                    ).fetchone()
                    if owner and owner["facility_id"] != facility_id:
                        summary.identifier_conflicts.append(
                            f"station {station}: facility {facility_id} conflicts with {owner['facility_id']}"
                        )
                except sqlite3.IntegrityError as error:
                    summary.identifier_conflicts.append(f"station {station}: {error}")

    return summary


def export_authority_csv(
    connection: sqlite3.Connection, csv_path: str | Path
) -> int:
    """Export one row per facility alias and identifier pairing."""
    rows = connection.execute(
        """
        SELECT
            facility.id AS facility_id,
            facility.authority_key,
            facility.canonical_name,
            facility.facility_kind,
            facility.research_active_status,
            facility.city,
            facility.state_code,
            facility.country_code,
            facility.lifecycle_status,
            facility.valid_from AS facility_valid_from,
            facility.valid_to AS facility_valid_to,
            facility_name.name AS alias,
            facility_name.normalized_name AS normalized_alias,
            facility_name.name_kind AS alias_kind,
            facility_name.review_status AS alias_review_status,
            facility_name.confidence AS alias_confidence,
            facility_name.valid_from AS alias_valid_from,
            facility_name.valid_to AS alias_valid_to,
            facility_identifier.namespace AS identifier_namespace,
            facility_identifier.value AS identifier_value,
            facility_identifier.is_primary AS identifier_is_primary,
            facility_identifier.valid_from AS identifier_valid_from,
            facility_identifier.valid_to AS identifier_valid_to,
            facility_identifier.source_name AS identifier_source,
            COUNT(DISTINCT alias_evidence.evidence_id) AS alias_evidence_count
        FROM facility
        JOIN facility_name ON facility_name.facility_id = facility.id
        JOIN facility_identifier ON facility_identifier.facility_id = facility.id
        LEFT JOIN alias_evidence ON alias_evidence.facility_name_id = facility_name.id
        GROUP BY facility_name.id, facility_identifier.id
        ORDER BY
            facility.canonical_name COLLATE NOCASE,
            facility.id,
            facility_name.name_kind,
            facility_name.name COLLATE NOCASE,
            facility_identifier.is_primary DESC,
            facility_identifier.namespace,
            facility_identifier.value
        """
    ).fetchall()

    output_path = Path(csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerows({column: row[column] for column in EXPORT_COLUMNS} for row in rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="SQLite database to create or update")
    parser.add_argument("--import-reference", type=Path, metavar="CSV")
    parser.add_argument("--export-csv", type=Path, metavar="CSV")
    args = parser.parse_args()

    connection = connect_database(args.database)
    try:
        initialize_database(connection)
        if args.import_reference:
            summary = import_vamc_reference(connection, args.import_reference)
            print(
                f"Imported {summary.facilities_created} facilities, "
                f"{summary.names_created} names, and "
                f"{summary.identifiers_created} identifiers."
            )
            if summary.identifier_conflicts:
                print("Identifier conflicts:")
                for conflict in summary.identifier_conflicts:
                    print(f"- {conflict}")
            if summary.rows_skipped:
                print("Rows skipped:")
                for skipped_row in summary.rows_skipped:
                    print(f"- {skipped_row}")
        if args.export_csv:
            exported_rows = export_authority_csv(connection, args.export_csv)
            print(f"Exported {exported_rows} rows to {args.export_csv}.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()