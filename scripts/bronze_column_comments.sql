-- Column-level comments for bronze tables, sourced directly from
-- leginfo.legislature.ca.gov (fetched 2026-07-23) — see docs/architecture.md
-- and the conversation that added this for context. Only columns with a real
-- citation are commented here; everything else is genuinely undocumented by
-- the data provider — don't add a guessed comment, ask a subject-matter
-- expert instead.
--
--   glossary: https://leginfo.legislature.ca.gov/faces/glossaryTemplate.xhtml
--   CONS Art. IV Sec. 8: https://leginfo.legislature.ca.gov/faces/
--     codes_displaySection.xhtml?lawCode=CONS&sectionNum=SEC.+8.&article=IV
--
-- ALTER TABLE ... ALTER COLUMN ... COMMENT is the mechanism that actually
-- works on this runtime — the parenthesized column-comment-list form on
-- CREATE OR REFRESH STREAMING TABLE (as used elsewhere in Databricks SQL
-- documentation/examples) does NOT parse here; confirmed against the live
-- pipeline, not assumed.
--
-- NOT run automatically. Lakeflow pipelines only accept CREATE MATERIALIZED
-- VIEW / CREATE STREAMING TABLE / APPLY CHANGES INTO / SET in a source file —
-- ALTER TABLE fails the whole pipeline (also confirmed live) — so this can't
-- live under src/ingest/ or any pipeline library glob. Apply by hand against
-- a SQL warehouse (substitute ${bronze_schema} yourself) after each fresh
-- table creation until this is wired into a proper job task — see
-- docs/architecture.md and CLAUDE.md's TODO (HUMANS).

ALTER TABLE ${bronze_schema}.bill
    ALTER COLUMN chapter_year
    COMMENT 'Chapter year, assigned by the SOS once the bill is chaptered (glossary: CHAPTER).';
ALTER TABLE ${bronze_schema}.bill
    ALTER COLUMN chapter_type
    COMMENT 'Chapter type, assigned at chaptering (glossary: CHAPTER).';
ALTER TABLE ${bronze_schema}.bill
    ALTER COLUMN chapter_session_num
    COMMENT 'Session number component of the chapter assignment (glossary: CHAPTER).';
ALTER TABLE ${bronze_schema}.bill
    ALTER COLUMN chapter_num
    COMMENT 'Chapter number the Secretary of State assigns once the bill is signed (glossary: CHAPTER).';
ALTER TABLE ${bronze_schema}.bill
    ALTER COLUMN current_house
    COMMENT 'Assembly or Senate (glossary: ASSEMBLY, SENATE, HOUSE OF ORIGIN).';
ALTER TABLE ${bronze_schema}.bill
    ALTER COLUMN days_31st_in_print
    COMMENT 'CONS Art. IV Sec. 8(a): bill sits in committee >=31 days after introduction, absent a 3/4 vote waiver.';

ALTER TABLE ${bronze_schema}.bill_version
    ALTER COLUMN appropriation
    COMMENT 'Whether the bill appropriates funds for a specific purpose (glossary: APPROPRIATION).';
ALTER TABLE ${bronze_schema}.bill_version
    ALTER COLUMN fiscal_committee
    COMMENT 'Whether referred to a fiscal committee (glossary: FISCAL BILL, FISCAL COMMITTEES).';
ALTER TABLE ${bronze_schema}.bill_version
    ALTER COLUMN substantive_changes
    COMMENT 'Substantive vs. nonsubstantive change — cf. a SPOT BILL (glossary: SPOT BILL).';
ALTER TABLE ${bronze_schema}.bill_version
    ALTER COLUMN urgency
    COMMENT 'Takes effect immediately, needs 2/3 vote (glossary: URGENCY CLAUSE, URGENCY MEASURE).';

ALTER TABLE ${bronze_schema}.bill_version_author
    ALTER COLUMN type
    COMMENT 'AUTHOR or COAUTHOR (glossary: AUTHOR, COAUTHOR).';
