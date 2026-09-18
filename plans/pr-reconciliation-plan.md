# Reconciling PR #6 (`bronze`) and PR #10 (`execute-bulk-download-plan`)

## Context

Two people independently implemented the ingestion plan from the merged PR #5. Both solve the
same real problem — a `pubinfo_2025.zip` expands to ~198K tiny `.lob` files, and materializing
those on a FUSE-mounted UC volume is pathologically slow (PR #10 measured 1h44m before
cancelling; even *listing* the directory timed out). Both avoid ever writing loose LOBs.

They split the work at different seams, and each found things the other didn't. Neither should
be merged as-is and neither should be discarded. Goal: **one PR** that takes the verified
findings and better engineering from both, with the genuinely contested architecture decision
settled by measurement rather than preference.

They conflict directly on 7 files: `ca-leginfo-bulk-download.md` (near-total rewrite by both),
`resources/legislation.job.yml`, `resources/legislation.pipeline.yml`, `pyproject.toml`,
`uv.lock`, `src/ingest/README.md`, `docs/setup.md`.

---

## How this proceeds (agreed)

1. **You authenticate** — `databricks auth login --host https://adb-7405607841560793.13.azuredatabricks.net`.
   The MCP tools currently fail with *"`/Users/andrew.king/.databrickscfg` has no DEFAULT profile
   configured"*, so nothing below can run until this is done.
2. **I run E3** (spec below) — the one measurement that settles the parse-architecture fork, and
   which also produces the bad-row magnitude number. First I check whether `pubinfo_2025.zip` is
   already staged on the raw volume; both PRs landed it, so a re-download is probably unnecessary.
3. **We decide P1 / P2 / P3** against the decision rule, on numbers.
4. **I build the single reconciling PR** per the file plan below.

Delivery shape is decided: **one PR** replacing both #6 and #10.

## The two approaches

| | PR #6 (`bronze`) | PR #10 (`execute-bulk-download-plan`) |
|---|---|---|
| Where parsing happens | Single-node Job task, pyarrow → per-table Parquet → SQL `read_files()` | Land zips only; Lakeflow pipeline unzips in-memory via `mapInPandas` → Delta |
| Bronze layer | 14 declared `STREAMING TABLE`s in SQL, each with a `COMMENT` | Python; tables registered dynamically in a loop over zip entries |
| LOB bodies | Inlined into the row at parse time | Separate `bronze.lob_raw` keyed by filename; join in silver |
| Column schema | Hardcoded `TABLES` dict (~180 lines) | Derived at runtime from the loader kit's `LOAD DATA` scripts, unit-tested |
| Malformed rows | `raise ValueError` | Pad/truncate + `_rescued` column |
| Governance | `docs/architecture.md`, `legislation.catalog.yml`, schema-literal pre-commit hook | None — `bronze` / `raw` hardcoded throughout |
| Tests | None | `tests/test_leginfo_bronze.py` + conftest |
| Downloader | `requests` — hit `SSLCertVerificationError` from serverless | stdlib `urllib` — 1.1 GB download reported working |
| Script location | `jobs/land_raw.py` (outside pipeline globs) | `src/ingest/land_raw.py` + pipeline glob narrowed to `src/ingest/bronze/**` |

---

## Settled — goes in regardless of the architecture fork

These are verified findings or clear principle matches, not preferences.

### From PR #6

1. **`BILL_ANALYSIS_TBL.SOURCE_DOC` is binary `.docx`, not text.** Verified across all 19,206
   analysis rows (100% start with `PK\x03\x04`). Undocumented by the provider. PR #10's blanket
   `decode_text(raw)` with `errors="replace"` corrupts these irreversibly. Whatever architecture
   wins, LOB columns need a per-table text/binary flag and binary LOBs must land as raw bytes.
2. **The whole governance layer.** `docs/architecture.md` (raw-vs-medallion model, dev-prefix
   isolation, the RBAC gap, the blocked `CREATE CATALOG` TODO),
   `resources/legislation.catalog.yml`, `scripts/check_schema_literals.py` + its pre-commit hook,
   and the `README.md` / `docs/index.md` / `docs/setup.md` / `mkdocs.yml` / `databricks.yml` /
   `CLAUDE.md` updates. PR #10 hardcodes `bronze` and `raw` in job params, pipeline config, and
   `@dp.table(name="bronze.…")` — under dev-mode prefixing two developers collide in one schema.
   This directly serves CLAUDE.md's *Governed* and *IaC* principles.
3. **Pipeline `configuration:` block** exposing `catalog` / `bronze_schema` / `gold_schema` /
   `parsed_volume` to `.sql` files, and `schema: ${resources.schemas.silver.name}` instead of the
   literal `silver`.
4. **`--local-zip` escape hatch** and the §9 write-up of the TLS egress blocker.
5. **`scripts/bronze_column_comments.sql`** — column comments with real citations to the leginfo
   glossary, plus the confirmed-live finding that `ALTER TABLE` is the *only* mechanism that adds
   column comments on this runtime and that it cannot live inside a Lakeflow pipeline source file.
