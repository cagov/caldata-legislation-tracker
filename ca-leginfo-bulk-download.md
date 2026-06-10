# California Legislative Information (leginfo) Bulk Download — Technical Reference

**Source:** https://downloads.leginfo.legislature.ca.gov
**Maintainer:** California Office of Legislative Counsel
**Access:** Plain HTTPS, no auth, no API key. Apache directory index.
**Verified:** 2026-06-10

## 1. File Inventory

| File pattern | Contents | Size | Update cadence |
|---|---|---|---|
| `pubinfo_YYYY.zip` (1989–2025, odd years = session start) | Full data for one 2-year legislative session | 16 MB (1989) → 1.2 GB (2023); 2025 currently 930 MB | Historical sessions frozen; current session zip refreshed weekly (Sundays) |
| `pubinfo_Mon.zip` … `pubinfo_Sat.zip` | Incremental: only records new/changed since the previous day's extract | 0.3–7 MB | Daily ~21:20 PT |
| `pubinfo_daily_Mon.zip` … `pubinfo_daily_Sun.zip` | Full snapshot of current session data, excluding code (statute) tables | ~800 MB | Daily ~21:22 PT |
| `pubinfo_load.zip` | Loader kit: `capublic.sql` (schema), `loadData.bat`, `create_capublic.bat`, `truncateAll.sql`, `cleanup.bat`, table lists | 15 KB | Static (last updated 2021) |
| `pubinfo_Readme.pdf` / `.txt` | Official setup instructions | 362 KB | Static |
| `pubinfo_News.pdf` / `.txt` | Announcements | 85 KB | Static |

Session zips are keyed by the odd year that starts the 2-year session (e.g., `pubinfo_2025.zip` = 2025–2026 session).

## 2. Data Format Inside the Zips

Each zip contains:

- **`*_TBL.dat` files** — tab-delimited rows, one file per database table.
- **`*.lob` files** — one file per large-object record (full bill text, bill analyses, law section text). Referenced by row in the corresponding `.dat` file. Bill version text LOBs are XML.
- The schema is defined in `capublic.sql` (in `pubinfo_load.zip`), targeting MySQL with a database named `capublic`.

## 3. Tables (17)

**Bill data:**
- `BILL_TBL` — one row per measure (bill ID, session, type, status, current location)
- `BILL_VERSION_TBL` — every printed version of a bill; full text lives in associated `.lob` (XML)
- `BILL_VERSION_AUTHORS_TBL` — authors/coauthors per version
- `BILL_HISTORY_TBL` — chronological action history
- `BILL_ANALYSIS_TBL` — committee/floor analyses (LOB-backed)
- `BILL_SUMMARY_VOTE_TBL` / `BILL_DETAIL_VOTE_TBL` — roll-call vote totals and per-legislator votes
- `BILL_MOTION_TBL` — motion text for votes
- `VETO_MESSAGE_TBL` — governor veto messages

**Statute (codified law) data:**
- `CODES_TBL` — the 29 California Codes
- `LAW_TOC_TBL` / `LAW_TOC_SECTIONS_TBL` — table-of-contents hierarchy
- `LAW_SECTION_TBL` — individual code sections; text in `.lob` files

**Reference data:**
- `LEGISLATOR_TBL` — member roster per session
- `LOCATION_CODE_TBL` — committee/desk location codes
- `COMMITTEE_HEARING_TBL`, `COMMITTEE_AGENDA_TBL`, `DAILY_FILE_TBL` — scheduling

Note: law/code tables appear only in the weekly session zip, not the `pubinfo_daily_*` snapshots.

## 4. Recommended Ingestion Pipeline

1. **Bootstrap:** download `pubinfo_load.zip`; use `capublic.sql` as the authoritative schema (port to Postgres/SQLite as needed — types are simple: varchar, date, LOB pointers).
2. **Initial load:** download `pubinfo_2025.zip` (current session, ~930 MB) and any needed historical session zips. Unzip; bulk-load each `.dat` (tab-delimited, `LOAD DATA INFILE` or equivalent); resolve `.lob` references for full text.
3. **Stay current (pick one):**
   - **Low bandwidth:** apply the small `pubinfo_<Day>.zip` incrementals Mon–Sat; reload the full session zip on Sundays (official process per Readme: delete session data, reload `pubinfo_YYYY.zip`).
   - **Simpler/idempotent:** re-download `pubinfo_daily_<Day>.zip` (~800 MB) nightly and truncate-and-reload; pull the weekly session zip when statute tables are needed.
4. **Markdown conversion (for Claude consumption):** parse bill version XML from `.lob` files → strip to text/markdown, one `.md` per bill version, with frontmatter from `BILL_TBL`/`BILL_VERSION_TBL` (bill ID, session, version date, status, authors).

## 5. Gotchas

- Files post ~21:20 Pacific daily; don't schedule pulls earlier.
- `.dat` files are tab-delimited with embedded LOB filename references — not CSV; quoting rules differ.
- Bill text XML uses Legislative Counsel's schema (caml namespace); strikeout/italic amendment markup is encoded in tags and matters for "as amended" readings.
- Pre-1999 data exists in the archives but the modern leginfo website only covers 1999+; the zips are the only official bulk source for older sessions.
- Loader scripts are Windows .BAT samples only; treat as documentation, not production tooling.

## 6. Alternatives Considered

- **LegiScan** (legiscan.com/CA/datasets): JSON/CSV/XML, cleaner API, but third-party and rate/licensing constraints.
- **leginfo.legislature.ca.gov website**: search UI only, no bulk export.
- The official zips are authoritative and free; preferred for full-corpus work.
