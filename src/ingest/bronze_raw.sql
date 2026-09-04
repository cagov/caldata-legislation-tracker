-- Bronze: raw landing over the CA leginfo bill/reference tables.
--
-- Source is the per-table Parquet jobs/land_raw.py stages into the
-- ${parsed_volume} volume (inside ${bronze_schema} — environment-scoped, see
-- docs/architecture.md) after joining .dat rows to their .lob bodies — NOT the
-- shared, fixed raw-zip volume under the bronze schema — untouched source zip only.
-- All columns are raw STRING, including LOB-backed body text (BILL_XML,
-- SOURCE_DOC, MESSAGE): bronze preserves source fidelity untouched.
-- Typing/cleaning happens in silver.
--
-- ${catalog}/${bronze_schema}/${parsed_volume} come from this pipeline's
-- `configuration:` block (resources/legislation.pipeline.yml) — never hardcode
-- a schema name here; see docs/architecture.md.
--
-- Code/statute tables (CODES_TBL, LAW_TOC_TBL, LAW_TOC_SECTIONS_TBL,
-- LAW_SECTION_TBL) are deferred — see ca-leginfo-bulk-download.md.
--
-- Column-level comments live in scripts/bronze_column_comments.sql — deliberately
-- OUTSIDE src/ingest/, since Lakeflow pipelines only accept CREATE MATERIALIZED
-- VIEW / CREATE STREAMING TABLE / APPLY CHANGES INTO / SET in a source file;
-- ALTER TABLE (the only mechanism that actually adds a column comment on this
-- runtime) errors the whole pipeline if placed here. A parenthesized
-- column-comment list on CREATE OR REFRESH STREAMING TABLE ...
-- AS SELECT is NOT valid syntax on this runtime either (confirmed against the live
-- pipeline, 2026-07-23: PARSE_SYNTAX_ERROR regardless of whether every column
-- has a COMMENT or some are bare) — ALTER TABLE ... ALTER COLUMN ... COMMENT
-- is the only mechanism that actually works here.

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill
COMMENT 'One row per measure (bill ID, session, type, status, current location).'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill_version
COMMENT 'Every printed version of a bill; bill_xml is the full CAML-XML text of that version.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_VERSION_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill_version_author
COMMENT 'Authors/coauthors per bill version.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_VERSION_AUTHORS_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill_history
COMMENT 'Chronological action history per bill.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_HISTORY_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill_analysis
COMMENT 'Committee/floor analyses; source_doc is raw bytes of a binary .docx file (confirmed by inspection), not text.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_ANALYSIS_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill_summary_vote
COMMENT 'Roll-call vote totals per bill (ayes/noes/abstain), not per-legislator votes.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_SUMMARY_VOTE_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill_detail_vote
COMMENT 'Per-legislator roll-call votes.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_DETAIL_VOTE_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill_motion
COMMENT 'Motion text referenced by bill_summary_vote/bill_detail_vote via motion_id.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/BILL_MOTION_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.veto_message
COMMENT 'Governor veto messages; message is the full CAML-XML text of the veto message.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/VETO_MESSAGE_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.legislator
COMMENT 'Member roster per session year.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/LEGISLATOR_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.location_code
COMMENT 'Committee/desk location codes referenced by bill_id-adjacent tables via location_code.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/LOCATION_CODE_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.committee_hearing
COMMENT 'Scheduled committee hearings per bill.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/COMMITTEE_HEARING_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.committee_agenda
COMMENT 'Committee hearing agendas (not bill-specific).'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/COMMITTEE_AGENDA_TBL/',
    format => 'parquet'
);

CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.daily_file
COMMENT 'Daily floor file listings per bill.'
AS SELECT * FROM STREAM read_files( -- noqa: AM04
    '/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/DAILY_FILE_TBL/',
    format => 'parquet'
);
