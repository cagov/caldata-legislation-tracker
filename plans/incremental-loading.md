# Incremental loading for CA leginfo bulk exports

## Context

`jobs/land_raw.py` + `src/ingest/bronze_raw.sql` today do a **one-shot manual load** of
`pubinfo_2025.zip` into 14 bronze `STREAMING TABLE`s. There is no schedule, and the streaming
semantics are wrong for the source: every leginfo export is a *full current-session snapshot*,
not an append-only feed. `CLAUDE.md`'s TODO and `pr-reconciliation-plan.md:576-587` both flag
this as unresolved and blocked on understanding the publication cadence.

This plan resolves the cadence question with direct evidence from the sample zips and the live
site, then makes the pipeline run nightly with correct full-replace semantics.

---

## What's actually in each export (measured, 2026-09-18)

The site publishes **three channels**. The names are a trap: `pubinfo_daily_<Day>.zip` is the
*full snapshot*, and `pubinfo_<Day>.zip` — which reads like a weekly — is the *daily delta*.

| Channel | Size / entries | Cadence | Tables | Semantics |
|---|---|---|---|---|
| `pubinfo_YYYY.zip` | 1.2 GB — 18 `.dat` + 198,476 `.lob` | **Weekly, Sundays ~21:26 PT**; frozen permanently once the session ends | **All 18**, incl. `CODES_TBL`, `LAW_TOC_TBL`, `LAW_TOC_SECTIONS_TBL`, `LAW_SECTION_TBL` | Full session snapshot |
| `pubinfo_daily_<Day>.zip` | ~1.1 GB — 14 `.dat` + 31,543 `.lob` | **Daily ~21:23 PT**, 7 rotating files Sun–Sat | **14** bill/reference tables — *no* law/code tables | Full current-session snapshot |
| `pubinfo_<Day>.zip` | 26 KB–1.3 MB — 4–8 `.dat` + a few `.lob` | **Daily ~21:20 PT**, 6 files Mon–Sat (no Sunday) | Only the tables that changed that day | Incremental upsert, **no deletes** |

Evidence for "weekly on Sunday": `pubinfo_2025.zip` last modified Sun 2026-09-13 21:26 PT, and
every frozen prior-session archive (2017, 2019, 2021, 2023) also lands on a Sunday.

### Findings that drive the design

1. **The 14/4 table split already matches the code.** The 14 tables in `land_raw.py`'s `TABLES`
   dict are *byte-for-byte the same set* as the daily snapshot's `.dat` files (verified by
   `diff`), and the 4 deferred code/statute tables are exactly the weekly-only remainder.
   The daily/weekly channel split falls out of the existing scope for free.

2. **Deltas can't carry deletions.** The loader kit (`pubinfo_load.zip`, static since 2021) uses
   `LOAD DATA ... REPLACE` — an upsert — for 17 of 18 tables (`LAW_SECTION_TBL` is a plain
   insert). The only delete path the vendor ships is `deleteSession.bat`, a manual, interactive,
   session-scoped `DELETE ... WHERE bill_id LIKE '<session>%'` wipe. Deletions only reconcile on
   a full reload.

3. **Only 4 of 18 tables declare a `PRIMARY KEY`** in `capublic.sql` (`bill_tbl.bill_id`,
   `bill_version_tbl.bill_version_id`, `bill_analysis_tbl.analysis_id`,
   `bill_motion_tbl.motion_id`). A `MERGE`/`APPLY CHANGES INTO` strategy would require
   reverse-engineering composite keys for the other 14.

4. **Delta table coverage is not stable.** Across the six live delta zips: Thu carried 4 tables,
   Sat carried 8, and `BILL_DETAIL_VOTE_TBL` / `BILL_SUMMARY_VOTE_TBL` / `LEGISLATOR_TBL` /
   `VETO_MESSAGE_TBL` appeared in none. Only `BILL_TBL` and `BILL_HISTORY_TBL` were present in
   all six.

