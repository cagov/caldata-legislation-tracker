# California Legislation Bulk Data — Summary

**What it is:** The State of California publishes its entire legislative database for free at downloads.leginfo.legislature.ca.gov. No account, no API key — you just download zip files over HTTPS.

**What's in it:** Every bill since 1989 (text of every version, amendments, vote records, author lists, committee analyses, action histories, veto messages), plus the full text of all 29 California Codes (the current statutes), legislator rosters, and committee hearing schedules.

**How it's organized:** One big zip per two-year legislative session (`pubinfo_2025.zip` covers 2025–26, about 930 MB). The state also posts small daily "what changed" zips every night around 9:20 PM Pacific, so a database can be kept current without re-downloading everything.

**Format:** The zips contain tab-delimited data files matching a 17-table MySQL schema the state provides, plus separate files holding full bill and statute text (the bill text is XML). The state includes its own schema file and sample load scripts.

**What this means for the project:** This is a viable, authoritative, zero-cost source. The work is straightforward ETL: load the session zip once, convert bill text XML into markdown documents Claude can read, and run a nightly job to apply the daily updates. The main effort is parsing the bill-text XML (amendment markup is embedded in tags) — everything else is standard bulk loading.

**Status against acceptance criteria:**
- Technical .md reference for Claude: done (`ca-leginfo-bulk-download.md`)
- Human summary: this document
- Actual bulk download/conversion: not run in this environment (outbound network from the sandbox is disabled); the pipeline above is ready to execute wherever the job runs.
