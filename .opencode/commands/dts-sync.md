---
description: Sync DTS Excel data into the local security knowledge base. This command does not review project code.
agent: dts-sync-maintainer
subtask: true
---

Run `dts_status`, then run `dts_sync_now` with `force: true`.

This is a knowledge-base maintenance command only. Do not call `dts_review_diff`, `dts_review_repo`, or `dts_generate_report`. Do not output a DTS security review report.

Support optional `$ARGUMENTS` path parameters:

- `excel=<path>` or `file=<path>`: read an existing DTS Excel/CSV file.
- `output-dir=<path>`: run `dts_data_fetch.py` and store the generated Excel/CSV in this directory.
- `output-file=<path>`: run `dts_data_fetch.py` and copy the generated Excel/CSV to this exact `.xlsx` or `.csv` path.

Use OpenCode Agent judgement mode by default:

1. If `$ARGUMENTS` contains `excel=` or `file=`, call `dts_import_excel` with `excelPath` and `skipBuildKb: true`. Do not call `dts_sync_now` for this case.
2. If `$ARGUMENTS` contains `output-dir=` or `output-file=`, call `dts_sync_now` with `excelOutputDir` or `excelOutputFile`, plus `force: true` and `skipBuildKb: true`.
3. If no path is specified, call `dts_sync_now` with `force: true` and `skipBuildKb: true`.
4. Call `dts_judgement_tasks`.
5. Judge each returned snippet with the current OpenCode model.
6. Call `dts_apply_judgement` for each snippet.

Summarize imported tickets, PR links, snippets, judgements, patterns, and failures. Use a short maintenance summary, not a security audit/report format.
