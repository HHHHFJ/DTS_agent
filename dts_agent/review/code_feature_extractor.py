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


def extract_repo_chunks(
    path: str | Path,
    window_lines: int = 80,
    exclude_dirs: list[str] | tuple[str, ...] | None = None,
) -> list[CodeChunk]:
    root = Path(path).resolve()
    chunks: list[CodeChunk] = []
    ignored_dirs = _merged_ignored_dirs(exclude_dirs)
    for source in _iter_source_files(root, ignored_dirs):
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


def extract_diff_chunks(
    path: str | Path,
    base: str = "HEAD~1",
    exclude_dirs: list[str] | tuple[str, ...] | None = None,
) -> list[CodeChunk]:
    root = Path(path).resolve()
    ignored_dirs = _merged_ignored_dirs(exclude_dirs)
    try:
        completed = subprocess.run(
            ["git", "diff", "--unified=20", base],
            cwd=str(root),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return extract_repo_chunks(root, exclude_dirs=exclude_dirs)
    if completed.returncode != 0 or not completed.stdout.strip():
        return extract_repo_chunks(root, exclude_dirs=exclude_dirs)
    return _chunks_from_diff(root, completed.stdout, ignored_dirs)


def _iter_source_files(root: Path, ignored_dirs: set[str]):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _is_excluded(path, root, ignored_dirs):
            continue
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            yield path


def _chunks_from_diff(root: Path, diff_text: str, ignored_dirs: set[str]) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    file_path: Path | None = None
    skip_file = False
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
            skip_file = _is_excluded(file_path, root, ignored_dirs)
            continue
        if skip_file:
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
    return chunks or extract_repo_chunks(root, exclude_dirs=tuple(ignored_dirs - IGNORED_DIRS))


def _merged_ignored_dirs(exclude_dirs: list[str] | tuple[str, ...] | None) -> set[str]:
    merged = set(IGNORED_DIRS)
    for item in exclude_dirs or ():
        normalized = item.strip().strip("/\\")
        if normalized:
            merged.add(normalized.replace("\\", "/"))
            merged.add(Path(normalized).name)
    return merged


def _is_excluded(path: Path, root: Path, ignored_dirs: set[str]) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = path
    parts = {part.replace("\\", "/") for part in relative.parts}
    relative_text = relative.as_posix()
    for ignored in ignored_dirs:
        if ignored in parts or relative_text == ignored or relative_text.startswith(f"{ignored}/"):
            return True
    return False


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