5. **`.lob` filenames are export-local sequence numbers, not stable IDs.** The same analysis is
   `BILL_ANALYSIS_TBL_1.lob` in a delta zip and `BILL_ANALYSIS_TBL_6380.lob` in the annual. The
   `.dat` row carries its own lob filename, so the join must happen *within a single zip*.
   (`land_raw.py` already does this correctly.)

6. **Filenames lie about freshness — this is the key operational risk.** `pubinfo_Sat.zip` has
   not been regenerated since 2026-08-29, three weeks stale. The `sample/pubinfo_daily_Wed.zip`
   downloaded on 2026-08-05 contains data only through 2026-06-03. Under full-replace semantics,
   blindly loading "today's" file would **roll bronze backwards**. Freshness must be decided by
   `Last-Modified`/`sha256`, never by day-of-week.

7. **Bill-text changes are fully recoverable — but only if bronze preserves the XML verbatim.**
   See the section below; this constrains the bronze design.

---

## Can we reason about sections struck or added?

Yes — on both meanings of the question, and the snapshot-replace design preserves all of it.
Three independent mechanisms, verified against the sample data:

**a. What the bill does to existing law — structured and directly queryable.** Each
`<caml:BillSection>` carries a `<caml:ActionLine action="…">` whose vocabulary across 60 sampled
versions is `IS_AMENDED` (78), `IS_ADDED` (47), `IS_REPEALED` (2), together with a
`<caml:DocName>` naming the code and an `xlink:href` URN pointing at the target law section.
So "which Insurance Code sections does AB 69 add vs. amend" is a parse, not an inference.

**b. Full version history is retained.** `BILL_VERSION_TBL` holds every printed version —
16,247 rows for the session, 7 versions of AB 69, up to 16 for SB 79 — each with its own
`BILL_XML` LOB. Critically, `<caml:BillSection id="…">` GUIDs are **stable across versions**
(verified identical between two consecutive AB 69 amendments), so version N and N+1 can be
diffed section-by-section on a join key rather than by fuzzy text matching.

**c. The XML already contains the legislature's own redlining.** Amended versions carry
word-level change markup as XML **processing instructions**:

```
<?xm-insertion_mark_start?>On and after January 1, 2028, this<?xm-insertion_mark_end?> bill
would authorize …<?xm-deletion_mark data=" simultaneously with the"?>…
```

505 insertion pairs and 388 deletion marks across the 60 sampled versions. Struck text is not
merely flagged — it is preserved verbatim inside the `data` attribute.

