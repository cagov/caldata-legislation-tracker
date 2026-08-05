# California Legislative Information (leginfo) Bulk Download — Technical Reference & Ingestion Plan

**Source:** https://downloads.leginfo.legislature.ca.gov
**Maintainer:** Legislative Counsel of California (official leginfo system)
**Access:** Plain HTTPS, no auth, no API key. Apache directory index.
**Verified:** 2026-08-05 (live directory index, README PDF, and inspection of sample zips)

This is the canonical, version-controlled plan for landing and structuring the leginfo bulk
data — it records both what the dataset *is* and how we ingest it.

## 1. File Inventory (verified 2026-08-05)

| File | Contents | Size | Days present | Cadence |
|---|---|---|---|---|
| `pubinfo_YYYY.zip` (odd years 1989–2025) | Full data for one 2-year session, **including** code/statute tables | 16 MB (1989) → 1.1 GB (2025) | one per session | Historical frozen; current session refreshed **Sundays** ~21:25 |
| `pubinfo_daily_<Day>.zip` | **Near-full snapshot** of current session **excluding** code tables | ~0.95 GB | **Mon–Sun** | Nightly ~21:23–21:28 |
| `pubinfo_<Day>.zip` | **True incremental** — only records new/changed since the prior day's extract | 0.5–14 MB | **Mon–Sat** (no Sun) | Nightly ~21:20 |
| `pubinfo_load.zip` | Loader kit: `capublic.sql` (schema), per-table `LOAD DATA` scripts, `loadData.bat`, `deleteSession.bat`, `truncateAll.sql`, table lists | 15 KB | static | Static (2021) |
| `pubinfo_Readme.pdf` | Official setup instructions (the `.txt` is now just an 83-byte "see the PDF" stub) | 362 KB | static | Static |
| `pubinfo_News.pdf` | Announcements (`.txt` likewise a stub) | 85 KB | static | Static |

**Even-year session zips are absent by design.** California legislative sessions are two-year,
keyed to the odd starting year: `pubinfo_2025.zip` = the 2025–2026 session, `pubinfo_2023.zip` =
2023–2024, etc. There is no `pubinfo_2024.zip` — this is not missing data.

**Posting times** (~21:20–21:28) are inferred from index `Last-Modified` stamps and are almost
certainly Pacific (the CA Legislature), but the README does not state a timezone. Don't schedule
pulls before ~21:30 PT.

## 2. Data Format Inside the Zips

Each zip contains:

