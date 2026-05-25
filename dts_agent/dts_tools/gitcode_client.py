from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from dts_agent.code_change import has_logical_code_change
from dts_agent.models import CodeSnippet, PrLink


class GitCodeFetchError(RuntimeError):
    pass


class GitCodeClient:
    def __init__(
        self,
        api_base: str,
        token: str | None = None,
        timeout: int = 30,
        codehub_token: str | None = None,
        repo_token: str | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.codehub_token = codehub_token
        self.repo_token = repo_token

    def fetch_pr_snippets(self, link: PrLink) -> list[CodeSnippet]:
        errors: list[str] = []
        token = self._token_for_link(link)
        for url in self._candidate_urls(link):
            try:
                payload = self._get(url, token=token)
            except GitCodeFetchError as exc:
                errors.append(str(exc))
                continue

            snippets = self._parse_payload(link, payload)
            if snippets:
                return snippets
        raise GitCodeFetchError("; ".join(errors) or f"No snippets returned for {link.pr_url}")

    def _candidate_urls(self, link: PrLink) -> list[str]:
        if link.provider == "gitcode" or link.host.endswith("gitcode.com"):
            return self._gitcode_candidate_urls(link)
        if link.provider == "codehub":
            return self._codehub_candidate_urls(link)
        return self._generic_candidate_urls(link)

    def _gitcode_candidate_urls(self, link: PrLink) -> list[str]:
        owner = _quote_path(link.owner)
        repo = _quote_path(link.repo)
        number = _quote_path(link.pr_number)
        candidates = [
            f"{self.api_base}/repos/{owner}/{repo}/pulls/{number}/files.json",
            f"{self.api_base}/repos/{owner}/{repo}/pulls/{number}/files",
            f"https://gitcode.com/{owner}/{repo}/pull/{number}.diff",
            f"https://gitcode.com/{owner}/{repo}/pulls/{number}.diff",
        ]
        return _unique(candidates)

    def _codehub_candidate_urls(self, link: PrLink) -> list[str]:
        repo_path = link.repo_path or f"{link.owner}/{link.repo}"
        project_id = _quote_project_path(repo_path)
        number = _quote_path(link.pr_number)
        base = _clean_change_url(link.original_url or link.pr_url)
        candidates: list[str] = []
        if link.change_type == "merge_requests":
            candidates.extend(
                [
                    f"https://{link.host}/api/v4/projects/{project_id}/merge_requests/{number}/changes",
                    f"https://{link.host}/api/v4/projects/{project_id}/merge_requests/{number}/diffs",
                ]
            )
        candidates.extend(_diff_candidates(base))
        return _unique(candidates)

    def _generic_candidate_urls(self, link: PrLink) -> list[str]:
        return _unique(_diff_candidates(_clean_change_url(link.original_url or link.pr_url)))

    def _get(self, url: str, token: str | None = None) -> bytes:
        request = urllib.request.Request(url)
        request.add_header("Accept", "application/json, text/plain, */*")
        request.add_header("User-Agent", "dts-agent/0.1")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
            request.add_header("PRIVATE-TOKEN", token)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise GitCodeFetchError(f"HTTP {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            raise GitCodeFetchError(f"{exc.reason} for {url}") from exc

    def _parse_payload(self, link: PrLink, payload: bytes) -> list[CodeSnippet]:
        text = payload.decode("utf-8", errors="replace")
        stripped = text.lstrip()
        if stripped.startswith(("[", "{")):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return parse_unified_diff(link, text)
            snippets = parse_gitcode_json(link, data)
            if snippets:
                return snippets
        return parse_unified_diff(link, text)

    def _token_for_link(self, link: PrLink) -> str | None:
        host_token = _host_token(link.host)
        if host_token:
            return host_token
        if link.provider == "gitcode":
            return self.token
        if link.provider == "codehub":
            return self.codehub_token or self.repo_token
        return self.repo_token


def parse_gitcode_json(link: PrLink, data: object) -> list[CodeSnippet]:
    files = _extract_files(data)
    snippets: list[CodeSnippet] = []
    for file_item in files:
        if not isinstance(file_item, dict):
            continue
        file_path = str(
            file_item.get("filename")
            or file_item.get("new_path")
            or file_item.get("old_path")
            or file_item.get("path")
            or ""
        )

        line_diff = file_item.get("diff") or file_item.get("lines")
        if isinstance(line_diff, list):
            snippets.extend(_parse_line_objects(link, file_path, line_diff))
            continue

        patch = file_item.get("patch") or file_item.get("diff") or file_item.get("content")
        if isinstance(patch, dict):
            patch = patch.get("diff") or patch.get("patch")
        if isinstance(patch, str) and patch.strip():
            snippets.extend(parse_unified_diff(link, _ensure_file_header(file_path, patch)))
    return snippets


def parse_unified_diff(link: PrLink, diff_text: str) -> list[CodeSnippet]:
    snippets: list[CodeSnippet] = []
    file_path = ""
    old_line: int | None = None
    new_line: int | None = None
    hunk_old_start: int | None = None
    hunk_new_start: int | None = None
    removed: list[str] = []
    added: list[str] = []
    context: list[str] = []

    def flush() -> None:
        nonlocal removed, added, context, hunk_old_start, hunk_new_start
        if not file_path or (not removed and not added):
            removed, added, context = [], [], []
            return
        snippet = CodeSnippet(
            ticket_id=link.ticket_id,
            pr_url=link.pr_url,
            file_path=file_path,
            old_start_line=hunk_old_start,
            new_start_line=hunk_new_start,
            vulnerable_snippet="\n".join(removed).strip(),
            fixed_snippet="\n".join(added).strip(),
            context="\n".join(context[-12:]).strip(),
        )
        if has_logical_code_change(snippet.vulnerable_snippet, snippet.fixed_snippet):
            snippets.append(snippet)
        removed, added, context = [], [], []

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            flush()
            file_path = _file_from_diff_header(raw_line) or file_path
            continue
        if raw_line.startswith("+++ "):
            target = raw_line[4:].strip()
            if target != "/dev/null":
                file_path = target[2:] if target.startswith("b/") else target
            continue
        if raw_line.startswith("@@"):
            flush()
            old_line, new_line = _parse_hunk_header(raw_line)
            hunk_old_start, hunk_new_start = old_line, new_line
            continue
        if old_line is None or new_line is None:
            continue
        if raw_line.startswith("--- "):
            continue
        if raw_line.startswith("-"):
            removed.append(raw_line[1:])
            old_line += 1
        elif raw_line.startswith("+"):
            added.append(raw_line[1:])
            new_line += 1
        elif raw_line.startswith(" "):
            context.append(raw_line[1:])
            old_line += 1
            new_line += 1
    flush()
    return [snippet for snippet in snippets if snippet.vulnerable_snippet or snippet.fixed_snippet]


def _parse_line_objects(link: PrLink, file_path: str, rows: list[object]) -> list[CodeSnippet]:
    snippets: list[CodeSnippet] = []
    removed: list[str] = []
    added: list[str] = []
    old_start: int | None = None
    new_start: int | None = None

    def flush() -> None:
        nonlocal removed, added, old_start, new_start
        if removed or added:
            snippet = CodeSnippet(
                ticket_id=link.ticket_id,
                pr_url=link.pr_url,
                file_path=file_path,
                old_start_line=old_start,
                new_start_line=new_start,
                vulnerable_snippet="\n".join(removed).strip(),
                fixed_snippet="\n".join(added).strip(),
            )
            if has_logical_code_change(snippet.vulnerable_snippet, snippet.fixed_snippet):
                snippets.append(snippet)
        removed, added, old_start, new_start = [], [], None, None

    for row in rows:
        if not isinstance(row, dict):
            continue
        line_type = str(row.get("type") or row.get("line_type") or row.get("tag") or "").lower()
        content = str(row.get("content") or row.get("text") or row.get("line") or "")
        if line_type in {"old", "del", "delete", "removed", "-"}:
            old_start = old_start or _to_int(row.get("old_line") or row.get("old_lineno"))
            removed.append(content)
        elif line_type in {"new", "add", "added", "+"}:
            new_start = new_start or _to_int(row.get("new_line") or row.get("new_lineno"))
            added.append(content)
        elif removed or added:
            flush()
    flush()
    return snippets


def _extract_files(data: object) -> list[object]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("files", "data", "diffs", "changes"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = _extract_files(value)
                if nested:
                    return nested
    return []


def _ensure_file_header(file_path: str, patch: str) -> str:
    if patch.startswith("diff --git"):
        return patch
    if patch.startswith("@@"):
        return f"diff --git a/{file_path} b/{file_path}\n--- a/{file_path}\n+++ b/{file_path}\n{patch}"
    return patch


def _file_from_diff_header(line: str) -> str | None:
    parts = line.split()
    if len(parts) >= 4:
        target = parts[3]
        return target[2:] if target.startswith("b/") else target
    return None


def _parse_hunk_header(line: str) -> tuple[int, int]:
    # Format: @@ -10,7 +10,8 @@ optional context
    parts = line.split()
    old_start = _range_start(parts[1]) if len(parts) > 1 else 0
    new_start = _range_start(parts[2]) if len(parts) > 2 else 0
    return old_start, new_start


def _range_start(value: str) -> int:
    value = value.lstrip("+-")
    start = value.split(",", 1)[0]
    try:
        return int(start)
    except ValueError:
        return 0


def _quote_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _quote_project_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _clean_change_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip().rstrip("/")
    path = parsed.path.rstrip("/")
    if path.endswith(".diff"):
        path = path.removesuffix(".diff")
    if path.endswith(".patch"):
        path = path.removesuffix(".patch")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _diff_candidates(base_url: str) -> list[str]:
    if not base_url:
        return []
    base_url = base_url.rstrip("/")
    return [
        f"{base_url}.diff",
        f"{base_url}.patch",
        f"{base_url}/diffs",
    ]


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _host_token(host: str) -> str | None:
    key = "DTS_REPO_TOKEN_" + "".join(ch if ch.isalnum() else "_" for ch in host.upper()).strip("_")
    return os.environ.get(key)


def _to_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
