# California Legislation Bulk Data — Summary

**What it is:** The State of California publishes its entire legislative database for free at downloads.leginfo.legislature.ca.gov. No account, no API key — you just download zip files over HTTPS.

**What's in it:** Every bill from the 1989–90 session onward (text of every version, amendments, vote records, author lists, committee analyses, action histories, veto messages), plus the full text of all 29 California Codes (the current statutes), legislator rosters, and committee hearing schedules.

**How it's organized:** One big zip per two-year legislative session (`pubinfo_2025.zip` covers 2025–26; 930 MB as of June 7, 2026). The state also posts small daily "what changed" zips and larger daily current-session snapshots every night around 9:20 PM Pacific. The daily snapshots are not identical to the session zip: they refresh current-session non-code tables, but exclude the code/statute tables that are only in the weekly session zip.

**Format:** The zips contain tab-delimited data files matching an 18-table MySQL schema the state provides, plus separate files holding full bill and statute text (the bill text is XML). The state includes its own schema file and sample load scripts.

**What this means for the project:** This is a viable, authoritative, zero-cost source. The first implementation should add `src/ingest/land_raw.py` as a Databricks Job task that runs before the Lakeflow pipeline: load the current session zip once, land the daily current-session snapshot nightly for non-code tables, and refresh the session zip weekly for code/statute tables. Ingestion should preserve the original `.dat` and `.lob` files, including bill-text XML; Markdown conversion, if useful, belongs in a later transform/publish step.

**Status against acceptance criteria:**
- Technical .md reference for LLM consumption: done (`ca-leginfo-bulk-download.md`)
- Human summary: this document
- Actual bulk download/landing: not yet run (requires Databricks job execution with outbound network access); the pipeline above is ready to implement in the bundle job.
