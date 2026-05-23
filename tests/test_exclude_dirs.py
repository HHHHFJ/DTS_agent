from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.review.code_feature_extractor import extract_repo_chunks


class ExcludeDirsTest(unittest.TestCase):
    def test_extract_repo_chunks_excludes_requested_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "test").mkdir()
            (root / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
            (root / "test" / "test_main.cpp").write_text("int test() { return 0; }\n", encoding="utf-8")

            chunks = extract_repo_chunks(root, exclude_dirs=["test"])

        files = {chunk.file_path.name for chunk in chunks}
        self.assertIn("main.cpp", files)
        self.assertNotIn("test_main.cpp", files)


if __name__ == "__main__":
    unittest.main()
