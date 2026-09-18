# California Legislative Information (leginfo) Bulk Download — Technical Reference

**Source:** https://downloads.leginfo.legislature.ca.gov
**Maintainer:** Legislative Counsel of California (official leginfo system)
**Access:** Plain HTTPS, no auth, no API key. Apache directory index.
**Verified:** 2026-06-10 (initial)

## 1. File Inventory

| File pattern | Contents | Size | Update cadence |
|---|---|---|---|
| `pubinfo_YYYY.zip` (1989–2025, odd years = session start) | Full data for one 2-year legislative session | 16 MB (1989) → 1.2 GB (2023); 2025 currently 930 MB | Historical sessions frozen; current session zip refreshed weekly (Sundays) |
| `pubinfo_Mon.zip` … `pubinfo_Sat.zip` | Incremental: only records new/changed since the previous day's extract | 0.3–7 MB | Daily ~21:20 PT |
| `pubinfo_daily_Mon.zip` … `pubinfo_daily_Sun.zip` | Full snapshot of current-session non-code data; excludes code/statute tables | ~800 MB | Daily ~21:22 PT |
| `pubinfo_load.zip` | Loader kit: `capublic.sql` (schema), `loadData.bat`, `create_capublic.bat`, `truncateAll.sql`, `cleanup.bat`, table lists | 15 KB | Static (last updated 2021) |
| `pubinfo_Readme.pdf` / `.txt` | Official setup instructions | 362 KB | Static |
| `pubinfo_News.pdf` / `.txt` | Announcements | 85 KB | Static |

Session zips are keyed by the odd year that starts the 2-year session (e.g., `pubinfo_2025.zip` = 2025–2026 session).

## 2. Data Format Inside the Zips

Each zip contains:

- **`*_TBL.dat` files** — tab-delimited rows, one file per database table.
- **`*.lob` files** — one file per large-object record (full bill text, bill analyses, veto messages, law section text). Referenced by row in the corresponding `.dat` file. **Format is not uniform** (confirmed by direct inspection of a real `pubinfo_2025.zip`, 2026-07-22 — this is not stated anywhere in the official docs/loader kit): `BILL_VERSION_TBL`'s `BILL_XML` and `VETO_MESSAGE_TBL`'s `MESSAGE` LOBs are UTF-8 CAML-XML/plain text, but `BILL_ANALYSIS_TBL`'s `SOURCE_DOC` LOBs are **binary OOXML `.docx` files** (100% of a full-spread sample across all 19,206 analysis rows started with the `PK\x03\x04` zip magic bytes — committee/floor analyses are apparently authored as Word documents and attached as-is, not run through the CAML-XML system bill text uses). Any ingestion code that assumes all LOBs are UTF-8 text will throw a `UnicodeDecodeError` on `BILL_ANALYSIS_TBL` specifically — this was hit and fixed during implementation (see `jobs/land_raw.py`), not caught in planning.
- The schema is defined in `capublic.sql` (in `pubinfo_load.zip`), targeting MySQL with a database named `capublic`.

## 3. Tables (18, per the loader SQL files in `pubinfo_load.zip`)

**Bill data:**
- `BILL_TBL` — one row per measure (bill ID, session, type, status, current location)
- `BILL_VERSION_TBL` — every printed version of a bill; full text lives in associated `.lob` (XML)
- `BILL_VERSION_AUTHORS_TBL` — authors/coauthors per version
- `BILL_HISTORY_TBL` — chronological action history
- `BILL_ANALYSIS_TBL` — committee/floor analyses; LOB-backed, but the LOB (`SOURCE_DOC`) is a binary `.docx` file, not text/XML — see §2
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

Note: law/code tables appear only in the weekly session zip, not the `pubinfo_daily_*` snapshots. The daily snapshot is therefore a replacement for current-session bill, vote, author, history, analysis, veto, roster, location, committee, agenda, and daily-file tables, but not for `CODES_TBL`, `LAW_TOC_TBL`, `LAW_TOC_SECTIONS_TBL`, or `LAW_SECTION_TBL`.

### 3.1 File count — why this dataset is a small-files problem

