from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable

from dts_agent.models import CodeSnippet, DtsTicket, IssuePattern, PrLink, ReviewFinding
from dts_agent.utils import (
    cosine,
    fingerprint_code,
    json_dumps,
    json_loads_dict,
    sparse_embedding,
    stable_hash,
    utc_now_text,
)


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS dts_tickets (
  ticket_id TEXT PRIMARY KEY,
  serial_no TEXT,
  summary TEXT,
  severity TEXT,
  created_at TEXT,
  reporter TEXT,
  raw_json TEXT,
  imported_at TEXT
);

CREATE TABLE IF NOT EXISTS pr_links (
  id TEXT PRIMARY KEY,
  ticket_id TEXT,
  pr_url TEXT,
  owner TEXT,
  repo TEXT,
  pr_number TEXT,
  status TEXT,
  error TEXT,
  created_at TEXT,
  UNIQUE(ticket_id, pr_url)
);

CREATE TABLE IF NOT EXISTS code_snippets (
  id TEXT PRIMARY KEY,
  ticket_id TEXT,
  pr_url TEXT,
  file_path TEXT,
  old_start_line INTEGER,
  new_start_line INTEGER,
  vulnerable_snippet TEXT,
  fixed_snippet TEXT,
  context TEXT,
  snippet_hash TEXT UNIQUE,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS issue_patterns (
  id TEXT PRIMARY KEY,
  ticket_id TEXT,
  snippet_id TEXT,
  pr_url TEXT,
  issue_type TEXT,
  code_feature TEXT,
  vulnerable_snippet TEXT,
  fixed_snippet TEXT,
  fix_advice TEXT,
  evidence TEXT,
  confidence REAL,
  embedding TEXT,
  fingerprint TEXT UNIQUE,
  created_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS issue_patterns_fts USING fts5(
  pattern_id UNINDEXED,
  ticket_id,
  issue_type,
  code_feature,
  vulnerable_snippet,
  fixed_snippet,
  fix_advice,
  evidence
);

CREATE TABLE IF NOT EXISTS sync_runs (
  id TEXT PRIMARY KEY,
  started_at TEXT,
  finished_at TEXT,
  status TEXT,
  excel_path TEXT,
  excel_hash TEXT,
  imported_count INTEGER,
  error TEXT,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS watermarks (
  name TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS review_runs (
  id TEXT PRIMARY KEY,
  target_path TEXT,
  mode TEXT,
  created_at TEXT,
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS review_findings (
  id TEXT PRIMARY KEY,
  review_id TEXT,
  file_path TEXT,
  line INTEGER,
  issue_type TEXT,
  matched_ticket_id TEXT,
  matched_pattern_id TEXT,
  evidence TEXT,
  recommendation TEXT,
  confidence REAL,
  snippet TEXT
);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class KnowledgeStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def upsert_ticket(self, ticket: DtsTicket) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dts_tickets(ticket_id, serial_no, summary, severity, created_at, reporter, raw_json, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket_id) DO UPDATE SET
                  serial_no=excluded.serial_no,
                  summary=excluded.summary,
                  severity=excluded.severity,
                  created_at=excluded.created_at,
                  reporter=excluded.reporter,
                  raw_json=excluded.raw_json,
                  imported_at=excluded.imported_at
                """,
                (
                    ticket.ticket_id,
                    ticket.serial_no,
                    ticket.summary,
                    ticket.severity,
                    ticket.created_at,
                    ticket.reporter,
                    json_dumps(ticket.raw),
                    utc_now_text(),
                ),
            )

    def upsert_pr_link(self, link: PrLink, status: str = "pending", error: str = "") -> str:
        link_id = stable_hash(link.stable_id, length=32)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pr_links(id, ticket_id, pr_url, owner, repo, pr_number, status, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticket_id, pr_url) DO UPDATE SET
                  owner=excluded.owner,
                  repo=excluded.repo,
                  pr_number=excluded.pr_number,
                  status=excluded.status,
                  error=excluded.error
                """,
                (
                    link_id,
                    link.ticket_id,
                    link.pr_url,
                    link.owner,
                    link.repo,
                    link.pr_number,
                    status,
                    error,
                    utc_now_text(),
                ),
            )
        return link_id

    def mark_pr_link(self, link: PrLink, status: str, error: str = "") -> None:
        self.upsert_pr_link(link, status=status, error=error)

    def upsert_snippet(self, snippet: CodeSnippet) -> str:
        snippet_hash = stable_hash(
            "|".join(
                [
                    snippet.ticket_id,
                    snippet.pr_url,
                    snippet.file_path,
                    str(snippet.old_start_line),
                    str(snippet.new_start_line),
                    snippet.vulnerable_snippet,
                    snippet.fixed_snippet,
                ]
            ),
            length=32,
        )
        snippet_id = stable_hash(f"snippet:{snippet_hash}", length=32)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO code_snippets(
                  id, ticket_id, pr_url, file_path, old_start_line, new_start_line,
                  vulnerable_snippet, fixed_snippet, context, snippet_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snippet_hash) DO UPDATE SET
                  vulnerable_snippet=excluded.vulnerable_snippet,
                  fixed_snippet=excluded.fixed_snippet,
                  context=excluded.context
                """,
                (
                    snippet_id,
                    snippet.ticket_id,
                    snippet.pr_url,
                    snippet.file_path,
                    snippet.old_start_line,
                    snippet.new_start_line,
                    snippet.vulnerable_snippet,
                    snippet.fixed_snippet,
                    snippet.context,
                    snippet_hash,
                    utc_now_text(),
                ),
            )
        return snippet_id

    def upsert_pattern(self, pattern: IssuePattern) -> str:
        pattern_id = stable_hash(f"pattern:{pattern.fingerprint}", length=32)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO issue_patterns(
                  id, ticket_id, snippet_id, pr_url, issue_type, code_feature,
                  vulnerable_snippet, fixed_snippet, fix_advice, evidence,
                  confidence, embedding, fingerprint, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                  issue_type=excluded.issue_type,
                  code_feature=excluded.code_feature,
                  vulnerable_snippet=excluded.vulnerable_snippet,
                  fixed_snippet=excluded.fixed_snippet,
                  fix_advice=excluded.fix_advice,
                  evidence=excluded.evidence,
                  confidence=excluded.confidence,
                  embedding=excluded.embedding
                """,
                (
                    pattern_id,
                    pattern.ticket_id,
                    pattern.snippet_id,
                    pattern.pr_url,
                    pattern.issue_type,
                    pattern.code_feature,
                    pattern.vulnerable_snippet,
                    pattern.fixed_snippet,
                    pattern.fix_advice,
                    pattern.evidence,
                    pattern.confidence,
                    json_dumps(pattern.embedding),
                    pattern.fingerprint,
                    utc_now_text(),
                ),
            )
            conn.execute("DELETE FROM issue_patterns_fts WHERE pattern_id = ?", (pattern_id,))
            conn.execute(
                """
                INSERT INTO issue_patterns_fts(
                  pattern_id, ticket_id, issue_type, code_feature, vulnerable_snippet,
                  fixed_snippet, fix_advice, evidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pattern_id,
                    pattern.ticket_id,
                    pattern.issue_type,
                    pattern.code_feature,
                    pattern.vulnerable_snippet,
                    pattern.fixed_snippet,
                    pattern.fix_advice,
                    pattern.evidence,
                ),
            )
        return pattern_id

    def get_ticket(self, ticket_id: str) -> DtsTicket | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM dts_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if not row:
            return None
        return DtsTicket(
            ticket_id=row["ticket_id"],
            serial_no=row["serial_no"] or "",
            summary=row["summary"] or "",
            severity=row["severity"] or "",
            created_at=row["created_at"] or "",
            reporter=row["reporter"] or "",
            raw=json_loads_dict(row["raw_json"]),
        )

    def list_tickets(self, ticket_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM dts_tickets"
        args: tuple[Any, ...] = ()
        if ticket_id:
            query += " WHERE ticket_id = ?"
            args = (ticket_id,)
        query += " ORDER BY imported_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    def list_pr_links(self, ticket_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM pr_links"
        args: tuple[Any, ...] = ()
        if ticket_id:
            query += " WHERE ticket_id = ?"
            args = (ticket_id,)
        query += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    def list_snippets_without_patterns(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*, t.summary, t.severity, t.created_at, t.reporter, t.serial_no, t.raw_json
                FROM code_snippets s
                LEFT JOIN issue_patterns p ON p.snippet_id = s.id
                LEFT JOIN dts_tickets t ON t.ticket_id = s.ticket_id
                WHERE p.id IS NULL
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def all_patterns(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM issue_patterns ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def search_patterns(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query = query or ""
        candidates = self._fts_candidates(query, max(limit * 8, 25)) if query.strip() else self.all_patterns()
        if not candidates:
            candidates = self.all_patterns()

        query_embedding = sparse_embedding(query)
        ranked: list[dict[str, Any]] = []
        for row in candidates:
            embedding = json_loads_dict(row.get("embedding"))
            vector_score = cosine(query_embedding, {k: float(v) for k, v in embedding.items()})
            text = "\n".join(
                str(row.get(key) or "")
                for key in (
                    "ticket_id",
                    "issue_type",
                    "code_feature",
                    "vulnerable_snippet",
                    "fixed_snippet",
                    "fix_advice",
                    "evidence",
                )
            )
            text_overlap = cosine(sparse_embedding(query), sparse_embedding(text))
            relevance = max(vector_score, text_overlap)
            item = dict(row)
            item["relevance"] = relevance
            ranked.append(item)

        ranked.sort(key=lambda item: (item["relevance"], item.get("confidence") or 0.0), reverse=True)
        return ranked[:limit]

    def _fts_candidates(self, query: str, limit: int) -> list[dict[str, Any]]:
        match_query = _fts_query(query)
        if not match_query:
            return []
        try:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT p.*
                    FROM issue_patterns_fts f
                    JOIN issue_patterns p ON p.id = f.pattern_id
                    WHERE issue_patterns_fts MATCH ?
                    ORDER BY bm25(issue_patterns_fts)
                    LIMIT ?
                    """,
                    (match_query, limit),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            return []

    def create_sync_run(
        self,
        *,
        started_at: str,
        finished_at: str,
        status: str,
        excel_path: str = "",
        excel_hash: str = "",
        imported_count: int = 0,
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_runs(
                  id, started_at, finished_at, status, excel_path, excel_hash,
                  imported_count, error, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started_at,
                    finished_at,
                    status,
                    excel_path,
                    excel_hash,
                    imported_count,
                    error,
                    json_dumps(metadata or {}),
                ),
            )
        return run_id

    def save_review_run(
        self,
        *,
        review_id: str,
        target_path: str,
        mode: str,
        findings: Iterable[ReviewFinding],
    ) -> None:
        findings_list = list(findings)
        summary = {
            "finding_count": len(findings_list),
            "high_count": sum(1 for finding in findings_list if finding.confidence >= 0.75),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO review_runs(id, target_path, mode, created_at, summary_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET summary_json=excluded.summary_json
                """,
                (review_id, target_path, mode, utc_now_text(), json_dumps(summary)),
            )
            conn.execute("DELETE FROM review_findings WHERE review_id = ?", (review_id,))
            conn.executemany(
                """
                INSERT INTO review_findings(
                  id, review_id, file_path, line, issue_type, matched_ticket_id,
                  matched_pattern_id, evidence, recommendation, confidence, snippet
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        finding.review_id,
                        finding.file_path,
                        finding.line,
                        finding.issue_type,
                        finding.matched_ticket_id,
                        finding.matched_pattern_id,
                        finding.evidence,
                        finding.recommendation,
                        finding.confidence,
                        finding.snippet,
                    )
                    for finding in findings_list
                ],
            )

    def load_review(self, review_id: str = "latest") -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        with self.connect() as conn:
            if review_id == "latest":
                run = conn.execute("SELECT * FROM review_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            else:
                run = conn.execute("SELECT * FROM review_runs WHERE id = ?", (review_id,)).fetchone()
            if not run:
                return None, []
            rows = conn.execute(
                "SELECT * FROM review_findings WHERE review_id = ? ORDER BY confidence DESC",
                (run["id"],),
            ).fetchall()
        return dict(run), [dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        with self.connect() as conn:
            counts = {
                "tickets": conn.execute("SELECT COUNT(*) FROM dts_tickets").fetchone()[0],
                "pr_links": conn.execute("SELECT COUNT(*) FROM pr_links").fetchone()[0],
                "code_snippets": conn.execute("SELECT COUNT(*) FROM code_snippets").fetchone()[0],
                "issue_patterns": conn.execute("SELECT COUNT(*) FROM issue_patterns").fetchone()[0],
                "review_runs": conn.execute("SELECT COUNT(*) FROM review_runs").fetchone()[0],
            }
            last_sync = conn.execute(
                "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return {
            "database": str(self.database_path),
            "counts": counts,
            "last_sync": dict(last_sync) if last_sync else None,
        }


def _fts_query(query: str) -> str:
    words = [word for word in query.replace('"', " ").split() if len(word) > 1]
    words = [word.strip("()[]{}:;,+-*'") for word in words]
    words = [word for word in words if word]
    return " OR ".join(f'"{word}"' for word in words[:12])
