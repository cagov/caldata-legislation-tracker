# CalData Legislation Tracker

A demonstration data project that tracks California legislation and regulation as they
move through their respective processes. Built on **Azure Databricks** using Databricks-native
idioms: **Unity Catalog**, **Lakeflow Declarative Pipelines**, and **Databricks Asset Bundles**.

## New developer onboarding

Everything you need to start working. The workspace and Unity Catalog already exist, so this is
just local tooling + auth (~10 min). Full detail: [docs/setup.md](docs/setup.md#developer-onboarding).

```bash
# 1. System tools — the Databricks CLI is in Databricks' tap, not homebrew-core
brew install databricks/tap/databricks uv azure-cli

# 2. Project Python deps
uv sync

# 3. Authenticate (everyone uses the `legislation` profile)
databricks auth login --host https://adb-7405607841560793.13.azuredatabricks.net --profile legislation

# 4. Verify your setup — resolves config against the workspace, creates nothing
databricks bundle validate -t dev

# 5. AI dev kit — Claude Code skills + MCP server (per-developer, git-ignored)
bash <(curl -sL https://raw.githubusercontent.com/databricks-solutions/ai-dev-kit/main/install.sh) \
  --tools claude --skills-profile data-engineer,analyst --profile legislation

# 6. Enable pre-commit hooks
uv run pre-commit install
```

Deploying and running pipelines is the [dev loop](docs/setup.md#the-dev-loop) — not part of
onboarding. Admin tasks (workspace + catalog provisioning, adding teammates) live in
[docs/setup.md](docs/setup.md#project-provisioning-admin-one-time).

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


## Documentation

All pipeline SQL files should document tables and columns inline using `COMMENT` clauses,
which feed the Unity Catalogue.
Strive to have complete documentation for the gold layer,
and document bronze/silver when column names are not intuitive,
or contain hidden assumptions/gotchas.
Try to capture human subject-matter expertise in these comments,
don't just let coding assistants make it up.

For example:

```sql
 CREATE OR REFRESH MATERIALIZED VIEW gold.bills
 COMMENT 'Active California bills involving data or technology'
 (
   bill_id COMMENT 'Unique identifier — e.g. AB-1234 or SB-567',
   status  COMMENT 'Current stage in the legislative process'
 )
 AS SELECT ...
```

## Source data

California's legislature publishes weekly public-information dumps at
[`downloads.leginfo.legislature.ca.gov`](https://downloads.leginfo.legislature.ca.gov)
(`pubinfo_*.zip`). Ingestion will pull from there into a Unity Catalog volume. The bulk data is
**never committed** to this repo (see `.gitignore`).

## License

[MIT](LICENSE)
