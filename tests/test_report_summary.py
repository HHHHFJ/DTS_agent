from __future__ import annotations

import unittest

from dts_agent.reporting.report import _markdown_report


class ReportSummaryTest(unittest.TestCase):
    def test_report_contains_summary_tables(self) -> None:
        report = _markdown_report(
            {"id": "review-1", "target_path": "D:/repo", "mode": "repo"},
            [
                {
                    "confidence": 0.92,
                    "issue_type": "命令注入风险",
                    "matched_ticket_id": "DTS001",
                    "file_path": "a.cpp",
                    "line": 10,
                    "evidence": "history",
                    "snippet": "popen(cmd)",
                    "recommendation": "avoid shell",
                },
                {
                    "confidence": 0.6,
                    "issue_type": "路径穿越风险",
                    "matched_ticket_id": "DTS002",
                    "file_path": "b.cpp",
                    "line": 20,
                    "evidence": "history",
                    "snippet": "../x",
                    "recommendation": "normalize path",
                },
            ],
        )

        self.assertIn("## 汇总统计", report)
        self.assertIn("| 高 | 1 |", report)
        self.assertIn("| 中 | 1 |", report)
        self.assertIn("| `命令注入风险` | 1 |", report)
        self.assertIn("| `DTS001` | 1 |", report)
        self.assertIn("| `a.cpp` | 1 |", report)
        self.assertIn("#### 问题位置", report)
        self.assertIn("#### 相似历史问题", report)
        self.assertNotIn("#### 证据片段", report)

    def test_report_marks_core_snippet_line(self) -> None:
        report = _markdown_report(
            {"id": "review-1", "target_path": "D:/repo", "mode": "repo"},
            [
                {
                    "confidence": 0.92,
                    "issue_type": "命令注入风险",
                    "matched_ticket_id": "DTS001",
                    "file_path": "a.cpp",
                    "line": 10,
                    "evidence": "DTS摘要: 历史命令注入\nPR: https://gitcode.com/a/b/pull/1\n文件: a.cpp\n修复前:\nold\n修复后:\nnew",
                    "snippet": "int x = 1;\nstd::string cmd = input;\npopen(cmd.data(), \"r\");\nreturn x;",
                    "recommendation": "avoid shell",
                },
            ],
        )

        self.assertIn(">> popen(cmd.data()", report)
        self.assertIn("- 历史摘要: 历史命令注入", report)
        self.assertNotIn("修复前:\nold", report)


if __name__ == "__main__":
    unittest.main()
