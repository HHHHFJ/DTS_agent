from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.dts_tools.fetch_tool import DtsFetchError, run_fetch_script


class FetchToolTest(unittest.TestCase):
    def test_fetch_script_uses_custom_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "fetch.py"
            output_dir = root / "custom-output"
            script.write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "import os",
                        "target = Path(os.environ['DTS_EXCEL_OUTPUT_DIR']) / 'dts.csv'",
                        "target.write_text('header\\n', encoding='utf-8')",
                        "print(target)",
                    ]
                ),
                encoding="utf-8",
            )

            result = run_fetch_script(script, output_dir, timeout=30)

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.excel_path, output_dir / "dts.csv")
            self.assertTrue(result.excel_path.exists())  # type: ignore[union-attr]

    def test_fetch_script_copies_to_custom_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "fetch.py"
            target = root / "final" / "custom.csv"
            script.write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "source = Path(__file__).with_name('raw.csv')",
                        "source.write_text('header\\n', encoding='utf-8')",
                        "print(source)",
                    ]
                ),
                encoding="utf-8",
            )

            result = run_fetch_script(script, root / "inbox", timeout=30, output_file=target)

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.excel_path, target)
            self.assertTrue(target.exists())

    def test_rejects_non_excel_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "fetch.py"
            script.write_text("print('ok')", encoding="utf-8")

            with self.assertRaises(DtsFetchError):
                run_fetch_script(script, root / "inbox", output_file=root / "bad.txt")


if __name__ == "__main__":
    unittest.main()
