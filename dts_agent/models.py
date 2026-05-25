from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DtsTicket:
    ticket_id: str
    summary: str
    severity: str = ""
    created_at: str = ""
    reporter: str = ""
    serial_no: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    pr_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrLink:
    ticket_id: str
    pr_url: str
    owner: str
    repo: str
    pr_number: str
    host: str = ""
    provider: str = "generic"
    change_type: str = "pull"
    repo_path: str = ""
    original_url: str = ""

    @property
    def stable_id(self) -> str:
        repo_path = self.repo_path or f"{self.owner}/{self.repo}"
        host = self.host or self.provider
        return f"{self.ticket_id}:{host}:{repo_path}/{self.change_type}/{self.pr_number}"


@dataclass(frozen=True)
class CodeSnippet:
    ticket_id: str
    pr_url: str
    file_path: str
    old_start_line: int | None
    new_start_line: int | None
    vulnerable_snippet: str
    fixed_snippet: str
    context: str = ""


@dataclass(frozen=True)
class IssuePattern:
    ticket_id: str
    snippet_id: str
    pr_url: str
    issue_type: str
    code_feature: str
    vulnerable_snippet: str
    fixed_snippet: str
    fix_advice: str
    evidence: str
    confidence: float
    embedding: dict[str, float]
    fingerprint: str


@dataclass(frozen=True)
class CodeChunk:
    file_path: Path
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class ReviewFinding:
    review_id: str
    file_path: str
    line: int
    issue_type: str
    matched_ticket_id: str
    matched_pattern_id: str
    evidence: str
    recommendation: str
    confidence: float
    snippet: str
