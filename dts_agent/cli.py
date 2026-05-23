from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from dts_agent.code_change import has_logical_code_change
from dts_agent.config import ensure_runtime_dirs, load_config
from dts_agent.dts_tools.excel_loader import ExcelLoadError, load_dts_excel
from dts_agent.dts_tools.fetch_tool import DtsFetchError, run_fetch_script
from dts_agent.dts_tools.gitcode_client import GitCodeClient, GitCodeFetchError
from dts_agent.dts_tools.pr_parser import parse_ticket_pr_links
from dts_agent.extraction import build_issue_pattern, classify_summary_issue
from dts_agent.extraction_rules import ISSUE_RULES
from dts_agent.kb.sqlite_store import KnowledgeStore
from dts_agent.llm_judge import SecurityJudgement, create_security_judge
from dts_agent.models import CodeSnippet, DtsTicket
from dts_agent.reporting.report import generate_report
from dts_agent.review.reviewer import findings_to_json, review_diff, review_repo
from dts_agent.utils import file_sha256, json_dumps, stable_hash, utc_now_text


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.root)
    ensure_runtime_dirs(config)
    store = KnowledgeStore(config.database_path)

    try:
        result = dispatch(args, config, store)
    except Exception as exc:  # noqa: BLE001 - CLI should return structured failures.
        if getattr(args, "json", False):
            _print_json({"status": "error", "error": str(exc)})
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1

    if isinstance(result, str):
        print(result)
    elif result is not None:
        if getattr(args, "json", False) or isinstance(result, (dict, list)):
            _print_json(result)
        else:
            print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m dts_agent")
    parser.add_argument("--root", help="DTS agent home directory. Defaults to DTS_AGENT_HOME or cwd.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize SQLite database and runtime directories.")
    init.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="Show knowledge base status.")
    status.add_argument("--json", action="store_true")

    inspect_db = sub.add_parser("inspect-db", help="Show table counts and sample knowledge base records.")
    inspect_db.add_argument("--limit", type=int, default=10)
    inspect_db.add_argument("--json", action="store_true")

    sync = sub.add_parser("sync", help="Run DTS fetch script and import the generated Excel file.")
    sync.add_argument("--fetch-script", help="Path to dts_data_fetch.py.")
    sync.add_argument("--file", help="Import an existing Excel/CSV instead of running the fetch script.")
    sync.add_argument("--mode", default="manual", choices=["manual", "scheduled"])
    sync.add_argument("--skip-fetch-pr", action="store_true", help="Only import tickets and PR links.")
    sync.add_argument("--skip-build-kb", action="store_true", help="Fetch PR snippets but do not build issue patterns.")
    sync.add_argument("--require-llm", action="store_true", help="Fail if no LLM security judge is configured.")
    sync.add_argument("--force", action="store_true", help="Reserved for callers that want explicit manual refresh.")
    sync.add_argument("--json", action="store_true")

    import_excel = sub.add_parser("import-excel", help="Import a DTS Excel/CSV file.")
    import_excel.add_argument("--file", required=True)
    import_excel.add_argument("--skip-fetch-pr", action="store_true")
    import_excel.add_argument("--skip-build-kb", action="store_true", help="Fetch PR snippets but do not build issue patterns.")
    import_excel.add_argument("--require-llm", action="store_true", help="Fail if no LLM security judge is configured.")
    import_excel.add_argument("--json", action="store_true")

    parse_urls = sub.add_parser("parse-pr-urls", help="Parse PR URLs from Excel or imported DB records.")
    parse_urls.add_argument("--file")
    parse_urls.add_argument("--ticket")
    parse_urls.add_argument("--json", action="store_true")

    fetch_diff = sub.add_parser("fetch-pr-diff", help="Fetch and parse GitCode PR diff snippets.")
    fetch_diff.add_argument("--url", required=True)
    fetch_diff.add_argument("--ticket", default="MANUAL")
    fetch_diff.add_argument("--json", action="store_true")

    build_kb = sub.add_parser("build-kb", help="Build issue patterns from stored code snippets.")
    build_kb.add_argument("--rebuild", action="store_true", help="Rebuild all issue patterns from stored snippets.")
    build_kb.add_argument("--require-llm", action="store_true", help="Fail if no LLM security judge is configured.")
    build_kb.add_argument("--json", action="store_true")

    clear_kb = sub.add_parser("clear-kb", help="Clear generated knowledge while keeping imported DTS tickets and snippets.")
    clear_kb.add_argument("--include-judgements", action="store_true", help="Also clear OpenCode agent snippet judgements.")
    clear_kb.add_argument("--json", action="store_true")

    judge_tasks = sub.add_parser("judge-tasks", help="List code snippets that need OpenCode agent security judgement.")
    judge_tasks.add_argument("--limit", type=int, default=5)
    judge_tasks.add_argument("--ticket")
    judge_tasks.add_argument("--rejudge", action="store_true", help="Include snippets that already have an agent judgement.")
    judge_tasks.add_argument("--json", action="store_true")

    apply_judgement = sub.add_parser("apply-judgement", help="Store an OpenCode agent security judgement for a snippet.")
    apply_judgement.add_argument("--file", help="JSON file containing one judgement object or a list of objects.")
    apply_judgement.add_argument("--stdin", action="store_true", help="Read one judgement object or a list of objects from stdin.")
    apply_judgement.add_argument("--snippet-id")
    apply_judgement.add_argument("--has-security-issue", type=_parse_bool)
    apply_judgement.add_argument("--issue-type")
    apply_judgement.add_argument("--confidence", type=float)
    apply_judgement.add_argument("--rationale")
    apply_judgement.add_argument("--fix-advice", default="")
    apply_judgement.add_argument("--source", default="opencode-agent")
    apply_judgement.add_argument("--json", action="store_true")

    query = sub.add_parser("query", help="Query the security knowledge base.")
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--json", action="store_true")

    review_repo_parser = sub.add_parser("review-repo", help="Review a repository against the DTS knowledge base.")
    review_repo_parser.add_argument("--path", default=".")
    review_repo_parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Directory name or relative path to exclude. Repeat for multiple values, e.g. --exclude test --exclude third_party.",
    )
    review_repo_parser.add_argument("--min-confidence", type=float)
    review_repo_parser.add_argument("--json", action="store_true")

    review_diff_parser = sub.add_parser("review-diff", help="Review current git diff against the DTS knowledge base.")
    review_diff_parser.add_argument("--path", default=".")
    review_diff_parser.add_argument("--base", default="HEAD~1")
    review_diff_parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Directory name or relative path to exclude. Repeat for multiple values, e.g. --exclude test --exclude third_party.",
    )
    review_diff_parser.add_argument("--min-confidence", type=float)
    review_diff_parser.add_argument("--json", action="store_true")

    report = sub.add_parser("report", help="Generate security test report from a review run.")
    report.add_argument("--review-id", default="latest")
    report.add_argument("--format", choices=["md", "json"], default="md")
    report.add_argument("--output")
    report.add_argument("--json", action="store_true")

    return parser


