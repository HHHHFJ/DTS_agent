from __future__ import annotations

import uuid
from pathlib import Path

from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.models import CodeChunk, ReviewFinding
from dts_agent.review.code_feature_extractor import extract_diff_chunks, extract_repo_chunks
from dts_agent.utils import cosine, json_loads_dict, normalize_code, sparse_embedding, truncate

GENERIC_TOKENS = {
    "std",
    "string",
    "vector",
    "map",
    "unordered_map",
    "unordered_set",
    "set",
    "list",
    "int",
    "char",
    "bool",
    "void",
    "auto",
    "const",
    "static",
    "return",
    "include",
    "namespace",
    "class",
    "struct",
    "public",
    "private",
    "protected",
    "size_t",
    "true",
    "false",
    "null",
    "nullptr",
}

ISSUE_ANCHORS = {
    "命令注入风险": {
        "popen",
        "system",
        "exec",
        "execl",
        "execv",
        "subprocess",
        "shell",
        "cmd",
        "command",
        "spawn",
        "createprocess",
    },
    "路径穿越风险": {
        "path",
        "filename",
        "filepath",
        "file",
        "open",
        "fopen",
        "ifstream",
        "ofstream",
        "remove",
        "unlink",
        "rename",
        "realpath",
        "canonical",
        "../",
        "..\\",
    },
    "权限校验缺失": {
        "auth",
        "permission",
        "access",
        "privilege",
        "capability",
        "role",
        "admin",
        "allow",
        "deny",
    },
    "输入校验缺失": {
        "validate",
        "check",
        "verify",
        "length",
        "size",
        "range",
        "bounds",
        "null",
        "regex",
        "stoi",
    },
}


def review_repo(
    store: KnowledgeStore,
    path: str | Path,
    min_confidence: float = 0.35,
    exclude_dirs: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, list[ReviewFinding]]:
    chunks = extract_repo_chunks(path, exclude_dirs=exclude_dirs)
    return review_chunks(store, Path(path), "repo", chunks, min_confidence)


def review_diff(
    store: KnowledgeStore,
    path: str | Path,
    base: str = "HEAD~1",
    min_confidence: float = 0.35,
    exclude_dirs: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, list[ReviewFinding]]:
    chunks = extract_diff_chunks(path, base=base, exclude_dirs=exclude_dirs)
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
        chunk_tokens = _meaningful_tokens(chunk_text)
        for pattern in patterns:
            pattern_text = "\n".join(
                [
                    str(pattern.get("issue_type") or ""),
                    str(pattern.get("code_feature") or ""),
                    str(pattern.get("vulnerable_snippet") or ""),
                    str(pattern.get("fixed_snippet") or ""),
                ]
            )
            pattern_tokens = _meaningful_tokens(pattern_text)
            overlap = sorted((chunk_tokens & pattern_tokens) - GENERIC_TOKENS)
            issue_type = str(pattern.get("issue_type") or "")
            anchor_hits = _anchor_hits(issue_type, chunk_text, pattern_text)
            if not _has_strong_match_signal(overlap, anchor_hits):
                continue

            pattern_embedding = {
                key: float(value)
                for key, value in json_loads_dict(pattern.get("embedding")).items()
            }
            vulnerable_embedding = sparse_embedding(pattern_text)
            score = max(cosine(chunk_embedding, pattern_embedding), cosine(chunk_embedding, vulnerable_embedding))
            anchor_bonus = min(0.18, len(anchor_hits) * 0.06)
            overlap_bonus = min(0.12, len(overlap) * 0.015)
            score = min(
                0.98,
                score * 0.72 + float(pattern.get("confidence") or 0.0) * 0.10 + anchor_bonus + overlap_bonus,
            )
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
                        f"匹配依据: {_format_match_basis(anchor_hits, overlap)}\n"
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


def _meaningful_tokens(text: str) -> set[str]:
    import re

    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|\.{2}[\\/]", text.lower()))
    return {token for token in tokens if token not in GENERIC_TOKENS}


def _anchor_hits(issue_type: str, chunk_text: str, pattern_text: str) -> list[str]:
    anchors = ISSUE_ANCHORS.get(issue_type, set())
    chunk_lower = chunk_text.lower()
    pattern_lower = pattern_text.lower()
    return sorted(anchor for anchor in anchors if anchor in chunk_lower and anchor in pattern_lower)


def _has_strong_match_signal(overlap: list[str], anchor_hits: list[str]) -> bool:
    if anchor_hits:
        return True
    specific_overlap = [token for token in overlap if len(token) >= 6]
    if len(specific_overlap) >= 3:
        return True
    very_specific_overlap = [token for token in overlap if len(token) >= 8]
    return bool(very_specific_overlap)


def _format_match_basis(anchor_hits: list[str], overlap: list[str]) -> str:
    parts: list[str] = []
    if anchor_hits:
        parts.append("安全锚点 " + ", ".join(anchor_hits[:8]))
    if overlap:
        parts.append("共同代码特征 " + ", ".join(overlap[:12]))
    return "；".join(parts) if parts else "未记录明确匹配依据"
