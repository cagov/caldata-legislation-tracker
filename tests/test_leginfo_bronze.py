"""Unit tests for the pure parsing helpers in the bronze leginfo reader.

These cover the logic that turns the leginfo loader kit + `.dat`/`.lob` zip entries
into rows, using synthetic zips built in-test — no real source data is committed.
The Spark `@dp.table` wiring is verified end-to-end on Databricks, not here.
"""

import zipfile
from pathlib import Path

import leginfo_bronze as lb
import pytest

# A realistic `LOAD DATA` loader script with no LOB column.
BILL_TBL_SQL = """LOAD DATA LOCAL
  INFILE "BILL_TBL.dat"
  REPLACE
  INTO TABLE capublic.bill_tbl
  FIELDS TERMINATED BY '\\t'
  OPTIONALLY ENCLOSED BY '`'
  LINES TERMINATED BY '\\n'
(
   BILL_ID
  ,SESSION_YEAR
  ,MEASURE_TYPE
)
"""

# A loader script whose row references a `.lob` file: the @var placeholder is mapped
# to a real column (BILL_XML) via a SET ... LOAD_FILE clause.
BILL_VERSION_TBL_SQL = """LOAD DATA LOCAL
  INFILE "BILL_VERSION_TBL.dat"
  REPLACE
  INTO TABLE capublic.bill_version_tbl
  FIELDS TERMINATED BY '\\t'
  OPTIONALLY ENCLOSED BY '`'
  LINES TERMINATED BY '\\n'
(
   BILL_VERSION_ID
  ,BILL_ID
  ,@var1
  ,ACTIVE_FLG
)
SET BILL_XML=LOAD_FILE(concat('c:\\\\pubinfo\\\\',@var1))
"""


def test_parse_loader_columns_plain():
    assert lb.parse_loader_columns(BILL_TBL_SQL) == ["bill_id", "session_year", "measure_type"]


def test_parse_loader_columns_maps_lob_var_to_set_target():
    # @var1 must become `bill_xml` (its SET target) and stay in positional order,
    # so the .dat column that holds the lob filename lands in the right place.
    assert lb.parse_loader_columns(BILL_VERSION_TBL_SQL) == [
        "bill_version_id",
        "bill_id",
        "bill_xml",
        "active_flg",
    ]


def test_parse_dat_line_strips_optional_backtick_enclosure():
    assert lb.parse_dat_line("`A`\t`B B`\tC") == ["A", "B B", "C"]


def test_parse_dat_line_preserves_empty_fields():
    assert lb.parse_dat_line("A\t\tC") == ["A", "", "C"]


def test_table_name_for():
    assert lb.table_name_for("BILL_TBL.dat") == "bill_tbl"


def test_is_dat_and_is_lob():
    assert lb.is_dat("BILL_TBL.dat")
    assert not lb.is_dat("BILL_ANALYSIS_TBL_1.lob")
    assert lb.is_lob("BILL_ANALYSIS_TBL_1.lob")
    assert not lb.is_lob("BILL_TBL.dat")


def test_decode_text_replaces_undecodable_bytes():
    assert lb.decode_text(b"hello") == "hello"
    assert "�" in lb.decode_text(b"\xff\xfe")


def _make_loader_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("bill_tbl.sql", BILL_TBL_SQL)
        z.writestr("bill_version_tbl.sql", BILL_VERSION_TBL_SQL)


def test_load_column_map_from_zip(tmp_path):
    loader = tmp_path / "pubinfo_load.zip"
    _make_loader_zip(loader)
    cols = lb.load_column_map(str(loader))
    assert cols["bill_tbl"] == ["bill_id", "session_year", "measure_type"]
    assert cols["bill_version_tbl"][2] == "bill_xml"


def test_list_entries_and_classification(tmp_path):
    data = tmp_path / "pubinfo_fake.zip"
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("BILL_TBL.dat", "1\t2025\tAB\n")
        z.writestr("BILL_ANALYSIS_TBL_1.lob", "<analysis/>")
        z.writestr("BILL_ANALYSIS_TBL_2.lob", "<analysis/>")
    entries = lb.list_entries(str(data))
    assert sum(lb.is_dat(e) for e in entries) == 1
    assert sum(lb.is_lob(e) for e in entries) == 2


# Optional real-data check: runs only when a sample loader kit is present locally.
_SAMPLE_LOADER = Path(__file__).resolve().parent.parent / "sample" / "pubinfo_load.zip"


@pytest.mark.skipif(not _SAMPLE_LOADER.exists(), reason="sample/pubinfo_load.zip not present")
def test_real_loader_kit_columns():
    cols = lb.load_column_map(str(_SAMPLE_LOADER))
    # 18 tables, and bill_version's lob column resolves to bill_xml.
    assert len(cols) == 18
    assert "bill_xml" in cols["bill_version_tbl"]
