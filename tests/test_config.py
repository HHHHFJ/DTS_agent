from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.config import load_config


class ConfigTest(unittest.TestCase):
    def test_default_fetch_script_lives_under_dts_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(tmp)

        self.assertEqual(
            config.fetch_script,
            Path(tmp).resolve() / "dts_agent" / "dts_tools" / "dts_data_fetch.py",
        )


if __name__ == "__main__":
    unittest.main()
