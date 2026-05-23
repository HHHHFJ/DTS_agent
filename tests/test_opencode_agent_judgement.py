from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.cli import _apply_single_judgement, command_judge_tasks
from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.models import CodeSnippet, DtsTicket


class OpenCodeAgentJudgementTest(unittest.TestCase):
    def test_positive_agent_judgement_creates_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "kb.sqlite")
            ticket = DtsTicket(ticket_id="DTS001", summary="存在命令注入问题")
            snippet = CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="a.cpp",
                old_start_line=10,
                new_start_line=10,
                vulnerable_snippet='popen(cmd.data(), "r");',
                fixed_snippet="safe_exec(cmd);",
                context="std::string cmd = userInput;",
            )
            store.upsert_ticket(ticket)
            snippet_id = store.upsert_snippet(snippet)

            result = _apply_single_judgement(
                store,
                {
                    "snippet_id": snippet_id,
                    "has_security_issue": True,
                    "issue_type": "命令注入风险",
                    "confidence": 0.91,
                    "rationale": "旧代码使用外部输入构造命令并调用 popen。",
                    "source": "opencode-agent",
                },
            )

            status = store.status()
            self.assertEqual(result["status"], "pattern_upserted")
            self.assertEqual(status["counts"]["snippet_judgements"], 1)
            self.assertEqual(status["counts"]["issue_patterns"], 1)

    def test_negative_agent_judgement_is_not_listed_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "kb.sqlite")
            ticket = DtsTicket(ticket_id="DTS001", summary="存在命令注入问题")
            snippet = CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="a.cpp",
                old_start_line=10,
                new_start_line=10,
                vulnerable_snippet="return status;",
                fixed_snippet="return status;",
                context="",
            )
            store.upsert_ticket(ticket)
            snippet_id = store.upsert_snippet(snippet)

            before = command_judge_tasks(store, limit=5)
            result = _apply_single_judgement(
                store,
                {
                    "snippet_id": snippet_id,
                    "has_security_issue": False,
                    "issue_type": "命令注入风险",
                    "confidence": 0.1,
                    "rationale": "旧代码上下文没有可确认的安全问题。",
                    "source": "opencode-agent",
                },
            )
            after = command_judge_tasks(store, limit=5)

            self.assertEqual(before["tasks"], [])
            self.assertEqual(result["status"], "skipped_no_logical_change")
            self.assertEqual(after["tasks"], [])
            self.assertEqual(store.status()["counts"]["issue_patterns"], 0)


if __name__ == "__main__":
    unittest.main()
