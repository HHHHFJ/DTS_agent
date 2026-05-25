from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dts_agent.cli import command_import_excel
from dts_agent.config import load_config
from dts_agent.models import CodeSnippet
from dts_agent.dts_tools.pr_parser import parse_ticket_pr_links
from dts_agent.dts_tools.token_setup import collect_missing_token_requirements, host_token_env_name
from dts_agent.kb.sqlite_store import KnowledgeStore
from tests.helpers import write_minimal_xlsx


class TokenSetupTest(unittest.TestCase):
    def test_collects_all_missing_codehub_hosts_after_url_parse(self) -> None:
        links_a, errors_a = parse_ticket_pr_links(
            "DTS001",
            "['https://codehub-y.huawei.com/group/repo/merge_requests/1']",
        )
        links_b, errors_b = parse_ticket_pr_links(
            "DTS002",
            "['https://szy-y.codehub.huawei.com/group/repo/merge_requests/2']",
        )

        with patch.dict(
            "os.environ",
            {
                "DTS_REPO_TOKEN_CODEHUB_Y_HUAWEI_COM": "",
                "DTS_REPO_TOKEN_SZY_Y_CODEHUB_HUAWEI_COM": "",
                "CODEHUB_ACCESS_TOKEN": "",
                "DTS_REPO_ACCESS_TOKEN": "",
                "REPO_ACCESS_TOKEN": "",
            },
        ):
            requirements = collect_missing_token_requirements([*links_a, *links_b])

        self.assertEqual(errors_a, [])
        self.assertEqual(errors_b, [])
        self.assertEqual({item.host for item in requirements}, {"codehub-y.huawei.com", "szy-y.codehub.huawei.com"})
        self.assertEqual(host_token_env_name("codehub-y.huawei.com"), "DTS_REPO_TOKEN_CODEHUB_Y_HUAWEI_COM")

    def test_import_reports_missing_token_requirements_before_fetch_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            excel = root / "dts.xlsx"
            write_minimal_xlsx(
                excel,
                [
                    ["序号", "问题单号", "简要描述", "严重程度", "创建时间", "提出方", "修改文件清单"],
                    [
                        "1",
                        "DTS001",
                        "CodeHub 权限测试",
                        "一般",
                        "2026-05-25",
                        "安全团队",
                        "['https://codehub-y.huawei.com/group/repo/merge_requests/1']",
                    ],
                ],
            )
            with patch.dict(
                "os.environ",
                {
                    "DTS_REPO_TOKEN_CODEHUB_Y_HUAWEI_COM": "",
                    "CODEHUB_ACCESS_TOKEN": "",
                    "DTS_REPO_ACCESS_TOKEN": "",
                    "REPO_ACCESS_TOKEN": "",
                },
            ):
                config = load_config(root)
                store = KnowledgeStore(config.database_path)
                result = command_import_excel(
                    str(excel),
                    fetch_pr=True,
                    config=config,
                    store=store,
                    build_kb=False,
                    interactive_token_setup=False,
                )

        self.assertEqual(result["ticket_count"], 1)
        self.assertEqual(result["missing_token_requirements"][0]["host"], "codehub-y.huawei.com")
        self.assertEqual(result["pr_link_results"][0]["status"], "failed")
        self.assertIn("CODEHUB_ACCESS_TOKEN", result["errors"][0]["error"])

    def test_interactive_setup_collects_all_hosts_before_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            excel = root / "dts.xlsx"
            write_minimal_xlsx(
                excel,
                [
                    ["序号", "问题单号", "简要描述", "严重程度", "创建时间", "提出方", "修改文件清单"],
                    [
                        "1",
                        "DTS001",
                        "CodeHub A",
                        "一般",
                        "2026-05-25",
                        "安全团队",
                        "['https://codehub-y.huawei.com/group/repo/merge_requests/1']",
                    ],
                    [
                        "2",
                        "DTS002",
                        "CodeHub B",
                        "一般",
                        "2026-05-25",
                        "安全团队",
                        "['https://szy-y.codehub.huawei.com/group/repo/merge_requests/2']",
                    ],
                ],
            )

            def fake_prompt(requirements: list[object]) -> dict[str, str]:
                for item in requirements:
                    env_var = getattr(item, "env_var")
                    patch_values[env_var] = "token"
                return dict(patch_values)

            patch_values: dict[str, str] = {}
            config = load_config(root)
            store = KnowledgeStore(config.database_path)
            snippet = CodeSnippet("DTS001", "url", "a.cpp", 1, 1, "old();", "new();")

            with patch.dict(
                "os.environ",
                {
                    "DTS_REPO_TOKEN_CODEHUB_Y_HUAWEI_COM": "",
                    "DTS_REPO_TOKEN_SZY_Y_CODEHUB_HUAWEI_COM": "",
                    "CODEHUB_ACCESS_TOKEN": "",
                    "DTS_REPO_ACCESS_TOKEN": "",
                    "REPO_ACCESS_TOKEN": "",
                },
            ), patch("dts_agent.cli.prompt_for_missing_tokens", side_effect=fake_prompt) as prompt, patch(
                "dts_agent.dts_tools.gitcode_client.GitCodeClient.fetch_pr_snippets",
                return_value=[snippet],
            ):
                result = command_import_excel(
                    str(excel),
                    fetch_pr=True,
                    config=config,
                    store=store,
                    build_kb=False,
                    interactive_token_setup=True,
                )

        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(result["token_setup"]["requested"], True)
        self.assertEqual(len(result["token_setup"]["configured_env_vars"]), 2)
        self.assertEqual([item["status"] for item in result["pr_link_results"]], ["ok", "ok"])


if __name__ == "__main__":
    unittest.main()
