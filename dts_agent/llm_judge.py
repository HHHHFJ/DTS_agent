from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from dts_agent.extraction_rules import ISSUE_RULES, issue_advice
from dts_agent.models import CodeSnippet, DtsTicket


@dataclass(frozen=True)
class SecurityJudgement:
    has_security_issue: bool
    issue_type: str
    confidence: float
    rationale: str
    source: str


class SecurityJudge(Protocol):
    source: str

    def assess(
        self,
        ticket: DtsTicket,
        snippet: CodeSnippet,
        summary_issue_type: str | None,
    ) -> SecurityJudgement:
        ...


class MissingLlmJudge(RuntimeError):
    pass


class CommandSecurityJudge:
    source = "llm-command"

    def __init__(self, command: str, timeout: int = 120) -> None:
        self.command = command
        self.timeout = timeout

    def assess(
        self,
        ticket: DtsTicket,
        snippet: CodeSnippet,
        summary_issue_type: str | None,
    ) -> SecurityJudgement:
        payload = build_judge_payload(ticket, snippet, summary_issue_type)
        completed = subprocess.run(
            self.command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=self.timeout,
            shell=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"LLM judge command failed with {completed.returncode}: {completed.stderr.strip()}"
            )
        return parse_judgement(completed.stdout, self.source)


class HttpSecurityJudge:
    source = "llm-http"

    def __init__(self, url: str, token: str | None = None, timeout: int = 120) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout

    def assess(
        self,
        ticket: DtsTicket,
        snippet: CodeSnippet,
        summary_issue_type: str | None,
    ) -> SecurityJudgement:
        body = json.dumps(build_judge_payload(ticket, snippet, summary_issue_type), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST")
        request.add_header("Content-Type", "application/json; charset=utf-8")
        request.add_header("Accept", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return parse_judgement(response.read().decode("utf-8", errors="replace"), self.source)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM judge HTTP request failed: {exc}") from exc


class HeuristicSecurityJudge:
    source = "heuristic"

    def assess(
        self,
        ticket: DtsTicket,
        snippet: CodeSnippet,
        summary_issue_type: str | None,
    ) -> SecurityJudgement:
        old_text = "\n".join([snippet.context or "", snippet.vulnerable_snippet or ""])
        fixed_text = snippet.fixed_snippet or ""
        haystack = old_text.lower()
        fixed_lower = fixed_text.lower()

        code_issue = _classify_code_by_anchors(haystack)
        if code_issue:
            return SecurityJudgement(
                has_security_issue=True,
                issue_type=code_issue,
                confidence=0.72,
                rationale=f"修复前代码上下文命中 {code_issue} 的安全锚点。",
                source=self.source,
            )

        if summary_issue_type == "权限校验缺失":
            added_auth_check = any(
                token in fixed_lower
                for token in ("admin", "auth", "permission", "access", "privilege", "capability", "role")
            )
            old_has_auth_check = any(
                token in haystack
                for token in ("admin", "auth", "permission", "access", "privilege", "capability", "role")
            )
            if added_auth_check and not old_has_auth_check:
                return SecurityJudgement(
                    has_security_issue=True,
                    issue_type="权限校验缺失",
                    confidence=0.68,
                    rationale="修复后新增权限/身份校验相关逻辑，修复前上下文未见等价校验。",
                    source=self.source,
                )

        return SecurityJudgement(
            has_security_issue=False,
            issue_type=summary_issue_type or "通用安全缺陷",
            confidence=0.0,
            rationale="修复前代码和上下文未命中可确认的安全锚点，跳过入库。",
            source=self.source,
        )


def build_judge_payload(
    ticket: DtsTicket,
    snippet: CodeSnippet,
    summary_issue_type: str | None,
) -> dict[str, Any]:
    return {
        "task": "Judge whether the vulnerable/old code snippet still contains a real security issue in its context. Return strict JSON only.",
        "output_schema": {
            "has_security_issue": "boolean",
            "issue_type": "one of allowed_issue_types",
            "confidence": "number from 0 to 1",
            "rationale": "short reason in Chinese",
        },
        "decision_policy": [
            "Only mark has_security_issue=true when the old code/context itself has a plausible security flaw.",
            "Use the DTS summary as a candidate issue type.",
            "If the old code judgement agrees with the summary type, return the summary type.",
            "If the old code judgement disagrees with the summary type, return the code judgement type.",
            "If there is not enough evidence in old code/context, return has_security_issue=false.",
        ],
        "allowed_issue_types": [rule[0] for rule in ISSUE_RULES] + ["通用安全缺陷"],
        "dts_ticket": ticket.ticket_id,
        "dts_summary": ticket.summary,
        "summary_issue_type": summary_issue_type,
        "file_path": snippet.file_path,
        "old_start_line": snippet.old_start_line,
        "new_start_line": snippet.new_start_line,
        "context": snippet.context,
        "vulnerable_snippet": snippet.vulnerable_snippet,
        "fixed_snippet": snippet.fixed_snippet,
    }


def parse_judgement(raw_output: str, source: str) -> SecurityJudgement:
    text = raw_output.strip()
    if "```" in text:
        text = _extract_json_block(text)
    data = json.loads(text)
    has_issue = bool(data.get("has_security_issue"))
    issue_type = str(data.get("issue_type") or "通用安全缺陷")
    allowed = {rule[0] for rule in ISSUE_RULES} | {"通用安全缺陷"}
    if issue_type not in allowed:
        issue_type = "通用安全缺陷"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return SecurityJudgement(
        has_security_issue=has_issue,
        issue_type=issue_type,
        confidence=confidence,
        rationale=str(data.get("rationale") or ""),
        source=source,
    )


def create_security_judge(config: Any, require_llm: bool = False) -> SecurityJudge:
    if getattr(config, "llm_judge_command", None):
        return CommandSecurityJudge(config.llm_judge_command, timeout=config.llm_judge_timeout)
    if getattr(config, "llm_judge_url", None):
        return HttpSecurityJudge(
            config.llm_judge_url,
            token=getattr(config, "llm_judge_token", None),
            timeout=config.llm_judge_timeout,
        )
    if require_llm:
        raise MissingLlmJudge(
            "LLM judge is required but not configured. Set DTS_AGENT_LLM_COMMAND or DTS_AGENT_LLM_URL."
        )
    return HeuristicSecurityJudge()


def _classify_code_by_anchors(text: str) -> str | None:
    anchor_map = {
        "命令注入风险": ("popen", "system(", "exec", "subprocess", "shell", "cmd.data", "cmd.c_str", "getcmdlineresult"),
        "路径穿越风险": ("../", "..\\", "realpath", "canonical", "normalize", "ifstream", "ofstream", "fopen"),
        "敏感信息泄露": ("password", "passwd", "secret", "token", "credential", "apikey", "api_key"),
        "资源释放遗漏": ("malloc", "new ", "fopen", "open(", "lock(", "unlock", "free(", "close("),
    }
    for issue_type, anchors in anchor_map.items():
        if any(anchor in text for anchor in anchors):
            return issue_type
    return None


def _extract_json_block(text: str) -> str:
    import re

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text
