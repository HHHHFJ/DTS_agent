from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import ParseResult, urlparse, urlunparse

from dts_agent.models import PrLink


URL_RE = re.compile(r"https?://[^\s'\",，\]\)]+", re.IGNORECASE)
CHANGE_MARKERS = ("pull", "pulls", "merge_requests")


@dataclass(frozen=True)
class RepoHostRule:
    host: str
    provider: str


class PrUrlParseError(ValueError):
    pass


def parse_pr_url_list(raw_value: object) -> list[str]:
    if raw_value is None:
        return []

    text = str(raw_value).strip()
    if not text or text.lower() in {"nan", "none", "null", "[]"}:
        return []

    try:
        loaded = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return URL_RE.findall(text)

    if isinstance(loaded, str):
        return [loaded] if loaded.startswith(("http://", "https://")) else URL_RE.findall(loaded)
    if isinstance(loaded, (list, tuple, set)):
        urls: list[str] = []
        for item in loaded:
            if item is None:
                continue
            item_text = str(item).strip()
            if item_text.startswith(("http://", "https://")):
                urls.append(item_text)
            else:
                urls.extend(URL_RE.findall(item_text))
        return urls

    return URL_RE.findall(text)


def normalize_pr_url(ticket_id: str, url: str) -> PrLink:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if not parsed.scheme.startswith("http") or not host:
        raise PrUrlParseError(f"Invalid PR URL: {url}")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    marker, marker_index = _find_change_marker(parts)
    if marker_index < 1 or marker_index + 1 >= len(parts):
        raise PrUrlParseError(f"Cannot parse repository change URL: {url}")

    repo_parts = parts[:marker_index]
    if repo_parts and repo_parts[-1] == "-":
        repo_parts = repo_parts[:-1]
    if len(repo_parts) < 2:
        raise PrUrlParseError(f"Cannot parse repository owner/repo from URL: {url}")

    pr_number = _extract_number(parts[marker_index + 1])
    if not pr_number:
        raise PrUrlParseError(f"Invalid PR/MR number in URL: {url}")

    owner = "/".join(repo_parts[:-1])
    repo = repo_parts[-1]
    repo_path = "/".join(repo_parts)
    provider = provider_for_host(host)
    change_type = "merge_requests" if marker == "merge_requests" else "pull"
    canonical = _canonical_url(parsed, host, repo_path, pr_number, provider, change_type)
    return PrLink(
        ticket_id=ticket_id,
        pr_url=canonical,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        host=host,
        provider=provider,
        change_type=change_type,
        repo_path=repo_path,
        original_url=url.strip(),
    )


def normalize_gitcode_pr_url(ticket_id: str, url: str) -> PrLink:
    link = normalize_pr_url(ticket_id, url)
    if link.provider != "gitcode":
        raise PrUrlParseError(f"Not a GitCode URL: {url}")
    return link


def parse_ticket_pr_links(ticket_id: str, raw_value: object) -> tuple[list[PrLink], list[str]]:
    links: list[PrLink] = []
    errors: list[str] = []
    seen: set[str] = set()

    for url in parse_pr_url_list(raw_value):
        try:
            link = normalize_pr_url(ticket_id, url)
        except PrUrlParseError as exc:
            errors.append(str(exc))
            continue
        key = f"{link.host}/{link.repo_path}/{link.change_type}/{link.pr_number}"
        if key in seen:
            continue
        seen.add(key)
        links.append(link)

    return links, errors


def provider_for_host(host: str) -> str:
    host = _clean_host(host)
    for rule in load_repo_host_rules():
        if _host_matches(host, rule.host):
            return rule.provider
    if host == "gitcode.com" or host.endswith(".gitcode.com"):
        return "gitcode"
    if "codehub" in host and host.endswith("huawei.com"):
        return "codehub"
    return "generic"


def load_repo_host_rules() -> list[RepoHostRule]:
    rules: list[RepoHostRule] = []
    json_text = os.environ.get("DTS_REPO_HOSTS_JSON", "").strip()
    if json_text:
        try:
            loaded = json.loads(json_text)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            for host, value in loaded.items():
                provider = value.get("provider") if isinstance(value, dict) else value
                if host and provider:
                    rules.append(RepoHostRule(_clean_host(str(host)), str(provider).lower()))

    pairs = os.environ.get("DTS_REPO_HOSTS", "").strip()
    for item in [part.strip() for part in pairs.split(",") if part.strip()]:
        if "=" in item:
            host, provider = item.split("=", 1)
        elif ":" in item:
            host, provider = item.split(":", 1)
        else:
            continue
        if host.strip() and provider.strip():
            rules.append(RepoHostRule(_clean_host(host), provider.strip().lower()))

    return rules


def _find_change_marker(parts: list[str]) -> tuple[str, int]:
    for index, part in enumerate(parts):
        if part in CHANGE_MARKERS:
            return part, index
    return "", -1


def _extract_number(value: str) -> str:
    match = re.match(r"(\d+)", value)
    return match.group(1) if match else ""


def _canonical_url(
    parsed: ParseResult,
    host: str,
    repo_path: str,
    number: str,
    provider: str,
    change_type: str,
) -> str:
    if provider == "gitcode":
        return f"https://gitcode.com/{repo_path}/pull/{number}"
    clean_path = parsed.path.rstrip("/")
    if clean_path.endswith(".diff"):
        clean_path = clean_path.removesuffix(".diff")
    return urlunparse((parsed.scheme, host, clean_path, "", "", ""))


def _clean_host(host: str) -> str:
    return host.lower().split(":", 1)[0].strip()


def _host_matches(host: str, pattern: str) -> bool:
    pattern = _clean_host(pattern)
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    return host == pattern