def dispatch(args: argparse.Namespace, config: Any, store: KnowledgeStore) -> Any:
    if args.command == "init":
        return {"status": "ok", "database": str(config.database_path)}
    if args.command == "status":
        return {"status": "ok", **store.status()}
    if args.command == "inspect-db":
        return {"status": "ok", **store.inspect(args.limit)}
    if args.command == "sync":
        return command_sync(args, config, store)
    if args.command == "import-excel":
        return command_import_excel(
            args.file,
            not args.skip_fetch_pr,
            config,
            store,
            build_kb=not args.skip_build_kb,
            require_llm=args.require_llm,
        )
    if args.command == "parse-pr-urls":
        return command_parse_pr_urls(args, store)
    if args.command == "fetch-pr-diff":
        return command_fetch_pr_diff(args, config)
    if args.command == "build-kb":
        return command_build_kb(store, rebuild=args.rebuild, config=config, require_llm=args.require_llm)
    if args.command == "clear-kb":
        return command_clear_kb(store, include_judgements=args.include_judgements)
    if args.command == "judge-tasks":
        return command_judge_tasks(store, limit=args.limit, ticket_id=args.ticket, rejudge=args.rejudge)
    if args.command == "apply-judgement":
        return command_apply_judgement(args, store)
    if args.command == "query":
        return {"status": "ok", "results": store.search_patterns(args.query, args.limit)}
    if args.command == "review-repo":
        min_confidence = args.min_confidence if args.min_confidence is not None else config.review_min_confidence
        review_id, findings = review_repo(
            store,
            args.path,
            min_confidence=min_confidence,
            exclude_dirs=args.exclude,
        )
        return findings_to_json(review_id, findings)
    if args.command == "review-diff":
        min_confidence = args.min_confidence if args.min_confidence is not None else config.review_min_confidence
        review_id, findings = review_diff(
            store,
            args.path,
            base=args.base,
            min_confidence=min_confidence,
            exclude_dirs=args.exclude,
        )
        return findings_to_json(review_id, findings)
    if args.command == "report":
        output = args.output
        if not output and args.format == "md":
            output = str(config.reports_dir / f"dts_security_report_{utc_now_text().replace(':', '-')}.md")
        path, content = generate_report(store, args.review_id, args.format, output)
        return {"status": "ok", "output": path, "content": content if not path else ""}
    raise ValueError(f"Unknown command: {args.command}")


