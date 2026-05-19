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
