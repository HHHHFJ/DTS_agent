from __future__ import annotations

import unittest

from dts_agent.extraction import build_issue_pattern
from dts_agent.llm_judge import SecurityJudgement
from dts_agent.models import CodeSnippet, DtsTicket


class FakeJudge:
    source = "fake-llm"

    def __init__(self, judgement: SecurityJudgement) -> None:
        self.judgement = judgement

    def assess(self, ticket, snippet, summary_issue_type):  # noqa: ANN001
        return self.judgement


class LlmJudgementTest(unittest.TestCase):
    def test_matching_summary_and_llm_type_uses_summary_type(self) -> None:
        pattern = build_issue_pattern(
            DtsTicket(ticket_id="DTS001", summary="存在命令注入问题"),
            "snippet-1",
            CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="a.cpp",
                old_start_line=1,
                new_start_line=1,
                vulnerable_snippet='popen(cmd.data(), "r");',
                fixed_snippet="safe_exec(cmd);",
            ),
            security_judge=FakeJudge(
                SecurityJudgement(True, "命令注入风险", 0.9, "old code has popen", "fake-llm")
            ),
        )

        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.issue_type, "命令注入风险")  # type: ignore[union-attr]
        self.assertIn("DTS摘要类型与代码判定一致", pattern.evidence)  # type: ignore[union-attr]

    def test_mismatched_summary_and_llm_type_uses_llm_type(self) -> None:
        pattern = build_issue_pattern(
            DtsTicket(ticket_id="DTS001", summary="存在命令注入问题"),
            "snippet-1",
            CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="a.cpp",
                old_start_line=1,
                new_start_line=1,
                vulnerable_snippet='std::ifstream file(user_path);',
                fixed_snippet="open_under_safe_root(user_path);",
            ),
            security_judge=FakeJudge(
                SecurityJudgement(True, "路径穿越风险", 0.88, "old code opens user path", "fake-llm")
            ),
        )

        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.issue_type, "路径穿越风险")  # type: ignore[union-attr]
        self.assertIn("采用代码/大模型判定类型", pattern.evidence)  # type: ignore[union-attr]

    def test_non_security_old_code_is_not_added_to_kb(self) -> None:
        pattern = build_issue_pattern(
            DtsTicket(ticket_id="DTS001", summary="存在命令注入问题"),
            "snippet-1",
            CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="a.cpp",
                old_start_line=1,
                new_start_line=1,
                vulnerable_snippet="ConnectAllNodes();",
                fixed_snippet="",
            ),
            security_judge=FakeJudge(
                SecurityJudgement(False, "命令注入风险", 0.1, "no security issue in old code", "fake-llm")
            ),
        )

        self.assertIsNone(pattern)


if __name__ == "__main__":
    unittest.main()
