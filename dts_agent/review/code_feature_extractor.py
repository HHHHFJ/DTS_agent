from __future__ import annotations

import subprocess
from pathlib import Path

from dts_agent.models import CodeChunk


SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".py",
    ".go",
    ".rs",
    ".java",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".sh",
    ".ps1",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
}

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "data",
    "reports",
    "dist",
    "build",
}


def extract_repo_chunks(path: str | Path, window_lines: int = 80) -> list[CodeChunk]:
    root = Path(path).resolve()
    chunks: list[CodeChunk] = []
    for source in _iter_source_files(root):
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = text.splitlines()
        for start in range(0, len(lines), window_lines):
            window = lines[start : start + window_lines]
            body = "\n".join(window).strip()
            if not body:
                continue
            chunks.append(
                CodeChunk(
                    file_path=source,
                    start_line=start + 1,
                    end_line=start + len(window),
                    text=body,
                )
            )
    return chunks


def extract_diff_chunks(path: str | Path, base: str = "HEAD~1") -> list[CodeChunk]:
    root = Path(path).resolve()
    try:
        completed = subprocess.run(
            ["git", "diff", "--unified=20", base],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return extract_repo_chunks(root)
    if completed.returncode != 0 or not completed.stdout.strip():
        return extract_repo_chunks(root)
    return _chunks_from_diff(root, completed.stdout)


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            yield path


def _chunks_from_diff(root: Path, diff_text: str) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    file_path: Path | None = None
    new_line = 0
    start_line = 0
    current: list[str] = []

    def flush() -> None:
        nonlocal current, start_line
        if file_path is not None and current:
            body = "\n".join(current).strip()
            if body:
                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        start_line=start_line or 1,
                        end_line=(start_line or 1) + len(current) - 1,
                        text=body,
                    )
                )
        current = []
        start_line = 0

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            flush()
            file_path = _path_from_diff(raw_line, root)
            continue
        if raw_line.startswith("@@"):
            flush()
            new_line = _new_start_from_hunk(raw_line)
            start_line = new_line
            continue
        if file_path is None:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            if not start_line:
                start_line = new_line
            current.append(raw_line[1:])
            new_line += 1
        elif raw_line.startswith(" ") and current:
            current.append(raw_line[1:])
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        elif raw_line.startswith(" "):
            new_line += 1
    flush()
    return chunks or extract_repo_chunks(root)


def _path_from_diff(line: str, root: Path) -> Path:
    parts = line.split()
    if len(parts) >= 4:
        value = parts[3]
        rel = value[2:] if value.startswith("b/") else value
        return root / rel
    return root


def _new_start_from_hunk(line: str) -> int:
    parts = line.split()
    if len(parts) < 3:
        return 1
    value = parts[2].lstrip("+")
    try:
        return int(value.split(",", 1)[0])
    except ValueError:
        return 1
