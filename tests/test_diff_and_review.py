from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.dts_tools.gitcode_client import parse_unified_diff
from dts_agent.extraction import build_issue_pattern
from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.models import DtsTicket, PrLink
from dts_agent.review.reviewer import review_repo


class DiffAndReviewTest(unittest.TestCase):
    def test_parse_unified_diff_extracts_old_and_new_snippets(self) -> None:
        link = PrLink("DTS001", "https://gitcode.com/o/r/pull/1", "o", "r", "1")
        diff = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,3 +10,5 @@
 def delete_user(user, target):
-    do_delete(target)
+    if not user.is_admin:
+        raise PermissionError()
+    do_delete(target)
"""

        snippets = parse_unified_diff(link, diff)

        self.assertEqual(len(snippets), 1)
        self.assertIn("do_delete", snippets[0].vulnerable_snippet)
        self.assertIn("is_admin", snippets[0].fixed_snippet)

    def test_review_repo_matches_similar_vulnerable_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "kb.sqlite")
            ticket = DtsTicket(
                ticket_id="DTS001",
                summary="权限校验缺失导致普通用户可删除资源",
            )
            link = PrLink("DTS001", "https://gitcode.com/o/r/pull/1", "o", "r", "1")
            snippet = parse_unified_diff(
                link,
                """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -1,2 +1,4 @@
 def delete_user(user, target):
-    do_delete(target)
+    if not user.is_admin:
+        raise PermissionError()
+    do_delete(target)
""",
            )[0]
            store.upsert_ticket(ticket)
            snippet_id = store.upsert_snippet(snippet)
            pattern = build_issue_pattern(ticket, snippet_id, snippet)
            self.assertIsNotNone(pattern)
            store.upsert_pattern(pattern)  # type: ignore[arg-type]

            repo = root / "repo"
            repo.mkdir()
            (repo / "auth.py").write_text(
                "def delete_user(user, target):\n    do_delete(target)\n",
                encoding="utf-8",
            )

            _review_id, findings = review_repo(store, repo, min_confidence=0.2)

        self.assertGreaterEqual(len(findings), 1)
        self.assertEqual(findings[0].matched_ticket_id, "DTS001")


if __name__ == "__main__":
    unittest.main()
