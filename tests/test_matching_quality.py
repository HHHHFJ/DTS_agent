from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.extraction import build_issue_pattern, classify_issue
from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.models import CodeSnippet, CodeChunk, DtsTicket
from dts_agent.review.reviewer import review_chunks


class MatchingQualityTest(unittest.TestCase):
    def test_summary_priority_keeps_command_injection_type(self) -> None:
        snippet = CodeSnippet(
            ticket_id="DTS001",
            pr_url="https://gitcode.com/a/b/pull/1",
            file_path="src/path_reader.cpp",
            old_start_line=1,
            new_start_line=1,
            vulnerable_snippet='std::ifstream cmdline_file("/proc/cmdline");',
            fixed_snippet="read_cmdline_safely();",
        )

        issue_type, _advice, _confidence = classify_issue(
            "在check方法中，有命令注入的问题，同在tmp路径下恶意文件名可导致提权",
            snippet,
        )

        self.assertEqual(issue_type, "命令注入风险")

    def test_generic_cpp_overlap_without_security_anchor_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "kb.sqlite")
            ticket = DtsTicket(ticket_id="DTS001", summary="有命令注入的问题")
            snippet = CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="src/a.cpp",
                old_start_line=1,
                new_start_line=1,
                vulnerable_snippet='FILE* raw_pipe = popen(cmd.data(), "r");',
                fixed_snippet="safe_exec(cmd);",
            )
            store.upsert_ticket(ticket)
            snippet_id = store.upsert_snippet(snippet)
            pattern = build_issue_pattern(ticket, snippet_id, snippet)
            self.assertIsNotNone(pattern)
            store.upsert_pattern(pattern)  # type: ignore[arg-type]

            chunk = CodeChunk(
                file_path=root / "src" / "generic.cpp",
                start_line=1,
                end_line=6,
                text="std::vector<int> values;\nstd::map<std::string, int> index;\nreturn;",
            )
            _review_id, findings = review_chunks(store, root, "repo", [chunk], min_confidence=0.2)

        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
