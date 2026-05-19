from __future__ import annotations

import re

from dts_agent.models import CodeSnippet, DtsTicket, IssuePattern
from dts_agent.utils import fingerprint_code, json_dumps, normalize_code, sparse_embedding, stable_hash, truncate


ISSUE_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "权限校验缺失",
        r"权限|鉴权|认证|授权|permission|auth|privilege|capability|access",
        "补充权限/鉴权检查，确保敏感路径在执行前完成主体、角色和资源范围校验。",
    ),
    (
        "输入校验缺失",
        r"参数|输入|校验|validate|check|invalid|非法|null|none|空指针|越界|bounds|range|length",
        "对外部输入、长度、空值、边界和状态组合做显式校验，并保持错误返回路径一致。",
    ),
    (
        "命令注入风险",
        r"命令|shell|exec|system|popen|subprocess|注入|injection",
        "避免拼接命令；使用参数化调用和白名单校验，必要时限制可执行命令范围。",
    ),
    (
        "路径穿越风险",
        r"路径|目录|path|file|filename|traversal|\.\./|绝对路径",
        "规范化路径并限制在可信根目录内，拒绝穿越、绝对路径和非法文件名。",
    ),
    (
        "资源释放遗漏",
        r"释放|泄漏|close|free|release|defer|cleanup|resource|fd|handle|memory leak",
        "确保异常和提前返回路径都释放资源，优先使用上下文管理或统一清理分支。",
    ),
    (
        "并发竞态",
        r"并发|竞态|race|lock|mutex|thread|goroutine|atomic|同步",
        "为共享状态补充锁、原子操作或事务边界，避免检查和使用之间的竞态窗口。",
    ),
    (
        "敏感信息泄露",
        r"敏感|泄露|密码|token|secret|key|log|日志|credential",
        "避免输出敏感字段；在日志、异常和接口响应中做脱敏或移除。",
    ),
    (
        "错误处理缺失",
        r"错误|异常|error|exception|return code|errno|fail|失败",
        "检查错误返回并补充失败分支，避免继续使用无效状态或不完整结果。",
    ),
)


def build_issue_pattern(ticket: DtsTicket, snippet_id: str, snippet: CodeSnippet) -> IssuePattern | None:
    vulnerable = normalize_code(snippet.vulnerable_snippet)
    fixed = normalize_code(snippet.fixed_snippet)
    if not vulnerable and not fixed:
        return None

    issue_type, advice, confidence = classify_issue(ticket.summary, snippet)
    code_feature = summarize_code_feature(snippet)
    evidence = truncate(
        "\n".join(
            part
            for part in (
                f"DTS摘要: {ticket.summary}",
                f"PR: {snippet.pr_url}",
                f"文件: {snippet.file_path}",
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
    haystack = "\n".join(
        [
            summary or "",
            snippet.vulnerable_snippet or "",
            snippet.fixed_snippet or "",
            snippet.file_path or "",
        ]
    ).lower()
    best: tuple[str, str, float] | None = None
    for issue_type, pattern, advice in ISSUE_RULES:
        matches = len(re.findall(pattern, haystack, flags=re.IGNORECASE))
        if matches:
            confidence = min(0.92, 0.55 + matches * 0.08)
            if best is None or confidence > best[2]:
                best = (issue_type, advice, confidence)

    if best:
        return best
    return (
        "通用安全缺陷",
        "结合历史修复前后差异补充等价防护逻辑，并为边界、异常和失败路径增加测试。",
        0.45,
    )


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
