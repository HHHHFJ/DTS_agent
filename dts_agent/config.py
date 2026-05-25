from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    root: Path
    data_dir: Path
    inbox_dir: Path
    processed_dir: Path
    failed_dir: Path
    reports_dir: Path
    database_path: Path
    fetch_script: Path
    gitcode_api_base: str
    gitcode_token: str | None
    codehub_token: str | None
    repo_access_token: str | None
    gitcode_timeout: int
    llm_judge_command: str | None
    llm_judge_url: str | None
    llm_judge_token: str | None
    llm_judge_timeout: int
    review_min_confidence: float


def load_config(root: str | Path | None = None) -> AppConfig:
    base = Path(root or os.environ.get("DTS_AGENT_HOME") or Path.cwd()).resolve()
    data_dir = Path(os.environ.get("DTS_AGENT_DATA_DIR", base / "data")).resolve()
    database_path = Path(
        os.environ.get("DTS_AGENT_DB", data_dir / "dts_agent.sqlite")
    ).resolve()
    default_fetch_script = base / "dts_agent" / "dts_tools" / "dts_data_fetch.py"
    fetch_script = Path(os.environ.get("DTS_FETCH_SCRIPT", default_fetch_script)).resolve()

    return AppConfig(
        root=base,
        data_dir=data_dir,
        inbox_dir=Path(os.environ.get("DTS_AGENT_INBOX_DIR", data_dir / "inbox")).resolve(),
        processed_dir=(data_dir / "processed").resolve(),
        failed_dir=(data_dir / "failed").resolve(),
        reports_dir=Path(os.environ.get("DTS_AGENT_REPORTS_DIR", base / "reports")).resolve(),
        database_path=database_path,
        fetch_script=fetch_script,
        gitcode_api_base=os.environ.get(
            "GITCODE_API_BASE", "https://gitcode.com/api/v5"
        ).rstrip("/"),
        gitcode_token=os.environ.get("GITCODE_ACCESS_TOKEN"),
        codehub_token=os.environ.get("CODEHUB_ACCESS_TOKEN"),
        repo_access_token=os.environ.get("DTS_REPO_ACCESS_TOKEN") or os.environ.get("REPO_ACCESS_TOKEN"),
        gitcode_timeout=int(os.environ.get("GITCODE_TIMEOUT", "30")),
        llm_judge_command=os.environ.get("DTS_AGENT_LLM_COMMAND"),
        llm_judge_url=os.environ.get("DTS_AGENT_LLM_URL"),
        llm_judge_token=os.environ.get("DTS_AGENT_LLM_TOKEN"),
        llm_judge_timeout=int(os.environ.get("DTS_AGENT_LLM_TIMEOUT", "120")),
        review_min_confidence=float(os.environ.get("DTS_REVIEW_MIN_CONFIDENCE", "0.70")),
    )


def ensure_runtime_dirs(config: AppConfig) -> None:
    for path in (
        config.data_dir,
        config.inbox_dir,
        config.processed_dir,
        config.failed_dir,
        config.reports_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
