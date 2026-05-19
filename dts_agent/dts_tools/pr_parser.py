from __future__ import annotations

import ast
import re
from urllib.parse import urlparse

from dts_agent.models import PrLink


URL_RE = re.compile(r"https?://[^\s'\",，\]\)]+", re.IGNORECASE)


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


def normalize_gitcode_pr_url(ticket_id: str, url: str) -> PrLink:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if "gitcode.com" not in host:
        raise PrUrlParseError(f"Not a GitCode URL: {url}")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    marker_index = -1
    for marker in ("pull", "pulls", "merge_requests"):
        if marker in parts:
            marker_index = parts.index(marker)
            break
    if marker_index < 2 or marker_index + 1 >= len(parts):
        raise PrUrlParseError(f"Cannot parse GitCode PR URL: {url}")

    owner = parts[marker_index - 2]
    repo = parts[marker_index - 1]
    pr_number = parts[marker_index + 1]
    if not pr_number.isdigit():
        raise PrUrlParseError(f"Invalid PR number in URL: {url}")

    canonical = f"https://gitcode.com/{owner}/{repo}/pull/{pr_number}"
    return PrLink(
        ticket_id=ticket_id,
        pr_url=canonical,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )


def parse_ticket_pr_links(ticket_id: str, raw_value: object) -> tuple[list[PrLink], list[str]]:
    links: list[PrLink] = []
    errors: list[str] = []
    seen: set[str] = set()

    for url in parse_pr_url_list(raw_value):
        try:
            link = normalize_gitcode_pr_url(ticket_id, url)
        except PrUrlParseError as exc:
            errors.append(str(exc))
            continue
        key = f"{link.owner}/{link.repo}/{link.pr_number}"
        if key in seen:
            continue
        seen.add(key)
        links.append(link)

    return links, errors
