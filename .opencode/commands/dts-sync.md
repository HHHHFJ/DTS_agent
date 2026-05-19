---
description: Sync DTS Excel data into the local security knowledge base
agent: dts-sync-maintainer
subtask: true
---

Run `dts_status`, then run `dts_sync_now` with `force: true`.

If `$ARGUMENTS` contains an Excel path, use `dts_import_excel` for that path instead of running the fetch script. Summarize imported tickets, PR links, snippets, patterns, and failures.