> **⚠ This is the one thing that can silently destroy the answer.** Processing instructions are
> discarded by default by essentially every XML reader, including Python's `ElementTree` and
> Spark's XML data source. Confirmed locally: parsing
> `keep<?xm-insertion_mark_start?>NEW<?xm-insertion_mark_end?><?xm-deletion_mark data="OLD"?>tail`
> with `ElementTree` yields `'keepNEWtail'` — the deleted text is gone entirely and the inserted
> text is now indistinguishable from unchanged text. Nothing errors.
>
> Consequences for this plan: bronze must keep `BILL_XML` as a **byte-exact `STRING`** straight
> from the `.lob` (which `land_raw.py` already does — preserve that, and don't "clean" it), and
> any future silver XML parsing must either use a PI-preserving parser
> (`lxml`, or `ElementTree` with a custom `XMLParser` target) or extract the marks by regex
> *before* parsing. Worth a comment in `bronze_raw.sql` so the next person doesn't lose it.

**Caveat:** the redline in version N is relative to the *immediately preceding* version, which is
the legislature's own convention, not a general N-vs-M diff. Cross-version comparison still needs
mechanism (b). Also note the sampled corpus showed no redlines on `Introduced` versions, as
expected — there is nothing yet to strike.

Nothing here depends on the load cadence: because every snapshot carries the complete version
history for the session, a nightly full replace loses none of it.

### Conclusion

Full-snapshot replace wins outright. It handles deletes for free, needs no keys, and is one code
path — and the measured parse cost is only ~70 s serverless for all 18 tables
(`pr-reconciliation-plan.md` bake-off), so the delta zips would buy essentially nothing.

---

## Plan

### 1. `jobs/land_raw.py` — channel selection, freshness guard, replace semantics

Add a `--channel {bills,laws}` argument that resolves both the zip and the table subset;
keep `--zip-name`/`--tables` as manual overrides.

- **`resolve_source(channel)`** — new.
  - `bills`: HTTP `HEAD` all 7 `pubinfo_daily_<Day>.zip` and pick the one with the greatest
    `Last-Modified`. Do *not* derive the name from today's weekday — finding 6.
  - `laws`: `pubinfo_{session_start_year}.zip`, where `session_start_year` is the current year
    if odd, else the previous year (sessions start in odd years; even-year zips don't exist).
  - Reuse the existing `urllib` + `USER_AGENT` approach — **not `requests`**
    (`ca-leginfo-bulk-download.md` §9: certifi predates leginfo's Sectigo root).

- **Skip-if-unchanged** — new. Persist `{zip_name, last_modified, content_length, sha256,
  loaded_at}` per channel at `parsed_root/_state/<channel>.json`. If the `HEAD` response matches
  the recorded `last_modified` + `content_length`, print and exit 0 without downloading.
  State lives under `parsed_root` (environment-scoped), **not** `raw_root` — `raw_root` is shared
  between dev and prod per `docs/architecture.md`, so per-run state there would let a dev run
  mark prod as loaded. Add `--force` to bypass.

- **Row-count collapse guard** — new, and load-bearing under full-replace. After parsing, compare
  each table's row count against the previous run's manifest; `raise` if any table falls below
  `--min-row-ratio` (default `0.9`) of its prior count. This is the safety net that stops a
  truncated or stale snapshot from silently wiping good data. `--force` bypasses.

- **Clear before write.** `write_table` currently writes `part-0000.parquet`… into a directory it
  never clears, so a smaller snapshot leaves orphaned parts from the previous run behind. Delete
  existing `part-*.parquet` in `parsed_root/<TABLE>/` before writing.

- **Fix the 1.1 GB memory blowup.** `jobs/land_raw.py:502`
  (`.write_bytes(zip_path.read_bytes())`) buffers the whole zip in RAM, contradicting its own
  docstring — already flagged at `pr-reconciliation-plan.md:115-120`, unfixed. Use
  `shutil.copyfile`. Skip the copy entirely when a zip with the same `sha256` is already in the
  raw zone, so nightly dev and prod runs don't rewrite the shared volume against each other.

- **Provenance columns.** Add `_source_zip`, `_source_last_modified`, `_ingested_at` to every
  parsed row so bronze can answer "which snapshot is this from?" — needed for debugging a
  scheduled full-replace pipeline.

- **Timestamped manifests.** `manifest_<utc_ts>.json` instead of a single overwritten
  `manifest.json` (a decision already recorded in `pr-reconciliation-plan.md`), giving per-run
  history. Raw-zip retention needs no new code: the 7 distinct daily stems under
  `raw_root/<zip_stem>/` are a self-maintaining rolling 7-day window.

- **The 4 law/code tables.** Rather than hand-copying four more column lists into the 180-line
  `TABLES` dict, reuse **`parse_loader_columns` / `load_column_map`**, which already exist on
  `upstream/execute-bulk-download-plan:src/ingest/bronze/leginfo_bronze.py` and derive column
  order from the loader kit's `.sql` files. This deletes the dict rather than growing it.
  *Judgment call — if you'd rather keep the change surface minimal, hand-adding the 4 lists also
  works and is the smaller diff.*

### 2. `src/ingest/bronze_raw.sql` — streaming table → materialized view

*Why:* this follows from choosing the snapshot channel, not from the delete gap. `STREAM
read_files()` is append-only over newly-arrived files, but each snapshot is a full restatement of
all ~5,000 bills — appending it would duplicate every row nightly. (Today's code hits the
opposite failure: part files are rewritten under the same names, so Auto Loader's file tracking
skips them and bronze never updates.) A streaming table cannot express an update at all; an MV
recomputes from the directory's current contents, which is exactly snapshot-replace semantics.
Had we gone the delta route instead, the right construct would have been `APPLY CHANGES INTO`,
not an MV.

Mechanical swap across all 14 blocks:
`CREATE OR REFRESH STREAMING TABLE … AS SELECT * FROM STREAM read_files(…)`
→ `CREATE OR REFRESH MATERIALIZED VIEW … AS SELECT * FROM read_files(…)` (drop `STREAM`).
Keep the `-- noqa: AM04` markers and the existing `COMMENT` clauses.

Then add 4 new MV blocks for `codes`, `law_toc`, `law_toc_section`, `law_section`, with
`COMMENT` clauses (CLAUDE.md: bronze gets comments when raw field names are cryptic — these
qualify).

Add non-null expectations on the four tables that actually declare a key, e.g.
`CONSTRAINT valid_bill_id EXPECT (BILL_ID IS NOT NULL) ON VIOLATION FAIL UPDATE`.
`pr-reconciliation-plan.md` notes expectations are unused today; this is the idiomatic place.

> **Breaking change:** Lakeflow cannot convert a `STREAMING TABLE` to a `MATERIALIZED VIEW`
> in place. The 14 existing bronze tables must be dropped in dev before the first run. This is
> also the moment to clear the 19 stray corrupt tables left in the shared `bronze` schema
> (`pr-reconciliation-plan.md` workspace-state section). **Dev only** — per CLAUDE.md's red lines.

Update the file header: the "code/statute tables are deferred" note is no longer true, and the
reason bronze is now an MV (snapshot replace) should be stated where the next reader will hit it.
Add a comment on the `bill_version` block recording that `BILL_XML` must stay byte-exact because
it carries `<?xm-insertion_mark_*?>` / `<?xm-deletion_mark?>` redlining that ordinary XML parsers
drop silently (see the section above).

### 3. `resources/legislation.job.yml` — one nightly job, three tasks

**There is no separate weekly job.** A single job runs **every night**, with three tasks:

```
land_bills (--channel bills) → land_laws (--channel laws) → run_pipeline
```

`land_laws` executes nightly like the others; it simply `HEAD`s `pubinfo_YYYY.zip`, finds
`Last-Modified` unchanged, and exits 0 without downloading. Because the annual only regenerates
on Sundays, it does real work roughly one night in seven and no-ops the other six. The freshness
guard *is* the schedule — there is no conditional task logic and no day-of-week branch anywhere.

Why not a separate Sunday-cron job for the laws channel:

- Two jobs targeting the same pipeline would overlap on Sunday night and race.
- A pinned day-of-week cron assumes a publication schedule the source does not actually keep —
  `pubinfo_Sat.zip` has gone unrefreshed for three weeks, and `pubinfo_daily_Fri` posted once at
  04:24 PT instead of the usual ~21:2x. `Last-Modified` gating degrades gracefully when the
  source slips a day; a cron silently loads the wrong thing.

The cost of this design is one wasted HTTP `HEAD` per night, plus the law MVs recomputing from
unchanged Parquet on the six no-op nights. The latter is a Parquet re-read, not a re-parse of
`LAW_SECTION_TBL`'s 162k LOBs, so it should be minor — but if it turns out to matter, the fix is
to refresh a subset of tables rather than the whole pipeline. Check what `pipeline_task` actually
exposes before relying on that; a second pipeline may be the only clean route.

Replace the commented-out `periodic:` stub with a cron trigger at **23:00
`America/Los_Angeles`** — comfortably after the ~21:20–21:29 PT posting window, with the
freshness guard absorbing late or missed postings.

`scripts/bronze_column_comments.sql` stays hand-applied; extend it for the 4 new tables and leave
the existing CLAUDE.md TODO about wiring it into a `sql_task` in place.

### 4. Docs

- `ca-leginfo-bulk-download.md` — replace §1 with the measured three-channel table above plus
  findings 1–6. The richer cadence research on
  `upstream/execute-bulk-download-plan:ca-leginfo-bulk-download.md` (§4 "the naming trap",
  §6 "full-refresh snapshot") was supposed to be merged into this doc and never was — fold it in
  now and supersede where this plan's measurements are newer. Extend §2 (format) with the CAML
  redline processing instructions and the parser hazard — §2 currently documents the LOB
  encodings but not this.
- `CLAUDE.md` — retire the "Daily/incremental scheduled loads" TODO; it's answered here.
- `docs/architecture.md` — document `parsed_root/_state/<channel>.json` and the rolling raw-zone
  window.

### 5. Tests

> **CLAUDE.md asks that I check before adding new behavior: I propose writing these tests first.**

`pytest` is not yet a dev dependency (`uv add --dev pytest`). Adopt the 11 synthetic-zip tests
from `upstream/execute-bulk-download-plan:tests/` (`conftest.py`, `test_leginfo_bronze.py`),
then add coverage for the new behavior:

- `resolve_source("bills")` picks max `Last-Modified`, not today's weekday.
- Session-year derivation: odd year → itself; even year → previous.
- Skip-if-unchanged returns without downloading; `--force` overrides.
- Row-count guard raises when a table shrinks past the ratio.
- `write_table` clears stale `part-*.parquet` before writing.

---

## Verification

1. **Local, offline** — the sample zips cover all three channels:
   ```bash
   uv run python jobs/land_raw.py --channel bills \
     --local-zip sample/pubinfo_daily_Wed.zip \
     --catalog test --bronze-schema b --parsed-volume v \
     --raw-root /tmp/raw --parsed-root /tmp/parsed
   ```
   Expect 14 table directories. Re-run: expect a skip. Re-run with `--force`: expect a rewrite
   with no orphaned part files. Then `--channel laws --local-zip sample/pubinfo_2025.zip` and
   expect the 4 law tables.
2. `uv run pytest` and `uv run pre-commit run --files <edited files>` (the
   `scripts/check_schema_literals.py` hook will catch any stray schema literal).
3. **Dev deploy** — `databricks bundle deploy -t dev`, drop the 14 old bronze streaming tables,
   then `databricks bundle run legislation_job -t dev`. Confirm all 18 bronze tables are
   `MATERIALIZED VIEW` and that the provenance columns name the expected snapshot.
4. **Prove the replace semantics** — run `--channel bills` against the older
   `sample/pubinfo_daily_Wed.zip` (4,978 bills, data through 2026-06-03) with `--force`, then
   against a fresh download (~5,000+ bills). Row counts should track the snapshot exactly rather
   than accumulating, which is the behavior the streaming tables got wrong.
5. **Let the schedule fire once** and confirm the following night's run skips `land_laws` while
   `land_bills` picks up the new snapshot.

## Out of scope

- Prior-session backfill from the frozen `pubinfo_1989.zip`–`pubinfo_2023.zip` archives. Every
  export here covers only session `20252026`; multi-session history is a separate one-time load.
- Silver and gold. `src/transform/` and `src/publish/` remain placeholders. Amendment diffing
  (`caml:ActionLine/@action` per bill section; redline extraction from the XML processing
  instructions) is the natural first silver/gold feature — this plan deliberately only makes sure
  bronze preserves the raw material for it intact.
- A "what changed today" feed built from the small `pubinfo_<Day>.zip` deltas — attractive for a
  tracker, but not needed for correct loading.
