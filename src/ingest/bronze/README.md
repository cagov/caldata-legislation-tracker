# `ingest/bronze/`

Lakeflow bronze source. The pipeline globs `../src/ingest/bronze/**`, so `.sql`
and `.py` files here become bronze tables that read the raw `.dat`/`.lob` files
landed by `../land_raw.py`. Placeholder — no definitions yet.
