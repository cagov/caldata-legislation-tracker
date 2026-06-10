# CalData Legislation Tracker

A demonstration data project that tracks California legislation and regulation as they
move through their respective processes. Built on **Azure Databricks** using Databricks-native
idioms: **Unity Catalog**, **Lakeflow Declarative Pipelines**, and **Databricks Asset Bundles**.

## Architecture

An ETL flow over a Unity Catalog medallion architecture, all in a single catalog
(`caldata_legislation_tracker`, the workspace's default managed catalog) with
`bronze` / `silver` / `gold` schemas:

```
ingest  → bronze   raw landing (Auto Loader over the CA leginfo dump)
transform → silver  cleaned, typed, validated tables
publish → gold     business-level marts for analysis & reporting
```

- **`databricks.yml`** — the Asset Bundle: the project's infrastructure-as-code-lite.
- **`resources/`** — the Lakeflow Declarative Pipeline and the orchestrating Job.
- **`src/{ingest,transform,publish}/`** — Databricks SQL for each layer (placeholders at bootstrap).

Compute is **serverless** — no clusters to manage. The bundle deploys via
`databricks bundle deploy`; classic ("hybrid") compute is a small YAML change if ever needed.

## Source data

California's legislature publishes weekly public-information dumps at
[`downloads.leginfo.legislature.ca.gov`](https://downloads.leginfo.legislature.ca.gov)
(`pubinfo_*.zip`). Ingestion will pull from there into a Unity Catalog volume. The bulk data is
**never committed** to this repo (see `.gitignore`).

## Getting started

See **[docs/setup.md](docs/setup.md)** for the full setup — provisioning the Azure Databricks
workspace, installing the toolchain, authenticating, and the dev loop. In brief:

```bash
# Note: the Databricks CLI is in Databricks' tap, not homebrew-core.
brew install databricks/tap/databricks uv azure-cli   # system tools
uv sync                                                # project Python deps
databricks auth login --host https://adb-7405607841560793.13.azuredatabricks.net --profile legislation
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

## AI dev kit

This repo uses the [Databricks AI dev kit](https://github.com/databricks-solutions/ai-dev-kit) to
give Claude Code Databricks skills and an MCP server. It's per-developer local tooling — each
person runs the installer once (its generated files are git-ignored). See [docs/setup.md](docs/setup.md).

## License

[MIT](LICENSE)