6. **NULL semantics**: a bare unenclosed `NULL` is SQL NULL; a backtick-enclosed `` `NULL` `` is
   the literal string. Matches the loader's `ENCLOSED BY` behaviour. PR #10 does not do this.
7. **v1 scope = the 14 bill/reference tables.** Code/statute tables deferred to their own pass.
   PR #10's dynamic registration would sweep in `LAW_SECTION_TBL` (162K LOBs) implicitly.

### From PR #10

8. **stdlib-only downloader.** No `requests`, no `pyarrow`-adjacent serverless dependency for the
   fetch. Likely explains why PR #10's download succeeded where PR #6's failed — `requests` ships
   its own certifi bundle, `urllib` uses the system trust store that presumably has the proxy CA.
   Confirm in E1 below; if it holds, the TLS blocker is *solved*, not merely worked around.
9. **Atomic download**: stream to `.part`, verify against `Content-Length`, then `replace()`.
   A cancelled or truncated fetch never leaves a bad zip in place. PR #6 has neither check.
10. **Loader-kit schema derivation** (`parse_loader_columns`) instead of PR #6's hardcoded
    `TABLES` dict — including resolving `@varN` placeholders to their `SET … LOAD_FILE` target
    column so the LOB column keeps its position. Deletes ~180 lines of hand-copied column names
    that would silently drift from the source.
11. **The test suite**, retargeted at whichever parsing module survives. Synthetic zips built
    in-test; no real data committed.
12. **Timestamped manifests** (`manifests/manifest_<ts>.json`) so repeat runs don't clobber
    provenance, vs PR #6's single overwritten `manifest.json`.
13. **The `land_raw`-must-not-be-pipeline-source problem is real.** Both solve it; we take PR #6's
    `jobs/land_raw.py` because "not under a glob at all" is more obvious than "the glob was
    narrowed" — a future `src/ingest/foo.py` silently stops being picked up under PR #10's fix.

### Merged source-research doc

`ca-leginfo-bulk-download.md` — both rewrote it almost entirely, and the research is
**complementary**. Merge rather than pick:

- **From PR #10**: the corrected file inventory (verified 2026-08-05); the *three* refresh
  channels and the naming trap (`pubinfo_daily_<Day>` is a ~0.95 GB near-full snapshot;
  `pubinfo_<Day>` is the true 0.5–14 MB incremental, Mon–Sat only); **only 4 of 18 tables declare
  a key** in `capublic.sql`; `LOAD DATA … REPLACE` semantics and the `deleteSession.bat`
  Sunday-wipe model; the full-refresh-over-MERGE rationale that follows from the keylessness; the
  FUSE "hard-won lesson" §5.
- **From PR #6**: the per-table file-count table (`LAW_SECTION_TBL` = 162,437 LOBs = 82% of the
  corpus); the binary-`.docx` finding; §9 on the network egress blocker.
- Reconcile the two acceptance-criteria tables — PR #6 loaded 14 tables via a local workaround,
  PR #10 landed the zips from the job. Both are true; state both.

### Bugs to fix in the merge

- `jobs/land_raw.py:475` — `write_bytes(zip_path.read_bytes())` reads the entire 1.1 GB zip into
  memory to copy it to the volume, contradicting the module's own "never buffered whole in
  memory" docstring. Stream it (`shutil.copyfileobj`), or stream straight to the volume on
  download as PR #10 does and skip the second copy entirely.
- `jobs/land_raw.py:369` — `dat_bytes.splitlines()` splits on bare `\r` as well as `\n`; the
  loader spec is `LINES TERMINATED BY '\n'`. A field containing a lone `\r` becomes two fragments
  with wrong field counts — a parser-manufactured "bad row". Use `split(b"\n")`. Quantify in E2.
- PR #10 commits `sample/pubinfo_load.zip` (15 KB) *and* adds `sample/*.zip` to `.gitignore`.
  Contradictory. Recommend dropping the committed zip — the synthetic-zip tests already cover the
  logic, and the `skipif` real-data test can point at a developer-local path.
- Job serverless environment: PR #6 pins `client: "1"`, PR #10 `client: "3"`. Pick `"3"` unless
  something needs the older runtime.

---

## Parked — to be settled by measurement, not argument

Three linked decisions. All hinge on the same unknown, so evaluate them together.

