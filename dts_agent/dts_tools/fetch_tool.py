from __future__ import annotations

import subprocess
import sys
import re
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from time import monotonic


@dataclass(frozen=True)
class FetchResult:
    exit_code: int
    excel_path: Path | None
    stdout: str
    stderr: str
    elapsed_seconds: float


class DtsFetchError(RuntimeError):
    pass


def run_fetch_script(
    script: Path,
    inbox_dir: Path,
    timeout: int = 1800,
    output_file: Path | None = None,
) -> FetchResult:
    if not script.exists():
        raise DtsFetchError(f"DTS fetch script not found: {script}")
    if output_file and output_file.suffix.lower() not in {".xlsx", ".csv"}:
        raise DtsFetchError(f"DTS fetch output file must end with .xlsx or .csv: {output_file}")

    inbox_dir.mkdir(parents=True, exist_ok=True)
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
    before = _known_excel_files(inbox_dir, script.parent, output_file.parent if output_file else None)
    start = monotonic()
    env = os.environ.copy()
    env["DTS_FETCH_OUTPUT_DIR"] = str(inbox_dir)
    env["DTS_EXCEL_OUTPUT_DIR"] = str(inbox_dir)
    if output_file:
        env["DTS_FETCH_OUTPUT_FILE"] = str(output_file)
        env["DTS_EXCEL_OUTPUT_FILE"] = str(output_file)
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(script.parent),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    elapsed = monotonic() - start
    excel_path = _path_from_output(completed.stdout, script.parent) or _newest_excel_file(
        inbox_dir, script.parent, before, output_file.parent if output_file else None
    )
    if completed.returncode == 0 and excel_path:
        excel_path = _materialize_excel_path(excel_path, inbox_dir, output_file)

    return FetchResult(
        exit_code=completed.returncode,
        excel_path=excel_path,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=elapsed,
    )


def _known_excel_files(*dirs: Path | None) -> set[Path]:
    files: set[Path] = set()
    for directory in dirs:
        if directory is None or not directory.exists():
            continue
        files.update(path.resolve() for path in directory.glob("*.xlsx"))
        files.update(path.resolve() for path in directory.glob("*.csv"))
    return files


def _newest_excel_file(
    inbox_dir: Path,
    script_dir: Path,
    before: set[Path],
    output_dir: Path | None = None,
) -> Path | None:
    candidates = _known_excel_files(inbox_dir, script_dir, output_dir)
    new_files = [path for path in candidates if path not in before]
    pool = new_files or list(candidates)
    if not pool:
        return None
    return max(pool, key=lambda path: path.stat().st_mtime)


def _path_from_output(stdout: str, script_dir: Path) -> Path | None:
    for match in re.findall(r"([A-Za-z]:\\[^\r\n]+?\.(?:xlsx|csv)|[^\s\r\n]+?\.(?:xlsx|csv))", stdout):
        path = Path(match.strip().strip('"').strip("'"))
        if not path.is_absolute():
            path = script_dir / path
        if path.exists():
            return path.resolve()
    return None


def _materialize_excel_path(excel_path: Path, inbox_dir: Path, output_file: Path | None) -> Path:
    source = excel_path.resolve()
    if output_file:
        target = output_file.resolve()
    else:
        target = (inbox_dir / source.name).resolve()
    if source == target:
        return source
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
