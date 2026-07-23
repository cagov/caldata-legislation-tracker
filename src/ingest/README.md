# `ingest/` → `bronze`

Raw landing layer. `bronze_raw.sql` defines one `STREAMING TABLE` per source
table, reading Parquet from the Unity Catalog raw volume — not the CA leginfo
`.dat`/`.lob` files directly. The download-and-join step (`jobs/land_raw.py`,
outside this directory since it's a single-node Job task, not pipeline source)
runs first and writes that Parquet; see `ca-leginfo-bulk-download.md` §4.
