# `ingest/` → `bronze`

Raw landing layer.

- **`land_raw.py`** — Job pre-task (not pipeline source). Streams the leginfo
  bulk-download zips into the Unity Catalog raw volume and writes a provenance
  manifest. Wired as the `land_raw` task in `resources/legislation.job.yml`,
  ahead of the pipeline task.
- **`bronze/`** — Lakeflow bronze source (`.sql`/`.py`) that reads the landed
  `.dat`/`.lob` files into bronze tables. This is the only path under `ingest/`
  globbed as pipeline source, so `land_raw.py` is never imported by the pipeline.
  Placeholder — no bronze definitions yet.
