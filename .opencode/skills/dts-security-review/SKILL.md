---
name: dts-security-review
description: Use the local DTS security knowledge base to identify same-class historical security issues in code and produce evidence-based findings.
license: MIT
compatibility: opencode
metadata:
  workflow: dts-guardian
---

## What This Skill Does

Use this skill when reviewing code with the local DTS Guardian knowledge base.

The workflow is:

1. Check knowledge base status with `dts_status`.
2. For changed code, call `dts_review_diff`; for a full scan, call `dts_review_repo`.
3. If a user asks about a topic, ticket, or code fragment, call `dts_kb_query`.
4. Only report risks grounded in matched DTS evidence.

## Knowledge Base Maintenance Mode

When maintaining the knowledge base, prefer OpenCode Agent judgement mode:

1. Import/sync DTS data with `skipBuildKb: true`.
2. Read pending snippets with `dts_judgement_tasks`.
3. Judge only the old snippet and its context; DTS summary is a candidate label, not proof.
4. Persist the decision with `dts_apply_judgement`.
5. Do not add a snippet to the knowledge base when the old code/context does not show a real security issue.
6. Ignore snippets where the old/new diff is only comments, whitespace, formatting, or variable rename without logic change.

## Finding Format

Each finding must include:

- Risk level: high, medium, or low.
- File and line.
- Matched DTS ticket id.
- Issue type.
- Why the current code is similar to the historical vulnerable snippet.
- Historical evidence from DTS summary or PR diff.
- Fix recommendation.
- Confidence.

## Guardrails

- Do not edit project files.
- Do not invent DTS tickets or issue history.
- If there is no credible knowledge base match, state that no historical same-class DTS evidence was found.
- Treat low confidence findings as items requiring manual confirmation, not confirmed defects.
