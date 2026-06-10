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

- **Unity Catalog** — a single `caldata_legislation_tracker` catalog with `bronze` / `silver` / `gold` schemas.
- **Lakeflow Declarative Pipelines** — SQL transformations, serverless.
- **Databricks Asset Bundles** — jobs and pipelines defined as code (`databricks.yml`), our
  path toward fuller infrastructure-as-code.
- **Databricks AI dev kit** — Databricks skills and an MCP server wired into Claude Code.

## Next steps

- [Setup](setup.md) — provision the workspace, install tooling, authenticate, and deploy.
