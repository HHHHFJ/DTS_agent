from __future__ import annotations

import json
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
        "## 风险清单",
        "",
    ]

    if not findings:
        lines.extend(["未发现与 DTS 知识库高度相似的历史同类问题。", ""])
    for index, finding in enumerate(findings, 1):
        confidence = float(finding.get("confidence") or 0.0)
        severity = "高" if confidence >= 0.78 else "中" if confidence >= 0.55 else "低"
        lines.extend(
            [
                f"### {index}. {finding.get('issue_type') or '未知问题'}",
                "",
                f"- 风险等级: {severity}",
                f"- 位置: `{finding.get('file_path')}:{finding.get('line')}`",
                f"- 相似问题单: `{finding.get('matched_ticket_id')}`",
                f"- 置信度: {confidence:.2f}",
                "",
                "#### 相似历史问题",
                "",
                finding.get("evidence") or "无证据",
                "",
                "#### 证据片段",
                "",
                "```",
                finding.get("snippet") or "",
                "```",
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
