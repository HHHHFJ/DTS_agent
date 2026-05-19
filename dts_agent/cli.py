from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dts_agent.config import ensure_runtime_dirs, load_config
from dts_agent.dts_tools.excel_loader import ExcelLoadError, load_dts_excel
from dts_agent.dts_tools.fetch_tool import DtsFetchError, run_fetch_script
from dts_agent.dts_tools.gitcode_client import GitCodeClient, GitCodeFetchError
from dts_agent.dts_tools.pr_parser import parse_ticket_pr_links
from dts_agent.extraction import build_issue_pattern
from dts_agent.kb.sqlite_store import KnowledgeStore
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

    sync = sub.add_parser("sync", help="Run DTS fetch script and import the generated Excel file.")
    sync.add_argument("--fetch-script", help="Path to dts_data_fetch.py.")
    sync.add_argument("--file", help="Import an existing Excel/CSV instead of running the fetch script.")
    sync.add_argument("--mode", default="manual", choices=["manual", "scheduled"])
    sync.add_argument("--skip-fetch-pr", action="store_true", help="Only import tickets and PR links.")
    sync.add_argument("--force", action="store_true", help="Reserved for callers that want explicit manual refresh.")
    sync.add_argument("--json", action="store_true")

    import_excel = sub.add_parser("import-excel", help="Import a DTS Excel/CSV file.")
    import_excel.add_argument("--file", required=True)
    import_excel.add_argument("--skip-fetch-pr", action="store_true")
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
    build_kb.add_argument("--json", action="store_true")

    query = sub.add_parser("query", help="Query the security knowledge base.")
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--json", action="store_true")

    review_repo_parser = sub.add_parser("review-repo", help="Review a repository against the DTS knowledge base.")
    review_repo_parser.add_argument("--path", default=".")
    review_repo_parser.add_argument("--min-confidence", type=float)
    review_repo_parser.add_argument("--json", action="store_true")

    review_diff_parser = sub.add_parser("review-diff", help="Review current git diff against the DTS knowledge base.")
    review_diff_parser.add_argument("--path", default=".")
    review_diff_parser.add_argument("--base", default="HEAD~1")
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
    if args.command == "sync":
        return command_sync(args, config, store)
    if args.command == "import-excel":
        return command_import_excel(args.file, not args.skip_fetch_pr, config, store)
    if args.command == "parse-pr-urls":
        return command_parse_pr_urls(args, store)
    if args.command == "fetch-pr-diff":
        return command_fetch_pr_diff(args, config)
    if args.command == "build-kb":
        return command_build_kb(store)
    if args.command == "query":
        return {"status": "ok", "results": store.search_patterns(args.query, args.limit)}
    if args.command == "review-repo":
        min_confidence = args.min_confidence if args.min_confidence is not None else config.review_min_confidence
        review_id, findings = review_repo(store, args.path, min_confidence=min_confidence)
        return findings_to_json(review_id, findings)
    if args.command == "review-diff":
        min_confidence = args.min_confidence if args.min_confidence is not None else config.review_min_confidence
        review_id, findings = review_diff(store, args.path, base=args.base, min_confidence=min_confidence)
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

    result = command_import_excel(str(excel_path), not args.skip_fetch_pr, config, store)
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
) -> dict[str, Any]:
    tickets = load_dts_excel(excel_path)
    client = GitCodeClient(config.gitcode_api_base, config.gitcode_token, config.gitcode_timeout)
    stats = {
        "status": "ok",
        "excel_path": str(Path(excel_path).resolve()),
        "ticket_count": len(tickets),
        "pr_link_count": 0,
        "snippet_count": 0,
        "pattern_count": 0,
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
                pattern = build_issue_pattern(ticket, snippet_id, snippet)
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


def command_build_kb(store: KnowledgeStore) -> dict[str, Any]:
    count = 0
    for row in store.list_snippets_without_patterns():
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
        pattern = build_issue_pattern(ticket, row["id"], snippet)
        if pattern:
            store.upsert_pattern(pattern)
            count += 1
    return {"status": "ok", "pattern_count": count}


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
