---
description: Sync DTS Excel data into the local security knowledge base
agent: dts-sync-maintainer
subtask: true
---

Run `dts_status`, then run `dts_sync_now` with `force: true`.

Use OpenCode Agent judgement mode by default:

1. If `$ARGUMENTS` contains an Excel path, run `dts_import_excel` with `skipBuildKb: true`; otherwise run `dts_sync_now` with `force: true` and `skipBuildKb: true`.
2. Call `dts_judgement_tasks`.
3. Judge each returned snippet with the current OpenCode model.
4. Call `dts_apply_judgement` for each snippet.

Summarize imported tickets, PR links, snippets, judgements, patterns, and failures.