def command_sync(args: argparse.Namespace, config: Any, store: KnowledgeStore) -> dict[str, Any]:
    started_at = utc_now_text()
    fetch_script = Path(args.fetch_script).resolve() if args.fetch_script else config.fetch_script
    excel_path: Path | None = Path(args.file).resolve() if args.file else None
    fetch_metadata: dict[str, Any] = {"mode": args.mode, "force": bool(args.force)}

    if excel_path is None:
        try:
            fetch_result = run_fetch_script(fetch_script, config.inbox_dir)
        except (DtsFetchError, TimeoutError) as exc:
            store.create_sync_run(
                started_at=started_at,
                finished_at=utc_now_text(),
                status="failed",
                error=str(exc),
                metadata=fetch_metadata,
            )
            raise
        fetch_metadata.update(
            {
                "fetch_exit_code": fetch_result.exit_code,
                "fetch_stdout": fetch_result.stdout[-4000:],
                "fetch_stderr": fetch_result.stderr[-4000:],
                "fetch_elapsed_seconds": fetch_result.elapsed_seconds,
            }
        )
        if fetch_result.exit_code != 0:
            store.create_sync_run(
                started_at=started_at,
                finished_at=utc_now_text(),
                status="failed",
                excel_path=str(fetch_result.excel_path or ""),
                error=f"dts_data_fetch.py exited with {fetch_result.exit_code}",
                metadata=fetch_metadata,
            )
            raise RuntimeError(f"dts_data_fetch.py exited with {fetch_result.exit_code}")
        excel_path = fetch_result.excel_path

    if excel_path is None or not excel_path.exists():
        store.create_sync_run(
            started_at=started_at,
            finished_at=utc_now_text(),
            status="failed",
            error="No Excel file was produced or provided.",
            metadata=fetch_metadata,
        )
        raise RuntimeError("No Excel file was produced or provided.")

    result = command_import_excel(
        str(excel_path),
        not args.skip_fetch_pr,
        config,
        store,
        build_kb=not args.skip_build_kb,
        require_llm=args.require_llm,
    )
    excel_hash = file_sha256(excel_path)
    store.create_sync_run(
        started_at=started_at,
        finished_at=utc_now_text(),
        status="ok",
        excel_path=str(excel_path),
        excel_hash=excel_hash,
        imported_count=int(result.get("ticket_count", 0)),
        metadata=fetch_metadata,
    )
    return {"status": "ok", "excel_path": str(excel_path), "excel_hash": excel_hash, **result}


