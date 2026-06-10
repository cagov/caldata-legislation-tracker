# Setup

This guide covers provisioning the Azure Databricks workspace, installing the local toolchain,
authenticating, and the day-to-day developer loop.

## 1. Local toolchain

There's a clean split between **system binaries** (installed once, via Homebrew) and
**project Python dependencies** (managed by `uv` from `pyproject.toml`).

System binaries — _not_ in `pyproject.toml`:

```bash
# The Databricks CLI lives in Databricks' own Homebrew tap, NOT homebrew-core.
# `brew install databricks` alone will report "no available formula".
brew install databricks/tap/databricks   # the unified Databricks CLI (drives bundles + auth)

brew install uv         # manages the project's Python environment
brew install azure-cli  # used to provision the workspace
```

Verify the CLI is the modern, bundle-capable one (expect `v0.2xx` or newer):

```bash
databricks --version
```

!!! warning
    Install the Go-based CLI from the tap above. Do **not** `pip install databricks-cli` — that's
    the deprecated legacy (v0.x) Python CLI with **no Asset Bundle support**, and it shadows the
    `databricks` command.

Project Python deps (`databricks-sdk`, `mkdocs-material`, plus dev tools) are installed with:

```bash
uv sync
```

## 2. Authenticate the Databricks CLI

```bash
databricks auth login --host https://adb-7405607841560793.13.azuredatabricks.net --profile legislation
```

This creates an OAuth profile in your local `~/.databrickscfg`. **Everyone uses the same profile
name, `legislation`** — the name is local to each machine, so there's no reason for it to differ
per developer, and keeping it consistent means every command in these docs (and the AI dev kit's
`--profile legislation` flag) is copy-paste for the whole team.

(The host is also pinned in `databricks.yml`, so even a differently-named profile pointing at this
host would still be auto-selected by `databricks bundle` — but standardize on `legislation`.)

## 3. One-time project provisioning

!!! note "Admin, once per project — most developers can skip to step 4"
    The workspace and Unity Catalog catalog already exist for this project. This section is the
    reproducible record of how they were created; run it only when standing the project up from
    scratch.

### Azure Databricks workspace

Created once with the Azure CLI, reusing the existing `rg-doe-databricks` resource group. (For a
brand-new workspace, do this *before* step 2 and authenticate against the resulting `workspaceUrl`.)

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

### Unity Catalog: catalog and schemas

For Azure accounts created after Nov 2023, a Unity Catalog metastore is auto-provisioned per region
and auto-assigned to new workspaces — and the workspace gets a **default managed catalog named
after itself**, `caldata_legislation_tracker`, with managed storage already wired. We **reuse that
catalog** rather than creating a new one: it avoids the Default Storage limitation (the
`databricks catalogs create` CLI/API can't target Default Storage —
[databricks/cli#4513](https://github.com/databricks/cli/issues/4513)).

So there's no catalog to create — just add the medallion schemas (authenticate in step 2 first):

```bash
databricks schemas create bronze caldata_legislation_tracker
databricks schemas create silver caldata_legislation_tracker
databricks schemas create gold   caldata_legislation_tracker
```

The bundle points at this catalog via the `catalog` variable in `databricks.yml` (default
`caldata_legislation_tracker`) but does not own it; the catalog, schemas, and grants are the
natural contents of a future Terraform IaC layer.

## 4. Verify your setup

The last setup step is a side-effect-free check that your toolchain and auth work. It resolves
the bundle config against the workspace **without creating anything**:

```bash
uv sync
databricks bundle validate -t dev
```

You should see `Validation OK!`. That's the end of setup — you do **not** need to deploy to be
set up.

## 5. Databricks AI dev kit

The AI dev kit is **per-developer local tooling — each person runs the installer once**; its
generated files are not committed. Install it scoped to this project so Claude Code gets Databricks
skills and an MCP server:

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

## 6. Adding teammates

Access is click-ops friendly and group-based:

1. **Add the person to Microsoft Entra ID** (your org's directory) if they aren't already.
2. In the workspace, go to **Settings → Identity and access** and add the user — or, better, an
   Entra **group** such as `legislation-developers`. (Automatic identity management lets a
   workspace admin search Entra directly; no SCIM setup needed.)
3. **Grant the group Unity Catalog privileges** on the `legislation` catalog once — in Catalog
   Explorer or via SQL:

   ```sql
   GRANT USE CATALOG ON CATALOG caldata_legislation_tracker TO `legislation-developers`;
   GRANT USE SCHEMA, SELECT ON CATALOG caldata_legislation_tracker TO `legislation-developers`;
   GRANT CREATE SCHEMA ON CATALOG caldata_legislation_tracker TO `legislation-developers`;  -- for developers
   ```

After that, onboarding a new teammate is just adding them to the group. Serverless compute means
there are no cluster permissions to hand out — new users can run SQL and notebooks immediately.

## 7. Pre-commit

```bash
uv run pre-commit install          # enable hooks on commit
uv run pre-commit run --all-files  # run them manually
```

Hooks: `ruff` (Python lint + format), `sqlfluff` (Databricks SQL), plus YAML/JSON/whitespace
checks, `prettier`, and `yamllint`.

## The dev loop (when you start building pipelines)

`deploy` and `run` belong to active development, not onboarding — so they live here, not in setup.
There's no reason for every new teammate to deploy on day one (at bootstrap there's no pipeline
SQL yet, so it would just create empty resources).

```bash
databricks bundle deploy -t dev              # provision your copy of the pipeline + job
databricks bundle run legislation_job -t dev # execute it (uses serverless compute)
databricks bundle destroy -t dev             # tear your copy back down
```

`dev` mode prefixes every resource with your username (e.g. `[dev ian_rose] legislation_job`) and
deploys under your own workspace user folder, so developers never collide and each can `destroy`
their own copy independently.
