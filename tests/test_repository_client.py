from __future__ import annotations

import unittest
from unittest.mock import patch

from dts_agent.dts_tools.gitcode_client import GitCodeFetchError
from dts_agent.dts_tools.gitcode_client import GitCodeClient
from dts_agent.dts_tools.pr_parser import parse_ticket_pr_links


class RepositoryClientTest(unittest.TestCase):
    def test_codehub_merge_request_candidates_include_api_and_diff_fallback(self) -> None:
        links, errors = parse_ticket_pr_links(
            "DTS001",
            "['https://codehub-y.huawei.com/group/sub/service/-/merge_requests/123']",
        )
        self.assertEqual(errors, [])
        client = GitCodeClient("https://gitcode.com/api/v5")

        candidates = client._candidate_urls(links[0])

        self.assertIn(
            "https://codehub-y.huawei.com/api/v4/projects/group%2Fsub%2Fservice/merge_requests/123/changes",
            candidates,
        )
        self.assertIn(
            "https://codehub-y.huawei.com/group/sub/service/-/merge_requests/123.diff",
            candidates,
        )

    def test_generic_pull_candidates_use_original_host(self) -> None:
        links, errors = parse_ticket_pr_links(
            "DTS001",
            "['https://git.example.com/team/repo/pull/9']",
        )
        self.assertEqual(errors, [])
        client = GitCodeClient("https://gitcode.com/api/v5")

        candidates = client._candidate_urls(links[0])

        self.assertEqual(candidates[0], "https://git.example.com/team/repo/pull/9.diff")

    def test_codehub_requires_token_before_fetching(self) -> None:
        links, errors = parse_ticket_pr_links(
            "DTS001",
            "['https://codehub-y.huawei.com/group/repo/merge_requests/123']",
        )
        self.assertEqual(errors, [])
        client = GitCodeClient("https://gitcode.com/api/v5")

        with patch.dict(
            "os.environ",
            {
                "DTS_REPO_TOKEN_CODEHUB_Y_HUAWEI_COM": "",
                "CODEHUB_ACCESS_TOKEN": "",
                "DTS_REPO_ACCESS_TOKEN": "",
                "REPO_ACCESS_TOKEN": "",
            },
        ):
            with self.assertRaises(GitCodeFetchError) as ctx:
                client.fetch_pr_snippets(links[0])

        self.assertIn("CODEHUB_ACCESS_TOKEN", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