- **`*_TBL.dat` files** — tab-delimited rows (`\t` field sep, `\n` line sep, values optionally
  enclosed by `` ` ``), one file per database table. **Not CSV** — quoting rules differ.
- **`*.lob` files** — one file per large-object record (full bill text, bill analyses, law
  section text). A `.dat` row references its LOB **by filename in a column**: the loader does
  `SET BILL_XML = LOAD_FILE(concat('c:\\pubinfo\\', <that column>))`. Bill-version text LOBs are
  XML. LOB filenames follow `<TABLE>_TBL_<n>.lob`.
- The schema is defined in `capublic.sql` (in `pubinfo_load.zip`), targeting MySQL, database
  `capublic`. It is the authoritative per-table column list.

## 3. Tables (18, per the loader SQL files in `pubinfo_load.zip`)

**Bill data:**
- `BILL_TBL` — one row per measure (bill ID, session, type, status, current location)
- `BILL_VERSION_TBL` — every printed version of a bill; full text in an associated `.lob` (XML)
- `BILL_VERSION_AUTHORS_TBL` — authors/coauthors per version
- `BILL_HISTORY_TBL` — chronological action history
- `BILL_ANALYSIS_TBL` — committee/floor analyses (LOB-backed)
- `BILL_SUMMARY_VOTE_TBL` / `BILL_DETAIL_VOTE_TBL` — roll-call vote totals and per-legislator votes
- `BILL_MOTION_TBL` — motion text for votes
- `VETO_MESSAGE_TBL` — governor veto messages

**Statute (codified law) data — the "Code tables":**
- `CODES_TBL` — the California Codes
- `LAW_TOC_TBL` / `LAW_TOC_SECTIONS_TBL` — table-of-contents hierarchy
- `LAW_SECTION_TBL` — individual code sections; text in `.lob` files

**Reference data:**
- `LEGISLATOR_TBL` — member roster per session
- `LOCATION_CODE_TBL` — committee/desk location codes
- `COMMITTEE_HEARING_TBL`, `COMMITTEE_AGENDA_TBL`, `DAILY_FILE_TBL` — scheduling

**Keys:** only **4 of the 18 tables declare a key** in `capublic.sql` — `BILL_TBL.bill_id`,
`BILL_VERSION_TBL.bill_version_id`, `BILL_ANALYSIS_TBL.analysis_id`, `BILL_MOTION_TBL.motion_id`.
The other 14 are keyless. This is the deciding factor for the refresh strategy (§6).

## 4. The three refresh channels (mind the naming trap)

The source publishes **three** update mechanisms. The names are misleading — the "daily" files
are near-full snapshots, and the *actually* incremental files are the tiny per-weekday ones.

| Channel | File(s) | Days | Size | Contents | Code tables? |
|---|---|---|---|---|---|
| **Weekly full** | `pubinfo_YYYY.zip` | Sun | 1.1 GB | Entire current session | ✅ included |
| **Daily snapshot** | `pubinfo_daily_<Day>.zip` | Mon–Sun | ~0.95 GB | Full current session **minus** code tables | ❌ excluded |
| **True incremental** | `pubinfo_<Day>.zip` | Mon–Sat | 0.5–14 MB | Only rows new/changed since the prior extract (with their `.lob` bodies) | n/a |

Measured on 2026-08-05 samples: full session = **198,476 `.lob` + 18 `.dat`**; daily snapshot =
31,543 `.lob` + 14 `.dat`; a weekday incremental = 52 `.lob` + 6 changed `.dat` (~1.8 MB). The
four tables in the full but not the daily snapshot are exactly `CODES_TBL`, `LAW_SECTION_TBL`,
`LAW_TOC_TBL`, `LAW_TOC_SECTIONS_TBL`.

**Load semantics.** Every per-table loader is `LOAD DATA … REPLACE` (upsert on key) **except
`LAW_SECTION_TBL` (plain insert)**. **Deletions are not carried by incrementals** — the only
delete path is the weekly Sunday process: `deleteSession.bat` wipes the session (by `bill_id` /
`session_year` prefix), then the full `pubinfo_YYYY.zip` is reloaded. So the official model is
*Mon–Sat apply incrementals, Sunday wipe-and-full-reload*, and deletions reconcile with up-to-
one-week latency.

## 5. Ingestion architecture

Landing is a Databricks **Job task** (`src/ingest/land_raw.py`) that runs before the Lakeflow
**pipeline** task in `resources/legislation.job.yml`. Do not use GitHub Actions or Airflow.

**Hard-won lesson — do not extract onto the volume.** A first attempt unzipped
`pubinfo_2025.zip` directly onto the FUSE-mounted UC volume. It ran 1 h 44 m before being
cancelled: the session zip expands to ~198 k tiny `.lob` files, and per-file create/close over
the `/Volumes` FUSE mount is latency-bound (even *listing* the directory timed out at 60 s).
Small files on FUSE is the wrong layout for object storage and Delta.

The load therefore splits into two responsibilities:

1. **`land_raw` (Job task) — land zips only.** Stream each needed zip from the source straight
   into the raw volume (`/Volumes/<catalog>/bronze/raw/zips/`) and write a manifest (source URL,
   `Last-Modified`, `Content-Length`, sha256, fetch time, run mode). A handful of large files —
   seconds, not hours. **No extraction.**

2. **bronze (Lakeflow pipeline) — unzip in-memory, in parallel.** A zip is not splittable, so
   parallelism comes from fanning out its *entries*: the driver reads the zip's central
   directory (cheap), distributes entry names across executors, and each task reopens the zip
   from the volume and inflates only its assigned entries — writing rows **directly to Delta**.
   No loose `.lob` files ever hit the volume. `numSlices`/partition count is the parallelism
   dial; serverless autoscales to it. (Concurrent reads of one ~1 GB zip over FUSE are fine —
   reads, not writes; if contention ever bites, copy the zip to executor-local disk once per
   partition.)

   Bronze tables:
   - **`bronze.lob_raw`** — a single table `(lob_name, content, source_zip, _ingested_at)` keyed
     by LOB filename. Silver joins it onto version/analysis/section rows via the `.dat` LOB
     references (§2). Preserve LOB XML/text as source data — no Markdown conversion in ingestion.
   - **`bronze.<table>_raw`** — one per `*_TBL.dat`, tab-delimited, parsed from the same zip.
     Start string-typed with a rescue column; type in silver using `capublic.sql` as the column
     reference. Watch memory on the large tables (`LAW_SECTION_TBL`, `BILL_VERSION_TBL`).

Cleanup: a partial `extracted/pubinfo_2025/` directory remains in the volume from the cancelled
run; delete it (slow over FUSE — low priority).

## 6. Refresh strategy — full-refresh snapshot (committed)

We refresh the current session by **full overwrite**, not row-level merge:

- **Nightly:** land `pubinfo_daily_<Day>.zip` and rebuild the current-session **non-code** bronze
  tables (and `bronze.lob_raw`) from it, overwriting.
- **Weekly (Sunday):** land `pubinfo_YYYY.zip` and rebuild **all** current-session tables,
  including the code/statute tables, overwriting.
- Historical session zips are frozen — load once, only on explicit backfill request.

**Why full-refresh over incremental MERGE:** 14 of 18 tables are keyless (§3), so a per-table
upsert would require reverse-engineering natural keys, and deletions need the weekly full reload
regardless (§4). Full-refresh needs no keys and no CDC, handles deletes for free, and is a single
code path. Reprocessing cost is acceptable because the in-bronze parallel unzip (§5) is
Spark-distributed. The tiny `pubinfo_<Day>.zip` incrementals remain a **deferred optimization**,
worth revisiting only if refresh cost or latency demands it (and only after defining keys).

## 7. Key Notes

- Files post ~21:20–21:28 (inferred Pacific); don't schedule pulls before ~21:30 PT.
- Bill-text XML uses Legislative Counsel's schema (caml namespace); strikeout/italic amendment
  markup is encoded in tags and matters for "as amended" readings.
- Pre-1999 data exists in these archives; the modern leginfo website only covers 1999+ (older
  measures live at the legacy leginfo.ca.gov archive). These zips are the primary official bulk
  source for older sessions.
- Loader scripts (`*.bat`, per-table `LOAD DATA` `.sql`) are MySQL samples — treat as
  documentation of intent (semantics, LOB wiring), not production tooling.
- Markdown conversion, if needed downstream, belongs in a transform/publish step after the raw
  XML is preserved.

## 8. Alternatives Considered

- **LegiScan** (legiscan.com/CA/datasets): JSON/CSV/XML, cleaner API, but third-party and
  rate/licensing constraints.
- **leginfo.legislature.ca.gov website**: search UI only, no bulk export.
- The official zips are authoritative and free; preferred for full-corpus work.

## 9. Acceptance Criteria Mapping

| Criterion | Status |
|---|---|
| Technical `.md` reference exists and is reviewable | This file — source, inventory, formats, refresh channels, and the ingestion architecture. |
| Human-audience summary exists and is reviewable | Moved into the tracking story (the companion `ca-leginfo-summary.md` file was removed). |
| Bulk download executed | **Land step implemented and validated** — `land_raw` downloads the zips in seconds (the 1.1 GB session zip landed successfully). Extraction relocated to the bronze pipeline (§5), which is the next implementation pass. |

## 10. Verification Sources

- Live directory index at https://downloads.leginfo.legislature.ca.gov (fetched 2026-08-05):
  file names, sizes, `Last-Modified` timestamps.
- `pubinfo_Readme.pdf` (official, dated 2021-05-21; text layer of pp. 1–3 recovered — p. 4 is
  image-only): file descriptions, table/loader inventory, weekly/daily update process.
- Inspection of sample zips `pubinfo_Wed.zip`, `pubinfo_daily_Wed.zip`, `pubinfo_2025.zip`,
  `pubinfo_load.zip` (2026-08-05): entry counts, `.dat`/`.lob` composition, the full−daily table
  diff, `LOAD DATA … REPLACE` semantics, LOB-by-filename wiring, and per-table keys.
- Unverified / to spot-check during implementation: caml XML markup details; whether the daily
  snapshot's "except Code tables" set is exactly the four observed; posting timezone.
