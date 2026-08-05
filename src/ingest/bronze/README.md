# `ingest/bronze/`

Lakeflow bronze source. The pipeline globs `../src/ingest/bronze/**`.

- **`leginfo_bronze.py`** — reads the zips landed by `../land_raw.py` and unzips them
  in-memory across the pipeline's executors, writing straight to Delta (no loose files
  on the volume). Produces `bronze.lob_raw` (all `.lob` payloads, keyed by filename) and
  one `bronze.<table>_raw` per `*_TBL.dat`. Source/loader zip paths come from the pipeline
  `configuration` block in `resources/legislation.pipeline.yml`.

Pure parsing helpers here are unit-tested in `tests/test_leginfo_bronze.py`.
