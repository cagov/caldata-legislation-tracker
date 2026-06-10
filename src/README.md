# `src/` — pipeline source

The ETL flow maps onto a Unity Catalog medallion architecture. Directory names use
the ETL verbs; the schemas they write to use the medallion layer names:

| Directory      | Stage     | Target schema | What lives here                                        |
| -------------- | --------- | ------------- | ------------------------------------------------------ |
| `ingest/`      | ingest    | `bronze`      | Raw landing — Auto Loader streaming tables over the CA leginfo dump |
| `transform/`   | transform | `silver`      | Cleaned, typed, validated tables                       |
| `publish/`     | publish   | `gold`        | Business-level marts for analysis/reporting            |

All three are loaded by the Lakeflow Declarative Pipeline defined in
`resources/legislation.pipeline.yml`. Write Databricks SQL (`*.sql`) and fully
qualify table names with their schema, e.g. `CREATE OR REFRESH STREAMING TABLE
bronze.bill_raw ...`.

At bootstrap these directories hold only placeholders — no pipeline logic yet.
