"""Land a CA leginfo bulk-download zip into Unity Catalog volumes.

Runs as a single-node Databricks Job task (no Spark) before the Lakeflow
pipeline. Downloads one `pubinfo_*.zip` from downloads.leginfo.legislature.ca.gov,
preserves the zip + a manifest as the raw audit artifact, then makes one pass
over each in-scope `*_TBL.dat` file joining each row to its `.lob` body text
(looked up by filename via zipfile's central-directory random access) and
writes the result as Parquet — one table per source table, never one file per
LOB. See ca-leginfo-bulk-download.md for the source format this parses.

Two different destinations, per docs/architecture.md — never confuse them:
  - The raw zip + manifest go to a FIXED, always-shared location under the
    catalog's bronze schema (hardcoded below as a literal path) — one copy,
    used by every developer and prod alike. This is the one deliberate
    exception to "never hardcode a schema name" in this project. (Today dev
    and prod share one physical catalog, so this is moot in practice — but the
    fixed literal is written for when a real prod catalog exists; see
    docs/architecture.md's "Current state vs. target state.")
  - The parsed per-table Parquet goes to `--bronze-schema`/`--parsed-volume`,
    which the caller MUST resolve from the bundle's schema/volume resources —
    this is environment-scoped (per-developer under dev, canonical under
    prod) because it's the output of manipulating raw data.

v1 scope is the bill/reference tables only; the four code/statute tables
(CODES_TBL, LAW_TOC_TBL, LAW_TOC_SECTIONS_TBL, LAW_SECTION_TBL) are deferred —
they ship only in the weekly session zip and dominate the file count
(162K of ~198K files in a full session zip), so they get their own ingestion
pass once this is proven.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pyarrow as pa
import pyarrow.parquet as pq

SOURCE_BASE_URL = "https://downloads.leginfo.legislature.ca.gov"
DEFAULT_ZIP_NAME = "pubinfo_2025.zip"
DOWNLOAD_CHUNK_BYTES = 1 << 20  # 1 MiB
DOWNLOAD_TIMEOUT_SECONDS = 300
# Identify the fetcher to the public source rather than sending urllib's default.
USER_AGENT = (
    "caldata-legislation-tracker/land_raw (+https://github.com/cagov/caldata-legislation-tracker)"
)
BATCH_ROWS = (
    5_000  # rows buffered per Parquet part file; bounds peak memory regardless of table size
)

# Column order per table, taken directly from the loader SQL files in
# pubinfo_load.zip (capublic.sql / *_tbl.sql). For LOB-backed tables, the
# column at `lob_column`'s position holds the LOB *filename* in the raw .dat
# row (the MySQL loader's `@var1`, resolved via `LOAD_FILE`); we resolve it to
# the actual LOB text ourselves and the column ends up holding that text.
TABLES: dict[str, dict] = {
    "BILL_TBL": {
        "columns": [
            "BILL_ID",
            "SESSION_YEAR",
            "SESSION_NUM",
            "MEASURE_TYPE",
            "MEASURE_NUM",
            "MEASURE_STATE",
            "CHAPTER_YEAR",
            "CHAPTER_TYPE",
            "CHAPTER_SESSION_NUM",
            "CHAPTER_NUM",
            "LATEST_BILL_VERSION_ID",
            "ACTIVE_FLG",
            "TRANS_UID",
            "TRANS_UPDATE",
            "CURRENT_LOCATION",
            "CURRENT_SECONDARY_LOC",
            "CURRENT_HOUSE",
            "CURRENT_STATUS",
            "DAYS_31ST_IN_PRINT",
        ],
    },
    "BILL_VERSION_TBL": {
        "columns": [
            "BILL_VERSION_ID",
            "BILL_ID",
            "VERSION_NUM",
            "BILL_VERSION_ACTION_DATE",
            "BILL_VERSION_ACTION",
            "REQUEST_NUM",
            "SUBJECT",
            "VOTE_REQUIRED",
            "APPROPRIATION",
            "FISCAL_COMMITTEE",
            "LOCAL_PROGRAM",
            "SUBSTANTIVE_CHANGES",
            "URGENCY",
            "TAXLEVY",
            "BILL_XML",
            "ACTIVE_FLG",
            "TRANS_UID",
            "TRANS_UPDATE",
        ],
        "lob_column": "BILL_XML",
    },
    "BILL_VERSION_AUTHORS_TBL": {
        "columns": [
            "BILL_VERSION_ID",
            "TYPE",
            "HOUSE",
            "NAME",
            "CONTRIBUTION",
            "COMMITTEE_MEMBERS",
            "ACTIVE_FLG",
            "TRANS_UID",
            "TRANS_UPDATE",
            "PRIMARY_AUTHOR_FLG",
        ],
    },
    "BILL_HISTORY_TBL": {
        "columns": [
            "BILL_ID",
            "BILL_HISTORY_ID",
            "ACTION_DATE",
            "ACTION",
            "TRANS_UID",
            "TRANS_UPDATE_DT",
            "ACTION_SEQUENCE",
            "ACTION_CODE",
            "ACTION_STATUS",
            "PRIMARY_LOCATION",
            "SECONDARY_LOCATION",
            "TERNARY_LOCATION",
            "END_STATUS",
        ],
    },
    "BILL_ANALYSIS_TBL": {
        "columns": [
            "ANALYSIS_ID",
            "BILL_ID",
            "HOUSE",
            "ANALYSIS_TYPE",
            "COMMITTEE_CODE",
            "COMMITTEE_NAME",
            "AMENDMENT_AUTHOR",
            "ANALYSIS_DATE",
            "AMENDMENT_DATE",
            "PAGE_NUM",
            "SOURCE_DOC",
            "RELEASED_FLOOR",
            "ACTIVE_FLG",
            "TRANS_UID",
            "TRANS_UPDATE",
        ],
        "lob_column": "SOURCE_DOC",
        # Verified 2026-07-22 against a full-spread sample of the real zip: every
        # SOURCE_DOC LOB is an OOXML (.docx) zip container, not UTF-8 text/XML like
        # BILL_XML/MESSAGE are. Land the raw bytes untouched; decoding to text is a
        # silver-layer concern.
        "lob_binary": True,
    },
    "BILL_SUMMARY_VOTE_TBL": {
        "columns": [
            "BILL_ID",
            "LOCATION_CODE",
            "VOTE_DATE_TIME",
            "VOTE_DATE_SEQ",
            "MOTION_ID",
            "AYES",
            "NOES",
            "ABSTAIN",
            "VOTE_RESULT",
            "TRANS_UID",
            "TRANS_UPDATE",
            "FILE_ITEM_NUM",
            "FILE_LOCATION",
            "DISPLAY_LINES",
            "SESSION_DATE",
        ],
    },
    "BILL_DETAIL_VOTE_TBL": {
        "columns": [
            "BILL_ID",
            "LOCATION_CODE",
            "LEGISLATOR_NAME",
            "VOTE_DATE_TIME",
            "VOTE_DATE_SEQ",
            "VOTE_CODE",
            "MOTION_ID",
            "TRANS_UID",
            "TRANS_UPDATE",
            "MEMBER_ORDER",
            "SESSION_DATE",
            "SPEAKER",
        ],
    },
    "BILL_MOTION_TBL": {
        "columns": ["MOTION_ID", "MOTION_TEXT", "TRANS_UID", "TRANS_UPDATE"],
    },
    "VETO_MESSAGE_TBL": {
        "columns": ["BILL_ID", "VETO_DATE", "MESSAGE", "TRANS_UID", "TRANS_UPDATE"],
        "lob_column": "MESSAGE",
    },
    "LEGISLATOR_TBL": {
        "columns": [
            "DISTRICT",
            "SESSION_YEAR",
            "LEGISLATOR_NAME",
            "HOUSE_TYPE",
            "AUTHOR_NAME",
            "FIRST_NAME",
            "LAST_NAME",
            "MIDDLE_INITIAL",
            "NAME_SUFFIX",
            "NAME_TITLE",
            "WEB_NAME_TITLE",
            "PARTY",
            "ACTIVE_FLG",
            "TRANS_UID",
            "TRANS_UPDATE",
            "ACTIVE_LEGISLATOR",
        ],
    },
    "LOCATION_CODE_TBL": {
        "columns": [
            "SESSION_YEAR",
            "LOCATION_CODE",
            "LOCATION_TYPE",
            "CONSENT_CALENDAR_CODE",
            "DESCRIPTION",
            "LONG_DESCRIPTION",
            "ACTIVE_FLG",
            "TRANS_UID",
            "TRANS_UPDATE",
            "INACTIVE_FILE_FLG",
        ],
    },
    "COMMITTEE_HEARING_TBL": {
        "columns": [
            "BILL_ID",
            "COMMITTEE_TYPE",
            "COMMITTEE_NR",
            "HEARING_DATE",
            "LOCATION_CODE",
            "TRANS_UID",
            "TRANS_UPDATE_DATE",
        ],
    },
    "COMMITTEE_AGENDA_TBL": {
        "columns": [
            "COMMITTEE_CODE",
            "COMMITTEE_DESC",
            "AGENDA_DATE",
            "AGENDA_TIME",
            "LINE1",
            "LINE2",
            "LINE3",
            "BUILDING_TYPE",
            "ROOM_NUM",
        ],
    },
    "DAILY_FILE_TBL": {
        "columns": [
            "BILL_ID",
            "LOCATION_CODE",
            "CONSENT_CALENDAR_CODE",
            "FILE_LOCATION",
            "PUBLICATION_DATE",
            "FLOOR_MANAGER",
            "TRANS_UID",
            "TRANS_UPDATE_DATE",
            "SESSION_NUM",
            "STATUS",
        ],
    },
}


def download_zip(zip_name: str, dest_dir: Path) -> tuple[Path, dict]:
    """Stream the zip to local disk; return its path and HTTP metadata for the manifest.

    Deliberately stdlib `urllib`, not `requests`. `requests` verifies TLS against
    the `certifi` bundle vendored into whichever version is installed — the
    Databricks runtime image pins certifi 2022.12.07, which predates the Sectigo
    root that anchors leginfo's certificate chain, so it rejects the connection
    with a misleading "self-signed certificate in certificate chain". `urllib`
    inherits the OS trust store, which carries that root. See
    ca-leginfo-bulk-download.md §9.
    """
    url = f"{SOURCE_BASE_URL}/{zip_name}"
    dest = dest_dir / zip_name
    # Stream to a temp name and rename only on success, so an interrupted fetch
    # can never leave a truncated zip standing in for a complete one.
    tmp = dest.with_name(dest.name + ".part")
    sha256 = hashlib.sha256()
    downloaded = 0

    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, tmp.open("wb") as f:
        last_modified = response.headers.get("Last-Modified")
        content_length = response.headers.get("Content-Length")
        while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
            f.write(chunk)
            sha256.update(chunk)
            downloaded += len(chunk)

    expected = int(content_length) if content_length is not None else None
    if expected is not None and downloaded != expected:
        tmp.unlink(missing_ok=True)
        raise OSError(f"{url}: downloaded {downloaded} bytes but Content-Length was {expected}")
    tmp.replace(dest)

    return dest, {
        "fetch_mode": "http",
        "source_url": url,
        "last_modified": last_modified,
        "content_length": content_length,
        "sha256": sha256.hexdigest(),
    }


def use_local_zip(local_path: Path) -> tuple[Path, dict]:
    """Use an already-downloaded zip instead of fetching over HTTP.

    Escape hatch for when Databricks compute can't reach the source but a
    developer's own machine can. Also useful for re-parsing a known zip without
    re-downloading 1.2 GB.
    """
    sha256 = hashlib.sha256()
    with local_path.open("rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_BYTES), b""):
            sha256.update(chunk)
    return local_path, {
        "fetch_mode": "local-upload",
        "source_url": f"{SOURCE_BASE_URL}/{local_path.name}",
        "last_modified": None,
        "content_length": str(local_path.stat().st_size),
        "sha256": sha256.hexdigest(),
    }


def parse_dat_row(raw_line: bytes) -> list[str | None]:
    """Split one `.dat` line into fields, per the loader's FIELDS/LINES rules.

    Fields are tab-separated and optionally backtick-enclosed. A field is SQL
    NULL only if it is the bare, unenclosed literal `NULL` — a backtick-enclosed
    `NULL` is the literal string, matching the loader's ENCLOSED BY semantics.
    """
    fields = []
    for raw_field in raw_line.rstrip(b"\n").split(b"\t"):
        if len(raw_field) >= 2 and raw_field[:1] == b"`" and raw_field[-1:] == b"`":
            fields.append(raw_field[1:-1].decode("utf-8"))
        else:
            text = raw_field.decode("utf-8")
            fields.append(None if text == "NULL" else text)
    return fields


def write_table(zf: zipfile.ZipFile, table: str, spec: dict, table_dir: Path) -> int:
    """Parse one `.dat` file, joining each row to its LOB text, and write Parquet.

    Buffers `BATCH_ROWS` rows at a time and flushes to its own part file, so
    peak memory is one batch's worth regardless of table size — the same code
    path handles a 124-row table and (later) a 162K-row one unchanged.
    """
    dat_bytes = zf.read(f"{table}.dat")
    columns = spec["columns"]
    lob_column = spec.get("lob_column")
    lob_index = columns.index(lob_column) if lob_column else None
    lob_binary = spec.get("lob_binary", False)
    arrow_types = [
        pa.binary() if (lob_binary and col == lob_column) else pa.string() for col in columns
    ]
    arrow_schema = pa.schema(list(zip(columns, arrow_types)))

    part_num = 0
    row_count = 0
    batch: list[list] = [[] for _ in columns]
    batch_rows = 0

    def flush() -> None:
        nonlocal part_num, batch, batch_rows
        if batch_rows == 0:
            return
        arrow_table = pa.table(
            {col: pa.array(values, type=t) for col, values, t in zip(columns, batch, arrow_types)},
            schema=arrow_schema,
        )
        pq.write_table(arrow_table, table_dir / f"part-{part_num:04d}.parquet")
        part_num += 1
        batch = [[] for _ in columns]
        batch_rows = 0

    for line in dat_bytes.splitlines():
        if not line:
            continue
        fields: list = parse_dat_row(line)
        if len(fields) != len(columns):
            raise ValueError(
                f"{table}.dat row has {len(fields)} fields, expected {len(columns)}: {fields!r}"
            )
        if lob_index is not None:
            lob_name = fields[lob_index]
            if not lob_name:
                raise ValueError(f"{table}.dat row missing LOB filename: {fields!r}")
            lob_bytes = zf.read(lob_name)
            fields[lob_index] = lob_bytes if lob_binary else lob_bytes.decode("utf-8")
        for i, value in enumerate(fields):
            batch[i].append(value)
        batch_rows += 1
        row_count += 1
        if batch_rows >= BATCH_ROWS:
            flush()

    flush()
    return row_count


def write_manifest(dest_dir: Path, zip_name: str, fetch_meta: dict, tables: list[str]) -> None:
    manifest = {
        **fetch_meta,
        "zip_name": zip_name,
        "fetch_time": datetime.now(timezone.utc).isoformat(),
        "tables_loaded": tables,
    }
    (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", required=True, help="UC catalog holding the medallion schemas."
    )
    parser.add_argument(
        "--bronze-schema",
        required=True,
        help="Resolved bronze schema name for parsed output, from the bundle's schema resource "
        "— environment-scoped (dev_<user>-prefixed under dev, canonical under prod). Never hardcode.",
    )
    parser.add_argument(
        "--parsed-volume",
        required=True,
        help="Resolved staging volume name, from the bundle's volume resource.",
    )
    parser.add_argument("--zip-name", default=DEFAULT_ZIP_NAME, help="Source zip filename to land.")
    parser.add_argument(
        "--tables",
        default=",".join(TABLES),
        help="Comma-separated subset of table names to load (default: all in-scope tables).",
    )
    parser.add_argument(
        "--work-dir",
        default="/tmp/land_raw",
        help="Local scratch directory for the downloaded zip.",
    )
    parser.add_argument(
        "--local-zip",
        default=None,
        help="Path to an already-downloaded zip; skip the HTTP fetch and use this instead "
        "(see use_local_zip's docstring for when this is needed).",
    )
    parser.add_argument(
        "--raw-root",
        default=None,
        help="Override the fixed shared raw-zip destination (default: "
        "/Volumes/<catalog>/bronze/raw). Only for local testing.",  # noqa: schema-literal
    )
    parser.add_argument(
        "--parsed-root",
        default=None,
        help="Override the parsed-Parquet destination (default: "
        "/Volumes/<catalog>/<bronze-schema>/<parsed-volume>). Only for local testing.",
    )
    args = parser.parse_args()

    tables = args.tables.split(",")
    unknown = [t for t in tables if t not in TABLES]
    if unknown:
        raise ValueError(f"Unknown table(s) requested: {unknown}. Known: {list(TABLES)}")

    # Fixed and shared regardless of environment — see docs/architecture.md.
    raw_root = Path(args.raw_root or f"/Volumes/{args.catalog}/bronze/raw")  # noqa: schema-literal
    # Environment-scoped — resolved by the caller from bundle resources, never hardcoded here.
    parsed_root = Path(
        args.parsed_root or f"/Volumes/{args.catalog}/{args.bronze_schema}/{args.parsed_volume}"
    )
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.local_zip:
        print(f"Using local zip {args.local_zip} ...")
        zip_path, fetch_meta = use_local_zip(Path(args.local_zip))
    else:
        print(f"Downloading {args.zip_name} ...")
        zip_path, fetch_meta = download_zip(args.zip_name, work_dir)
    print(f"Zip is {zip_path.stat().st_size:,} bytes.")

    raw_zone = raw_root / Path(args.zip_name).stem
    raw_zone.mkdir(parents=True, exist_ok=True)
    (raw_zone / args.zip_name).write_bytes(zip_path.read_bytes())
    write_manifest(raw_zone, args.zip_name, fetch_meta, tables)
    print(f"Preserved raw zip + manifest at {raw_zone}")

    with zipfile.ZipFile(zip_path) as zf:
        for table in tables:
            print(f"Parsing {table} ...")
            table_dir = parsed_root / table
            table_dir.mkdir(parents=True, exist_ok=True)
            row_count = write_table(zf, table, TABLES[table], table_dir)
            print(f"  wrote {row_count:,} rows -> {table_dir}")


if __name__ == "__main__":
    main()
