#!/usr/bin/env python3
"""HTML版と同等の機能を持つ HTTP POST デスクトップGUIツール。"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any
import urllib.error
import urllib.request

VAR_PATTERN = re.compile(r"\{\{\s*([^\s{}]+)\s*\}\}")
APP_DIR_NAME = "HttpPostTool"
CONFIG_FILE_NAME = "config.json"


def _create_half_hour_options() -> list[str]:
    """00:00〜23:30 の30分刻み時刻リスト（全48件）を返す。"""
    return [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]


def create_default_config() -> dict[str, Any]:
    """デフォルト設定（Power Automate Webhook トリガ向け・sample-config.json と互換）を返す。"""
    return {
        "version": 1,
        "url": "https://prod-00.japaneast.logic.azure.com:443/workflows/<workflow-id>/triggers/manual/paths/invoke?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=<signature>",
        "headers": [{"key": "Content-Type", "value": "application/json"}],
        "payload": '{\n  "name": "{{名前}}",\n  "time": "{{時刻}}"\n}',
        "variables": [
            {"name": "名前", "type": "text", "value": "山田 太郎", "options": []},
            {
                "name": "時刻",
                "type": "select",
                "value": "18:00",
                "options": _create_half_hour_options(),
            },
        ],
    }


def get_config_file_path() -> Path:
    """OSごとのローカル設定保存先パスを返す。"""
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else home / ".config"
    return base / APP_DIR_NAME / CONFIG_FILE_NAME


def normalize_option(opt: Any) -> dict[str, str] | None:
    """選択肢要素（文字列または {label, value} 辞書）を正規化する。"""
    if isinstance(opt, str):
        return {"label": opt, "value": opt}
    if isinstance(opt, dict):
        value = "" if opt.get("value") is None else str(opt.get("value"))
        label = value if opt.get("label") is None else str(opt.get("label"))
        return {"label": label, "value": value}
    return None


def serialize_options_for_input(options: list[Any] | None) -> str:
    """選択肢配列をカンマ区切りテキストに整形する。"""
    parts: list[str] = []
    for opt in options or []:
        if isinstance(opt, str):
            val = opt
        elif isinstance(opt, dict):
            val = "" if opt.get("value") is None else str(opt.get("value"))
        else:
            val = ""
        if val:
            parts.append(val)
    return ", ".join(parts)


def parse_options_input(raw: str) -> list[str]:
    """カンマ区切りテキストから選択肢の文字列リストを抽出する。"""
    return [item.strip() for item in raw.split(",") if item.strip()]


def validate_config(raw: Any) -> dict[str, Any]:
    """設定オブジェクトを検証し、欠落フィールドをデフォルト値で補完する。"""
    if not isinstance(raw, dict):
        raise ValueError("設定はJSONオブジェクトである必要があります。")

    defaults = create_default_config()

    if "url" in raw and not isinstance(raw["url"], str):
        raise ValueError("url は文字列である必要があります。")
    if "payload" in raw and not isinstance(raw["payload"], str):
        raise ValueError("payload は文字列である必要があります。")
    if "headers" in raw and not isinstance(raw["headers"], list):
        raise ValueError("headers は配列である必要があります。")
    if "variables" in raw and not isinstance(raw["variables"], list):
        raise ValueError("variables は配列である必要があります。")

    raw_headers = raw["headers"] if "headers" in raw else defaults["headers"]
    headers: list[dict[str, str]] = []
    for idx, h in enumerate(raw_headers):
        if not isinstance(h, dict):
            raise ValueError(f"headers[{idx}] はオブジェクトである必要があります。")
        if "key" in h and h["key"] is not None and not isinstance(h["key"], str):
            raise ValueError(f"headers[{idx}].key は文字列である必要があります。")
        if "value" in h and h["value"] is not None and not isinstance(h["value"], str):
            raise ValueError(f"headers[{idx}].value は文字列である必要があります。")
        headers.append(
            {
                "key": h.get("key") or "",
                "value": h.get("value") or "",
            }
        )

    raw_variables = raw["variables"] if "variables" in raw else defaults["variables"]
    variables: list[dict[str, Any]] = []
    for idx, v in enumerate(raw_variables):
        if not isinstance(v, dict):
            raise ValueError(f"variables[{idx}] はオブジェクトである必要があります。")
        if "name" in v and v["name"] is not None and not isinstance(v["name"], str):
            raise ValueError(f"variables[{idx}].name は文字列である必要があります。")

        var_type = v.get("type", "text")
        if var_type not in ("text", "select"):
            raise ValueError(
                f'variables[{idx}].type は "text" または "select" である必要があります。'
            )

        if "options" in v and v["options"] is not None and not isinstance(v["options"], list):
            raise ValueError(f"variables[{idx}].options は配列である必要があります。")

        raw_options = v.get("options") if isinstance(v.get("options"), list) else []
        clean_options: list[Any] = []
        for opt_idx, opt in enumerate(raw_options):
            if isinstance(opt, str):
                clean_options.append(opt)
            elif isinstance(opt, dict):
                val = "" if opt.get("value") is None else str(opt.get("value"))
                lbl = val if opt.get("label") is None else str(opt.get("label"))
                clean_options.append({"label": lbl, "value": val})
            else:
                raise ValueError(
                    f"variables[{idx}].options[{opt_idx}] の型が不正です。"
                )

        val_raw = v.get("value")
        value = "" if val_raw is None else str(val_raw)
        variables.append(
            {
                "name": v.get("name") or "",
                "type": var_type,
                "value": value,
                "options": clean_options,
            }
        )

    version = raw.get("version")
    return {
        "version": version if isinstance(version, (int, float)) and not isinstance(version, bool) else 1,
        "url": raw["url"] if "url" in raw else defaults["url"],
        "headers": headers,
        "payload": raw["payload"] if "payload" in raw else defaults["payload"],
        "variables": variables,
    }


def build_variable_map(variables: list[dict[str, Any]]) -> dict[str, str]:
    """変数定義リストから {変数名: 値} マップを構築する。"""
    var_map: dict[str, str] = {}
    for v in variables:
        name = str(v.get("name", "")).strip()
        if name:
            var_map[name] = str(v.get("value", ""))
    return var_map


def substitute(text: str, var_map: dict[str, str]) -> str:
    """テキスト内の {{変数名}} を var_map の値で置換する。"""

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return var_map[key] if key in var_map else match.group(0)

    return VAR_PATTERN.sub(_repl, text)


def collect_undefined_vars(strings: list[str], var_map: dict[str, str]) -> list[str]:
    """文字列群から未定義の {{変数名}} を重複なく抽出する。"""
    missing: list[str] = []
    seen: set[str] = set()
    for text in strings:
        for match in VAR_PATTERN.finditer(text):
            key = match.group(1)
            if key not in var_map and key not in seen:
                seen.add(key)
                missing.append(key)
    return missing


def is_json_content_type(headers: list[dict[str, str]], var_map: dict[str, str]) -> bool:
    """Content-Type ヘッダーに json が含まれるかを判定する。"""
    for h in headers:
        if h.get("key", "").strip().lower() == "content-type":
            val = substitute(h.get("value", ""), var_map).lower()
            if "json" in val:
                return True
    return False


def _create_ssl_context() -> ssl.SSLContext:
    """certifi が利用可能であればその証明書バンドルで SSLContext を作成する。"""
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def send_post_request(
    url: str,
    headers: dict[str, str],
    body: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """HTTP POST リクエストを送信し、レスポンス情報の辞書を返す。"""
    data = body.encode("utf-8")
    req = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
    ssl_ctx = _create_ssl_context()
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            raw_bytes = resp.read()
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            resp_headers = list(resp.headers.items())
            status = getattr(resp, "status", 200)
            reason = getattr(resp, "reason", "") or ""
            return {
                "ok": 200 <= status < 300,
                "status": status,
                "reason": reason,
                "elapsed_ms": elapsed_ms,
                "headers": resp_headers,
                "body": raw_bytes.decode("utf-8", errors="replace"),
                "error": None,
            }
    except urllib.error.HTTPError as err:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        try:
            raw_bytes = err.read()
            body_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        resp_headers = list(err.headers.items()) if err.headers else []
        return {
            "ok": False,
            "status": err.code,
            "reason": err.reason or "",
            "elapsed_ms": elapsed_ms,
            "headers": resp_headers,
            "body": body_text,
            "error": None,
        }
    except urllib.error.URLError as err:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return {
            "ok": False,
            "status": None,
            "reason": "",
            "elapsed_ms": elapsed_ms,
            "headers": [],
            "body": "",
            "error": f"接続エラー: {err.reason}",
        }
    except Exception as err:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return {
            "ok": False,
            "status": None,
            "reason": "",
            "elapsed_ms": elapsed_ms,
            "headers": [],
            "body": "",
            "error": f"リクエストに失敗しました: {err}",
        }


def get_variable_validation_statuses(
    variables: list[dict[str, Any]],
) -> list[tuple[bool, str]]:
    """各変数の空名・重複チェック結果を返す。"""
    counts: dict[str, int] = {}
    for v in variables:
        name = str(v.get("name", "")).strip()
        if name:
            counts[name] = counts.get(name, 0) + 1

    statuses: list[tuple[bool, str]] = []
    for v in variables:
        name = str(v.get("name", "")).strip()
        if not name:
            statuses.append((True, "変数名が空です。"))
        elif counts[name] > 1:
            statuses.append((True, f'変数名 "{name}" が重複しています。'))
        else:
            statuses.append((False, ""))
    return statuses


class HttpPostToolApp:
    """HTTP POST ツールの Tkinter GUI アプリケーション。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("HTTP POST ツール")
        self.root.geometry("1220x820")
        self.root.minsize(820, 560)

        self.mono_font = ("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10)
        self.ui_font = ("Hiragino Sans", 11) if sys.platform == "darwin" else ("Yu Gothic UI", 10)

        self.state: dict[str, Any] = create_default_config()
        self.mode: str = "run"
        self._banner_after_id: str | None = None
        self._suppress_events = False
        self._var_row_refs: list[dict[str, Any]] = []
        self._mousewheel_bound = False

        self._setup_styles()
        self._build_ui()

        if not self._load_from_local_file(silent_if_missing=True):
            self.state = create_default_config()
            self.render()
        self.set_mode("run")

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if sys.platform == "darwin" and "aqua" in available:
            style.theme_use("aqua")
        elif "clam" in available:
            style.theme_use("clam")

    def _build_ui(self) -> None:
        # ツールバー
        toolbar = ttk.Frame(self.root, padding=(12, 10))
        toolbar.pack(fill=tk.X)

        title_lbl = ttk.Label(
            toolbar,
            text="HTTP POST ツール",
            font=(self.ui_font[0], 14, "bold"),
        )
        title_lbl.pack(side=tk.LEFT)

        sub_lbl = ttk.Label(
            toolbar,
            text="変数テンプレート対応・ローカル設定保存",
            foreground="#57606a",
        )
        sub_lbl.pack(side=tk.LEFT, padx=(10, 12))

        right_controls = ttk.Frame(toolbar)
        right_controls.pack(side=tk.RIGHT)

        # モード切替セグメントボタン
        mode_switch = tk.Frame(
            right_controls,
            bg="#eaeef2",
            highlightbackground="#b6c0ca",
            highlightthickness=1,
            padx=2,
            pady=2,
        )
        mode_switch.pack(side=tk.LEFT, padx=(0, 12))

        self.mode_run_btn = tk.Label(
            mode_switch,
            text="実行モード",
            font=(self.ui_font[0], 10, "bold"),
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.mode_run_btn.pack(side=tk.LEFT)
        self.mode_run_btn.bind("<Button-1>", lambda _e: self.set_mode("run"))

        self.mode_config_btn = tk.Label(
            mode_switch,
            text="設定モード",
            font=(self.ui_font[0], 10, "bold"),
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.mode_config_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.mode_config_btn.bind("<Button-1>", lambda _e: self.set_mode("config"))

        self.btn_frame = ttk.Frame(right_controls)
        self.btn_frame.pack(side=tk.LEFT)

        self.save_local_btn = ttk.Button(
            self.btn_frame, text="設定を保存", command=self._on_save_local
        )
        self.load_local_btn = ttk.Button(
            self.btn_frame, text="設定を読込", command=self._on_load_local
        )
        self.import_json_btn = ttk.Button(
            self.btn_frame, text="JSONファイル読込", command=self._on_import_json
        )
        self.export_json_btn = ttk.Button(
            self.btn_frame, text="JSONエクスポート", command=self._on_export_json
        )
        self.reset_btn = ttk.Button(
            self.btn_frame, text="リセット", command=self._on_reset
        )

        self.config_only_buttons: list[ttk.Button] = [
            self.save_local_btn,
            self.load_local_btn,
            self.export_json_btn,
            self.reset_btn,
        ]

        # 通知バナー
        self.banner_var = tk.StringVar(value="")
        self.banner_label = tk.Label(
            self.root,
            textvariable=self.banner_var,
            anchor="w",
            padx=12,
            pady=6,
            bg="#dafbe1",
            fg="#1a7f37",
            relief=tk.SOLID,
            bd=1,
        )

        # メイン2カラム (PanedWindow)
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # 左ペイン（スクロール対応）
        left_outer = ttk.Frame(self.paned)
        self.paned.add(left_outer, weight=3)

        self.left_canvas = tk.Canvas(left_outer, highlightthickness=0)
        left_vbar = ttk.Scrollbar(left_outer, orient=tk.VERTICAL, command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=left_vbar.set)

        left_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.left_inner = ttk.Frame(self.left_canvas, padding=(4, 4, 8, 12))
        self.left_window_id = self.left_canvas.create_window(
            (0, 0), window=self.left_inner, anchor="nw"
        )

        self.left_inner.bind("<Configure>", self._on_left_inner_configure)
        self.left_canvas.bind("<Configure>", self._on_left_canvas_configure)
        self.left_canvas.bind("<Enter>", lambda _e: self._bind_mousewheel(True))
        self.left_canvas.bind("<Leave>", lambda _e: self._bind_mousewheel(False))

        # 実行モード / 設定モードのフレーム
        self.run_frame = ttk.Frame(self.left_inner)
        self.config_frame = ttk.Frame(self.left_inner)

        self._build_run_sections(self.run_frame)
        self._build_config_sections(self.config_frame)

        # 右ペイン（レスポンス）
        right_outer = ttk.Frame(self.paned, padding=(6, 4, 4, 4))
        self.paned.add(right_outer, weight=2)
        self._build_right_panel(right_outer)

    def _on_left_inner_configure(self, _event: tk.Event[Any]) -> None:
        self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

    def _on_left_canvas_configure(self, event: tk.Event[Any]) -> None:
        self.left_canvas.itemconfigure(self.left_window_id, width=event.width)

    def _bind_mousewheel(self, enable: bool) -> None:
        if enable and not self._mousewheel_bound:
            self.root.bind_all("<MouseWheel>", self._on_mousewheel)
            self._mousewheel_bound = True
        elif not enable and self._mousewheel_bound:
            self.root.unbind_all("<MouseWheel>")
            self._mousewheel_bound = False

    def _on_mousewheel(self, event: tk.Event[Any]) -> None:
        widget = event.widget
        if isinstance(widget, tk.Text):
            return
        if sys.platform == "darwin":
            step = -int(event.delta)
        else:
            step = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        if step != 0:
            self.left_canvas.yview_scroll(step, "units")

    def _build_run_sections(self, parent: ttk.Frame) -> None:
        # 1. 送信先（読み取り専用）
        dest_frame = ttk.LabelFrame(parent, text="送信先", padding=10)
        dest_frame.pack(fill=tk.X, pady=(0, 10))

        dest_row = ttk.Frame(dest_frame)
        dest_row.pack(fill=tk.X)

        tk.Label(
            dest_row,
            text="POST",
            bg="#ddf4ff",
            fg="#0969da",
            font=(self.ui_font[0], 10, "bold"),
            padx=10,
            pady=4,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.run_url_var = tk.StringVar(value="")
        run_url_lbl = tk.Label(
            dest_row,
            textvariable=self.run_url_var,
            font=self.mono_font,
            bg="#f6f8fa",
            fg="#1f2328",
            anchor="w",
            padx=8,
            pady=5,
            relief=tk.SOLID,
            bd=1,
        )
        run_url_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 2. 変数入力フォーム＋実行ボタン
        vars_frame = ttk.LabelFrame(parent, text="変数", padding=10)
        vars_frame.pack(fill=tk.X)

        self.run_variables_container = ttk.Frame(vars_frame)
        self.run_variables_container.pack(fill=tk.X)

        self.run_variables_empty_lbl = ttk.Label(
            vars_frame,
            text="設定された変数がありません。",
            foreground="#57606a",
        )

        self.run_warnings_var = tk.StringVar(value="")
        self.run_warnings_lbl = tk.Label(
            vars_frame,
            textvariable=self.run_warnings_var,
            justify=tk.LEFT,
            anchor="w",
            bg="#fff8c5",
            fg="#9a6700",
            padx=8,
            pady=6,
            relief=tk.SOLID,
            bd=1,
            wraplength=560,
        )

        self.run_actions_frame = ttk.Frame(vars_frame)
        self.run_actions_frame.pack(fill=tk.X, pady=(12, 0))

        self.run_send_btn = ttk.Button(
            self.run_actions_frame,
            text="実行（POST送信）",
            command=self._on_send,
        )
        self.run_send_btn.pack(anchor="w")

    def _build_config_sections(self, parent: ttk.Frame) -> None:
        # 1. エンドポイント
        ep_frame = ttk.LabelFrame(parent, text="エンドポイント", padding=10)
        ep_frame.pack(fill=tk.X, pady=(0, 10))

        url_row = ttk.Frame(ep_frame)
        url_row.pack(fill=tk.X)

        method_lbl = tk.Label(
            url_row,
            text="POST",
            bg="#ddf4ff",
            fg="#0969da",
            font=(self.ui_font[0], 10, "bold"),
            padx=10,
            pady=4,
        )
        method_lbl.pack(side=tk.LEFT, padx=(0, 8))

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.url_var.trace_add("write", self._on_url_changed)

        self.send_btn = ttk.Button(url_row, text="送信", command=self._on_send)
        self.send_btn.pack(side=tk.LEFT)

        ttk.Label(
            ep_frame,
            text="URL・ヘッダー値・ペイロード内で {{変数名}} を使用できます。",
            foreground="#57606a",
        ).pack(anchor="w", pady=(6, 0))

        # 2. 変数
        var_frame = ttk.LabelFrame(parent, text="変数", padding=10)
        var_frame.pack(fill=tk.X, pady=(0, 10))

        var_top = ttk.Frame(var_frame)
        var_top.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(var_top, text="＋変数追加", command=self._on_add_variable).pack(
            side=tk.RIGHT
        )

        self.variables_container = ttk.Frame(var_frame)
        self.variables_container.pack(fill=tk.X)

        self.variables_empty_lbl = ttk.Label(
            var_frame,
            text="変数がありません。「＋変数追加」から追加できます。",
            foreground="#57606a",
        )

        # 3. ヘッダー
        hdr_frame = ttk.LabelFrame(parent, text="ヘッダー", padding=10)
        hdr_frame.pack(fill=tk.X, pady=(0, 10))

        hdr_top = ttk.Frame(hdr_frame)
        hdr_top.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(hdr_top, text="＋ヘッダー追加", command=self._on_add_header).pack(
            side=tk.RIGHT
        )

        self.headers_container = ttk.Frame(hdr_frame)
        self.headers_container.pack(fill=tk.X)

        self.headers_empty_lbl = ttk.Label(
            hdr_frame,
            text="ヘッダーがありません。",
            foreground="#57606a",
        )

        # 4. ペイロード
        pay_frame = ttk.LabelFrame(parent, text="ペイロード", padding=10)
        pay_frame.pack(fill=tk.X, pady=(0, 10))

        pay_text_wrap = ttk.Frame(pay_frame)
        pay_text_wrap.pack(fill=tk.BOTH, expand=True)

        self.payload_text = tk.Text(
            pay_text_wrap,
            height=9,
            font=self.mono_font,
            wrap=tk.NONE,
            undo=True,
        )
        pay_ybar = ttk.Scrollbar(
            pay_text_wrap, orient=tk.VERTICAL, command=self.payload_text.yview
        )
        self.payload_text.configure(yscrollcommand=pay_ybar.set)
        pay_ybar.pack(side=tk.RIGHT, fill=tk.Y)
        self.payload_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.payload_text.bind("<KeyRelease>", self._on_payload_changed)
        self.payload_text.bind("<FocusOut>", self._on_payload_changed)

        ttk.Label(
            pay_frame,
            text="{{変数名}} で変数を埋め込めます（JSON文字列の引用符はテンプレート側に記述してください）。",
            foreground="#57606a",
        ).pack(anchor="w", pady=(6, 0))

        # 5. 送信プレビュー
        prev_frame = ttk.LabelFrame(parent, text="送信プレビュー（変数展開後）", padding=10)
        prev_frame.pack(fill=tk.X)

        url_prev_row = ttk.Frame(prev_frame)
        url_prev_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(url_prev_row, text="URL:", foreground="#57606a").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.preview_url_var = tk.StringVar()
        ttk.Label(
            url_prev_row,
            textvariable=self.preview_url_var,
            font=self.mono_font,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.preview_warnings_var = tk.StringVar()
        self.preview_warnings_lbl = tk.Label(
            prev_frame,
            textvariable=self.preview_warnings_var,
            justify=tk.LEFT,
            anchor="w",
            bg="#fff8c5",
            fg="#9a6700",
            padx=8,
            pady=6,
            relief=tk.SOLID,
            bd=1,
            wraplength=560,
        )

        self.preview_payload_text = tk.Text(
            prev_frame,
            height=8,
            font=self.mono_font,
            bg="#f6f8fa",
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.preview_payload_text.pack(fill=tk.BOTH, expand=True)

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        resp_frame = ttk.LabelFrame(parent, text="レスポンス", padding=10)
        resp_frame.pack(fill=tk.BOTH, expand=True)

        meta_row = ttk.Frame(resp_frame)
        meta_row.pack(fill=tk.X, pady=(0, 8))

        self.resp_status_var = tk.StringVar(value="未送信")
        self.resp_status_lbl = tk.Label(
            meta_row,
            textvariable=self.resp_status_var,
            bg="#eaeef2",
            fg="#57606a",
            font=(self.ui_font[0], 10, "bold"),
            padx=10,
            pady=3,
        )
        self.resp_status_lbl.pack(side=tk.LEFT)

        self.resp_time_var = tk.StringVar(value="")
        ttk.Label(meta_row, textvariable=self.resp_time_var, foreground="#57606a").pack(
            side=tk.LEFT, padx=(10, 0)
        )

        self.resp_error_var = tk.StringVar()
        self.resp_error_lbl = tk.Label(
            resp_frame,
            textvariable=self.resp_error_var,
            justify=tk.LEFT,
            anchor="w",
            bg="#ffebe9",
            fg="#cf222e",
            padx=10,
            pady=8,
            relief=tk.SOLID,
            bd=1,
            wraplength=420,
        )

        self.resp_headers_title_lbl = ttk.Label(
            resp_frame, text="レスポンスヘッダー", foreground="#57606a"
        )
        self.resp_headers_title_lbl.pack(anchor="w", pady=(4, 2))
        hdr_wrap = ttk.Frame(resp_frame)
        hdr_wrap.pack(fill=tk.X, pady=(0, 10))
        self.resp_headers_text = tk.Text(
            hdr_wrap,
            height=7,
            font=self.mono_font,
            bg="#f6f8fa",
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        hdr_ybar = ttk.Scrollbar(
            hdr_wrap, orient=tk.VERTICAL, command=self.resp_headers_text.yview
        )
        self.resp_headers_text.configure(yscrollcommand=hdr_ybar.set)
        hdr_ybar.pack(side=tk.RIGHT, fill=tk.Y)
        self.resp_headers_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(resp_frame, text="レスポンスボディ", foreground="#57606a").pack(
            anchor="w", pady=(0, 2)
        )
        body_wrap = ttk.Frame(resp_frame)
        body_wrap.pack(fill=tk.BOTH, expand=True)
        self.resp_body_text = tk.Text(
            body_wrap,
            font=self.mono_font,
            bg="#f6f8fa",
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        body_ybar = ttk.Scrollbar(
            body_wrap, orient=tk.VERTICAL, command=self.resp_body_text.yview
        )
        self.resp_body_text.configure(yscrollcommand=body_ybar.set)
        body_ybar.pack(side=tk.RIGHT, fill=tk.Y)
        self.resp_body_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._set_readonly_text(self.resp_headers_text, "（なし）")
        self._set_readonly_text(self.resp_body_text, "送信するとここに結果が表示されます。")

    def _set_readonly_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.configure(state=tk.DISABLED)

    def _show_banner(self, message: str, is_error: bool = False) -> None:
        if self._banner_after_id is not None:
            self.root.after_cancel(self._banner_after_id)
            self._banner_after_id = None

        self.banner_var.set(message)
        if is_error:
            self.banner_label.configure(bg="#ffebe9", fg="#cf222e")
        else:
            self.banner_label.configure(bg="#dafbe1", fg="#1a7f37")
        self.banner_label.pack(fill=tk.X, padx=12, pady=(0, 8), before=self.paned)
        self._banner_after_id = self.root.after(3500, self._hide_banner)

    def _hide_banner(self) -> None:
        self._banner_after_id = None
        self.banner_label.pack_forget()

    def set_mode(self, next_mode: str) -> None:
        """実行モード（run）と設定モード（config）を切り替える。"""
        self.mode = "config" if next_mode == "config" else "run"

        if self.mode == "run":
            self.mode_run_btn.configure(bg="#0969da", fg="#ffffff")
            self.mode_config_btn.configure(bg="#eaeef2", fg="#1f2328")
        else:
            self.mode_run_btn.configure(bg="#eaeef2", fg="#1f2328")
            self.mode_config_btn.configure(bg="#0969da", fg="#ffffff")

        # ツールバーボタンをモードに応じて再配置
        for btn in (
            self.save_local_btn,
            self.load_local_btn,
            self.import_json_btn,
            self.export_json_btn,
            self.reset_btn,
        ):
            btn.pack_forget()

        if self.mode == "config":
            self.save_local_btn.pack(side=tk.LEFT, padx=3)
            self.load_local_btn.pack(side=tk.LEFT, padx=3)
            self.import_json_btn.pack(side=tk.LEFT, padx=3)
            self.export_json_btn.pack(side=tk.LEFT, padx=3)
            self.reset_btn.pack(side=tk.LEFT, padx=(3, 0))
            self.run_frame.pack_forget()
            self.config_frame.pack(fill=tk.BOTH, expand=True)
            self.render()
        else:
            self.import_json_btn.pack(side=tk.LEFT, padx=3)
            self.config_frame.pack_forget()
            self.run_frame.pack(fill=tk.BOTH, expand=True)
            self.render_run_view()

        self.left_canvas.yview_moveto(0.0)

    def _on_url_changed(self, *_args: Any) -> None:
        if self._suppress_events:
            return
        self.state["url"] = self.url_var.get()
        self.update_preview()
        self.update_run_summary()

    def _on_payload_changed(self, _event: tk.Event[Any] | None = None) -> None:
        if self._suppress_events:
            return
        self.state["payload"] = self.payload_text.get("1.0", "end-1c")
        self.update_preview()
        self.update_run_summary()

    def _on_add_variable(self) -> None:
        self.state["variables"].append(
            {"name": "", "type": "text", "value": "", "options": []}
        )
        self.render_variables()
        self.render_run_variables()
        self.update_preview()
        self.update_run_summary()
        if self._var_row_refs:
            self._var_row_refs[-1]["name_entry"].focus_set()

    def _on_add_header(self) -> None:
        self.state["headers"].append({"key": "", "value": ""})
        self.render_headers()
        self.update_preview()
        self.update_run_summary()

    def render(self) -> None:
        self._suppress_events = True
        try:
            self.url_var.set(self.state["url"])
            self.payload_text.delete("1.0", tk.END)
            self.payload_text.insert("1.0", self.state["payload"])
        finally:
            self._suppress_events = False

        self.render_variables()
        self.render_headers()
        self.update_preview()
        self.render_run_view()

    def render_run_view(self) -> None:
        """実行モード用のシンプルな変数入力フォーム・送信先を再描画する。"""
        self.render_run_variables()
        self.update_run_summary()

    def render_run_variables(self) -> None:
        for child in self.run_variables_container.winfo_children():
            child.destroy()

        variables = self.state["variables"]
        if not variables:
            self.run_variables_empty_lbl.pack(anchor="w")
            return
        self.run_variables_empty_lbl.pack_forget()

        for variable in variables:
            row = ttk.Frame(self.run_variables_container)
            row.pack(fill=tk.X, pady=(0, 8))

            name_text = str(variable.get("name", "")).strip() or "（未設定）"
            lbl = ttk.Label(row, text=name_text, width=18, anchor="w")
            lbl.pack(side=tk.LEFT, padx=(0, 10))

            if variable.get("type") == "select":
                val_combo = ttk.Combobox(row, state="readonly")
                val_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
                norm_items, _ = self._populate_select_combobox(val_combo, variable)

                def on_run_val_selected(
                    _e: tk.Event[Any],
                    v: dict[str, Any] = variable,
                    cb: ttk.Combobox = val_combo,
                    items: list[dict[str, str]] = norm_items,
                ) -> None:
                    sel = cb.current()
                    if 0 <= sel < len(items):
                        v["value"] = items[sel]["value"]
                    else:
                        v["value"] = ""
                    self.update_run_summary()
                    self.update_preview()

                val_combo.bind("<<ComboboxSelected>>", on_run_val_selected)
            else:
                val_var = tk.StringVar(value=str(variable.get("value", "")))
                val_entry = ttk.Entry(row, textvariable=val_var)
                val_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

                def on_run_val_write(
                    *_args: Any,
                    v: dict[str, Any] = variable,
                    sv: tk.StringVar = val_var,
                ) -> None:
                    v["value"] = sv.get()
                    self.update_run_summary()
                    self.update_preview()

                val_var.trace_add("write", on_run_val_write)

    def update_run_summary(self) -> None:
        """実行モードの送信先URL表示と未定義変数警告を更新する。"""
        var_map = build_variable_map(self.state["variables"])
        expanded_url = substitute(self.state["url"], var_map)
        self.run_url_var.set(expanded_url if expanded_url else "（未入力）")

        all_strings = [self.state["url"], self.state["payload"]] + [
            h.get("value", "") for h in self.state["headers"]
        ]
        missing = collect_undefined_vars(all_strings, var_map)
        if missing:
            missing_fmt = ", ".join(f"{{{{{m}}}}}" for m in missing)
            self.run_warnings_var.set(f"未定義の変数があります: {missing_fmt}")
            if not self.run_warnings_lbl.winfo_ismapped():
                self.run_warnings_lbl.pack(
                    fill=tk.X, pady=(8, 0), before=self.run_actions_frame
                )
        else:
            if self.run_warnings_lbl.winfo_ismapped():
                self.run_warnings_lbl.pack_forget()

    def _populate_select_combobox(
        self, combo: ttk.Combobox, variable: dict[str, Any]
    ) -> tuple[list[dict[str, str]], bool]:
        normalized: list[dict[str, str]] = []
        for opt in variable.get("options", []):
            norm = normalize_option(opt)
            if norm is not None:
                normalized.append(norm)

        if not normalized:
            combo.configure(values=["（選択肢なし）"])
            combo.current(0)
            variable["value"] = ""
            return [], False

        labels = [opt["label"] for opt in normalized]
        combo.configure(values=labels)

        current_val = str(variable.get("value", ""))
        selected_idx = 0
        for idx, opt in enumerate(normalized):
            if opt["value"] == current_val:
                selected_idx = idx
                break
        combo.current(selected_idx)
        variable["value"] = normalized[selected_idx]["value"]
        return normalized, True

    def render_variables(self) -> None:
        for child in self.variables_container.winfo_children():
            child.destroy()
        self._var_row_refs = []

        variables = self.state["variables"]
        if not variables:
            self.variables_empty_lbl.pack(anchor="w")
        else:
            self.variables_empty_lbl.pack_forget()

        for idx, variable in enumerate(variables):
            outer = tk.Frame(
                self.variables_container,
                bg="#fafbfc",
                highlightbackground="#d8dee4",
                highlightthickness=1,
                padx=8,
                pady=6,
            )
            outer.pack(fill=tk.X, pady=(0, 6))

            top_row = tk.Frame(outer, bg="#fafbfc")
            top_row.pack(fill=tk.X)

            name_var = tk.StringVar(value=variable.get("name", ""))
            name_entry = ttk.Entry(top_row, textvariable=name_var, width=18)
            name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

            def on_name_write(*_args: Any, v: dict[str, Any] = variable, sv: tk.StringVar = name_var) -> None:
                v["name"] = sv.get()
                self._update_variable_row_errors()
                self.update_preview()
                self.update_run_summary()

            name_var.trace_add("write", on_name_write)

            type_label = "テキスト" if variable.get("type") == "text" else "選択肢"
            type_var = tk.StringVar(value=type_label)
            type_combo = ttk.Combobox(
                top_row,
                textvariable=type_var,
                values=["テキスト", "選択肢"],
                state="readonly",
                width=9,
            )
            type_combo.pack(side=tk.LEFT, padx=(0, 6))

            def on_type_selected(_e: tk.Event[Any], v: dict[str, Any] = variable, tv: tk.StringVar = type_var) -> None:
                new_type = "select" if tv.get() == "選択肢" else "text"
                v["type"] = new_type
                if new_type == "select" and not v.get("options"):
                    v["options"] = [v["value"]] if v.get("value") else ["option1", "option2"]
                self.render_variables()
                self.update_preview()
                self.update_run_summary()

            type_combo.bind("<<ComboboxSelected>>", on_type_selected)

            if variable.get("type") == "select":
                val_combo = ttk.Combobox(top_row, state="readonly", width=20)
                val_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
                norm_holder: dict[str, list[dict[str, str]]] = {"items": []}
                norm_items, _has_items = self._populate_select_combobox(val_combo, variable)
                norm_holder["items"] = norm_items

                def on_val_selected(
                    _e: tk.Event[Any],
                    v: dict[str, Any] = variable,
                    cb: ttk.Combobox = val_combo,
                    holder: dict[str, list[dict[str, str]]] = norm_holder,
                ) -> None:
                    sel = cb.current()
                    items = holder["items"]
                    if 0 <= sel < len(items):
                        v["value"] = items[sel]["value"]
                    else:
                        v["value"] = ""
                    self.update_preview()
                    self.update_run_summary()

                val_combo.bind("<<ComboboxSelected>>", on_val_selected)
            else:
                val_var = tk.StringVar(value=str(variable.get("value", "")))
                val_entry = ttk.Entry(top_row, textvariable=val_var, width=20)
                val_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

                def on_val_write(*_args: Any, v: dict[str, Any] = variable, sv: tk.StringVar = val_var) -> None:
                    v["value"] = sv.get()
                    self.update_preview()
                    self.update_run_summary()

                val_var.trace_add("write", on_val_write)

            def on_delete(i: int = idx) -> None:
                del self.state["variables"][i]
                self.render_variables()
                self.render_run_variables()
                self.update_preview()
                self.update_run_summary()

            ttk.Button(top_row, text="削除", command=on_delete, width=6).pack(side=tk.LEFT)

            if variable.get("type") == "select":
                opt_row = tk.Frame(outer, bg="#fafbfc")
                opt_row.pack(fill=tk.X, pady=(6, 0))
                opt_lbl = tk.Label(
                    opt_row,
                    text="選択肢 (カンマ区切り):",
                    bg="#fafbfc",
                    fg="#57606a",
                )
                opt_lbl.pack(side=tk.LEFT, padx=(0, 6))

                opts_var = tk.StringVar(
                    value=serialize_options_for_input(variable.get("options"))
                )
                opts_entry = ttk.Entry(opt_row, textvariable=opts_var)
                opts_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

                def on_opts_write(
                    *_args: Any,
                    v: dict[str, Any] = variable,
                    ov: tk.StringVar = opts_var,
                    cb: ttk.Combobox = val_combo,
                    holder: dict[str, list[dict[str, str]]] = norm_holder,
                ) -> None:
                    v["options"] = parse_options_input(ov.get())
                    new_items, _ = self._populate_select_combobox(cb, v)
                    holder["items"] = new_items
                    self.update_preview()
                    self.update_run_summary()

                opts_var.trace_add("write", on_opts_write)

            err_var = tk.StringVar(value="")
            err_lbl = tk.Label(
                outer,
                textvariable=err_var,
                bg="#ffebe9",
                fg="#cf222e",
                anchor="w",
            )

            self._var_row_refs.append(
                {
                    "outer": outer,
                    "top_row": top_row,
                    "name_entry": name_entry,
                    "err_var": err_var,
                    "err_lbl": err_lbl,
                }
            )

        self._update_variable_row_errors()

    def _update_variable_row_errors(self) -> None:
        statuses = get_variable_validation_statuses(self.state["variables"])
        for ref, (invalid, msg) in zip(self._var_row_refs, statuses):
            outer: tk.Frame = ref["outer"]
            top_row: tk.Frame = ref["top_row"]
            err_lbl: tk.Label = ref["err_lbl"]
            ref["err_var"].set(msg)

            if invalid:
                outer.configure(bg="#ffebe9", highlightbackground="#cf222e")
                top_row.configure(bg="#ffebe9")
                if not err_lbl.winfo_ismapped():
                    err_lbl.pack(fill=tk.X, pady=(4, 0))
            else:
                outer.configure(bg="#fafbfc", highlightbackground="#d8dee4")
                top_row.configure(bg="#fafbfc")
                if err_lbl.winfo_ismapped():
                    err_lbl.pack_forget()

    def render_headers(self) -> None:
        for child in self.headers_container.winfo_children():
            child.destroy()

        headers = self.state["headers"]
        if not headers:
            self.headers_empty_lbl.pack(anchor="w")
        else:
            self.headers_empty_lbl.pack_forget()

        for idx, header in enumerate(headers):
            row = ttk.Frame(self.headers_container)
            row.pack(fill=tk.X, pady=(0, 6))

            key_var = tk.StringVar(value=header.get("key", ""))
            val_var = tk.StringVar(value=header.get("value", ""))

            ttk.Entry(row, textvariable=key_var, width=20).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
            )
            ttk.Entry(row, textvariable=val_var, width=26).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
            )

            def on_key_write(*_args: Any, h: dict[str, str] = header, kv: tk.StringVar = key_var) -> None:
                h["key"] = kv.get()
                self.update_preview()
                self.update_run_summary()

            def on_val_write(*_args: Any, h: dict[str, str] = header, vv: tk.StringVar = val_var) -> None:
                h["value"] = vv.get()
                self.update_preview()
                self.update_run_summary()

            key_var.trace_add("write", on_key_write)
            val_var.trace_add("write", on_val_write)

            def on_delete(i: int = idx) -> None:
                del self.state["headers"][i]
                self.render_headers()
                self.update_preview()
                self.update_run_summary()

            ttk.Button(row, text="削除", command=on_delete, width=6).pack(side=tk.LEFT)

    def update_preview(self) -> None:
        var_map = build_variable_map(self.state["variables"])
        expanded_url = substitute(self.state["url"], var_map)
        expanded_payload = substitute(self.state["payload"], var_map)

        self.preview_url_var.set(expanded_url if expanded_url else "（未入力）")
        self._set_readonly_text(self.preview_payload_text, expanded_payload)

        all_strings = [self.state["url"], self.state["payload"]] + [
            h.get("value", "") for h in self.state["headers"]
        ]
        missing = collect_undefined_vars(all_strings, var_map)
        warnings: list[str] = []
        if missing:
            missing_fmt = ", ".join(f"{{{{{m}}}}}" for m in missing)
            warnings.append(f"未定義の変数があります: {missing_fmt}")

        if expanded_payload.strip() and is_json_content_type(
            self.state["headers"], var_map
        ):
            try:
                json.loads(expanded_payload)
            except json.JSONDecodeError as err:
                warnings.append(f"JSON構文エラー（送信自体は可能です）: {err}")

        if warnings:
            self.preview_warnings_var.set("\n".join(f"• {w}" for w in warnings))
            if not self.preview_warnings_lbl.winfo_ismapped():
                self.preview_warnings_lbl.pack(
                    fill=tk.X, pady=(0, 6), before=self.preview_payload_text
                )
        else:
            if self.preview_warnings_lbl.winfo_ismapped():
                self.preview_warnings_lbl.pack_forget()

    def _on_send(self) -> None:
        var_map = build_variable_map(self.state["variables"])
        target_url = substitute(self.state["url"], var_map).strip()

        if not target_url:
            self._show_banner("URLが未設定です。設定モードでURLを入力してください。", is_error=True)
            if self.mode == "config":
                self.url_entry.focus_set()
            return

        req_headers: dict[str, str] = {}
        for h in self.state["headers"]:
            k = h.get("key", "").strip()
            if k:
                req_headers[k] = substitute(h.get("value", ""), var_map)

        body = substitute(self.state["payload"], var_map)

        self.send_btn.configure(state=tk.DISABLED)
        self.run_send_btn.configure(state=tk.DISABLED)
        self.resp_status_var.set("送信中...")
        self.resp_status_lbl.configure(bg="#eaeef2", fg="#57606a")
        self.resp_time_var.set("")
        if self.resp_error_lbl.winfo_ismapped():
            self.resp_error_lbl.pack_forget()
        self._set_readonly_text(self.resp_headers_text, "（待機中）")
        self._set_readonly_text(self.resp_body_text, "（待機中）")

        def worker() -> None:
            result = send_post_request(target_url, req_headers, body)
            self.root.after(0, lambda: self._apply_response(result))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_response(self, result: dict[str, Any]) -> None:
        self.send_btn.configure(state=tk.NORMAL)
        self.run_send_btn.configure(state=tk.NORMAL)
        self.resp_time_var.set(f"{result['elapsed_ms']} ms")

        if result["error"]:
            self.resp_status_var.set("エラー")
            self.resp_status_lbl.configure(bg="#ffebe9", fg="#cf222e")
            self.resp_error_var.set(result["error"])
            if not self.resp_error_lbl.winfo_ismapped():
                self.resp_error_lbl.pack(
                    fill=tk.X, pady=(0, 8), before=self.resp_headers_title_lbl
                )
            self._set_readonly_text(self.resp_headers_text, "（なし）")
            self._set_readonly_text(self.resp_body_text, "")
            return

        if self.resp_error_lbl.winfo_ismapped():
            self.resp_error_lbl.pack_forget()

        status = result["status"]
        reason = result["reason"]
        self.resp_status_var.set(f"{status} {reason}".strip())
        if result["ok"]:
            self.resp_status_lbl.configure(bg="#dafbe1", fg="#1a7f37")
        else:
            self.resp_status_lbl.configure(bg="#ffebe9", fg="#cf222e")

        hdr_lines = [f"{k}: {v}" for k, v in result["headers"]]
        self._set_readonly_text(
            self.resp_headers_text, "\n".join(hdr_lines) if hdr_lines else "（なし）"
        )

        raw_body = result["body"]
        if not raw_body:
            self._set_readonly_text(self.resp_body_text, "（空のレスポンス）")
        else:
            try:
                parsed = json.loads(raw_body)
                pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
                self._set_readonly_text(self.resp_body_text, pretty)
            except json.JSONDecodeError:
                self._set_readonly_text(self.resp_body_text, raw_body)

    def _on_save_local(self) -> None:
        path = get_config_file_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._show_banner(f"保存しました ({path})", is_error=False)
        except Exception as err:
            self._show_banner(f"設定の保存に失敗しました: {err}", is_error=True)

    def _load_from_local_file(self, silent_if_missing: bool) -> bool:
        path = get_config_file_path()
        if not path.exists():
            if not silent_if_missing:
                self._show_banner("保存された設定ファイルが見つかりません。", is_error=True)
            return False
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            self.state = validate_config(parsed)
            self.render()
            if not silent_if_missing:
                self._show_banner("ローカル設定を読み込みました", is_error=False)
            return True
        except Exception as err:
            if not silent_if_missing:
                messagebox.showerror("読込エラー", f"設定の読み込みに失敗しました:\n{err}")
            return False

    def _on_load_local(self) -> None:
        self._load_from_local_file(silent_if_missing=False)

    def _on_import_json(self) -> None:
        file_path = filedialog.askopenfilename(
            title="JSON設定ファイルを選択",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not file_path:
            return
        try:
            parsed = json.loads(Path(file_path).read_text(encoding="utf-8"))
            self.state = validate_config(parsed)
            self.render()
            self._show_banner("JSONファイルから設定を読み込みました", is_error=False)
        except Exception as err:
            messagebox.showerror(
                "JSON読込エラー", f"JSONファイルの読み込みに失敗しました:\n{err}"
            )

    def _on_export_json(self) -> None:
        file_path = filedialog.asksaveasfilename(
            title="JSON設定ファイルを保存",
            defaultextension=".json",
            initialfile="post-config.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not file_path:
            return
        try:
            Path(file_path).write_text(
                json.dumps(self.state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._show_banner(
                f"{Path(file_path).name} にエクスポートしました", is_error=False
            )
        except Exception as err:
            messagebox.showerror(
                "JSONエクスポートエラー", f"ファイルの保存に失敗しました:\n{err}"
            )

    def _on_reset(self) -> None:
        self.state = create_default_config()
        self.render()
        self._show_banner("設定を初期状態にリセットしました", is_error=False)


def main() -> None:
    root = tk.Tk()
    HttpPostToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
