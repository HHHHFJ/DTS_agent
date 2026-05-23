from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.models import DtsTicket


class InspectDbTest(unittest.TestCase):
    def test_inspect_db_returns_counts_samples_and_query_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "kb.sqlite")
            store.upsert_ticket(DtsTicket(ticket_id="DTS001", summary="命令注入风险"))

            data = store.inspect(limit=5)

        self.assertEqual(data["counts"]["tickets"], 1)
        self.assertEqual(data["samples"]["tickets"][0]["ticket_id"], "DTS001")
        self.assertTrue(data["query_examples"])


if __name__ == "__main__":
    unittest.main()
