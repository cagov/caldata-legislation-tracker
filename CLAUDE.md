# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Build a tracker for pending legislation and regulations in California that involve data or technology.
Secondary objective: develop best practices for working with claude code and databricks that can be used by any Office of Data and Innovation project.

---
## Tech Stack
Work in databricks, claude code, github. 

---

## Red Lines — Never Do These

- **Never `git commit` without explicit human permission**
- **Never `git push` without explicit human permission**
- **Never deploy to a production target without explicit confirmation**
- **Never drop, truncate, or overwrite production data EVER (you should only edit the DEV environment)**

---

## Working with Humans

**Default to plan mode.** Before writing any code (except single-line fixes), enter plan mode and get approval on the approach. Build only what was agreed in the plan.

**Write PRs that are easy to review.** Keep PRs small and focused on one thing. In the PR description, explain *why* the change exists — not what the diff shows. In code comments, describe *why*, never *what*.

**Use tests as your feedback loop.** Before marking any task done, run the relevant tests and confirm they pass. When adding new behavior, ask the human if a test should be written first. A passing test suite is the definition of done.

**Write less code, not more.** Default to the smallest implementation that solves the problem.

---

## Common Commands

All Python tooling uses [uv](https://docs.astral.sh/uv/).

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
- Deployment: databicks assetg bundles? CLI workspace?
- Testing: local only? there are also some databricks cloud options it seems
- Architecture. We should probably write out the architecture somewhere. (e.g medallion, roles based permissions, etc. )
- Do we put linting convensions here, or do we rely on traditional linters? (I think the latter, b/c the bot can infer those from the repo?)