def command_import_excel(
    excel_path: str,
    fetch_pr: bool,
    config: Any,
    store: KnowledgeStore,
    build_kb: bool = True,
    require_llm: bool = False,
) -> dict[str, Any]:
    tickets = load_dts_excel(excel_path)
    client = GitCodeClient(config.gitcode_api_base, config.gitcode_token, config.gitcode_timeout)
    security_judge = create_security_judge(config, require_llm=require_llm) if build_kb else None
    stats = {
        "status": "ok",
        "excel_path": str(Path(excel_path).resolve()),
        "ticket_count": len(tickets),
        "pr_link_count": 0,
        "snippet_count": 0,
        "pattern_count": 0,
        "build_kb": build_kb,
        "errors": [],
    }

    for ticket in tickets:
        store.upsert_ticket(ticket)
        links, errors = parse_ticket_pr_links(ticket.ticket_id, ticket.raw.get("修改文件清单", ""))
        stats["errors"].extend({"ticket_id": ticket.ticket_id, "error": error} for error in errors)
        for link in links:
            stats["pr_link_count"] += 1
            store.upsert_pr_link(link, status="pending")
            if not fetch_pr:
                continue
            try:
                snippets = client.fetch_pr_snippets(link)
            except GitCodeFetchError as exc:
                store.mark_pr_link(link, status="failed", error=str(exc))
                stats["errors"].append({"ticket_id": ticket.ticket_id, "pr_url": link.pr_url, "error": str(exc)})
                continue
            for snippet in snippets:
                snippet_id = store.upsert_snippet(snippet)
                stats["snippet_count"] += 1
                if build_kb:
                    pattern = build_issue_pattern(ticket, snippet_id, snippet, security_judge=security_judge)
                    if pattern:
                        store.upsert_pattern(pattern)
                        stats["pattern_count"] += 1
            store.mark_pr_link(link, status="ok")
    return stats


def command_parse_pr_urls(args: argparse.Namespace, store: KnowledgeStore) -> dict[str, Any]:
    if args.file:
        tickets = load_dts_excel(args.file)
        if args.ticket:
            tickets = [ticket for ticket in tickets if ticket.ticket_id == args.ticket]
        parsed = []
        for ticket in tickets:
            links, errors = parse_ticket_pr_links(ticket.ticket_id, ticket.raw.get("修改文件清单", ""))
            parsed.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "links": [asdict(link) for link in links],
                    "errors": errors,
                }
            )
        return {"status": "ok", "results": parsed}
    return {"status": "ok", "results": store.list_pr_links(args.ticket)}


def command_fetch_pr_diff(args: argparse.Namespace, config: Any) -> dict[str, Any]:
    links, errors = parse_ticket_pr_links(args.ticket, f"['{args.url}']")
    if errors or not links:
        raise ValueError("; ".join(errors) or f"Cannot parse PR URL: {args.url}")
    client = GitCodeClient(config.gitcode_api_base, config.gitcode_token, config.gitcode_timeout)
    snippets = client.fetch_pr_snippets(links[0])
    return {"status": "ok", "snippets": [asdict(snippet) for snippet in snippets]}


def command_build_kb(
    store: KnowledgeStore,
    rebuild: bool = False,
    config: Any | None = None,
    require_llm: bool = False,
) -> dict[str, Any]:
    security_judge = create_security_judge(config, require_llm=require_llm) if config else None
    if rebuild:
        store.clear_issue_patterns()
    count = 0
    rows = store.list_snippets_for_pattern_build(only_missing_patterns=not rebuild)
    for row in rows:
        ticket = DtsTicket(
            ticket_id=row["ticket_id"],
            serial_no=row.get("serial_no") or "",
            summary=row.get("summary") or "",
            severity=row.get("severity") or "",
            created_at=row.get("created_at") or "",
            reporter=row.get("reporter") or "",
        )
        snippet = CodeSnippet(
            ticket_id=row["ticket_id"],
            pr_url=row["pr_url"],
            file_path=row["file_path"],
            old_start_line=row["old_start_line"],
            new_start_line=row["new_start_line"],
            vulnerable_snippet=row["vulnerable_snippet"] or "",
            fixed_snippet=row["fixed_snippet"] or "",
            context=row["context"] or "",
        )
        pattern = build_issue_pattern(ticket, row["id"], snippet, security_judge=security_judge)
        if pattern:
            store.upsert_pattern(pattern)
            count += 1
    return {"status": "ok", "pattern_count": count, "rebuild": rebuild}


def command_clear_kb(store: KnowledgeStore, include_judgements: bool = False) -> dict[str, Any]:
    store.clear_issue_patterns()
    if include_judgements:
        store.clear_snippet_judgements()
    return {"status": "ok", "cleared": {"issue_patterns": True, "snippet_judgements": include_judgements}}


