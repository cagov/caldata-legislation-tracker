# California Legislation Bulk Data — Summary

**What it is:** The State of California publishes its entire legislative database for free at downloads.leginfo.legislature.ca.gov. No account, no API key — you just download zip files over HTTPS.

**What's in it:** Every bill from the 1989–90 session onward (text of every version, amendments, vote records, author lists, committee analyses, action histories, veto messages), plus the full text of all 29 California Codes (the current statutes), legislator rosters, and committee hearing schedules.

**How it's organized:** One big zip per two-year legislative session (`pubinfo_2025.zip` covers 2025–26; 930 MB as of June 7, 2026). The state also posts small daily "what changed" zips every night around 9:20 PM Pacific, so a database can be kept current without re-downloading everything.

**Format:** The zips contain tab-delimited data files matching an 18-table MySQL schema the state provides, plus separate files holding full bill and statute text (the bill text is XML). The state includes its own schema file and sample load scripts.

**What this means for the project:** This is a viable, authoritative, zero-cost source. The work is straightforward ETL: load the session zip once, convert bill text XML into markdown documents an LLM can read, and run a nightly job to apply the daily updates. The main effort is parsing the bill-text XML (amendment markup is embedded in tags) — everything else is standard bulk loading.

**Status against acceptance criteria:**
- Technical .md reference for LLM consumption: done (`ca-leginfo-bulk-download.md`)
- Human summary: this document
- Actual bulk download/conversion: not yet run (requires a machine with outbound network access); the pipeline above is ready to execute wherever the job runs.