A real `pubinfo_2025.zip` was downloaded and inspected (2026-07-22): **1.1 GB compressed → 1.94 GB uncompressed → 198,032 files.** Only 18 of those are `.dat` files (one per table, fixed count regardless of session size); the rest are `.lob` files — one per record with body text:

| Source | `.lob` files | Share |
|---|---|---|
| `LAW_SECTION_TBL` (codified law text) | 162,437 | 82% |
| `BILL_ANALYSIS_TBL` | 19,206 | 10% |
| `BILL_VERSION_TBL` | 16,247 | 8% |
| `VETO_MESSAGE_TBL` | 124 | <1% |

`LAW_SECTION_TBL` was confirmed (via `capublic.sql` and a sample LOB) to hold the full current text of every section of all 29 California Codes — real codified law (`active_flg='Y'` uniformly), not pending/diff text — dominating the file count by itself. Bill/reference-only ingestion (this doc's v1 scope) faces ~35,600 LOBs instead of 198K.

Materializing that many files anywhere — a Unity Catalog volume, or an agent/loop enumerating them one at a time — is the classic small-files problem: Spark/Auto Loader per-file listing and task-scheduling overhead dominates over actual data volume, and an LLM agent iterating file-by-file burns its context/turn budget the same way. Section 4 avoids ever materializing per-record LOBs as loose files.

## 4. Recommended Ingestion Pipeline

**v1 scope: current-session bill/reference tables only** (`BILL_TBL`, `BILL_VERSION_TBL`, `BILL_VERSION_AUTHORS_TBL`, `BILL_HISTORY_TBL`, `BILL_ANALYSIS_TBL`, `BILL_SUMMARY_VOTE_TBL`, `BILL_DETAIL_VOTE_TBL`, `BILL_MOTION_TBL`, `VETO_MESSAGE_TBL`, `LEGISLATOR_TBL`, `LOCATION_CODE_TBL`, `COMMITTEE_HEARING_TBL`, `COMMITTEE_AGENDA_TBL`, `DAILY_FILE_TBL`) — a one-shot manual run of `pubinfo_2025.zip`, no schedule yet. Code/statute tables (`CODES_TBL`, `LAW_TOC_TBL`, `LAW_TOC_SECTIONS_TBL`, `LAW_SECTION_TBL`) and the daily/weekly schedule split are deferred follow-ups (§3.1's 162K-file corpus warrants its own pass once bill ingestion is proven).

**The core idea: collapse ~198K files into a few dozen Parquet files, in one Python pass, before Lakeflow ever sees the data.** Lakeflow/Auto Loader can't read inside a zip or join a `.dat` row to its `.lob` file by filename — that join has to happen in Python, once, and the output has to be columnar, not one file per record.

Implement one landing script at **`jobs/land_raw.py`** (not `src/ingest/` — that directory's glob (`resources/legislation.pipeline.yml`) loads every file under it as Lakeflow pipeline source, and this is a single-node job task, not pipeline code). Run it as a Databricks Job task before the Lakeflow pipeline task in `resources/legislation.job.yml`, on serverless job compute (no cluster — this is sequential single-archive work, not something a cluster helps with). Do not use GitHub Actions or Airflow for this project.

1. **Bootstrap schema:** `capublic.sql` (from `pubinfo_load.zip`) is the authoritative source schema; `jobs/land_raw.py` hardcodes the column order for each in-scope table directly from the `*_tbl.sql` loader files (types are simple: varchar, date, LOB pointers — kept as raw `STRING` in bronze, see below).
2. **Download + preserve raw:** stream-download the target zip (stdlib `urllib`, chunked, never buffered whole in memory — see §9 for why not `requests`) to local disk, then copy the original `.zip` itself — one file — plus a manifest (source URL, `Last-Modified`, `Content-Length`, sha256, fetch time, run mode) to the Unity Catalog raw volume (`resources/legislation.catalog.yml` declares the `bronze` schema and a `raw` managed volume as bundle resources). **Never extract the exploded `.dat`/`.lob` files to the volume** — that's exactly the small-files problem this design avoids.
3. **Parse in-process, batched:** open the zip once with `zipfile.ZipFile` (loads only the central directory — filename/offset metadata, not LOB content). For each in-scope `.dat` file, iterate rows; for LOB-backed tables (`BILL_VERSION_TBL`, `BILL_ANALYSIS_TBL`, `VETO_MESSAGE_TBL`) resolve the row's LOB filename via `zf.open()`'s random access and inline the decoded text as that row's column value. Buffer ~5,000 rows at a time and flush each batch to its own Parquet part file — peak memory is one batch, independent of table size, so the same code handles a 124-row table today and a 162K-row one later without change. Result: one folder of a handful of Parquet files per table (~14 folders, dozens of files total) instead of ~35,600 loose LOBs.
4. **Bronze loading:** Lakeflow (`src/ingest/*.sql`) reads the landed Parquet via `read_files()` into one `STREAMING TABLE` per source table — trivial now, since it's reading dozens of files, not tens of thousands. LOB text lands as a raw, unparsed `STRING` column (CAML-XML); do not convert bill text to Markdown or parse the XML at bronze — that belongs in silver/downstream.
5. **Nightly current-session refresh (follow-up, not v1):** after 21:30 PT, download that day's `pubinfo_daily_<Day>.zip` (~800 MB) and re-run the same script against the daily-scoped tables. Keep code/statute tables from the latest weekly `pubinfo_YYYY.zip`.
6. **Weekly code/statute refresh (follow-up, not v1):** after the Sunday session zip is posted, run the script against `CODES_TBL`/`LAW_TOC_TBL`/`LAW_TOC_SECTIONS_TBL`/`LAW_SECTION_TBL` — decoupled from the daily bill cadence since the source itself only refreshes these weekly. Historical session zips are frozen and should be loaded once unless backfill is explicitly requested.

## 5. Key Notes

- Files post ~21:20 Pacific daily; don't schedule pulls earlier.
- `.dat` files are tab-delimited with embedded LOB filename references — not CSV; quoting rules differ.
- Bill version text (`BILL_VERSION_TBL.BILL_XML`) and veto messages (`VETO_MESSAGE_TBL.MESSAGE`) use Legislative Counsel's CAML XML schema; strikeout/italic amendment markup is encoded in tags and matters for "as amended" readings. **Bill analyses (`BILL_ANALYSIS_TBL.SOURCE_DOC`) are binary `.docx`, not CAML XML or any text format** — see §2; confirmed by inspection, not documented by the data provider.
- Pre-1999 data exists in these archives; the modern leginfo website only covers 1999+ (older measures live at the legacy leginfo.ca.gov archive). These zips are the primary official bulk source for older sessions.
- Loader scripts are samples only; treat as documentation, not production tooling.
- Markdown conversion, if needed for downstream search or review, belongs in a downstream transform/publish step after the raw XML/docx has been preserved.

## 6. Alternatives Considered

- **LegiScan** (legiscan.com/CA/datasets): JSON/CSV/XML, cleaner API, but third-party and rate/licensing constraints.
- **leginfo.legislature.ca.gov website**: search UI only, no bulk export.
- The official zips are authoritative and free; preferred for full-corpus work.

## 7. Acceptance Criteria Mapping

| Criterion | Status |
|---|---|
| Technical `.md` reference exists and is reviewable | This file. It provides everything needed to reason about and operate on the dataset: source URL, file inventory, schema, formats, ingestion steps. |
| Human-audience summary exists and is reviewable | `ca-leginfo-summary.md` (companion file). |
| Bulk download executed | **Done, 2026-07-23** — all 14 v1 bill/reference tables landed in the real dev workspace (`dev_andrew_king_bronze`), row counts verified against source `.dat` line counts, binary `.docx` content spot-checked end to end. Executed via a local-machine workaround (see §9) rather than the `land_raw` job task itself, because outbound HTTPS from Databricks serverless compute to the source domain is currently blocked by a TLS-inspecting network proxy with no trusted CA configured — that's unresolved and tracked separately, not a code issue. |

## 8. Verification Sources

- Live directory index at https://downloads.leginfo.legislature.ca.gov (fetched 2026-06-10): file names, sizes, last-modified timestamps.
- `pubinfo_Readme.pdf` (official, dated 2021-05-21, fetched 2026-06-10): file descriptions, table/loader inventory, weekly/daily update process.
- **Direct inspection of a real, fully-downloaded `pubinfo_2025.zip`** (2026-07-22): exact file counts (§3.1), and the `BILL_ANALYSIS_TBL` binary-`.docx` LOB finding (§2, §5). Neither the live directory index nor `pubinfo_Readme.pdf` documents per-record file counts or LOB content-type — these were only discoverable by unzipping the archive and sampling its contents, which is how they were found here. Treat this doc's file-count and LOB-format claims as more authoritative than the provider's own documentation, which is silent on both.
- Statements not directly verifiable from any of the above (e.g., full caml XML tag semantics) are based on documented characteristics of the dataset and should be spot-checked against an actual `.lob` file during implementation.

## 9. Resolved: `SSLCertVerificationError` on download was a stale certifi bundle (2026-09-04)

**Symptom.** Running `jobs/land_raw.py` as the `land_raw` Databricks Job task
failed within ~40s with
`SSLCertVerificationError: ... self-signed certificate in certificate chain`
while fetching `downloads.leginfo.legislature.ca.gov`.

**This was originally diagnosed as a TLS-inspecting egress proxy. That was
wrong** — nothing intercepts this workspace's traffic. The server presents the
genuine public leginfo certificate, and `openssl s_client` from serverless
reports `Verify return code: 0 (ok)`.

**Actual cause: which trust store the HTTP client consults.** leginfo's chain
anchors at a root that the runtime's vendored certifi bundle predates:

```
0 s:CN = *.leginfo.legislature.ca.gov
  i:Entrust DV TLS Issuing RSA CA 2
1 s:Entrust DV TLS Issuing RSA CA 2
  i:Sectigo Public Server Authentication Root R46   ← self-signed root
```

Verified on serverless compute (2026-09-04):

| Client | Trust store consulted | Has the Sectigo root? | Result |
| --- | --- | --- | --- |
| stdlib `urllib` | OS store, `/usr/lib/ssl/certs` (122 roots) | yes | `200`, 1,267,605,195 bytes |
| `requests` | vendored `certifi` 2022.12.07 (138 roots, **no Sectigo roots at all**) | no | `CERTIFICATE_VERIFY_FAILED` |

`requests` ignores the OS trust store by design, defaulting `verify` to
`certifi.where()`; `urllib` passes no CA path and so inherits OpenSSL's
compiled-in default, which is the OS store. Handing `requests` that one Sectigo
root explicitly (`verify=/usr/lib/ssl/certs/Sectigo_Public_Server_Authentication_Root_R46.pem`)
also succeeds, confirming the missing anchor was the only fault. OpenSSL's
"self-signed certificate in certificate chain" wording describes *any*
untrusted terminal root — it is not evidence of interception, which is what made
this look like an infrastructure problem for six weeks.

**Fix (applied).** `download_zip()` uses stdlib `urllib`, and `requests` is
dropped as a dependency (`pyproject.toml`, and the `land_raw` environment spec
in `resources/legislation.job.yml`). Do **not** "fix" this class of error by
disabling certificate verification. Two rejected alternatives, for the record:
pinning a newer `certifi` leaves trust dependent on a transitive package
version, and the failing traceback showed the *preinstalled* `requests` 2.28.1
being used despite the env spec declaring the dependency; hardcoding
`verify="/usr/lib/ssl/certs"` bakes a DBR image path into the job.

**Note on `ssl.get_default_verify_paths()`** on this image: `openssl_cafile`
(`/usr/lib/ssl/cert.pem`) **does not exist** — only `openssl_capath`
(`/usr/lib/ssl/certs`) does. Any fix that passes the reported `cafile` to a
client will fail with `invalid path`.

**Local escape hatch (still available, no longer required).**
`jobs/land_raw.py --local-zip <path>` with `--raw-root`/`--parsed-root`
overrides runs download-and-parse on a developer's machine; `databricks fs cp -r`
each local directory to its Unity Catalog volume path, then trigger the pipeline
(`databricks bundle run legislation_pipeline -t dev`). The v1 bill tables were
loaded this way on 2026-07-23, when the job task was believed to be blocked.
Useful now mainly for re-parsing an already-downloaded zip without refetching
1.2 GB.
