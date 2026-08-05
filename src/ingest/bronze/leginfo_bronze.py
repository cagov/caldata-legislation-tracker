"""Bronze: unzip the landed leginfo zips in-memory and write them to Delta.

`land_raw` (the Job task) lands the zips only — it does NOT extract, because the
session zip explodes into ~200k tiny `.lob` files and writing those onto the FUSE
volume is pathologically slow (see `ca-leginfo-bulk-download.md` §5). Unzipping
happens here instead, distributed across the pipeline's executors and written
straight to Delta, so no loose files ever hit the volume.

A zip is not splittable, so parallelism comes from fanning out its *entries*: the
driver reads the central directory (cheap), the entry names are parallelized, and
each task reopens the zip from the volume and inflates only its assigned entries.

The pure helpers below (parsing/classification) are unit-tested off-cluster; the
`@dp.table` registration is guarded so importing this module without Spark (e.g. in
tests) only loads the helpers.
"""

from __future__ import annotations

import re
import zipfile

DEFAULT_ROOT = "/Volumes/caldata_legislation_tracker/bronze/raw/zips"
DEFAULT_SOURCE_ZIP = f"{DEFAULT_ROOT}/pubinfo_2025.zip"
DEFAULT_LOADER_ZIP = f"{DEFAULT_ROOT}/pubinfo_load.zip"

# `.dat`/`.lob` text has no declared charset; decode leniently so a stray byte never
# fails a whole partition. Bill-version LOBs are UTF-8 XML in practice.
_ENCODING = "utf-8"

# One paren group holds the column list, after the FIELDS/LINES clauses.
_COLS_RE = re.compile(r"into table.*?\((.*?)\)", re.IGNORECASE | re.DOTALL)
# `SET <col>=LOAD_FILE(concat(..., @varN))` maps a placeholder to its real column.
_SET_RE = re.compile(r"(\w+)\s*=\s*load_file\(.*?(@\w+)", re.IGNORECASE | re.DOTALL)


def parse_loader_columns(sql_text: str) -> list[str]:
    """Ordered, lowercased column names from a per-table `LOAD DATA` script.

    `@varN` placeholders (LOB filename inputs) are replaced by their `SET` target
    column, so the `.dat` column carrying the `.lob` filename keeps its position.
    """
    block = _COLS_RE.search(sql_text)
    if not block:
        raise ValueError("no column list found in loader SQL")
    set_targets = {var.lower(): col.lower() for col, var in _SET_RE.findall(sql_text)}
    columns = []
    for token in block.group(1).split(","):
        name = token.strip().lower()
        if not name:
            continue
        columns.append(set_targets.get(name, name.lstrip("@")) if name.startswith("@") else name)
    return columns


def load_column_map(loader_zip_path: str) -> dict[str, list[str]]:
    """Map each table name to its column list, read from the loader kit zip."""
    with zipfile.ZipFile(loader_zip_path) as z:
        return {
            name[: -len(".sql")]: parse_loader_columns(z.read(name).decode(_ENCODING))
            for name in z.namelist()
            if name.endswith("_tbl.sql")
        }


def parse_dat_line(line: str) -> list[str]:
    """Split one tab-delimited `.dat` line, stripping optional backtick enclosure."""
    fields = line.split("\t")
    return [f[1:-1] if len(f) >= 2 and f[0] == "`" and f[-1] == "`" else f for f in fields]


def table_name_for(entry: str) -> str:
    """`BILL_TBL.dat` -> `bill_tbl`."""
    return entry[: -len(".dat")].lower()


def is_dat(name: str) -> bool:
    return name.endswith("_TBL.dat")


def is_lob(name: str) -> bool:
    return name.lower().endswith(".lob")


def list_entries(zip_path: str) -> list[str]:
    with zipfile.ZipFile(zip_path) as z:
        return z.namelist()


def decode_text(raw: bytes) -> str:
    return raw.decode(_ENCODING, "replace")


