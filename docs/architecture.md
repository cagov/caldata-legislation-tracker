# Architecture: raw vs. medallion, and per-developer isolation

This is the project's actual data-environment model — read this before adding any
table, volume, or schema reference. It exists because an earlier change hardcoded
schema names as literal strings in SQL/Python, which silently broke the moment
Databricks Asset Bundles' dev-mode prefixing was involved. The rules below are
written to be mechanically followed, including by Claude Code: **if you are about
to write a schema or catalog name into a `.sql` or `.py` file, stop and re-read
this page first.**

## Current state vs. target state — read this part first

**There is currently no real `prod` environment, and no access-control boundary
enforcing one.** This matters more than the rest of this page, so it's stated up
front rather than buried:

- `caldata_legislation_tracker` (the one Unity Catalog catalog this project uses)
  contains Ian's unprefixed `bronze`/`silver`/`gold` schemas — created as
  placeholders for a future canonical prod, but **nothing currently deploys or
  writes to them**. No CI/CD exists yet (tracked in `CLAUDE.md`'s `TODO (HUMANS)`),
  and no `-t prod` bundle deploy has ever been run.
- `SHOW GRANTS ON CATALOG caldata_legislation_tracker` (checked 2026-07-23) returns
  `account users` → `ALL PRIVILEGES`. **Every workspace user — including via
  Claude Code — can currently write to or drop Ian's `bronze`/`silver`/`gold`
  directly.** The only thing protecting them today is convention ("don't touch
  those"), not a technical control.
- The originally-intended fix was **catalog-per-environment**: a separate
  `caldata_legislation_tracker_dev` catalog for all developer work, leaving
  `caldata_legislation_tracker` exclusively for prod with RBAC restricting writes
  to a future CI/CD service principal. **This is blocked**: creating a new
  catalog requires the metastore-level `CREATE CATALOG` privilege, which is
  admin-only (this metastore has no registered storage credential/external
  location, so new catalogs can *only* use Default Storage, which in turn can
  *only* be created via the UI by someone with that privilege — regular
  workspace users, including the author of this doc, don't have it).
- **Until an account admin acts, `caldata_legislation_tracker` is being used as
  the de facto dev catalog** — every developer's `dev_<user>_bronze/silver/gold`
  schema (see below) lives right alongside Ian's placeholder prod schemas, in the
  same catalog, with the same (currently wide-open) grants.

**TODO (HUMANS) — needs an account admin:**
1. Either (a) create `caldata_legislation_tracker_dev` via the UI (Catalog
   Explorer → Create Catalog → Default Storage), or (b) grant a developer
   `CREATE CATALOG ON METASTORE` so it can be scripted. (a) is simpler for a
   one-time action.
2. Once a real dev catalog exists: add `variables.catalog` override for the
   `dev` target in `databricks.yml` (`caldata_legislation_tracker_dev`), migrate
   the per-developer schemas out of the shared catalog, and apply the grants in
   [RBAC](#rbac-current-gap-and-target-state) below.
3. Until then, don't assume `bronze`/`silver`/`gold` (unprefixed) are actually
   isolated from dev work — they're not, technically, only by convention.

## Unity Catalog hierarchy, mapped to dbt/Snowflake terms

If you're coming from dbt/Snowflake, the concepts don't line up name-for-name —
this is the mapping that matters for this project:

```
Metastore   (account-level, one per region — not ours to manage)
  └─ Catalog     ≈ a Snowflake/dbt "database"
       └─ Schema      ≈ a Snowflake/dbt "schema"
            └─ Table / View / Volume / Function / Model
```

Your prior dbt/Snowflake setup's "separate databases for prod and dev" pattern is
the UC equivalent of **separate catalogs** — not separate schemas within one
catalog. That's the target state above (blocked). What's actually running today
is closer to a different, also-valid dbt pattern: one shared database with a
schema per developer (`target.schema` set per-developer in `profiles.yml`) — see
the next section.

## Two tiers, treated completely differently

### 1. `raw` — one copy, ever, shared by everyone

The literal bytes downloaded from the source (for this project: the CA leginfo
`pubinfo_*.zip` + a fetch manifest) live in **`{catalog}.bronze.raw`** — a Unity
Catalog volume that already exists (created once by an admin; see
[setup.md](setup.md#project-provisioning-admin-one-time)). This volume:

- Is **never duplicated per developer**. Downloading a ~1 GB zip is expensive;
  every developer and prod reads the exact same landed files.
- Is **never touched by dev-mode prefixing**. Its path is a fixed literal,
  `/Volumes/{catalog}/bronze/raw/...`, hardcoded in `jobs/land_raw.py`. This is
  the **one deliberate exception** to the "never hardcode a schema name" rule
  below — it's an exception because this data is never mutated by a pipeline,
  so there is nothing for per-developer isolation to protect.
- Holds the zip/manifest exactly as fetched — no parsing, no joins, no typing.

If you're tempted to add a second raw-landing volume "for dev," don't — route
around the SSL/network problem some other way (e.g. downloading locally and
uploading the *result of parsing*, not a duplicate raw zone) instead of
duplicating the one shared copy.

### 2. `bronze` / `silver` / `gold` — medallion layers, environment-scoped by schema (today) or catalog (target)

Everything downstream of "read the raw bytes" — joining a `.dat` row to its
`.lob` body, typing a column, aggregating a mart — counts as **manipulating
data**, and every such artifact (staging volumes, tables, views) must be
**environment-scoped**:

- **`dev` target**: each developer's copy is isolated and disposable.
  Databricks Asset Bundles' `mode: development` auto-prefixes bundle-declared
  resource names with `dev_<user>_`, so `bronze` becomes `dev_andrew_king_bronze`,
  `silver` becomes `dev_andrew_king_silver`, etc. Iterate freely; `bundle destroy
  -t dev` tears down only your own copy. **Today this isolation is
  namespace-only** (schema-name prefixing within the one shared catalog) — see
  [Current state vs. target state](#current-state-vs-target-state--read-this-part-first)
  for why it isn't yet also access-controlled.
- **`prod` target**: intended to be a single canonical `bronze` / `silver` /
  `gold` (no prefix — `mode: production` deploys names as-is), with the bundle
  *adopting* the schemas the admin provisioning step already created (via
  `databricks bundle deployment bind`) rather than recreating them. **Not
  real yet** — no CI/CD runs this target, per the TODO above.

Because both targets currently share the same physical catalog
(`databricks.yml`'s `catalog` variable), the only thing separating a developer's
tables from prod's placeholder schemas is this per-target schema name — which is
exactly why it can never be a hardcoded literal, target-state catalog-split or not.

## The mechanical rule

**A schema name is never a literal string in `.sql` or `.py`, with the single
exception of the `raw` volume above.** Concretely:

1. Bundle resources (`resources/legislation.catalog.yml`) declare each schema
   *once*: `resources.schemas.bronze`, `.silver`, `.gold`, plus the per-developer
   staging volume `resources.volumes.parsed_raw` (inside the `bronze` schema —
   this is where `jobs/land_raw.py` writes its joined Parquet output, distinct
   from the shared `bronze.raw` zip volume above).
2. **Anything in bundle YAML** references a schema via
   `${resources.schemas.bronze.name}` — never types "bronze" as a bare string.
   For example, `resources/legislation.pipeline.yml` sets its default schema to
   `${resources.schemas.silver.name}`, not `silver`.
3. **`.sql` and `.py` files can't see bundle variables directly** — they only
   see whatever the pipeline `configuration:` block or a job's `parameters:`
   list hands them as a plain string. So:
   - `legislation.pipeline.yml`'s `configuration:` block exposes `catalog`,
     `bronze_schema`, `gold_schema` (silver doesn't need exposing — see below).
   - Bronze/gold `.sql` files reference `${bronze_schema}` / `${gold_schema}` as
     plain substitution text, e.g.
     `CREATE OR REFRESH STREAMING TABLE ${bronze_schema}.bill ...` and
     `read_files('/Volumes/${catalog}/${bronze_schema}/${parsed_volume}/...')`.
   - **Silver `.sql` files never qualify a schema at all** — the pipeline's own
     default schema is already `${resources.schemas.silver.name}`, so a bare
     `CREATE OR REFRESH MATERIALIZED VIEW bill AS ...` lands in the right place
     automatically. This is the one case where *not* writing a schema name is
     the correct, parameterized behavior.
   - `resources/legislation.job.yml` passes `jobs/land_raw.py` its schema/volume
     names as `parameters:`, resolved from `${resources.schemas.bronze.name}`
     and `${resources.volumes.parsed_raw.name}` — the script never hardcodes
     them (only the fixed `bronze.raw` exception above is hardcoded).
4. A pre-commit hook (`scripts/check_schema_literals.py` — see
   `.pre-commit-config.yaml`) greps tracked `.sql`/`.py` files for bare
   `bronze.`/`silver.`/`gold.` literals or hardcoded `/Volumes/.../bronze/`,
   `/silver/`, `/gold/` paths, and fails the commit if it finds one outside the
   documented `bronze.raw` exception. If this hook blocks you, you've almost
   certainly hit the mistake this page exists to prevent — parameterize instead
   of suppressing the check.

## RBAC: current gap and target state

**Current (2026-07-23):** `GRANT ALL PRIVILEGES ON CATALOG caldata_legislation_tracker
TO \`account users\`` (from `docs/setup.md`'s provisioning step) is a blanket grant
across the whole catalog — dev schemas and Ian's placeholder prod schemas alike.
Nothing enforces "only CI/CD writes to prod." This is a known, tracked gap, not an
oversight to silently work around.

**Target, once a real prod catalog exists** (see the TODO above):
- Dev catalog: `GRANT ALL PRIVILEGES ON CATALOG <dev catalog> TO \`account users\`` —
  wide open is correct here, that's the point of a disposable dev environment.
- Prod catalog: revoke the blanket grant; replace with
  `GRANT USE CATALOG, USE SCHEMA, SELECT, READ VOLUME ON CATALOG <prod catalog> TO
  \`account users\`` (read-only — people can query/reference prod, not write it),
  and reserve `MODIFY`/`CREATE TABLE`/etc. for a CI/CD service principal once one
  exists.
- The `raw.raw` volume's `READ VOLUME` grant must remain available cross-catalog
  to whichever catalog dev pipelines run in, since dev reads raw input from prod's
  catalog even though it writes medallion output to its own.

## One-time prod setup (blocked — see TODO above)

Once a real prod catalog/target exists, binding the bundle's schema resources to
the schemas an admin already created lets `bundle deploy -t prod` reconcile
instead of erroring "already exists":

```bash
databricks bundle deployment bind resources.schemas.bronze bronze -t prod
databricks bundle deployment bind resources.schemas.silver silver -t prod
databricks bundle deployment bind resources.schemas.gold gold -t prod
```

CI/CD running `databricks bundle deploy -t prod` + `databricks bundle run
legislation_job -t prod` on merge to `main` is also future work — see
`CLAUDE.md`'s `TODO (HUMANS)`.
