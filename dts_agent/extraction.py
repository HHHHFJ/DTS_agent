from __future__ import annotations

import re

from dts_agent.code_change import has_logical_code_change
from dts_agent.extraction_rules import ISSUE_RULES, issue_advice
from dts_agent.llm_judge import HeuristicSecurityJudge, SecurityJudge
from dts_agent.models import CodeSnippet, DtsTicket, IssuePattern
from dts_agent.utils import normalize_code, sparse_embedding, stable_hash, truncate


def build_issue_pattern(
    ticket: DtsTicket,
    snippet_id: str,
    snippet: CodeSnippet,
    security_judge: SecurityJudge | None = None,
) -> IssuePattern | None:
    vulnerable = normalize_code(snippet.vulnerable_snippet)
    fixed = normalize_code(snippet.fixed_snippet)
    if not vulnerable and not fixed:
        return None
    if not has_logical_code_change(snippet.vulnerable_snippet, snippet.fixed_snippet):
        return None

    summary_issue = classify_summary_issue(ticket.summary)
    judge = security_judge or HeuristicSecurityJudge()
    judgement = judge.assess(ticket, snippet, summary_issue[0] if summary_issue else None)
    if not judgement.has_security_issue or judgement.confidence < 0.5:
        return None

    if summary_issue and judgement.issue_type == summary_issue[0]:
        issue_type = summary_issue[0]
        type_decision = "DTS摘要类型与代码判定一致，采用DTS摘要类型"
    elif judgement.issue_type and judgement.issue_type != "通用安全缺陷":
        issue_type = judgement.issue_type
        type_decision = "DTS摘要类型与代码判定不一致，采用代码/大模型判定类型"
    elif summary_issue:
        issue_type = summary_issue[0]
        type_decision = "代码判定未给出明确类型，采用DTS摘要类型"
    else:
        issue_type = "通用安全缺陷"
        type_decision = "无明确摘要类型，采用通用安全缺陷"

    advice = issue_advice(issue_type)
    confidence = min(0.98, max(judgement.confidence, summary_issue[2] if summary_issue else 0.0))
    code_feature = summarize_code_feature(snippet)
    evidence = truncate(
        "\n".join(
            part
            for part in (
                f"DTS摘要: {ticket.summary}",
                f"DTS摘要类型: {summary_issue[0] if summary_issue else '未命中'}",
                f"代码安全判定: {'存在安全问题' if judgement.has_security_issue else '未确认安全问题'}",
                f"代码判定类型: {judgement.issue_type}",
                f"类型决策: {type_decision}",
                f"判定来源: {judgement.source}",
                f"判定理由: {judgement.rationale}",
                f"PR: {snippet.pr_url}",
                f"文件: {snippet.file_path}",
                f"上下文:\n{normalize_code(snippet.context)}",
                f"修复前:\n{vulnerable}",
                f"修复后:\n{fixed}",
            )
            if part.strip()
        ),
        4000,
    )
    text_for_embedding = "\n".join([issue_type, code_feature, vulnerable, fixed, ticket.summary])
    fingerprint = stable_hash(
        "|".join([ticket.ticket_id, snippet.pr_url, snippet.file_path, vulnerable, fixed]),
        length=32,
    )

    return IssuePattern(
        ticket_id=ticket.ticket_id,
        snippet_id=snippet_id,
        pr_url=snippet.pr_url,
        issue_type=issue_type,
        code_feature=code_feature,
        vulnerable_snippet=vulnerable,
        fixed_snippet=fixed,
        fix_advice=advice,
        evidence=evidence,
        confidence=confidence,
        embedding=sparse_embedding(text_for_embedding),
        fingerprint=fingerprint,
    )


def classify_issue(summary: str, snippet: CodeSnippet) -> tuple[str, str, float]:
    summary_best = classify_summary_issue(summary)
    if summary_best:
        return summary_best

    haystack = "\n".join(
        [
            snippet.vulnerable_snippet or "",
            snippet.fixed_snippet or "",
            snippet.file_path or "",
        ]
    ).lower()
    best = _classify_text(haystack, base=0.50)
    if best:
        return best
    return (
        "通用安全缺陷",
        "结合历史修复前后差异补充等价防护逻辑，并为边界、异常和失败路径增加测试。",
        0.45,
    )


def classify_summary_issue(summary: str) -> tuple[str, str, float] | None:
    return _classify_text(summary or "", base=0.72)


def _classify_text(text: str, base: float) -> tuple[str, str, float] | None:
    best: tuple[str, str, float] | None = None
    for issue_type, pattern, advice in ISSUE_RULES:
        matches = len(re.findall(pattern, text, flags=re.IGNORECASE))
        if matches:
            confidence = min(0.96, base + matches * 0.08)
            if best is None or confidence > best[2]:
                best = (issue_type, advice, confidence)
    return best


def summarize_code_feature(snippet: CodeSnippet) -> str:
    vulnerable_tokens = _interesting_tokens(snippet.vulnerable_snippet)
    fixed_tokens = _interesting_tokens(snippet.fixed_snippet)
    removed = ", ".join(vulnerable_tokens[:16]) or "无明显修复前符号"
    added = ", ".join(fixed_tokens[:16]) or "无明显修复后符号"
    return f"文件 {snippet.file_path}; 修复前关键符号: {removed}; 修复后关键符号: {added}"


def _interesting_tokens(code: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", code or "")
    stop = {
        "the",
        "and",
        "for",
        "while",
        "return",
        "static",
        "const",
        "void",
        "int",
        "char",
        "bool",
        "true",
        "false",
        "null",
        "none",
        "this",
        "self",
    }
    seen: set[str] = set()
    selected: list[str] = []
    for token in tokens:
        lower = token.lower()
        if lower in stop or lower in seen:
            continue
        seen.add(lower)
        selected.append(token)
    return selected
