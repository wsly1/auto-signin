#!/usr/bin/env python3
"""
Tkinter GUI for the Skland/KuroBBS batch sign-in tool.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import traceback
import uuid
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, BooleanVar, StringVar, Tk, Toplevel
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk
from typing import Any

from signin_tool import (
    DEFAULT_SKLAND_GAMES,
    KuroClient,
    SignInError,
    SignResult,
    SklandClient,
    active_accounts,
    read_config,
    write_config,
)


def default_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("accounts.json")
    return Path(__file__).resolve().with_name("accounts.json")


def empty_account(provider: str) -> dict[str, Any]:
    if provider == "kuro":
        return {
            "provider": "kuro",
            "name": "库街区账号",
            "enabled": True,
            "token": "",
            "device_code": "",
            "game_ids": [3],
            "extra_headers": {},
        }
    return {
        "provider": "skland",
        "name": "森空岛账号",
        "enabled": True,
        "token": "",
        "cred": "",
        "cred_token": "",
        "device_id": uuid.uuid4().hex,
        "skland_games": DEFAULT_SKLAND_GAMES,
    }


def account_summary(account: dict[str, Any]) -> tuple[str, str, str, str]:
    provider = account.get("provider") or ""
    name = account.get("name") or ""
    enabled = "启用" if account.get("enabled", True) else "停用"
    if provider == "skland":
        games = account.get("skland_games") or DEFAULT_SKLAND_GAMES
        detail = ",".join(str(item) for item in games)
        detail += " / " + ("token" if account.get("token") else "cred" if account.get("cred") else "未填凭据")
    elif provider == "kuro":
        detail = f"game_ids={account.get('game_ids') or [3]}"
    else:
        detail = ""
    return provider, name, enabled, detail


def normalize_account(account: dict[str, Any]) -> dict[str, Any]:
    provider = account.get("provider")
    result = {k: v for k, v in account.items() if v not in ("", None)}
    result["provider"] = provider
    result["enabled"] = bool(account.get("enabled", True))
    if provider == "kuro":
        game_ids = result.get("game_ids") or [3]
        if isinstance(game_ids, str):
            game_ids = [int(x.strip()) for x in game_ids.split(",") if x.strip()]
        result["game_ids"] = game_ids or [3]
        extra_headers = result.get("extra_headers") or {}
        if isinstance(extra_headers, str):
            result["extra_headers"] = json.loads(extra_headers) if extra_headers.strip() else {}
    if provider == "skland":
        if not result.get("device_id"):
            result["device_id"] = uuid.uuid4().hex
        games = result.get("skland_games") or DEFAULT_SKLAND_GAMES
        if isinstance(games, str):
            games = [item.strip() for item in games.split(",") if item.strip()]
        result["skland_games"] = games or DEFAULT_SKLAND_GAMES
    return result


def parse_kuro_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("-h "):
            line = line[3:].strip().strip("'\"")
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key:
            headers[key] = value
    return headers


class KuroHeaderDialog(Toplevel):
    def __init__(self, parent: Tk) -> None:
        super().__init__(parent)
        self.title("导入库街区请求头")
        self.geometry("720x520")
        self.minsize(640, 440)
        self.result: dict[str, Any] | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        self.name_var = StringVar(value="库街区账号")
        self.game_ids_var = StringVar(value="3")

        ttk.Label(self, text="备注").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        ttk.Entry(self, textvariable=self.name_var).grid(row=1, column=0, sticky="ew", padx=10)
        ttk.Label(self, text="game_ids：鸣潮填 3，战双填 2，两个都签填 2,3").grid(
            row=2, column=0, sticky="w", padx=10, pady=(10, 4)
        )
        ttk.Entry(self, textvariable=self.game_ids_var).grid(row=3, column=0, sticky="ew", padx=10)
        ttk.Label(self, text="把 Edge 开发者工具里 api.kurobbs.com 请求的 Request Headers 全部粘贴到这里").grid(
            row=4, column=0, sticky="nw", padx=10, pady=(10, 4)
        )
        self.headers_text = ScrolledText(self, height=16, wrap="word")
        self.headers_text.grid(row=5, column=0, sticky="nsew", padx=10)
        self.rowconfigure(5, weight=1)

        buttons = ttk.Frame(self)
        buttons.grid(row=6, column=0, sticky="e", padx=10, pady=10)
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(buttons, text="导入", command=self._import).pack(side=RIGHT)

        self.transient(parent)
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def _import(self) -> None:
        headers = parse_kuro_headers(self.headers_text.get("1.0", END))
        token = headers.get("token")
        device_code = headers.get("devcode") or headers.get("dev-code") or ""
        if not token:
            messagebox.showerror(
                "导入失败",
                "没有从请求头里找到 token。请确认复制的是库街区页面里带 Token 的 Request Headers。",
                parent=self,
            )
            return
        data = {
            "provider": "kuro",
            "name": self.name_var.get().strip() or "库街区账号",
            "enabled": True,
            "token": token,
            "device_code": device_code,
            "game_ids": self.game_ids_var.get().strip() or "3",
            "bat": headers.get("b-at", ""),
            "version": headers.get("version", ""),
            "source": headers.get("source", "h5"),
            "extra_headers": {},
        }
        try:
            self.result = normalize_account(data)
        except Exception as exc:
            messagebox.showerror("导入失败", f"配置格式不正确：{exc}", parent=self)
            return
        self.destroy()


class AccountDialog(Toplevel):
    def __init__(self, parent: Tk, account: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.title("账号设置")
        self.resizable(False, False)
        self.result: dict[str, Any] | None = None
        self.account = account.copy() if account else empty_account("skland")
        self.vars: dict[str, StringVar | BooleanVar] = {}

        self.columnconfigure(1, weight=1)
        self._build()
        self._load(self.account)
        self.transient(parent)
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def _build(self) -> None:
        padding = {"padx": 10, "pady": 5}
        provider = StringVar(value="skland")
        self.vars["provider"] = provider
        ttk.Label(self, text="平台").grid(row=0, column=0, sticky="w", **padding)
        provider_box = ttk.Combobox(
            self, textvariable=provider, values=["skland", "kuro"], state="readonly", width=28
        )
        provider_box.grid(row=0, column=1, sticky="ew", **padding)
        provider_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_fields())

        enabled = BooleanVar(value=True)
        self.vars["enabled"] = enabled
        ttk.Checkbutton(self, text="启用这个账号", variable=enabled).grid(
            row=1, column=1, sticky="w", **padding
        )

        self.fields_frame = ttk.Frame(self)
        self.fields_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.fields_frame.columnconfigure(1, weight=1)

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", padx=10, pady=(8, 12))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(buttons, text="保存", command=self._save).pack(side=RIGHT)

    def _load(self, account: dict[str, Any]) -> None:
        self.vars["provider"].set(account.get("provider") or "skland")
        self.vars["enabled"].set(bool(account.get("enabled", True)))
        self._refresh_fields(account)

    def _refresh_fields(self, account: dict[str, Any] | None = None) -> None:
        for child in self.fields_frame.winfo_children():
            child.destroy()
        provider = str(self.vars["provider"].get())
        account = account or empty_account(provider)

        fields = ["name"]
        if provider == "skland":
            fields += ["token", "cred", "cred_token", "device_id", "skland_games"]
        else:
            fields += ["token", "device_code", "game_ids", "bat", "version", "extra_headers"]

        labels = {
            "name": "备注",
            "token": "token",
            "cred": "cred",
            "cred_token": "cred_token",
            "device_id": "device_id",
            "skland_games": "森空岛游戏",
            "device_code": "device_code/devCode",
            "game_ids": "game_ids",
            "bat": "b-at（可选）",
            "version": "版本号（可选）",
            "extra_headers": "额外请求头 JSON",
        }

        for row, key in enumerate(fields):
            value = account.get(key, "")
            if key == "game_ids" and isinstance(value, list):
                value = ",".join(str(x) for x in value)
            if key == "skland_games" and isinstance(value, list):
                value = ",".join(str(x) for x in value)
            if key == "extra_headers" and isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            var = StringVar(value=str(value))
            self.vars[key] = var
            ttk.Label(self.fields_frame, text=labels[key]).grid(
                row=row, column=0, sticky="w", padx=10, pady=5
            )
            show = "*" if key in {"token", "cred", "cred_token", "bat"} else ""
            entry = ttk.Entry(self.fields_frame, textvariable=var, width=44, show=show)
            entry.grid(row=row, column=1, sticky="ew", padx=10, pady=5)

    def _save(self) -> None:
        provider = str(self.vars["provider"].get())
        data: dict[str, Any] = {
            "provider": provider,
            "enabled": bool(self.vars["enabled"].get()),
            "name": str(self.vars["name"].get()).strip() or provider,
        }
        if provider == "skland":
            for key in ["token", "cred", "cred_token", "device_id", "skland_games"]:
                data[key] = str(self.vars[key].get()).strip()
        else:
            for key in ["token", "device_code", "bat", "version"]:
                data[key] = str(self.vars[key].get()).strip()
            data["game_ids"] = str(self.vars["game_ids"].get()).strip()
            data["extra_headers"] = str(self.vars["extra_headers"].get()).strip()

        try:
            self.result = normalize_account(data)
        except Exception as exc:
            messagebox.showerror("保存失败", f"配置格式不正确：{exc}", parent=self)
            return
        self.destroy()


class SignInApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("森空岛 / 库街区批量签到")
        self.root.geometry("900x620")
        self.root.minsize(780, 520)

        self.config_path = default_config_path()
        self.config: dict[str, Any] = {"accounts": []}
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self._build()
        self.load_config()
        self.root.after(120, self._poll_events)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        outer.rowconfigure(3, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="配置文件").pack(side=LEFT)
        self.path_var = StringVar(value=str(self.config_path))
        ttk.Entry(header, textvariable=self.path_var).pack(side=LEFT, fill="x", expand=True, padx=8)
        ttk.Button(header, text="加载", command=self.load_config).pack(side=LEFT, padx=(0, 6))
        ttk.Button(header, text="保存", command=self.save_config).pack(side=LEFT)

        account_frame = ttk.LabelFrame(outer, text="账号")
        account_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 8))
        account_frame.columnconfigure(0, weight=1)
        account_frame.rowconfigure(0, weight=1)

        columns = ("provider", "name", "enabled", "detail")
        self.tree = ttk.Treeview(account_frame, columns=columns, show="headings", height=8)
        self.tree.heading("provider", text="平台")
        self.tree.heading("name", text="备注")
        self.tree.heading("enabled", text="状态")
        self.tree.heading("detail", text="摘要")
        self.tree.column("provider", width=120, anchor="center")
        self.tree.column("name", width=220)
        self.tree.column("enabled", width=80, anchor="center")
        self.tree.column("detail", width=360)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda _event: self.edit_account())

        scroll = ttk.Scrollbar(account_frame, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=0, column=1, sticky="ns")

        account_buttons = ttk.Frame(outer)
        account_buttons.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(account_buttons, text="添加森空岛", command=lambda: self.add_account("skland")).pack(
            side=LEFT
        )
        ttk.Button(account_buttons, text="添加库街区", command=lambda: self.add_account("kuro")).pack(
            side=LEFT, padx=6
        )
        ttk.Button(account_buttons, text="粘贴库街区请求头", command=self.import_kuro_headers).pack(
            side=LEFT
        )
        ttk.Button(account_buttons, text="编辑", command=self.edit_account).pack(side=LEFT)
        ttk.Button(account_buttons, text="删除", command=self.delete_account).pack(side=LEFT, padx=6)
        ttk.Button(account_buttons, text="选中签到", command=self.sign_selected).pack(side=LEFT)
        ttk.Button(account_buttons, text="刷新森空岛凭据", command=self.refresh_selected_skland_cred).pack(
            side=LEFT, padx=6
        )
        ttk.Button(account_buttons, text="试运行", command=lambda: self.sign(dry_run=True)).pack(
            side=RIGHT, padx=(6, 0)
        )
        self.sign_button = ttk.Button(account_buttons, text="一键签到", command=self.sign)
        self.sign_button.pack(side=RIGHT)

        log_frame = ttk.LabelFrame(outer, text="结果")
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = ScrolledText(log_frame, height=12, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")

        self.status_var = StringVar(value="就绪")
        ttk.Label(outer, textvariable=self.status_var).grid(row=4, column=0, sticky="w", pady=(8, 0))

    def load_config(self) -> None:
        self.config_path = Path(self.path_var.get() or default_config_path())
        if not self.config_path.exists():
            self.config = {"accounts": []}
            self.refresh_accounts()
            self.write_log(f"未找到配置文件，已准备新配置：{self.config_path}")
            return
        try:
            self.config = read_config(self.config_path)
            self.config.setdefault("accounts", [])
            self.refresh_accounts()
            self.write_log(f"已加载配置：{self.config_path}")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc), parent=self.root)

    def save_config(self) -> None:
        self.config_path = Path(self.path_var.get() or default_config_path())
        try:
            write_config(self.config_path, self.config)
            self.write_log(f"已保存配置：{self.config_path}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)

    def refresh_accounts(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, account in enumerate(self.config.get("accounts", [])):
            self.tree.insert("", END, iid=str(index), values=account_summary(account))

    def selected_index(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def add_account(self, provider: str) -> None:
        dialog = AccountDialog(self.root, empty_account(provider))
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self.config.setdefault("accounts", []).append(dialog.result)
        self.refresh_accounts()
        self.save_config()

    def import_kuro_headers(self) -> None:
        dialog = KuroHeaderDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self.config.setdefault("accounts", []).append(dialog.result)
        self.refresh_accounts()
        self.save_config()
        self.write_log(f"已导入库街区账号：{dialog.result.get('name')}")

    def edit_account(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("提示", "请先选中一个账号。", parent=self.root)
            return
        dialog = AccountDialog(self.root, self.config["accounts"][index])
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self.config["accounts"][index] = dialog.result
        self.refresh_accounts()
        self.save_config()

    def delete_account(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("提示", "请先选中一个账号。", parent=self.root)
            return
        account = self.config["accounts"][index]
        name = account.get("name") or account.get("provider") or "账号"
        if not messagebox.askyesno("确认删除", f"删除 {name}？", parent=self.root):
            return
        del self.config["accounts"][index]
        self.refresh_accounts()
        self.save_config()

    def sign_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("提示", "请先选中一个账号。", parent=self.root)
            return
        account = self.config.get("accounts", [])[index]
        if not account.get("enabled", True):
            messagebox.showinfo("提示", "选中的账号已停用。", parent=self.root)
            return
        self._start_sign(accounts=[account])

    def refresh_selected_skland_cred(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("提示", "请先选中一个账号。", parent=self.root)
            return
        account = self.config.get("accounts", [])[index]
        if account.get("provider") != "skland":
            messagebox.showinfo("提示", "只有森空岛账号需要刷新 cred/cred_token。", parent=self.root)
            return
        if not account.get("token"):
            messagebox.showinfo("提示", "请先编辑账号并填写当前有效的森空岛 token。", parent=self.root)
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "当前有任务正在执行，请稍等。", parent=self.root)
            return
        self.save_config()
        self.status_var.set("正在刷新森空岛凭据...")
        self.write_log(f"开始刷新森空岛凭据：{account.get('name') or 'skland'}")
        self.worker = threading.Thread(target=self._refresh_skland_cred_worker, args=(index,), daemon=True)
        self.worker.start()

    def _refresh_skland_cred_worker(self, index: int) -> None:
        try:
            account = dict(self.config["accounts"][index])
            client = SklandClient(account)
            client.ensure_cred(force_refresh=True)
            account["cred"] = client.cred
            account["cred_token"] = client.cred_token
            self.events.put(("account_updated", (index, account)))
            self.events.put(("log", f"森空岛凭据刷新成功：{account.get('name') or 'skland'}"))
            self.events.put(("done", True))
        except Exception as exc:
            self.events.put(("log", f"森空岛凭据刷新失败：{exc}"))
            self.events.put(("done", False))

    def sign(self, dry_run: bool = False) -> None:
        self._start_sign(dry_run=dry_run, accounts=None)

    def _start_sign(
        self, dry_run: bool = False, accounts: list[dict[str, Any]] | None = None
    ) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "签到正在执行，请稍等。", parent=self.root)
            return
        self.save_config()
        self.sign_button.configure(state="disabled")
        single = accounts is not None
        if dry_run:
            self.status_var.set("正在执行试运行...")
            self.write_log("开始试运行")
        elif single:
            self.status_var.set("正在签到选中账号...")
            self.write_log("开始签到选中账号")
        else:
            self.status_var.set("正在签到...")
            self.write_log("开始签到")
        self.worker = threading.Thread(target=self._sign_worker, args=(dry_run, accounts), daemon=True)
        self.worker.start()

    def _sign_worker(self, dry_run: bool, accounts: list[dict[str, Any]] | None = None) -> None:
        try:
            before_config = json.dumps(self.config, ensure_ascii=False, sort_keys=True)
            accounts = accounts if accounts is not None else active_accounts(self.config)
            if not accounts:
                self.events.put(("log", "没有启用的账号。"))
                self.events.put(("done", False))
                return

            ok = True
            for account in accounts:
                provider = str(account.get("provider") or "").lower()
                try:
                    if provider == "skland":
                        results = SklandClient(account, dry_run=dry_run).sign()
                    elif provider == "kuro":
                        results = KuroClient(account, dry_run=dry_run).sign()
                    else:
                        results = [
                            SignResult(provider or "unknown", account.get("name") or "", False, "未知平台")
                        ]
                except SignInError as exc:
                    results = [
                        SignResult(provider or "unknown", account.get("name") or "", False, str(exc))
                    ]

                for item in results:
                    ok = ok and item.ok
                    mark = "OK" if item.ok else "FAIL"
                    self.events.put(("log", f"[{mark}] {item.provider}/{item.account} - {item.message}"))
            after_config = json.dumps(self.config, ensure_ascii=False, sort_keys=True)
            if not dry_run and after_config != before_config:
                self.events.put(("config_changed", None))
            self.events.put(("done", ok))
        except Exception:
            self.events.put(("log", traceback.format_exc()))
            self.events.put(("done", False))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self.write_log(str(payload))
                elif event == "account_updated":
                    index, account = payload
                    self.config["accounts"][index] = account
                    self.refresh_accounts()
                    self.save_config()
                elif event == "config_changed":
                    self.refresh_accounts()
                    self.save_config()
                    self.write_log("已保存自动刷新的森空岛凭据")
                elif event == "done":
                    self.sign_button.configure(state="normal")
                    self.status_var.set("完成" if payload else "完成，有失败项")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def write_log(self, text: str) -> None:
        self.log.insert(END, text + "\n")
        self.log.see(END)


def main() -> None:
    root = Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = SignInApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
