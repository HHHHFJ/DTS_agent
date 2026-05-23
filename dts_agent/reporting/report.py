from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.utils import utc_now_text


def generate_report(
    store: KnowledgeStore,
    review_id: str = "latest",
    output_format: str = "md",
    output_path: str | Path | None = None,
) -> tuple[str, str]:
    run, findings = store.load_review(review_id)
    if not run:
        raise ValueError(f"Review run not found: {review_id}")

    if output_format == "json":
        content = json.dumps({"review": run, "findings": findings}, ensure_ascii=False, indent=2)
    else:
        content = _markdown_report(run, findings)

    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target), content
    return "", content


def _markdown_report(run: dict, findings: list[dict]) -> str:
    high = [item for item in findings if float(item.get("confidence") or 0.0) >= 0.78]
    medium = [
        item
        for item in findings
        if 0.55 <= float(item.get("confidence") or 0.0) < 0.78
    ]
    low = [item for item in findings if float(item.get("confidence") or 0.0) < 0.55]
    type_counts = Counter(str(item.get("issue_type") or "未知问题") for item in findings)
    ticket_counts = Counter(str(item.get("matched_ticket_id") or "未知问题单") for item in findings)
    file_counts = Counter(str(item.get("file_path") or "未知文件") for item in findings)

    lines = [
        "# DTS 同类安全问题测试报告",
        "",
        "## 概览",
        "",
        f"- Review ID: `{run['id']}`",
        f"- 目标路径: `{run['target_path']}`",
        f"- 检视模式: `{run['mode']}`",
        f"- 生成时间: `{utc_now_text()}`",
        f"- 风险总数: {len(findings)}，高: {len(high)}，中: {len(medium)}，低: {len(low)}",
        "",
        "## 汇总统计",
        "",
        "### 按风险等级",
        "",
        "| 风险等级 | 数量 |",
        "| --- | ---: |",
        f"| 高 | {len(high)} |",
        f"| 中 | {len(medium)} |",
        f"| 低 | {len(low)} |",
        "",
        "### 按问题类型",
        "",
        *_counter_table(type_counts, "问题类型"),
        "",
        "### 按历史问题单",
        "",
        *_counter_table(ticket_counts, "问题单号"),
        "",
        "### 按文件",
        "",
        *_counter_table(file_counts, "文件", limit=20),
        "",
        "## 风险清单",
        "",
    ]

    if not findings:
        lines.extend(["未发现与 DTS 知识库高度相似的历史同类问题。", ""])
    for index, finding in enumerate(findings, 1):
        confidence = float(finding.get("confidence") or 0.0)
        severity = "高" if confidence >= 0.78 else "中" if confidence >= 0.55 else "低"
        snippet = _core_snippet(finding.get("snippet") or "")
        history = _history_summary(finding.get("evidence") or "")
        lines.extend(
            [
                f"### {index}. {finding.get('issue_type') or '未知问题'}",
                "",
                f"- 风险等级: {severity}",
                f"- 位置: `{finding.get('file_path')}:{finding.get('line')}`",
                f"- 相似问题单: `{finding.get('matched_ticket_id')}`",
                f"- 置信度: {confidence:.2f}",
                "",
                "#### 问题位置",
                "",
                f"扫描命中位置位于 `{finding.get('file_path')}:{finding.get('line')}` 附近，核心代码片段如下：",
                "",
                "```",
                snippet or "未记录代码片段",
                "```",
                "",
                "#### 相似历史问题",
                "",
                history or "无历史证据摘要",
                "",
                "#### 修复建议",
                "",
                finding.get("recommendation") or "请结合历史修复模式补充防护逻辑。",
                "",
            ]
        )

    lines.extend(
        [
            "## 误报待确认项",
            "",
            "低置信度结果需要人工确认是否存在相同触发条件、调用路径和安全边界。",
            "",
        ]
    )
    return "\n".join(lines)


def _counter_table(counter: Counter[str], label: str, limit: int | None = None) -> list[str]:
    if not counter:
        return [f"暂无{label}统计。"]
    rows = [f"| {label} | 数量 |", "| --- | ---: |"]
    for name, count in counter.most_common(limit):
        rows.append(f"| `{_escape_table_cell(name)}` | {count} |")
    return rows


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _core_snippet(snippet: str, max_lines: int = 18, max_width: int = 180) -> str:
    lines = [line.rstrip() for line in snippet.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return ""

    keyword_groups = (
        (
            "popen",
            "system",
            "exec",
            "subprocess",
            "fopen",
            "open(",
            "strcpy",
            "sprintf",
            "../",
        ),
        (
            "ifstream",
            "ofstream",
            "getline",
            "regex",
            "stoi",
            "cmd",
            "path",
            "file",
        ),
    )
    hit_index = 0
    for keywords in keyword_groups:
        found = False
        for index, line in enumerate(lines):
            lowered = line.lower()
            if any(keyword in lowered for keyword in keywords):
                hit_index = index
                found = True
                break
        if found:
            break

    before = max(0, hit_index - 5)
    after = min(len(lines), hit_index + 6)
    selected = lines[before:after]
    if len(selected) > max_lines:
        selected = selected[:max_lines]

    result: list[str] = []
    for offset, line in enumerate(selected, before):
        prefix = ">> " if offset == hit_index else "   "
        result.append(prefix + _truncate_line(line, max_width))
    return "\n".join(result)


def _history_summary(evidence: str) -> str:
    match_basis = _match_line(evidence, r"^匹配依据:\s*(.+)$")
    summary = _match_line(evidence, r"^DTS摘要:\s*(.+)$")
    pr_url = _match_line(evidence, r"^PR:\s*(.+)$")
    file_path = _match_line(evidence, r"^文件:\s*(.+)$")
    parts = []
    if match_basis:
        parts.append(f"- 匹配依据: {match_basis}")
    if summary:
        parts.append(f"- 历史摘要: {summary}")
    if file_path:
        parts.append(f"- 历史文件: `{file_path}`")
    if pr_url:
        parts.append(f"- 来源 PR: {pr_url}")
    return "\n".join(parts)


def _match_line(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _truncate_line(line: str, max_width: int) -> str:
    if len(line) <= max_width:
        return line
    return line[: max_width - 3] + "..."