ALTER TABLE ${bronze_schema}.bill_version_author
    ALTER COLUMN house
    COMMENT 'Assembly or Senate (glossary: ASSEMBLY, SENATE).';
ALTER TABLE ${bronze_schema}.bill_version_author
    ALTER COLUMN primary_author_flg
    COMMENT 'Distinguishes the primary author from coauthors (glossary: AUTHOR, PRINCIPAL COAUTHOR).';

ALTER TABLE ${bronze_schema}.bill_analysis
    ALTER COLUMN house
    COMMENT 'Assembly or Senate (glossary: ASSEMBLY, SENATE).';
ALTER TABLE ${bronze_schema}.bill_analysis
    ALTER COLUMN analysis_type
    COMMENT 'E.g. committee vs. floor analysis (glossary: FLOOR ANALYSIS).';
ALTER TABLE ${bronze_schema}.bill_analysis
    ALTER COLUMN amendment_author
    COMMENT 'Who proposed it — author, committee, other member (glossary: AUTHOR''S/COMMITTEE/HOSTILE AMENDMENTS).';
ALTER TABLE ${bronze_schema}.bill_analysis
    ALTER COLUMN released_floor
    COMMENT 'Whether this analysis was released for floor consideration (glossary: FLOOR ANALYSIS).';

ALTER TABLE ${bronze_schema}.bill_summary_vote
    ALTER COLUMN ayes
    COMMENT 'Roll-call aye tally (glossary: ROLL CALL).';
ALTER TABLE ${bronze_schema}.bill_summary_vote
    ALTER COLUMN noes
    COMMENT 'Roll-call no tally (glossary: ROLL CALL).';
ALTER TABLE ${bronze_schema}.bill_summary_vote
    ALTER COLUMN abstain
    COMMENT 'Roll-call abstention tally (glossary: ROLL CALL).';
ALTER TABLE ${bronze_schema}.bill_summary_vote
    ALTER COLUMN file_location
    COMMENT 'Where the bill sits in the Daily File (glossary: ON FILE, ACTIVE FILE, INACTIVE FILE).';

ALTER TABLE ${bronze_schema}.bill_detail_vote
    ALTER COLUMN vote_code
    COMMENT 'This legislator''s individual roll-call vote (glossary: ROLL CALL).';

ALTER TABLE ${bronze_schema}.bill_motion
    ALTER COLUMN motion_text
    COMMENT 'Procedural motion text, e.g. reconsideration/re-referral (glossary: MOTION TO RECONSIDER, RE-REFER).';

ALTER TABLE ${bronze_schema}.veto_message
    ALTER COLUMN message
    COMMENT 'Full text of the Governor''s veto message (glossary: VETO, LINE ITEM VETO).';

ALTER TABLE ${bronze_schema}.legislator
    ALTER COLUMN house_type
    COMMENT 'Assembly or Senate (glossary: ASSEMBLY, SENATE).';

ALTER TABLE ${bronze_schema}.location_code
    ALTER COLUMN consent_calendar_code
    COMMENT 'Marks bills placed on the noncontroversial consent calendar (glossary: CONSENT CALENDAR).';
ALTER TABLE ${bronze_schema}.location_code
    ALTER COLUMN inactive_file_flg
    COMMENT 'Dormant, inactive portion of the Daily File (glossary: ACTIVE FILE, INACTIVE FILE).';

ALTER TABLE ${bronze_schema}.daily_file
    ALTER COLUMN consent_calendar_code
    COMMENT 'Marks bills placed on the noncontroversial consent calendar (glossary: CONSENT CALENDAR).';
ALTER TABLE ${bronze_schema}.daily_file
    ALTER COLUMN file_location
    COMMENT 'Where the bill sits in the Daily File (glossary: ON FILE, ACTIVE FILE, INACTIVE FILE).';
