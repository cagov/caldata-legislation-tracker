# CLAUDE.md

## Project Overview

Build a tracker for pending legislation and regulations in California that involve data or technology.
Secondary objective: develop best practices for working with claude code and databricks that can be used by any Office of Data and Innovation project.

---
## Tech Stack

This is a learning project to explore both claude code and databricks.
Follow these principles when building
- Open
- Modular
- Interoperable
- Non-coder friendly
- Governed
- Platform is all Infrastructure as Code

To that end, lean toward using these parts of the databricks stack.
- **Delta Lake with UniForm enabled** for storage — UniForm writes valid Iceberg metadata alongside Delta tables, satisfying the interoperability principle without sacrificing native Databricks tooling (Lakeflow, UC, Genie all work natively with Delta)
- **Data Asset Bundles** for IaC
- **Unity Catalog** for governance (use this to its fullest so we can test it)
- **Lakeflow Jobs and Lakeflow Spark Declarative Pipelines** for modular, medallion-style transformations (bronze → silver → gold)
- **Semantic Layer** via Unity Catalog Metric Views and Genie — note that Metric Views and Genie Spaces are not yet native DAB resource types, so they require SDK scripts or MCP provisioning outside the bundle (known gap)
- **Inline SQL `COMMENT` clauses** for data documentation — declared in pipeline `.sql` files, stored in Unity Catalog, and consumed by Genie. Document gold layer always; bronze when raw field names are cryptic; silver is optional. Comments do not inherit across layers — each table must be documented explicitly.
Finally, use components that are building blocks for agent-data interfaces (e.g. the databricks-ai-devkit).

---

## Red Lines — Never Do These

- **Never `git commit` or `git push`. Kindly remind the human to make their own commits. It is okay for you to use read-only git commands.**
- **Never deploy to a production target without explicit confirmation**
- **Never drop, truncate, or overwrite production data EVER (you should only edit the DEV environment)**
- **If you can see a secret or confidential data, notify the human immediately.**

---

## Code style

Prefer code that is expressive, succinct, explicit, and legible.
Do not over-engineer. Avoid premature abstraction.
Flag dead code for the human.


Comment in code to explain *why*, never *what*. Comments should be evergreen, self-explanatory. If something is important, put it in the comment text directly.

## Testing
This project uses pre-commit hooks for linting/formatting
After editing files, run uv run pre-commit run --files <edited files> as a courtesy
Fix any issues reported before considering the task done
When adding a new behavior, ask the human if a test should be written first.
Avoid silent failures. Exceptions should be raised explicitly unless otherwise instructed. Do not hide failures with dummy values unless specifically told to. Try/except blocks should be used sparingly and catch specific cases.

**Write less code, not more.** Default to the smallest implementation that solves the problem.

---

## Common Commands

All Python tooling uses [uv](https://docs.astral.sh/uv/).
Never invoke `pip` directly — use `uv add <package>` to add dependencies (or `uv add --dev <package>` for dev deps)

```bash
uv run ruff check --fix          # lint
uv run ruff format               # format
uv run mypy .                    # type check
uv run pre-commit run --all-files
uv run pytest
uv run pytest -k <test_name>     # single test
```

## TODO (HUMANS)
A series of decisions that should be added to this doc once a convention is decided:
- Deployment: Databricks asset bundles? CLI workspace?
- Testing: local only? there are also some databricks cloud options it seems
- Architecture. We should probably write out the architecture somewhere. (e.g medallion, roles based permissions, etc. )
- Do we put linting conventions here, or do we rely on traditional linters? (I think the latter, b/c the bot can infer those from the repo?)