def _lob_frames(zip_path: str):
    """mapInPandas worker: inflate a partition's assigned `.lob` entries.

    Uses the DataFrame `mapInPandas` API (not RDDs) because serverless Lakeflow
    blocks the low-level `sparkContext` RDD methods. The zip is opened once per
    partition and only the assigned entries are read.
    """

    def transform(batches):
        import pandas as pd

        with zipfile.ZipFile(zip_path) as z:
            for batch in batches:
                names = batch["lob_name"].tolist()
                yield pd.DataFrame(
                    {"lob_name": names, "content": [decode_text(z.read(n)) for n in names]}
                )

    return transform


def _dat_frames(zip_path: str, entry: str, columns: list[str]):
    """mapInPandas worker: inflate one `.dat` entry into fixed-width string rows.

    Rows whose field count doesn't match the schema are padded/truncated and their
    raw line is kept in a trailing `_rescued` column rather than dropped.
    """
    ncols = len(columns)
    out_columns = [*columns, "_rescued"]

    def transform(batches):
        import pandas as pd

        for _ in batches:  # drain the single-row trigger frame
            pass
        with zipfile.ZipFile(zip_path) as z:
            text = decode_text(z.read(entry))
        rows = []
        for line in text.split("\n"):
            if not line:
                continue
            values = parse_dat_line(line)
            if len(values) == ncols:
                rows.append([*values, None])
            else:
                rows.append([*(values + [None] * ncols)[:ncols], line])
        yield pd.DataFrame(rows, columns=out_columns)

    return transform


# --- Lakeflow pipeline registration (skipped off-cluster) ------------------------
# Guarded on both pyspark and the injected `spark` global so this module imports
# cleanly in unit tests, where neither is present.
try:
    from pyspark import pipelines as dp
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    _HAS_PIPELINES = True
except ImportError:
    _HAS_PIPELINES = False

if _HAS_PIPELINES and "spark" in globals():
    _source_zip = spark.conf.get("leginfo.source_zip", DEFAULT_SOURCE_ZIP)  # noqa: F821
    _loader_zip = spark.conf.get("leginfo.loader_zip", DEFAULT_LOADER_ZIP)  # noqa: F821
    _columns = load_column_map(_loader_zip)
    _entries = list_entries(_source_zip)

    # Names are schema-qualified with `bronze.` because the pipeline's default schema
    # is `silver`; unqualified names would land these raw tables in the wrong schema.
    @dp.table(
        name="bronze.lob_raw",
        comment="Raw leginfo LOB payloads (bill text, analyses, law sections), keyed by "
        "LOB filename; the referencing *_raw table joins on it. Inflated from the source zip.",
    )
    def lob_raw():
        names = [e for e in _entries if is_lob(e)]
        slices = max(8, min(1024, len(names) // 200 or 1))
        names_df = spark.createDataFrame(  # noqa: F821
            [(n,) for n in names], "lob_name string"
        ).repartition(slices)
        return (
            names_df.mapInPandas(_lob_frames(_source_zip), "lob_name string, content string")
            .withColumn("source_zip", F.lit(_source_zip))
            .withColumn("_ingested_at", F.current_timestamp())
        )

    def _register_dat_table(entry: str, columns: list[str]):
        schema = T.StructType(
            [T.StructField(c, T.StringType()) for c in columns]
            + [T.StructField("_rescued", T.StringType())]
        )

        @dp.table(
            name=f"bronze.{table_name_for(entry)}_raw",
            comment=f"Raw tab-delimited rows from {entry}.",
        )
        def _dat():
            trigger = spark.createDataFrame([(entry,)], "entry string")  # noqa: F821
            return (
                trigger.mapInPandas(_dat_frames(_source_zip, entry, columns), schema)
                .withColumn("source_zip", F.lit(_source_zip))
                .withColumn("_ingested_at", F.current_timestamp())
            )

    for _entry in _entries:
        if is_dat(_entry) and table_name_for(_entry) in _columns:
            _register_dat_table(_entry, _columns[table_name_for(_entry)])
