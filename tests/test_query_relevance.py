from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.extraction import build_issue_pattern
from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.models import CodeSnippet, DtsTicket


class QueryRelevanceTest(unittest.TestCase):
    def test_chinese_substring_query_matches_and_unrelated_query_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "kb.sqlite")
            ticket = DtsTicket(ticket_id="DTS001", summary="存在命令注入风险")
            snippet = CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="a.cpp",
                old_start_line=1,
                new_start_line=1,
                vulnerable_snippet='popen(cmd.data(), "r");',
                fixed_snippet='safe_exec(cmd);',
            )
            store.upsert_ticket(ticket)
            snippet_id = store.upsert_snippet(snippet)
            pattern = build_issue_pattern(ticket, snippet_id, snippet)
            self.assertIsNotNone(pattern)
            store.upsert_pattern(pattern)  # type: ignore[arg-type]

            matched = store.search_patterns("命令注入", limit=5)
            unrelated = store.search_patterns("权限校验缺失", limit=5)

        self.assertEqual(len(matched), 1)
        self.assertGreater(matched[0]["relevance"], 0.0)
        self.assertEqual(unrelated, [])


if __name__ == "__main__":
    unittest.main()
