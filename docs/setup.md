# Setup

**New developer?** Do everything under **[Developer onboarding](#developer-onboarding)** — that's
all you need to start working. The sections after it are reference:

- **[The dev loop](#the-dev-loop)** — deploy/run a pipeline once you're building.
- **[Project provisioning](#project-provisioning-admin-one-time)** — how the workspace + catalog
  were created (admin, already done).
- **[Managing access](#managing-access-admin)** — adding teammates (admin).

---

## Developer onboarding

Everything a new developer runs once on their own machine. The workspace and Unity Catalog already
exist, so this is just local tooling + auth — about ten minutes.

### 1. Install the toolchain

There's a clean split between **system binaries** (installed once, via Homebrew) and **project
Python dependencies** (managed by `uv` from `pyproject.toml`).

System binaries — _not_ in `pyproject.toml`:

```bash
# The Databricks CLI lives in Databricks' own Homebrew tap, NOT homebrew-core.
# `brew install databricks` alone will report "no available formula".
brew install databricks/tap/databricks   # the unified Databricks CLI (drives bundles + auth)

brew install uv         # manages the project's Python environment
brew install azure-cli  # only needed for the admin provisioning steps
```

Verify the CLI is the modern, bundle-capable one (expect `v0.2xx` or newer):

```bash
databricks --version
```

!!! warning
    Install the Go-based CLI from the tap above. Do **not** `pip install databricks-cli` — that's
    the deprecated legacy (v0.x) Python CLI with **no Asset Bundle support**, and it shadows the
    `databricks` command.

Then install the project's Python dependencies (`databricks-sdk`, `mkdocs-material`, dev tools):

```bash
uv sync
```

### 2. Authenticate the Databricks CLI

```bash
databricks auth login --host https://adb-7405607841560793.13.azuredatabricks.net --profile legislation
```

This creates an OAuth profile in your local `~/.databrickscfg`. **Everyone uses the same profile
name, `legislation`** — the name is local to each machine, so there's no reason for it to differ
per developer, and keeping it consistent means every command in these docs (and the AI dev kit's
`--profile legislation` flag) is copy-paste for the whole team.

(The host is also pinned in `databricks.yml`, so even a differently-named profile pointing at this
host would still be auto-selected by `databricks bundle` — but standardize on `legislation`.)

### 3. Verify your setup

A side-effect-free check that your toolchain and auth work — it resolves the bundle config against
the workspace **without creating anything**:

```bash
databricks bundle validate -t dev
```

You should see `Validation OK!`. That's the bar for being set up — you do **not** need to deploy.

### 4. Install the Databricks AI dev kit

The AI dev kit is **per-developer local tooling — each person runs the installer once**; its
generated files are not committed. It gives Claude Code Databricks skills and an MCP server:

```bash
bash <(curl -sL https://raw.githubusercontent.com/databricks-solutions/ai-dev-kit/main/install.sh) \
  --tools claude \
  --skills-profile data-engineer,analyst \
  --profile legislation
```

This generates `.mcp.json`, `.claude/skills/`, and a local `.ai-dev-kit/` state directory — all
**git-ignored**. `.mcp.json` is intentionally not committed because it embeds a machine-specific
path to the MCP server in your home directory; the skills are installer-managed, so the installer
(not the repo) is their source of truth. Re-run the command to update skills or repoint the profile.

### 5. Enable pre-commit hooks

```bash
uv run pre-commit install          # run hooks on every commit
uv run pre-commit run --all-files  # run them manually now
```

Hooks: `ruff` (Python lint + format), `sqlfluff` (Databricks SQL), plus YAML/JSON/whitespace
checks, `prettier`, and `yamllint`.

---

## The dev loop

`deploy` and `run` belong to active development, not onboarding. There's no reason for every new
teammate to deploy on day one (at bootstrap there's no pipeline SQL yet, so it would just create
empty resources).

```bash
databricks bundle deploy -t dev              # provision your copy of the pipeline + job
databricks bundle run legislation_job -t dev # execute it (uses serverless compute)
databricks bundle destroy -t dev             # tear your copy back down
```

`dev` mode prefixes every bundle-declared resource with your username — not just the job/pipeline
(e.g. `[dev ian_rose] legislation_job`), but also the `bronze`/`silver`/`gold` schemas and staging
volume declared in `resources/legislation.catalog.yml` (e.g. `dev_ian_rose_bronze`). That schema-level
isolation is what actually prevents developers from colliding when their pipelines write tables —
see [Architecture](architecture.md) for the full rule and the one exception (the shared `raw`
landing volume). Each developer can `destroy` their own copy independently.

---

## Project provisioning (admin, one-time)

!!! note "Already done for this project"
    The workspace and Unity Catalog catalog already exist. This is the reproducible record of how
    they were created — run it only when standing the project up from scratch.

### Azure Databricks workspace

Created once with the Azure CLI, reusing the existing `rg-doe-databricks` resource group. (For a
brand-new workspace, do this *before* onboarding step 2 and authenticate against the resulting
`workspaceUrl`.)

```bash
az login
az account set --subscription <subscription>   # if you have more than one
az extension add --name databricks              # if not already installed

az databricks workspace create \
  --resource-group rg-doe-databricks \
  --name <workspace-name> \
  --location <region> \
  --sku premium                                 # Premium is REQUIRED for Unity Catalog
```

The `workspaceUrl` in the output is the workspace host — for this project,
**`adb-7405607841560793.13.azuredatabricks.net`** (already pinned in `databricks.yml`). Databricks
also creates its own managed resource group for the workspace's internal VNet/storage; that's
expected and separate from `rg-doe-databricks`.

### Unity Catalog schemas

For Azure accounts created after Nov 2023, a Unity Catalog metastore is auto-provisioned per region
and auto-assigned to new workspaces — and the workspace gets a **default managed catalog named
after itself**, `caldata_legislation_tracker`, with managed storage already wired. We **reuse that
catalog** rather than creating a new one: it avoids the Default Storage limitation (the
`databricks catalogs create` CLI/API can't target Default Storage —
[databricks/cli#4513](https://github.com/databricks/cli/issues/4513)).

So there's no catalog to create — just add the medallion schemas. **These three are intended to
become the single canonical `prod` schemas** once a real prod environment exists — see
[Architecture](architecture.md#current-state-vs-target-state--read-this-part-first) for the current
(blocked) status. Today, nothing actually deploys to them and nothing technically stops a developer
from writing to them either — that's a tracked gap, not the design:

```bash
databricks schemas create bronze caldata_legislation_tracker
databricks schemas create silver caldata_legislation_tracker
databricks schemas create gold   caldata_legislation_tracker
```

The bundle points at this catalog via the `catalog` variable in `databricks.yml`. `dev` and `prod`
currently resolve to the *same* catalog (see Architecture) — `resources/legislation.catalog.yml`
declares `bronze`/`silver`/`gold` as managed schema resources, which is why `dev` deploys get their
own auto-prefixed `dev_<user>_*` copies alongside these. **Once a real prod catalog/target exists**,
deploying to it for the first time will require binding those bundle declarations to the schemas
created above, so `bundle deploy -t prod` reconciles instead of erroring "already exists" — not
needed yet, since no `-t prod` deploy has ever been run:

```bash
databricks bundle deployment bind resources.schemas.bronze bronze -t prod
databricks bundle deployment bind resources.schemas.silver silver -t prod
databricks bundle deployment bind resources.schemas.gold gold -t prod
```

The one exception is the raw landing volume (`bronze.raw`), which is never bundle-managed and never
per-developer — see [Architecture](architecture.md#1-raw--one-copy-ever-shared-by-everyone) for why:

```bash
databricks volumes create caldata_legislation_tracker bronze raw --volume-type MANAGED
```

---

## Managing access (admin)

No Entra group is required. This workspace's default catalog `caldata_legislation_tracker` is owned
by the workspace-admins group, and Databricks already grants **`USE CATALOG`** on it to **all
workspace users** — so access is mostly automatic. Onboarding is two steps.

### One-time: grant working privileges to all workspace users

A workspace admin runs this once (in a SQL editor or notebook), so every current and future member
can build. `USE CATALOG` is already granted; this adds read + create/modify:

```sql
-- Simplest for a single-purpose demo workspace — everyone is a builder:
GRANT ALL PRIVILEGES ON CATALOG caldata_legislation_tracker TO `account users`;
```

**This is what's actually applied today** (verified via `SHOW GRANTS ON CATALOG
caldata_legislation_tracker`, 2026-07-23) — and per
[Architecture](architecture.md#rbac-current-gap-and-target-state), it's a known,
tracked gap: it grants every workspace user write access to Ian's placeholder
prod schemas, not just their own dev schema. It's tolerable only because no real
prod deployment exists yet. Revisit this — with the tiered grant below, split
across a real dev catalog and a locked-down prod catalog — once the blocked
`CREATE CATALOG` TODO in `CLAUDE.md` is resolved.

For tiered least-privilege instead:

```sql
-- Read-only:
GRANT USE SCHEMA, SELECT ON CATALOG caldata_legislation_tracker TO `account users`;
-- Developer extras (pipelines, volumes):
GRANT MODIFY, CREATE TABLE, CREATE MATERIALIZED VIEW, CREATE VOLUME, READ VOLUME, WRITE VOLUME
  ON CATALOG caldata_legislation_tracker TO `account users`;
```

`account users` is safe here: the **workspace–catalog binding** means only people assigned to this
workspace can use the catalog, even though the group is account-wide.

### Per new developer: add them to the workspace

That's the only recurring step — they inherit the grants above, and serverless compute means no
cluster permissions to hand out.

1. In the workspace, open **Settings → Identity and access → Users → Add user** and enter their
   email. They must exist in your Microsoft **Entra** tenant. If they're not yet in the Databricks
   *account* and you're not an account admin, an account admin adds them to the account once; then
   you assign them to the workspace. (Workspace admin ≠ account admin — the one boundary you may hit.)
2. New workspace users get **Workspace access** and **Databricks SQL access** by default.