def command_judge_tasks(
    store: KnowledgeStore,
    *,
    limit: int,
    ticket_id: str | None = None,
    rejudge: bool = False,
) -> dict[str, Any]:
    candidate_limit = max(limit * 10, 50)
    rows = [
        row
        for row in store.list_judgement_tasks(limit=candidate_limit, ticket_id=ticket_id, rejudge=rejudge)
        if has_logical_code_change(row.get("vulnerable_snippet") or "", row.get("fixed_snippet") or "")
    ][: max(1, limit)]
    return {
        "status": "ok",
        "tasks": [_judgement_task_payload(row) for row in rows],
        "allowed_issue_types": [rule[0] for rule in ISSUE_RULES] + ["通用安全缺陷"],
        "output_schema": {
            "snippet_id": "string",
            "has_security_issue": "boolean",
            "issue_type": "allowed issue type",
            "confidence": "number from 0 to 1",
            "rationale": "short Chinese reason",
            "fix_advice": "optional Chinese fix advice",
        },
    }


def command_apply_judgement(args: argparse.Namespace, store: KnowledgeStore) -> dict[str, Any]:
    judgements = _load_judgement_inputs(args)
    results = [_apply_single_judgement(store, judgement) for judgement in judgements]
    return {"status": "ok", "results": results}


class StaticSecurityJudge:
    def __init__(self, judgement: SecurityJudgement) -> None:
        self.judgement = judgement
        self.source = judgement.source

    def assess(
        self,
        ticket: DtsTicket,
        snippet: CodeSnippet,
        summary_issue_type: str | None,
    ) -> SecurityJudgement:
        return self.judgement


def _apply_single_judgement(store: KnowledgeStore, data: dict[str, Any]) -> dict[str, Any]:
    snippet_id = str(data.get("snippet_id") or "").strip()
    if not snippet_id:
        raise ValueError("judgement.snippet_id is required")
    row = store.get_snippet_task(snippet_id)
    if not row:
        raise ValueError(f"Unknown snippet_id: {snippet_id}")

    has_issue = bool(data.get("has_security_issue"))
    issue_type = _normalize_issue_type(str(data.get("issue_type") or "通用安全缺陷"))
    confidence = _clamp_float(data.get("confidence", 0.0))
    rationale = str(data.get("rationale") or "").strip()
    fix_advice = str(data.get("fix_advice") or "").strip()
    source = str(data.get("source") or "opencode-agent").strip() or "opencode-agent"

    if not has_logical_code_change(row.get("vulnerable_snippet") or "", row.get("fixed_snippet") or ""):
        store.upsert_snippet_judgement(
            snippet_id=snippet_id,
            ticket_id=row["ticket_id"],
            has_security_issue=False,
            issue_type=issue_type,
            confidence=0.0,
            rationale="Skipped because old/new snippets have no logical code change.",
            fix_advice="",
            source=source,
            raw=data,
        )
        store.delete_pattern_by_snippet(snippet_id)
        return {
            "snippet_id": snippet_id,
            "ticket_id": row["ticket_id"],
            "has_security_issue": False,
            "pattern_id": "",
            "status": "skipped_no_logical_change",
        }

    store.upsert_snippet_judgement(
        snippet_id=snippet_id,
        ticket_id=row["ticket_id"],
        has_security_issue=has_issue,
        issue_type=issue_type,
        confidence=confidence,
        rationale=rationale,
        fix_advice=fix_advice,
        source=source,
        raw=data,
    )
    store.delete_pattern_by_snippet(snippet_id)

    if not has_issue or confidence < 0.5:
        return {
            "snippet_id": snippet_id,
            "ticket_id": row["ticket_id"],
            "has_security_issue": has_issue,
            "pattern_id": "",
            "status": "judgement_saved_no_pattern",
        }

    ticket = DtsTicket(
        ticket_id=row["ticket_id"],
        serial_no=row.get("serial_no") or "",
        summary=row.get("summary") or "",
        severity=row.get("severity") or "",
        created_at=row.get("ticket_created_at") or "",
        reporter=row.get("reporter") or "",
    )
    snippet = CodeSnippet(
        ticket_id=row["ticket_id"],
        pr_url=row["pr_url"],
        file_path=row["file_path"],
        old_start_line=row["old_start_line"],
        new_start_line=row["new_start_line"],
        vulnerable_snippet=row["vulnerable_snippet"] or "",
        fixed_snippet=row["fixed_snippet"] or "",
        context=row["context"] or "",
    )
    judgement = SecurityJudgement(
        has_security_issue=True,
        issue_type=issue_type,
        confidence=confidence,
        rationale=rationale,
        source=source,
    )
    pattern = build_issue_pattern(ticket, snippet_id, snippet, security_judge=StaticSecurityJudge(judgement))
    if pattern is None:
        return {
            "snippet_id": snippet_id,
            "ticket_id": row["ticket_id"],
            "has_security_issue": has_issue,
            "pattern_id": "",
            "status": "judgement_saved_pattern_skipped",
        }
    if fix_advice:
        pattern = replace(pattern, fix_advice=fix_advice)
    pattern_id = store.upsert_pattern(pattern)
    return {
        "snippet_id": snippet_id,
        "ticket_id": row["ticket_id"],
        "has_security_issue": True,
        "issue_type": pattern.issue_type,
        "pattern_id": pattern_id,
        "status": "pattern_upserted",
    }


