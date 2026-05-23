from __future__ import annotations

import unittest

from dts_agent.code_change import has_logical_code_change
from dts_agent.dts_tools.gitcode_client import parse_unified_diff
from dts_agent.extraction import build_issue_pattern
from dts_agent.llm_judge import SecurityJudgement
from dts_agent.models import CodeSnippet, DtsTicket, PrLink


class AlwaysPositiveJudge:
    source = "test"

    def assess(self, ticket, snippet, summary_issue_type):  # noqa: ANN001
        return SecurityJudgement(True, "命令注入风险", 0.9, "forced positive", "test")


class LogicalCodeChangeTest(unittest.TestCase):
    def test_comments_whitespace_and_variable_rename_are_not_logical_changes(self) -> None:
        self.assertFalse(
            has_logical_code_change(
                "int count = 1;\nreturn count;\n",
                "// renamed for style\nint total = 1;\n\nreturn total;\n",
            )
        )
        self.assertFalse(
            has_logical_code_change(
                "std::string cmdline_output = GetCmdLineResult(\"getconf PAGE_SIZE\");",
                "std::string cmdlineOutput = GetCmdLineResult(\"getconf PAGE_SIZE\");",
            )
        )

    def test_function_or_operator_change_is_logical_change(self) -> None:
        self.assertTrue(
            has_logical_code_change(
                "while (fgets(buffer, sizeof(buffer), pipe.get()) != nullptr) { output += buffer; }",
                "while ((bytesRead = fread(buffer, 1, sizeof(buffer), pipe.get())) > 0) { output += buffer; }",
            )
        )

    def test_diff_parser_drops_non_logical_hunks(self) -> None:
        link = PrLink("DTS001", "https://gitcode.com/o/r/pull/1", "o", "r", "1")
        diff = """diff --git a/src/a.cpp b/src/a.cpp
--- a/src/a.cpp
+++ b/src/a.cpp
@@ -1,3 +1,4 @@
-int count = 1;
-return count;
+// style-only rename
+int total = 1;
+return total;
"""

        self.assertEqual(parse_unified_diff(link, diff), [])

    def test_non_logical_change_never_builds_issue_pattern(self) -> None:
        pattern = build_issue_pattern(
            DtsTicket(ticket_id="DTS001", summary="存在命令注入问题"),
            "snippet-1",
            CodeSnippet(
                ticket_id="DTS001",
                pr_url="https://gitcode.com/a/b/pull/1",
                file_path="a.cpp",
                old_start_line=1,
                new_start_line=1,
                vulnerable_snippet='std::string cmdline_output = GetCmdLineResult("getconf PAGE_SIZE");',
                fixed_snippet='std::string cmdlineOutput = GetCmdLineResult("getconf PAGE_SIZE");',
            ),
            security_judge=AlwaysPositiveJudge(),
        )

        self.assertIsNone(pattern)


if __name__ == "__main__":
    unittest.main()
