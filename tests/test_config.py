from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dts_agent.config import load_config


class ConfigTest(unittest.TestCase):
    def test_default_fetch_script_lives_under_dts_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(tmp)

        self.assertEqual(
            config.fetch_script,
            Path(tmp).resolve() / "dts_agent" / "dts_tools" / "dts_data_fetch.py",
        )

    def test_custom_inbox_dir_can_be_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "custom-inbox"
            with patch.dict("os.environ", {"DTS_AGENT_INBOX_DIR": str(inbox)}):
                config = load_config(tmp)

        self.assertEqual(config.inbox_dir, inbox.resolve())

    def test_repository_tokens_can_be_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                "os.environ",
                {
                    "CODEHUB_ACCESS_TOKEN": "codehub-token",
                    "DTS_REPO_ACCESS_TOKEN": "repo-token",
                },
            ):
                config = load_config(tmp)

        self.assertEqual(config.codehub_token, "codehub-token")
        self.assertEqual(config.repo_access_token, "repo-token")


if __name__ == "__main__":
    unittest.main()