- **P1. Parse architecture** — single-node → Parquet → SQL bronze (PR #6) vs distributed
  in-pipeline unzip → Delta (PR #10).
- **P2. LOB shape** — inlined into the row (PR #6) vs separate LOB table joined in silver
  (PR #10). Largely falls out of P1.
- **P3. Malformed rows** — raise (PR #6) vs `_rescued` column (PR #10) vs rescue-with-threshold.

**What we already know about P3:** PR #6's parser is fail-loud and *completed* a real
`pubinfo_2025.zip` across all 14 bill/reference tables with row counts verified against source
`.dat` line counts. That is zero malformed rows in 14 of 18 tables on one real session zip.
Unknown: the 4 code/statute tables, the daily snapshots, historical sessions — and how much of
any future failure would be the `splitlines()` artefact above rather than real source data.

**What decides P1:** the only place the two architectures genuinely diverge is
`LAW_SECTION_TBL` (162K LOBs, 82% of the corpus) — which *both* PRs defer. For the v1 14 tables
(~35,600 LOBs) PR #6's single-node pass is already proven to work. Note also that PR #10's `.dat`
path is not actually distributed: `_dat_frames` seeds `mapInPandas` with a one-row trigger frame,
so each table is parsed by a single task holding the whole table in one pandas DataFrame. Only
`lob_raw` genuinely fans out.

**Standing argument against PR #10's shape, independent of performance:** dynamic table
registration in a `for` loop over zip contents means the deployed table set is discovered at
runtime rather than declared, and each table gets a generated comment
(`f"Raw tab-delimited rows from {entry}."`). CLAUDE.md asks for inline SQL `COMMENT`s consumed by
Genie, non-coder-friendly source, and "Platform is all IaC." If P1 goes to PR #10's approach,
we should decide separately what the semantic layer attaches to.

### Decided: fix B, then run A and B head-to-head over the full corpus

Measuring A alone would leave B judged on defects rather than on its architecture. So: repair B's
two silent corruptions first, then race both over identical input and score them on **speed**,
**best practices**, and **how Databricks-idiomatic** each is.

#### Step 1 — fix B's two bugs

*Duplication.* In `_dat_frames`, drive the work off the batch instead of ignoring it, so empty
partitions emit nothing:

```python
def transform(batches):
    import pandas as pd
    for batch in batches:
        for entry_name in batch["entry"]:      # only the partition holding the trigger row
            ...                                 # read + yield that entry's rows
```

*Binary LOBs.* `lob_raw.content` becomes `BinaryType`, not a `errors="replace"` string decode.
Bronze preserves source bytes; text families get decoded in silver. Confirmed safe by the
measurement above — only `BILL_ANALYSIS` is binary, the other three families are clean text.

Do **not** fix anything else in B (schema hardcoding, dynamic registration, generated comments).
Those are architecture, and they're what the comparison is meant to judge.

#### Step 2 — put both on equal footing

- Same input: `bronze/raw/zips/pubinfo_2025.zip` (2026-08-05) + `pubinfo_load.zip`.
- Same scope: **all 18 tables + all LOBs**, full corpus. A needs the 4 code/statute tables added —
  derive their columns with `parse_loader_columns` rather than hand-copying `capublic.sql`.
- Same compute class: serverless.
- **Both write to dev-scoped schemas** (`dev_andrew_king_*`), never the shared `bronze`. This is
  the CLAUDE.md red line and also the thing B got wrong in the first place.

#### Step 3 — correctness gates (a run only counts if it passes)

1. Row count per table **==** source `.dat` line count.
2. Distinct-key ratio **== 1.00** for the 4 keyed tables — the check that would have caught the 8×.
3. `BILL_ANALYSIS` LOBs **byte-identical to source** (sha256 on a sample), zero U+FFFD.
4. Zero rescued rows / no raises.

#### Step 4 — score

| Criterion | What we actually measure |
|---|---|
| **Speed** | End-to-end wall clock, full corpus, plus per-phase split. Compute-seconds as a cost proxy, since serverless job vs pipeline aren't the same shape. |
| **Best practices** | Testability off-cluster; failure mode when the source drifts; memory bounds; whether a correctness regression like the 8× would be *caught* rather than shipped; schema-drift resistance. |
| **Databricks-idiomatic** | Declarative Lakeflow SQL + inline `COMMENT`s feeding Genie; `read_files`/Auto Loader; UC governance and dev-mode prefixing via DABs; declared vs runtime-discovered tables; Delta/UniForm. Note **neither PR uses Lakeflow expectations** (`CONSTRAINT … EXPECT`) — the most Databricks-native way to express the correctness gates above, and a gap worth closing in whichever design wins. |

No fixed time threshold this round — we compare two real numbers against each other rather than
against a guess.

### Results, 2026-08-07

**B, as originally run (buggy), full corpus, serverless Lakeflow pipeline update:** recovered from
`information_schema.tables` creation/alter timestamps on the real completed run — earliest table
created `17:41:18.218`, `lob_raw` (last to finish, 198K LOBs) altered `17:47:00.896`. **~5m43s**
end-to-end wall clock for unzip + parse + write of the entire 18-table, 198K-LOB corpus.

**A, fixed + extended to full scope (18 tables incl. all 4 code/statute tables), same zip:**

| Run | Stage-to-local | Parse + write | Total | Peak RSS |
|---|---|---|---|---|
| Laptop, local disk | *(pre-staged)* | **14.6s** | 14.6s | 1.84 GB |
| Serverless job compute | 3.2s | **66.3s** | 69.8s | ~2 GB |

Both exclude the initial ~1m40s zip download from the public internet, which both architectures
pay once, identically, on first landing — not re-measured here since the zip was already staged.

**A pitfall worth recording:** the first serverless attempt pointed `--local-zip` directly at the
FUSE-mounted `/Volumes/.../pubinfo_2025.zip` path, skipping the local-disk copy. It stalled for
4+ minutes on a single mid-sized table before being cancelled — `zipfile`'s random-access seeks
into the central directory and each entry were going over the network mount instead of local
disk. This is not a flaw in A's design (the real job downloads straight to local disk and never
does this), but it's a sharp edge worth documenting: **never open a zip for random access directly
from a UC volume path; stage it locally first.** The corrected run copies volume→local disk
(3.2s, sequential — fast) before parsing.

**Correctness gates, A:** row counts match source `.dat` line counts exactly on every table
checked (`BILL_TBL` 5,019, `LAW_SECTION_TBL` 162,414, `CODES_TBL` 30, `BILL_ANALYSIS_TBL` 19,691 —
gate 1 ✅). `BILL_ANALYSIS_TBL.SOURCE_DOC` lands as pyarrow `binary`, 19,691/19,691 starting with
`PK`, zero corruption (gate 3 ✅). Total rows across all 18 tables: **1,238,736** — which is
*exactly* `9,909,888 / 8`, i.e. B's corrupted total divided by its duplication factor. That
identity is strong independent triangulation: A's full-corpus parse is correct, and the earlier
8× diagnosis of B's bug is confirmed from a second, independent angle.

**Cost of A's one real drawback**, measured: total staged Parquet is **~1.11 GB**, dominated by
`BILL_ANALYSIS_TBL` (834 MB — binary `.docx` bytes don't compress well under Parquet's default
codec) and `BILL_VERSION_TBL` (170 MB). This is the per-developer staging copy the plan flagged;
now it's a real number instead of a guess.

**Reading so far:** a 14.6-second single-node parse against a ~5m43s distributed pipeline update
is not a close call, even before the serverless confirmation. The premise behind B's architecture
— that the FUSE small-files disaster generalizes to *reading* a zip's central directory, not just
*writing* loose files — does not hold at this corpus size. Serverless confirmation (E3b) in
progress to rule out a laptop-vs-cloud-compute artifact before treating this as decisive.

### Qualitative scoring — best practices / Databricks-idiomatic

**Extends cleanly to new tables?** Added the 4 code/statute tables to A's declarative
`bronze_raw.sql` mentally against the existing pattern — each is a 4-line
`CREATE OR REFRESH STREAMING TABLE ... COMMENT '...' AS SELECT * FROM STREAM read_files(...)`
block, identical in shape to the 14 already there, human-authored comment included. B's
equivalent is automatic (the `for _entry in _entries` loop already picks up any new `_TBL.dat`
in the zip) but the comment is generated (`f"Raw tab-delimited rows from {entry}."`) and the
table only exists because the zip happened to contain it — nothing declares it. A trades
automatic pickup for an explicit, reviewable, documented table list; B trades explicitness for
zero-touch scaling. For a project whose stated principles include *non-coder-friendly* and
*governed*, explicit and documented wins.

**Would the 8× bug have been caught?** A's discipline — raise on field-count mismatch, and the
production practice of checking row counts against source line counts — is exactly the check
that would have caught B's duplication immediately (any keyed table's row count would have been
obviously wrong). B shipped with no such check, in either PR. This isn't inherent to B's
architecture (nothing stops adding the same check to a Lakeflow pipeline), but it's what actually
happened, and it happened in the schema everyone shares.

**Testability off-cluster.** A's core parsing (`parse_dat_row`, `write_table`) needs only
`pyarrow`, runs and is fully testable on a laptop with no Spark — which is exactly how E3a
happened, same-day, no cluster spin-up. B's `_dat_frames`/`_lob_frames` transforms need
`pyspark.sql.functions`/`mapInPandas` machinery to exercise end-to-end; only the pure
regex/classification helpers (`parse_loader_columns`, `is_dat`, etc.) are unit-testable without
it, per its own test suite's docstring ("The `@dp.table` wiring is verified end-to-end on
Databricks, not here") — which is exactly how the 8× bug shipped without a test catching it.

**Databricks-native idioms used well by each:** B's `mapInPandas` fan-out for `lob_raw` and its
`@dp.table`/DLT-style declarative registration are genuinely idiomatic Lakeflow patterns — the
architecture isn't wrong in kind, it's wrong in this execution (untested trigger-partitioning,
blanket text decode). A's use of `read_files()` + `STREAMING TABLE` + inline `COMMENT` is equally
idiomatic Lakeflow SQL, and additionally gets UniForm/Delta and Genie-visible documentation for
free once the pipeline runs. **Neither uses Lakeflow expectations** (`CONSTRAINT ... EXPECT` /
`EXPECT OR DROP` / `EXPECT OR FAIL`) — the standard Databricks-native mechanism for declaring
exactly the correctness gates this bake-off had to construct externally (row-count/key-uniqueness
checks). Worth adding to whichever design ships, as a follow-up, not blocking this PR.

**Net:** A wins on speed, on demonstrated correctness, and on how legibly it extends — the
declarative-SQL/inline-COMMENT shape that CLAUDE.md and the Genie/semantic-layer principles
call for. B's LOB-fan-out idea (a single keyed `lob_raw` table, joined in silver) is a genuinely
good idea independent of the architecture question — see P2 below.

### Still to run

| | Experiment | Settles |
|---|---|---|
| **E1** | Run PR #10's stdlib `land_raw.py` as a serverless job task against the source. Does it reach `downloads.leginfo.legislature.ca.gov`? If yes, re-run the same fetch with `requests` to confirm certifi is the culprit. | Whether the pipeline can run unattended at all, and whether PR #6's §9 local workaround is still needed. Independent of E3. |

### Workspace state — inspected 2026-08-07, and it changes the comparison

**PR #10's bronze parse has been run at full corpus scale — and it produced silently corrupt
output.** Its acceptance table calls extraction "the next implementation pass", which is stale:
`caldata_legislation_tracker.bronze` holds all 19 tables including `law_section_tbl_raw`,
`codes_tbl_raw` and `lob_raw`. But **every `.dat` table is duplicated exactly 8×**:

| Table | Rows | Distinct key | Ratio |
|---|---|---|---|
| `bill_tbl_raw` | 40,152 | 5,019 (`bill_id`) | 8.00 |
| `bill_version_tbl_raw` | 129,976 | 16,247 (`bill_version_id`) | 8.00 |
| `bill_analysis_tbl_raw` | 157,528 | 19,691 (`analysis_id`) | 8.00 |
| `bill_motion_tbl_raw` | 840,880 | 105,110 (`motion_id`) | 8.00 |
| `lob_raw` | 198,476 | 198,476 (`lob_name`) | **1.00** |

*Root cause*, in `_dat_frames`: `spark.createDataFrame([(entry,)], …)` spreads one row across
`defaultParallelism` (8) partitions. `mapInPandas` calls the transform once per partition —
including the 7 empty ones — and the transform drains `batches` without consulting it, then
unconditionally reads the whole `.dat` and yields every row. So each partition emits the full
table. `lob_raw` is correct because it partitions real data and reads `batch["lob_name"]`.

*Consequence for the comparison:* B is not proven, it is **disproven as currently written**. The
failure went unnoticed because row counts were never validated against source `.dat` line counts
— exactly the check A ran. The bug itself is small (emit only for non-empty partitions, or drive
off the batch), but the verification gap is the real finding, and A's discipline is what caught
the equivalent class of error.

**Second silent corruption: every binary LOB was destroyed.** Measured on `lob_raw`, 2026-08-07:

| LOB family | Count | Contains U+FFFD | Starts `PK` |
|---|---|---|---|
| `BILL_ANALYSIS` (binary `.docx`) | 19,691 | **19,691 (100%)** | 19,691 |
| `BILL_VERSION` (CAML XML) | 16,247 | 0 | 0 |
| `VETO_MESSAGE` (CAML XML) | 124 | 0 | 0 |
| `LAW_SECTION` (text) | 162,414 | 0 | 0 |

PR #6's binary-`.docx` finding is confirmed at 100%, and PR #10's `decode_text(raw)` with
`errors="replace"` corrupted every one of them irrecoverably — the bytes cannot be recovered from
the bronze table, only by re-ingesting. Also settles a deferred-scope question for free:
`LAW_SECTION` LOBs are genuinely text, so the code-table pass needs no binary handling.

*Two silent data-corruption bugs, both shipped into a shared schema, neither detected.* That
pattern — not the architecture per se — is the strongest argument in this whole comparison.

**PR #10 wrote those tables into `bronze` — the shared placeholder prod schema, not a
dev-prefixed one.** This is precisely the collision `docs/architecture.md` was written to prevent,
now demonstrated live rather than hypothetically. It strengthens the case for PR #6's governance
layer considerably, and it means **cleanup is part of this work**: 19 stray tables in `bronze`.

**Both zips are already staged — E3 needs no download.**

| Path | Bytes | Landed | From |
|---|---|---|---|
| `bronze/raw/zips/pubinfo_2025.zip` | 1,130,087,347 | 2026-08-05 | PR #10 |
| `bronze/raw/zips/pubinfo_load.zip` | 15,662 | 2026-08-05 | PR #10 |
| `bronze/raw/pubinfo_2025/pubinfo_2025.zip` | 1,111,562,882 | 2026-07-23 | PR #6 |

The ~18.5 MB delta is two weeks of session growth, not a discrepancy. Use the 2026-08-05 copy for
E3. Note the loader kit on the volume is the same 15,662 bytes as PR #10's committed
`sample/pubinfo_load.zip` — reinforcing that the committed copy is redundant.

Also present: `bronze/raw/extracted/` — the partial output of the cancelled 1h44m FUSE extraction.
Still needs deleting (slow over FUSE, low priority), and `bronze/raw/manifests/` holds 4 manifests
from both PRs' runs.

### P3 (malformed rows) — RESOLVED: strict fail

Measured directly from PR #10's full-corpus run, 2026-08-07: **zero non-null `_rescued` across all
18 `.dat` tables**, 9,909,888 stored rows (~1,238,736 real rows after the 8× duplication above) —
**including all 4 code/statute tables that had never been parsed by either PR**. Field-count
conformance against the loader-derived schema is perfect over the whole corpus.

**Decision: keep PR #6's `raise`.** There is nothing to absorb, a fail-loud parser costs nothing
at a rate of zero, and it matches CLAUDE.md's "avoid silent failures". If the rate ever becomes
nonzero we get an exact table and row instead of silently padded data — which is precisely how
the 8× duplication above should have been caught and wasn't.

*Caveat:* this run used `split("\n")`, so it does not exercise PR #6's `splitlines()` divergence.
That stays on the bugs list and gets a regression test rather than a measurement.

### Deferred cleanup discovered by this inspection

- 19 tables in `caldata_legislation_tracker.bronze` written by PR #10's run, which should have
  gone to a dev-prefixed schema.
- `bronze/raw/extracted/` leftover directory.
- `dev_andrew_king_{bronze,silver,gold}` from PR #6's deploy — legitimately dev-scoped, tear down
  with `bundle destroy -t dev` when convenient.

---

## Final decisions, 2026-08-07

Six calls, made by the user after reviewing the bake-off results:

| # | Decision | Resolution |
|---|---|---|
| 1 | Parse | **Single job (PR #6/A shape).** Confirmed by the bake-off: 14.6s–70s vs B's ~5m43s. |
| 2 | Bronze layer | **PR #10 shape.** See interpretation below. |
| 3 | LOBs | Delegated to Claude. See below. |
| 4 | Schema / data dictionary | Delegated to Claude. See below. |
| 5 | Bad rows | **Raise** — reconfirmed; matches the P3 measurement (zero bad rows across the full corpus). |
| 6 | Governance | **Keep PR #6's layer**, but defer the actual file updates (docs, catalog.yml, etc.) to the end of this PR's work, after the ingestion code is settled. |
| 7 | Tests | **Keep PR #10's suite**, retargeted at whatever module survives. |
| 8 | Downloader | **Whichever one actually worked.** See below. |

**#2, interpreted.** PR #6 and PR #10's "bronze layer" differ on two independent axes: *how tables
are registered* (SQL `CREATE OR REFRESH STREAMING TABLE` vs. Python `@dp.table` in a runtime loop)
and *table shape* (LOBs inlined per-row vs. a separate `lob_raw` keyed table). The bake-off's
qualitative scoring favored SQL registration specifically — it's what extends legibly, is
non-coder-readable, and is what CLAUDE.md's Genie/`COMMENT` principles assume. Reading "bronze
layer like PR #10" as reopening *that* axis would contradict decision #1's own rationale. The
coherent reading — and the one this plan implements — is the **table-shape axis**: keep SQL-declared
tables (extending A's `bronze_raw.sql` pattern, since it already won on that axis), and add a
**separate `lob_raw` table**, PR #10-style, rather than inlining LOB content into each owning row.
**Flagging this interpretation explicitly — correct if the intent was the Python/dynamic
registration mechanism instead of the table-shape.**

This requires reworking `jobs/land_raw.py`'s `write_table`: it currently resolves each row's LOB
filename to content inline (`lob_bytes = zf.read(lob_name); fields[lob_index] = ...`). Under the
PR #10 shape, that resolution goes away entirely — a `.dat` row keeps the **LOB filename** as a
plain string column, unresolved. Concretely, this *simplifies* the script: the per-table
`lob_column`/`lob_binary` metadata (`TABLES`, `CODE_TABLE_LOB_METADATA`) is no longer needed by
`write_table` at all, since no table-specific LOB resolution happens there anymore. In its place,
one new function harvests every `.lob` entry in the zip into a single `LOB_RAW` Parquet output —
`(lob_name, content, source_zip, ingested_at)` — using the same `BATCH_ROWS`-bounded batching as
`write_table`, keyed only by filename, agnostic to which table references it (mirrors PR #10's
`is_lob()`-filtered harvest, just run sequentially in the single job instead of fanned out across
`mapInPandas` partitions). `src/ingest/bronze_raw.sql` gets one more declared block:
`CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.lob_raw ... AS SELECT * FROM STREAM
read_files('.../LOB_RAW/', format => 'parquet')`. Silver joins `<table>_raw.<lob_column>` to
`lob_raw.lob_name` to reconstitute body text — exactly PR #10's intended silver-layer join.

**#3, LOBs — Claude's call: store `lob_raw.content` as binary, uniformly, always.** Not
per-family text/binary typing at the bronze layer. Bronze doesn't need to know that
`BILL_ANALYSIS` is `.docx` and `BILL_VERSION`/`VETO_MESSAGE`/`LAW_SECTION` are CAML XML — it only
needs to not corrupt any of them, and "never decode" is the only rule that can't be wrong.
Per-family decoding (UTF-8 for the three text families, left as bytes for `BILL_ANALYSIS`) is a
silver-layer concern, once a row's owning table (and therefore its LOB family) is known via the
join. This is the same fix already applied and validated in the bake-off (`_lob_frames` in
`bakeoff-b`), just executed by the single job's sequential pass rather than a Spark transform.

**#4, schema / data dictionary — Claude's recommendation:** keep table-level `COMMENT` inline in
`CREATE OR REFRESH STREAMING TABLE` (already true for every bronze table; no change needed —
that's the source of truth and it works). For column-level comments, where Lakeflow's own runtime
rejects inline syntax (confirmed live by PR #6) and `ALTER TABLE` can't run inside pipeline
source: keep `scripts/bronze_column_comments.sql` as the single version-controlled source of
truth (already glossary-cited, already reviewed against real column semantics — don't replace it
with AI-generated comments; that contradicts the file's own stated principle of asking a subject-
matter expert rather than guessing), but **wire it into `resources/legislation.job.yml` as a
`sql_task`** running against a SQL warehouse after `run_pipeline` completes. `ALTER COLUMN ...
COMMENT` is idempotent, so re-running it every job execution is safe. This closes PR #6's own
carried-forward TODO ("apply by hand") using infrastructure the bundle already has — no new
tooling, no AI-guessed content. Implementation is part of the governance pass (#6), at the end.

**Clarification (user question, 2026-08-07): does table-level inline `COMMENT` still work given
column names are now derived dynamically?** Yes — the two are orthogonal. `parse_loader_columns`
derives *column lists*, used only inside `jobs/land_raw.py` to build each table's Parquet schema.
`bronze_raw.sql` never declares columns at all (`SELECT * FROM STREAM read_files(...)`, schema
inferred) — the table-level `COMMENT` is metadata on the table declaration, independent of the
column list, and this was already true before dynamic derivation existed. The real interaction is
with **column-level** comments (decision #4): `bronze_column_comments.sql` hardcodes
`ALTER COLUMN <name> COMMENT ...` against specific names. **Case mismatch to verify, not
assumed-safe:** `parse_loader_columns` derives `UPPERCASE` (`CHAPTER_YEAR`, matching
`capublic.sql`), while `bronze_column_comments.sql` was written lowercase (`chapter_year`).
Databricks SQL identifier resolution is case-insensitive by default, so this should resolve
correctly — but add an explicit check to Verification (below) rather than assume it silently.

**#8, downloader — resolved from evidence, not re-tested in this session.** Neither downloader
was actually exercised here (every bake-off run used `--local-zip`/`--local-loader-zip` against
already-staged files). But the staged `bronze/raw/zips/pubinfo_2025.zip` (2026-08-05) *is* the
product of a real, successful `land_raw` job run — and that run used PR #10's stdlib `urllib`
downloader (its manifest's provenance matches PR #10's script, not PR #6's). PR #6's own doc
(§9) records its `requests`-based downloader hitting `SSLCertVerificationError` from serverless.
**Decision: PR #10's stdlib `urllib` downloader** — streaming, `.part` atomic rename,
`Content-Length` verification (already stronger than PR #6's version regardless). Drop `requests`
as a dependency. Flagging one residual gap: this is evidenced, not independently re-verified via
a fresh E1 run in this session — worth a quick smoke test before calling it fully proven, but not
a blocker.

---

## The PR

One PR replacing both #6 and #10, branched from `main`. Two-pass build, per decision #6:
**ingestion code first**, **governance file updates last**.

### Pass 1 — ingestion code

- `jobs/land_raw.py` — single job task (decision #1), built from A/PR #6's structure:
  - **Download**: PR #10's stdlib `urllib`, streaming, `.part` atomic rename, `Content-Length`
    verification (decision #8). No `requests` dependency.
  - **Schema**: PR #10's `parse_loader_columns`, derived from `pubinfo_load.zip` at runtime, for
    **all 18 tables** — not just the 4 code/statute ones as in the bake-off patch. Deletes the
    ~180-line hand-copied `TABLES` dict entirely.
  - **`.dat` parsing**: PR #6's `parse_dat_row` (bytes-level, NULL semantics: bare `NULL` vs.
    backtick-enclosed `` `NULL` ``), with `split(b"\n")` not `splitlines()` (the `\r` bug fix).
  - **LOBs**: decision #2/#3 — `.dat` rows keep the LOB filename as a plain string column,
    unresolved. A new `harvest_lob_raw()` pass reads every `.lob` zip entry once and writes a
    single `LOB_RAW` Parquet output — `(lob_name, content: binary, source_zip, ingested_at)` —
    batched the same way as `write_table`. No per-table `lob_column`/`lob_binary` metadata needed.
  - **Bad rows**: raise (decision #5), unchanged from PR #6.
  - **Manifests**: PR #10's timestamped `manifest_<ts>.json`.
  - **Bug fix carried over**: stream the raw-zip copy (`shutil.copyfileobj`), not
    `read_bytes()`/`write_bytes()`.
  - Keep `--local-zip`/`--local-loader-zip` escape hatches (used throughout the bake-off; also
    PR #6's answer to the TLS egress question if #8's resolution doesn't hold up under E1).
- `src/ingest/bronze_raw.sql` — PR #6's declared-`STREAMING TABLE` pattern, extended to **all 18
  source tables** (not just the 14 bill/reference ones — deferred-scope reconsideration: since
  the loader-kit derivation and the single-job parse both already generalize cleanly, and the
  bake-off already validated correctness on the full corpus, there's no remaining reason to hold
  the 4 code/statute tables out of v1) **plus one more block**: `${bronze_schema}.lob_raw`,
  reading the new `LOB_RAW` Parquet folder.
- `resources/legislation.job.yml` — one task (no `run_pipeline` dependency chain complexity
  beyond what already exists), PR #10's `client: "3"`, no extra dependencies beyond `pyarrow`.
- `resources/legislation.pipeline.yml` — PR #6's version (`configuration:` block, silver schema
  by resource reference, `src/ingest/**` glob — no narrowing needed since there's no separate
  in-pipeline parse module to exclude).

**Tests** — PR #10's suite (decision #7), retargeted at `jobs/land_raw.py`'s surviving functions:
`parse_loader_columns`, `parse_dat_row` (NULL semantics, backtick enclosure), `harvest_lob_raw`'s
batching, binary-LOB passthrough (no decode, ever), and the `\r`-in-field regression test for the
`split(b"\n")` fix. Drop the `mapInPandas`/Spark-dependent tests entirely — no longer applicable.

**Docs (working draft only)** — `ca-leginfo-bulk-download.md` merged per the "Merged
source-research doc" section above; this can mostly land in pass 1 since it's source research,
not governance policy.

**Deps** — `pyarrow` in main deps, `pytest` in dev. No `requests`. Regenerate `uv.lock` fresh.

### Pass 2 — governance (per decision #6, done after pass 1 is working)

- `docs/architecture.md`, `resources/legislation.catalog.yml`, `scripts/check_schema_literals.py`
  + pre-commit hook, `databricks.yml` TODO, `CLAUDE.md` pointer — PR #6's layer, **updated** to
  reflect the final shape: add `lob_raw`'s volume/schema references, and correct anything that
  assumed the 14-table v1 scope (now 18) or assumed inlined LOBs.
- `scripts/bronze_column_comments.sql` — PR #6's file, **wired into
  `resources/legislation.job.yml`** as a `sql_task` after `run_pipeline` (decision #4), replacing
  the "apply by hand" caveat.
- `README.md`, `docs/index.md`, `docs/setup.md`, `mkdocs.yml`, `src/ingest/README.md` — PR #6's
  updates, reconciled against the final architecture (single job, `lob_raw` table, 18-table scope).

---

## Verification

1. `uv run pre-commit run --all-files` — must pass, including the schema-literal hook against the
   whole tree.
2. `uv run pytest` — `parse_loader_columns` (all 18 tables incl. the 4 code/statute ones),
   `parse_dat_row` NULL semantics, `harvest_lob_raw` batching, binary-LOB passthrough (no decode),
   `\r`-in-field regression.
3. `databricks bundle validate -t dev`, then `deploy -t dev`. Confirm the dev deploy creates
   `dev_<user>_bronze` / `_silver` / `_gold` and the `parsed_raw` volume.
4. `databricks bundle run legislation_job -t dev`. Confirm `land_raw` reaches the source (revisit
   E1 here — decision #8 is evidence-based, not freshly re-verified), lands the zip + manifest to
   the shared `bronze.raw` volume, writes per-table Parquet **and** `LOB_RAW` under the
   dev-prefixed schema, and the pipeline materializes all 18 `<table>_raw` tables plus `lob_raw`.
5. Row counts per bronze table vs. source `.dat` line counts, and per-LOB-family byte-identity
   (sha256 sample) against the source zip — the checks the bake-off already ran; reuse them here
   against a fresh dev deploy rather than the scratch bake-off paths.
6. Spot-check a `bill_analysis`-referenced `lob_raw` row: `content` must still start with
   `PK\x03\x04` and be `binary`, not decoded text.
7. After pass 2: confirm the `sql_task` applies `scripts/bronze_column_comments.sql` and that
   table + column comments are visible in Unity Catalog (and therefore to Genie). Specifically
   confirm the lowercase `ALTER COLUMN` names in that file resolve against the uppercase columns
   `parse_loader_columns` actually produces (case-insensitive resolution, expected but unverified).
8. `databricks bundle destroy -t dev` to confirm teardown is clean and scoped to one developer.

## Open items to carry forward (not this PR)

- **Daily/weekly schedule split, and STREAMING TABLE vs MATERIALIZED_VIEW.** Raised by the user
  2026-08-07: each load is a full-session snapshot replace, not an incremental append, which is
  `MATERIALIZED_VIEW` semantics — a streaming table's checkpoint/exactly-once machinery solves a
  problem this pipeline doesn't have. Now that the bronze SQL shape is settled (18 declared
  tables + `lob_raw`), this is ready to revisit directly — likely a mechanical
  `STREAMING TABLE` → `MATERIALIZED VIEW` swap across `bronze_raw.sql`.
- The blocked `CREATE CATALOG` / real-prod-target TODO from `docs/architecture.md`.
- `LAW_SECTION_TBL`'s code/statute siblings are now in v1 scope (decision #2 generalized cleanly
  to all 18 tables) — no longer a carried-forward item, but worth an explicit note in the PR
  description since both source PRs treated it as deferred.
