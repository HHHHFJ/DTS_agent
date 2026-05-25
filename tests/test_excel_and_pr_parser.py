from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dts_agent.dts_tools.excel_loader import REQUIRED_HEADERS, load_dts_excel
from dts_agent.dts_tools.pr_parser import parse_pr_url_list, parse_ticket_pr_links, provider_for_host
from tests.helpers import write_minimal_xlsx


class ExcelAndPrParserTest(unittest.TestCase):
    def test_loads_required_excel_headers_and_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dts.xlsx"
            write_minimal_xlsx(
                path,
                [
                    list(REQUIRED_HEADERS),
                    [
                        "1",
                        "DTS001",
                        "修复参数校验缺失",
                        "严重",
                        "2026-05-19",
                        "安全团队",
                        "['https://gitcode.com/openeuler/ubs-engine/pull/466']",
                    ],
                ],
            )

            tickets = load_dts_excel(path)

        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].ticket_id, "DTS001")
        self.assertEqual(tickets[0].pr_urls, ("https://gitcode.com/openeuler/ubs-engine/pull/466",))

    def test_parse_url_list_supports_multiple_and_invalid_literals(self) -> None:
        urls = parse_pr_url_list(
            "['https://gitcode.com/a/b/pull/1', 'https://gitcode.com/a/b/pull/2']"
        )
        self.assertEqual(len(urls), 2)

        fallback = parse_pr_url_list("see https://gitcode.com/a/b/pull/3 for details")
        self.assertEqual(fallback, ["https://gitcode.com/a/b/pull/3"])

    def test_normalizes_gitcode_links(self) -> None:
        links, errors = parse_ticket_pr_links(
            "DTS001",
            "['https://gitcode.com/openeuler/ubs-engine/pull/466']",
        )

        self.assertEqual(errors, [])
        self.assertEqual(links[0].owner, "openeuler")
        self.assertEqual(links[0].repo, "ubs-engine")
        self.assertEqual(links[0].pr_number, "466")
        self.assertEqual(links[0].host, "gitcode.com")
        self.assertEqual(links[0].provider, "gitcode")
        self.assertEqual(links[0].repo_path, "openeuler/ubs-engine")

    def test_parses_codehub_merge_request_links(self) -> None:
        links, errors = parse_ticket_pr_links(
            "DTS001",
            "['https://codehub-y.huawei.com/group/subgroup/service/-/merge_requests/123']",
        )

        self.assertEqual(errors, [])
        self.assertEqual(links[0].host, "codehub-y.huawei.com")
        self.assertEqual(links[0].provider, "codehub")
        self.assertEqual(links[0].owner, "group/subgroup")
        self.assertEqual(links[0].repo, "service")
        self.assertEqual(links[0].repo_path, "group/subgroup/service")
        self.assertEqual(links[0].change_type, "merge_requests")
        self.assertEqual(links[0].pr_number, "123")

    def test_parses_configured_repository_hosts(self) -> None:
        with patch.dict("os.environ", {"DTS_REPO_HOSTS": "git.example.com=codehub"}):
            links, errors = parse_ticket_pr_links(
                "DTS001",
                "['https://git.example.com/team/repo/pulls/9']",
            )

        self.assertEqual(errors, [])
        self.assertEqual(links[0].provider, "codehub")
        self.assertEqual(links[0].change_type, "pull")
        self.assertEqual(links[0].pr_number, "9")
        self.assertEqual(provider_for_host("szy-y.codehub.huawei.com"), "codehub")


if __name__ == "__main__":
    unittest.main()
