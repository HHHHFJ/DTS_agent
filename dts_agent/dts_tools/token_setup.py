from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable

from dts_agent.models import PrLink


@dataclass
class TokenRequirement:
    host: str
    provider: str
    env_var: str
    fallback_env_vars: list[str] = field(default_factory=list)
    ticket_ids: set[str] = field(default_factory=set)
    pr_urls: set[str] = field(default_factory=set)

    def to_json(self) -> dict[str, object]:
        return {
            "host": self.host,
            "provider": self.provider,
            "env_var": self.env_var,
            "fallback_env_vars": self.fallback_env_vars,
            "ticket_ids": sorted(self.ticket_ids),
            "pr_urls": sorted(self.pr_urls),
        }


def collect_missing_token_requirements(links: Iterable[PrLink]) -> list[TokenRequirement]:
    requirements: dict[tuple[str, str], TokenRequirement] = {}
    for link in links:
        env_vars = token_env_vars_for_link(link)
        if not env_vars or any(os.environ.get(name) for name in env_vars):
            continue
        key = (link.host, link.provider)
        item = requirements.get(key)
        if item is None:
            item = TokenRequirement(
                host=link.host,
                provider=link.provider,
                env_var=env_vars[0],
                fallback_env_vars=env_vars[1:],
            )
            requirements[key] = item
        item.ticket_ids.add(link.ticket_id)
        item.pr_urls.add(link.pr_url)
    return list(requirements.values())


def token_env_vars_for_link(link: PrLink) -> list[str]:
    host_env = host_token_env_name(link.host)
    if link.provider == "codehub":
        return [host_env, "CODEHUB_ACCESS_TOKEN", "DTS_REPO_ACCESS_TOKEN", "REPO_ACCESS_TOKEN"]
    return []


def host_token_env_name(host: str) -> str:
    return "DTS_REPO_TOKEN_" + "".join(ch if ch.isalnum() else "_" for ch in host.upper()).strip("_")


def apply_token_values(values: dict[str, str], persist_user_env: bool = False) -> None:
    for name, token in values.items():
        token = token.strip()
        if not name or not token:
            continue
        os.environ[name] = token
        if persist_user_env:
            _persist_user_env(name, token)


def prompt_for_missing_tokens(requirements: list[TokenRequirement]) -> dict[str, str]:
    if not requirements:
        return {}
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception as exc:  # noqa: BLE001 - GUI availability differs by Python install.
        raise RuntimeError(f"Cannot open token setup dialog: {exc}") from exc

    result: dict[str, str] = {}
    root = tk.Tk()
    root.title("DTS Agent Token Setup")
    root.geometry("860x420")
    root.resizable(True, True)

    header = tk.Label(
        root,
        text=(
            "DTS Agent 已解析完所有 PR/MR URL，但以下代码仓需要访问 Token。\n"
            "请输入 Token 后继续，本次同步会立即使用；勾选后也会写入 Windows 用户环境变量。"
        ),
        justify="left",
        anchor="w",
    )
    header.pack(fill="x", padx=14, pady=(12, 8))

    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=14, pady=4)

    entries: dict[str, tk.Entry] = {}
    for row, requirement in enumerate(requirements):
        label_text = (
            f"{requirement.host} ({requirement.provider})\n"
            f"变量: {requirement.env_var}\n"
            f"问题单: {', '.join(sorted(requirement.ticket_ids))}"
        )
        tk.Label(frame, text=label_text, justify="left", anchor="w").grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=8,
        )
        entry = tk.Entry(frame, show="*", width=72)
        entry.grid(row=row, column=1, sticky="ew", pady=8)
        entries[requirement.env_var] = entry

    frame.columnconfigure(1, weight=1)

    persist_var = tk.BooleanVar(value=True)
    tk.Checkbutton(
        root,
        text="写入当前 Windows 用户环境变量，供后续 OpenCode 会话使用",
        variable=persist_var,
    ).pack(anchor="w", padx=14, pady=(4, 6))

    def on_ok() -> None:
        missing = []
        for env_var, entry in entries.items():
            token = entry.get().strip()
            if token:
                result[env_var] = token
            else:
                missing.append(env_var)
        if missing:
            messagebox.showerror("Token 未填写", "请填写这些变量:\n" + "\n".join(missing))
            return
        result["__persist_user_env__"] = "1" if persist_var.get() else "0"
        root.destroy()

    def on_cancel() -> None:
        root.destroy()

    button_row = tk.Frame(root)
    button_row.pack(fill="x", padx=14, pady=(0, 12))
    tk.Button(button_row, text="取消", command=on_cancel, width=12).pack(side="right", padx=(8, 0))
    tk.Button(button_row, text="保存并继续", command=on_ok, width=14).pack(side="right")

    root.mainloop()
    persist = result.pop("__persist_user_env__", "0") == "1"
    apply_token_values(result, persist_user_env=persist)
    return result


def _persist_user_env(name: str, value: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            5000,
            None,
        )
    except Exception:
        return
