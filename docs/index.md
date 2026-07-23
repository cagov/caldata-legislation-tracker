# CalData Legislation Tracker

A demonstration data project that tracks California legislation and regulation as they move
through their respective processes, built on **Azure Databricks**.

## What it does

The project ingests California's published legislative data, transforms it into clean,
queryable tables, and publishes business-level marts for analysis — following an
ingest → transform → publish flow over a Unity Catalog medallion architecture
(`bronze` → `silver` → `gold`).

## How it's built

The project leans on Databricks-native idioms rather than porting a Snowflake/dbt shape:

- **Unity Catalog** — a single `caldata_legislation_tracker` catalog with `bronze` / `silver` /
  `gold` schemas. `bronze`/`silver`/`gold` are environment-scoped (per-developer under `dev`,
  single canonical copy under `prod`) — see [Architecture](architecture.md). The raw downloaded
  source data is the one exception: a single shared, never-duplicated landing volume.
- **Lakeflow Declarative Pipelines** — SQL transformations, serverless.
- **Databricks Asset Bundles** — jobs and pipelines defined as code (`databricks.yml`), our
  path toward fuller infrastructure-as-code.
- **Databricks AI dev kit** — Databricks skills and an MCP server wired into Claude Code.

## Next steps

- [Architecture](architecture.md) — the raw-vs-medallion data model and per-developer isolation
  rules; read this before touching any schema/catalog reference.
- [Setup](setup.md) — provision the workspace, install tooling, authenticate, and deploy.
