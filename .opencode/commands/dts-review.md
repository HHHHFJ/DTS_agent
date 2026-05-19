---
description: Review current code against DTS historical same-class security issues
agent: dts-guardian
---

Load the `dts-security-review` skill. Review the current git diff with `dts_review_diff`.

If `$ARGUMENTS` contains `repo`, review the full repository with `dts_review_repo` instead. Present findings ordered by confidence and include matched DTS ticket ids, evidence, and recommendations.
