---
description: Sync DTS Excel data into the local security knowledge base. This command does not review project code.
agent: dts-sync-maintainer
subtask: true
---

This is a knowledge-base maintenance command only. Do not call `dts_review_diff`, `dts_review_repo`, or `dts_generate_report`. Do not scan, inspect, or review the current workspace repository. Do not output a DTS security review report.

Support optional `$ARGUMENTS` path parameters:

- `excel=<path>` or `file=<path>`: read an existing DTS Excel/CSV file.
- `output-dir=<path>`: run `dts_data_fetch.py` and store the generated Excel/CSV in this directory.
- `output-file=<path>`: run `dts_data_fetch.py` and copy the generated Excel/CSV to this exact `.xlsx` or `.csv` path.

Use OpenCode Agent judgement mode by default:

1. Run `dts_status`.
2. If `$ARGUMENTS` contains `excel=` or `file=`, call `dts_import_excel` with `excelPath`, `skipBuildKb: true`, and `interactiveTokenSetup: true`. Do not call `dts_sync_now` for this case.
3. If `$ARGUMENTS` contains `output-dir=` or `output-file=`, call `dts_sync_now` with `excelOutputDir` or `excelOutputFile`, plus `force: true`, `skipBuildKb: true`, and `interactiveTokenSetup: true`.
4. If no path is specified, call `dts_sync_now` with `force: true`, `skipBuildKb: true`, and `interactiveTokenSetup: true`.
5. The tool parses all PR/MR URLs before fetching. If any parsed host needs a token, it opens one local token setup dialog for all missing hosts before diff fetching continues.
6. Read the tool result. If it contains `errors` or failed `pr_link_results`, report those failures explicitly, including missing token messages. Do not present the run as fully successful when any PR/MR fetch failed.
7. Only call `dts_judgement_tasks` for ticket ids returned by this import/sync result. Do not judge old pending snippets from unrelated previous runs.
8. Judge only the `vulnerable_snippet` and `context` returned by `dts_judgement_tasks`. Do not read or audit files from the current workspace.
9. Call `dts_apply_judgement` for each returned snippet.

Summarize imported tickets, PR links, snippets, judgements, patterns, and failures. Use a short knowledge-base maintenance summary, not a security audit/report format.