def _judgement_task_payload(row: dict[str, Any]) -> dict[str, Any]:
    summary_issue = classify_summary_issue(row.get("summary") or "")
    return {
        "snippet_id": row["id"],
        "ticket_id": row["ticket_id"],
        "dts_summary": row.get("summary") or "",
        "summary_issue_type": summary_issue[0] if summary_issue else "",
        "severity": row.get("severity") or "",
        "pr_url": row.get("pr_url") or "",
        "file_path": row.get("file_path") or "",
        "old_start_line": row.get("old_start_line"),
        "new_start_line": row.get("new_start_line"),
        "context": row.get("context") or "",
        "vulnerable_snippet": row.get("vulnerable_snippet") or "",
        "fixed_snippet": row.get("fixed_snippet") or "",
        "existing_judgement": {
            "has_security_issue": bool(row.get("has_security_issue"))
            if row.get("has_security_issue") is not None
            else None,
            "issue_type": row.get("judged_issue_type") or "",
            "confidence": row.get("judged_confidence"),
            "rationale": row.get("judged_rationale") or "",
            "fix_advice": row.get("judged_fix_advice") or "",
            "source": row.get("judged_source") or "",
            "judged_at": row.get("judged_at") or "",
        },
        "decision_policy": [
            "Use DTS summary only as a candidate issue type.",
            "Judge whether the vulnerable_snippet and context themselves still show a plausible security issue.",
            "If code evidence agrees with the DTS summary issue type, use the summary issue type.",
            "If code evidence disagrees, use the issue type supported by code evidence.",
            "If code evidence is insufficient, set has_security_issue=false so it will not enter the knowledge base.",
        ],
    }


def _load_judgement_inputs(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
        loaded = json.loads(raw)
    elif args.stdin:
        loaded = json.loads(sys.stdin.read())
    else:
        if args.snippet_id is None or args.has_security_issue is None:
            raise ValueError("--snippet-id and --has-security-issue are required when not using --file or --stdin")
        loaded = {
            "snippet_id": args.snippet_id,
            "has_security_issue": args.has_security_issue,
            "issue_type": args.issue_type or "通用安全缺陷",
            "confidence": args.confidence if args.confidence is not None else 0.0,
            "rationale": args.rationale or "",
            "fix_advice": args.fix_advice or "",
            "source": args.source or "opencode-agent",
        }
    if isinstance(loaded, dict):
        return [loaded]
    if isinstance(loaded, list) and all(isinstance(item, dict) for item in loaded):
        return loaded
    raise ValueError("judgement input must be a JSON object or a list of JSON objects")


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _clamp_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _normalize_issue_type(issue_type: str) -> str:
    allowed = {rule[0] for rule in ISSUE_RULES} | {"通用安全缺陷"}
    return issue_type if issue_type in allowed else "通用安全缺陷"


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
