from __future__ import annotations

import uuid
from pathlib import Path

from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.models import CodeChunk, ReviewFinding
from dts_agent.review.code_feature_extractor import extract_diff_chunks, extract_repo_chunks
from dts_agent.utils import cosine, json_loads_dict, normalize_code, sparse_embedding, truncate


def review_repo(store: KnowledgeStore, path: str | Path, min_confidence: float = 0.35) -> tuple[str, list[ReviewFinding]]:
    chunks = extract_repo_chunks(path)
    return review_chunks(store, Path(path), "repo", chunks, min_confidence)


def review_diff(
    store: KnowledgeStore,
    path: str | Path,
    base: str = "HEAD~1",
    min_confidence: float = 0.35,
) -> tuple[str, list[ReviewFinding]]:
    chunks = extract_diff_chunks(path, base=base)
    return review_chunks(store, Path(path), "diff", chunks, min_confidence)


def review_chunks(
    store: KnowledgeStore,
    target_path: Path,
    mode: str,
    chunks: list[CodeChunk],
    min_confidence: float,
) -> tuple[str, list[ReviewFinding]]:
    review_id = str(uuid.uuid4())
    patterns = store.all_patterns()
    findings: list[ReviewFinding] = []
    seen: set[tuple[str, int, str]] = set()

    for chunk in chunks:
        chunk_text = normalize_code(chunk.text)
        if not chunk_text:
            continue
        chunk_embedding = sparse_embedding(chunk_text)
        for pattern in patterns:
            pattern_embedding = {
                key: float(value)
                for key, value in json_loads_dict(pattern.get("embedding")).items()
            }
            vulnerable_embedding = sparse_embedding(
                "\n".join(
                    [
                        str(pattern.get("issue_type") or ""),
                        str(pattern.get("code_feature") or ""),
                        str(pattern.get("vulnerable_snippet") or ""),
                    ]
                )
            )
            score = max(cosine(chunk_embedding, pattern_embedding), cosine(chunk_embedding, vulnerable_embedding))
            score = min(0.98, score * 0.85 + float(pattern.get("confidence") or 0.0) * 0.15)
            if score < min_confidence:
                continue
            key = (str(chunk.file_path), chunk.start_line, str(pattern.get("id")))
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                ReviewFinding(
                    review_id=review_id,
                    file_path=str(_relative_or_absolute(chunk.file_path, target_path)),
                    line=chunk.start_line,
                    issue_type=str(pattern.get("issue_type") or "未知问题"),
                    matched_ticket_id=str(pattern.get("ticket_id") or ""),
                    matched_pattern_id=str(pattern.get("id") or ""),
                    evidence=truncate(
                        f"当前代码片段与历史问题 {pattern.get('ticket_id')} 的修复前特征相似。\n"
                        f"历史证据:\n{pattern.get('evidence') or ''}",
                        2400,
                    ),
                    recommendation=str(pattern.get("fix_advice") or ""),
                    confidence=round(score, 4),
                    snippet=truncate(chunk.text, 1600),
                )
            )

    findings.sort(key=lambda item: item.confidence, reverse=True)
    findings = findings[:100]
    store.save_review_run(
        review_id=review_id,
        target_path=str(Path(target_path).resolve()),
        mode=mode,
        findings=findings,
    )
    return review_id, findings


def findings_to_json(review_id: str, findings: list[ReviewFinding]) -> dict[str, object]:
    return {
        "status": "ok",
        "review_id": review_id,
        "finding_count": len(findings),
        "findings": [
            {
                "severity": _severity(finding.confidence),
                "file": finding.file_path,
                "line": finding.line,
                "issue_type": finding.issue_type,
                "matched_ticket_id": finding.matched_ticket_id,
                "matched_pattern_id": finding.matched_pattern_id,
                "evidence": finding.evidence,
                "recommendation": finding.recommendation,
                "confidence": finding.confidence,
                "snippet": finding.snippet,
            }
            for finding in findings
        ],
    }


def _severity(confidence: float) -> str:
    if confidence >= 0.78:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def _relative_or_absolute(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.resolve()
