"""Tkinter 深色界面：来源文件夹、目标目录、机制与开关、进度与日志。"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional
from urllib.parse import unquote

from . import APP_SUBTITLE, APP_TITLE, __version__, macos, theme
from .config import AppConfig, RunOptions, save_config
from .platform_utils import human_duration, human_size
from .rule_worker import RuleWorker
from .rules import Rule, RuleError, RuleSettings, default_rules_payload, load_rules, save_rules
from .rules.store import default_rules_path
from .scanner import RECURSION_LABELS
from .worker import CutWorker, TaskSummary

try:  # 可选依赖：缺失时降级为按钮选择
    from tkinterdnd2 import DND_FILES

    DND_AVAILABLE = True
except Exception:  # pragma: no cover - 取决于环境
    DND_FILES = None
    DND_AVAILABLE = False

LOGGER = logging.getLogger(__name__)


def _elide(text: str, limit: int = 72) -> str:
    if len(text) <= limit:
        return text
    keep = limit // 2 - 2
    return text[:keep] + " … " + text[-keep:]


class FolderOpsApp:
    """主窗口。界面只负责收集参数与展示事件，实际工作在线程里完成。"""

    def __init__(
        self,
        root: tk.Misc,
        config: AppConfig,
        log_path: Path,
        log_queue: "queue.Queue[str]",
    ):
        self.root = root
        self.config = config
        self.log_path = Path(log_path)
        self.log_queue = log_queue
        self.events: "queue.Queue[dict]" = queue.Queue()

        self.folders: List[Path] = []
        self.worker: Optional[CutWorker] = None
        self.running = False
        self.rules: List[Rule] = []
        self.rule_settings = RuleSettings()
        self._verify_pref = bool(config.options.verify)
        self.appearance = macos.system_appearance()
        self._fonts = theme.apply_theme(root, appearance=self.appearance)

        self._create_variables()
        self._build_ui()
        self._setup_dnd()
        self._center_window()
        self._sync_mechanism_ui()
        self._update_start_button_text()
        self._load_rules_ui(quiet=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        macos.configure_app(self.root, self.on_close)
        macos.bring_to_front(self.root)
        self.root.after(120, self._poll)
        LOGGER.info(
            "界面初始化完成，版本 v%s，外观=%s，日志文件=%s",
            __version__, self.appearance, self.log_path,
        )

    # ---------- 变量 ----------
    def _create_variables(self) -> None:
        opts = self.config.options
        self.mechanism_var = tk.StringVar(value=opts.mechanism)
        self.recursion_var = tk.StringVar(value=opts.recursion)
        self.conflict_var = tk.StringVar(value=opts.conflict)
        self.cleanup_var = tk.BooleanVar(value=opts.cleanup_empty)
        self.verify_var = tk.BooleanVar(value=opts.verify)
        self.ds_store_var = tk.BooleanVar(value=opts.ignore_ds_store)
        self.dry_run_var = tk.BooleanVar(value=opts.dry_run)
        self.target_var = tk.StringVar(value=self.config.target_dir)
        self.rule_path_var = tk.StringVar(value=str(default_rules_path()))
        self.rule_count_var = tk.StringVar(value="规则未加载")
        self.rules_dry_run_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就绪：拖入多个文件夹，选择目标目录后开始")
        self.current_var = tk.StringVar(value="—")
        self.speed_var = tk.StringVar(value="速度 — ｜ 剩余 —")
        self.stats = {
            "total": tk.StringVar(value="0"),
            "done": tk.StringVar(value="0"),
            "skipped": tk.StringVar(value="0"),
            "failed": tk.StringVar(value="0"),
        }

    # ---------- 界面 ----------
    def _build_ui(self) -> None:
        colors = theme.COLORS
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        header = ttk.Frame(self.root, padding=(18, 10, 18, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        title = ttk.Label(header, text=APP_TITLE, style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")
        appearance_label = "深色" if self.appearance == "dark" else "浅色"
        version = ttk.Label(
            header, text=f"v{__version__} · {appearance_label}模式（跟随系统）", style="Subtitle.TLabel"
        )
        version.grid(row=0, column=1, sticky="e")
        subtitle = ttk.Label(
            header,
            text=f"{APP_SUBTITLE} · 转移默认 MD5+SHA1 双校验 · 全程日志可追溯",
            style="Subtitle.TLabel",
        )
        subtitle.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))

        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew", padx=16, pady=(2, 6))

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=0)
        paned.add(right, weight=1)
        self._build_left(left)
        self._build_right(right)
        self.root.after(50, lambda: self._set_sash(paned, 500))

        footer = ttk.Frame(self.root, padding=(18, 0, 18, 12))
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        log_label = ttk.Label(
            footer, text=f"日志文件：{self.log_path}", style="Tiny.TLabel"
        )
        log_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        self.cancel_btn = ttk.Button(
            footer, text="取消任务", style="Danger.TButton", command=self.cancel_task
        )
        self.cancel_btn.grid(row=1, column=1, sticky="e", padx=(0, 8))
        self.cancel_btn.state(["disabled"])
        self.start_btn = ttk.Button(
            footer, text="开始复制（源文件保留）", style="Accent.TButton", command=self.start_task
        )
        self.start_btn.grid(row=1, column=2, sticky="e")

    def _build_left(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        source = ttk.Labelframe(parent, text=" 来源文件夹 ", padding=(10, 8))
        source.grid(row=0, column=0, sticky="nsew")
        source.grid_columnconfigure(0, weight=1)

        tree_wrap = ttk.Frame(source)
        tree_wrap.grid(row=0, column=0, sticky="nsew")
        tree_wrap.grid_columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            tree_wrap, columns=("path",), show="headings", height=3, selectmode="extended"
        )
        self.tree.heading("path", text="文件夹路径")
        self.tree.column("path", width=420, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(source)
        buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        buttons.grid_columnconfigure(2, weight=1)
        self.add_btn = ttk.Button(buttons, text="添加文件夹", command=self.choose_folders)
        self.add_btn.grid(row=0, column=0, padx=(0, 6))
        self.remove_btn = ttk.Button(buttons, text="移除选中", command=self.remove_selected)
        self.remove_btn.grid(row=0, column=1, padx=(0, 6))
        self.clear_btn = ttk.Button(buttons, text="清空", command=self.clear_folders)
        self.clear_btn.grid(row=0, column=2, sticky="w")

        hint = (
            "支持一次拖入多个文件夹；也可点「添加文件夹」逐个选择"
            if DND_AVAILABLE
            else "未安装 tkinterdnd2，拖拽不可用；请点「添加文件夹」逐个选择（pip install tkinterdnd2）"
        )
        self.drop_hint = ttk.Label(
            source,
            text=hint,
            style="Warn.TLabel" if not DND_AVAILABLE else "Muted.TLabel",
            wraplength=430,
        )
        self.drop_hint.grid(row=2, column=0, sticky="w", pady=(6, 0))

        target = ttk.Labelframe(parent, text=" 目标目录（仅文件夹转移模式使用） ", padding=(10, 8))
        target.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.target_frame = target
        target.grid_columnconfigure(0, weight=1)
        entry = ttk.Entry(target, textvariable=self.target_var)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        browse = ttk.Button(target, text="选择…", command=self.choose_target)
        browse.grid(row=0, column=1)
        self.target_entry = entry
        self.browse_btn = browse

        self.mode_tabs = ttk.Notebook(parent)
        self.mode_tabs.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        transfer_tab = ttk.Frame(self.mode_tabs, padding=(2, 2))
        rules_tab = ttk.Frame(self.mode_tabs, padding=(2, 2))
        self.mode_tabs.add(transfer_tab, text=" 文件夹转移 ")
        self.mode_tabs.add(rules_tab, text=" 规则引擎 ")
        self.mode_tabs.bind("<<NotebookTabChanged>>", lambda _event: self._on_mode_change())

        # 执行设置内容较高，放入纵向滚动容器，避免小屏笔记本被裁切
        scroll_wrap = ttk.Frame(transfer_tab)
        scroll_wrap.pack(fill="both", expand=True)
        self.settings_canvas = tk.Canvas(
            scroll_wrap, bg=theme.COLORS["bg"], highlightthickness=0, bd=0
        )
        settings_scroll = ttk.Scrollbar(
            scroll_wrap, orient="vertical", command=self.settings_canvas.yview
        )
        self.settings_canvas.configure(yscrollcommand=settings_scroll.set)
        settings_scroll.pack(side="right", fill="y")
        self.settings_canvas.pack(side="left", fill="both", expand=True)

        settings_inner = ttk.Frame(self.settings_canvas)
        self._settings_window = self.settings_canvas.create_window(
            (0, 0), window=settings_inner, anchor="nw"
        )
        settings_inner.bind(
            "<Configure>",
            lambda _event: self.settings_canvas.configure(
                scrollregion=self.settings_canvas.bbox("all")
            ),
        )
        self.settings_canvas.bind(
            "<Configure>",
            lambda event: self.settings_canvas.itemconfigure(
                self._settings_window, width=event.width
            ),
        )
        self.settings_canvas.bind("<Enter>", self._bind_settings_wheel)
        self.settings_canvas.bind("<Leave>", self._unbind_settings_wheel)

        settings = ttk.Labelframe(settings_inner, text=" 执行设置 ", padding=(10, 8))
        settings.pack(fill="x", padx=(0, 2), pady=(2, 8))
        settings.grid_columnconfigure(0, weight=1)
        self.settings_frame = settings
        row = ttk.Frame(settings)
        row.grid(row=0, column=0, sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        mech_box = ttk.Frame(row)
        mech_box.grid(row=0, column=0, sticky="ew")
        ttk.Label(mech_box, text="执行机制", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.copy_radio = ttk.Radiobutton(
            mech_box,
            text="复制模式：只复制，源文件保留",
            value="copy",
            variable=self.mechanism_var,
            command=self._on_mechanism_change,
        )
        self.copy_radio.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.move_radio = ttk.Radiobutton(
            mech_box,
            text="剪切模式：移动到目标，成功后删除源",
            value="move",
            variable=self.mechanism_var,
            command=self._on_mechanism_change,
        )
        self.move_radio.grid(row=2, column=0, sticky="w")

        self.verify_check = ttk.Checkbutton(
            mech_box,
            text="启用 MD5 + SHA1 双校验（仅复制模式）",
            variable=self.verify_var,
            command=self._on_verify_change,
        )
        self.verify_check.grid(row=3, column=0, sticky="w", pady=(3, 0))
        self.verify_note = ttk.Label(
            mech_box, text="", style="Muted.TLabel", wraplength=430
        )
        self.verify_note.grid(row=4, column=0, sticky="w", pady=(0, 2))

        ttk.Separator(settings, orient="horizontal").grid(
            row=1, column=0, sticky="ew", pady=2
        )

        ttk.Label(settings, text="递归范围（三选一）", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.recursion_radios = []
        for offset, key in enumerate(("level1", "level2", "full")):
            text = {
                "level1": "仅第一层文件（不进入子文件夹）",
                "level2": "所选文件夹 + 二级子文件夹",
                "full": "全递归（所有层级的所有文件）",
            }[key]
            radio = ttk.Radiobutton(
                settings, text=text, value=key, variable=self.recursion_var
            )
            radio.grid(row=3 + offset, column=0, sticky="w")
            self.recursion_radios.append(radio)

        conflict_row = ttk.Frame(settings)
        conflict_row.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(conflict_row, text="同名文件冲突", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.conflict_radios = []
        for index, (key, text) in enumerate(
            (("skip", "跳过同名"), ("rename", "自动重命名 _1.ext 递增")), start=1
        ):
            radio = ttk.Radiobutton(
                conflict_row, text=text, value=key, variable=self.conflict_var
            )
            radio.grid(row=0, column=index, sticky="w", padx=(0 if index == 1 else 12, 0))
            self.conflict_radios.append(radio)

        checks = ttk.Frame(settings)
        checks.grid(row=9, column=0, sticky="w", pady=(6, 0))
        self.cleanup_check = ttk.Checkbutton(
            checks, text="清理空文件夹", variable=self.cleanup_var
        )
        self.cleanup_check.grid(row=0, column=0, sticky="w")
        self.ds_check = ttk.Checkbutton(
            checks, text="忽略 .DS_Store", variable=self.ds_store_var
        )
        self.ds_check.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.dry_run_check = ttk.Checkbutton(
            checks, text="仅预览 dry-run", variable=self.dry_run_var
        )
        self.dry_run_check.grid(row=0, column=2, sticky="w", padx=(12, 0))

        self._editable_widgets = [
            self.add_btn, self.remove_btn, self.clear_btn,
            self.target_entry, self.browse_btn,
            self.copy_radio, self.move_radio,
            self.verify_check,
            *self.recursion_radios, *self.conflict_radios,
            self.cleanup_check, self.ds_check, self.dry_run_check,
            self.tree,
        ]
        self._build_rules_tab(rules_tab)

    def _bind_settings_wheel(self, _event=None) -> None:
        self.settings_canvas.bind_all("<MouseWheel>", self._scroll_settings)

    def _unbind_settings_wheel(self, _event=None) -> None:
        self.settings_canvas.unbind_all("<MouseWheel>")

    def _scroll_settings(self, event) -> None:
        if self._current_mode() != "transfer":
            return
        step = -1 if event.delta > 0 else 1
        self.settings_canvas.yview_scroll(step, "units")

    def _build_rules_tab(self, parent: ttk.Frame) -> None:
        """规则引擎面板：规则文件、规则清单、dry-run 开关。"""
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        file_box = ttk.Labelframe(parent, text=" 规则文件 ", padding=(10, 8))
        file_box.grid(row=0, column=0, sticky="ew")
        file_box.grid_columnconfigure(0, weight=1)
        self.rule_path_entry = ttk.Entry(file_box, textvariable=self.rule_path_var)
        self.rule_path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.rule_choose_btn = ttk.Button(file_box, text="选择…", command=self.choose_rule_file)
        self.rule_choose_btn.grid(row=0, column=1, padx=(0, 6))
        self.rule_reload_btn = ttk.Button(file_box, text="加载", command=self._load_rules_ui)
        self.rule_reload_btn.grid(row=0, column=2)

        actions = ttk.Frame(file_box)
        actions.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.rule_default_btn = ttk.Button(
            actions, text="恢复默认规则", command=self.restore_default_rules
        )
        self.rule_default_btn.grid(row=0, column=0)
        self.rule_preview_btn = ttk.Button(
            actions, text="查看规则 JSON", command=self.preview_rules_json
        )
        self.rule_preview_btn.grid(row=0, column=1, padx=(6, 0))
        ttk.Label(actions, textvariable=self.rule_count_var, style="Muted.TLabel").grid(
            row=0, column=2, sticky="w", padx=(10, 0)
        )

        hint = ttk.Label(
            parent,
            text="规则按优先级升序执行，首个命中规则生效；移动/复制目标为相对路径时，"
                 "落到规则设置的 target_root，未配置则落到来源文件夹。",
            style="Muted.TLabel",
            wraplength=430,
        )
        hint.grid(row=1, column=0, sticky="w", pady=(6, 6))

        tree_wrap = ttk.Frame(parent)
        tree_wrap.grid(row=2, column=0, sticky="nsew")
        tree_wrap.grid_columnconfigure(0, weight=1)
        tree_wrap.grid_rowconfigure(0, weight=1)
        self.rule_tree = ttk.Treeview(
            tree_wrap, columns=("priority", "name", "actions", "status"),
            show="headings", height=8,
        )
        self.rule_tree.heading("priority", text="优先级")
        self.rule_tree.heading("name", text="规则")
        self.rule_tree.heading("actions", text="动作")
        self.rule_tree.heading("status", text="状态")
        self.rule_tree.column("priority", width=58, anchor="center", stretch=False)
        self.rule_tree.column("name", width=150, anchor="w")
        self.rule_tree.column("actions", width=120, anchor="w")
        self.rule_tree.column("status", width=52, anchor="center", stretch=False)
        self.rule_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.rule_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.rule_tree.configure(yscrollcommand=scroll.set)

        self.rules_dry_check = ttk.Checkbutton(
            parent, text="仅预览 dry-run（默认开启，先看计划再执行）",
            variable=self.rules_dry_run_var,
            command=self._update_start_button_text,
        )
        self.rules_dry_check.grid(row=3, column=0, sticky="w", pady=(6, 0))

        self._editable_widgets.extend([
            self.rule_path_entry, self.rule_choose_btn, self.rule_reload_btn,
            self.rule_default_btn, self.rule_preview_btn, self.rule_tree,
            self.rules_dry_check,
        ])

    # ---------- 规则 ----------
    def _current_mode(self) -> str:
        try:
            return "rules" if self.mode_tabs.index("current") == 1 else "transfer"
        except tk.TclError:
            return "transfer"

    def _on_mode_change(self) -> None:
        rules_mode = self._current_mode() == "rules"
        if rules_mode:
            self.target_frame.grid_remove()
            self.status_var.set("规则引擎模式：先预览，再决定是否真实执行")
        else:
            self.target_frame.grid()
            self.status_var.set("文件夹转移模式：复制默认双校验，剪切成功后删除源")
        self._update_start_button_text()

    def _load_rules_ui(self, quiet: bool = False) -> None:
        path = Path(self.rule_path_var.get().strip()).expanduser()
        try:
            rules, settings, _ = load_rules(path)
        except RuleError as exc:
            self.rule_count_var.set("规则加载失败")
            LOGGER.error("规则加载失败：%s", exc)
            if not quiet:
                messagebox.showerror("规则不可用", f"{exc}\n\n文件：{path}")
            return
        self.rules = rules
        self.rule_settings = settings
        self.rule_tree.delete(*self.rule_tree.get_children())
        for rule in sorted(rules, key=lambda item: (item.priority, item.id)):
            self.rule_tree.insert(
                "", "end",
                values=(rule.priority, rule.name, rule.describe_actions(),
                        "启用" if rule.enabled else "停用"),
            )
        self.rule_count_var.set(f"已加载 {len(rules)} 条规则")
        if not quiet:
            self.status_var.set(f"规则已加载：{len(rules)} 条")
            LOGGER.info("界面加载规则 %d 条：%s", len(rules), path)

    def choose_rule_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择规则文件", filetypes=[("JSON 规则", "*.json"), ("所有文件", "*.*")]
        )
        if path:
            self.rule_path_var.set(path)
            self._load_rules_ui()

    def restore_default_rules(self) -> None:
        path = Path(self.rule_path_var.get().strip()).expanduser()
        if path.exists() and not messagebox.askyesno(
            "恢复默认规则", f"将覆盖现有规则文件：\n{path}\n\n继续？"
        ):
            return
        save_rules(default_rules_payload(), path)
        LOGGER.info("已写入默认规则：%s", path)
        self._load_rules_ui()

    def preview_rules_json(self) -> None:
        path = Path(self.rule_path_var.get().strip()).expanduser()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("无法读取", f"{exc}")
            return
        window = tk.Toplevel(self.root)
        window.title(f"规则预览 · {path.name}")
        window.geometry("760x560")
        text = tk.Text(window, wrap="none", font=self._fonts["mono"])
        text.pack(fill="both", expand=True)
        text.insert("1.0", content)
        text.configure(state="disabled")

    def start_rules(self) -> None:
        if not self.folders:
            messagebox.showwarning("缺少来源", "请先拖入或添加至少一个文件夹。")
            return
        self._load_rules_ui(quiet=True)
        if not self.rules:
            messagebox.showerror("没有规则", "规则未加载成功，请检查规则文件。")
            return
        dry_run = bool(self.rules_dry_run_var.get())
        if not dry_run and not messagebox.askyesno(
            "真实执行规则",
            "将按规则真实修改磁盘（移动/复制/解压/清理空目录）。\n\n建议先用 dry-run 预览。继续？",
        ):
            return

        for key in self.stats:
            self.stats[key].set("0")
        self.current_var.set("正在扫描…")
        self.speed_var.set("规则执行中…")
        self._set_running(True)
        self.progress.stop()
        self.progress.configure(mode="indeterminate", maximum=1, value=0)
        self.progress.start(12)
        self.status_var.set(
            "规则预览中…" if dry_run else "规则执行中…"
        )
        self.worker = RuleWorker(
            self.folders, self.rules, self.rule_settings, self.events, dry_run=dry_run
        )
        self.worker.start()

    def _build_right(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        progress = ttk.Labelframe(parent, text=" 任务进度（按文件计数） ", padding=(12, 10))
        progress.grid(row=0, column=0, sticky="ew")
        progress.grid_columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(progress, mode="determinate", maximum=1, value=0)
        self.progress.grid(row=0, column=0, sticky="ew")

        stats = ttk.Frame(progress)
        stats.grid(row=1, column=0, sticky="ew", pady=(10, 6))
        for index, (key, label) in enumerate(
            (("total", "总数"), ("done", "已完成"), ("skipped", "跳过"), ("failed", "失败"))
        ):
            stats.grid_columnconfigure(index, weight=1)
            cell = ttk.Frame(stats, style="Panel.TFrame", padding=(10, 6))
            cell.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0))
            ttk.Label(cell, text=label, style="StatName.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(
                cell, textvariable=self.stats[key], style="StatValue.TLabel"
            ).grid(row=1, column=0, sticky="w")

        ttk.Label(progress, text="当前文件", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        ttk.Label(
            progress, textvariable=self.current_var, style="Panel.TLabel"
        ).grid(row=3, column=0, sticky="w", pady=(2, 4))
        ttk.Label(
            progress, textvariable=self.speed_var, style="Muted.TLabel"
        ).grid(row=4, column=0, sticky="w")

        logs = ttk.Labelframe(parent, text=" 运行日志 ", padding=(10, 8))
        logs.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        logs.grid_columnconfigure(0, weight=1)
        logs.grid_rowconfigure(0, weight=1)

        text_wrap = ttk.Frame(logs)
        text_wrap.grid(row=0, column=0, sticky="nsew")
        text_wrap.grid_columnconfigure(0, weight=1)
        text_wrap.grid_rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            text_wrap,
            height=12,
            wrap="word",
            bg=theme.COLORS["field"],
            fg=theme.COLORS["fg"],
            insertbackground=theme.COLORS["fg"],
            selectbackground=theme.COLORS["selection"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.COLORS["border"],
            font=self._fonts["mono"],
            padx=8,
            pady=6,
            state="disabled",
            spacing1=1,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(text_wrap, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.tag_configure("error", foreground=theme.COLORS["danger"])
        self.log_text.tag_configure("warn", foreground=theme.COLORS["warning"])
        self.log_text.tag_configure("debug", foreground=theme.COLORS["muted"])
        self.log_text.tag_configure("success", foreground=theme.COLORS["success"])

        toolbar = ttk.Frame(logs)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        toolbar.grid_columnconfigure(2, weight=1)
        ttk.Button(toolbar, text="导出日志", command=self.export_log).grid(row=0, column=0)
        ttk.Button(toolbar, text="打开日志目录", command=self.open_log_dir).grid(
            row=0, column=1, padx=(6, 6)
        )
        ttk.Button(toolbar, text="清空面板", command=self.clear_log_panel).grid(
            row=0, column=2, sticky="w"
        )

    def _set_sash(self, paned: ttk.Panedwindow, position: int) -> None:
        try:
            paned.sashpos(0, position)
        except tk.TclError:
            pass

    # ---------- 窗口 ----------
    def _center_window(self) -> None:
        width = max(1000, min(self.config.window.width, 4000))
        height = max(860, min(self.config.window.height, 3000))
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1000, 860)

    def _setup_dnd(self) -> None:
        if not DND_AVAILABLE:
            return
        for widget in (self.tree, self.drop_hint):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("注册拖拽失败：%s", exc)

    def _on_drop(self, event) -> None:
        try:
            raw = self.root.tk.splitlist(event.data)
        except tk.TclError:
            raw = [event.data]
        paths = []
        for item in raw:
            text = str(item)
            if text.startswith("file://"):
                text = unquote(text[len("file://"):])
            paths.append(Path(text))
        self.add_folders(paths)

    # ---------- 文件夹列表 ----------
    def choose_folders(self) -> None:
        folder = filedialog.askdirectory(title="选择一个来源文件夹")
        if folder:
            self.add_folders([Path(folder)])

    def add_folders(self, paths: List[Path]) -> None:
        added = 0
        existing = {os.path.abspath(str(p)) for p in self.folders}
        for path in paths:
            path = Path(path).expanduser()
            if not path.is_dir():
                LOGGER.warning("忽略非文件夹路径：%s", path)
                continue
            key = os.path.abspath(str(path))
            if key in existing:
                continue
            self.folders.append(path)
            existing.add(key)
            added += 1
            LOGGER.info("添加来源文件夹：%s", path)
        self._refresh_tree()
        if added:
            self.status_var.set(f"已添加 {added} 个文件夹，共 {len(self.folders)} 个")

    def remove_selected(self) -> None:
        selected = list(self.tree.selection())
        if not selected:
            return
        for item in selected:
            values = self.tree.item(item, "values")
            if not values:
                continue
            target_path = values[0]
            self.folders = [p for p in self.folders if str(p) != target_path]
            LOGGER.info("移除来源文件夹：%s", target_path)
        self._refresh_tree()
        self.status_var.set(f"当前共 {len(self.folders)} 个文件夹")

    def clear_folders(self) -> None:
        if self.folders:
            LOGGER.info("清空来源文件夹列表（%d 个）", len(self.folders))
        self.folders = []
        self._refresh_tree()
        self.status_var.set("来源列表已清空")

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for path in self.folders:
            self.tree.insert("", "end", values=(str(path),))

    # ---------- 目标目录 ----------
    def choose_target(self) -> None:
        initial = self.target_var.get().strip() or str(Path.home())
        folder = filedialog.askdirectory(title="选择目标目录", initialdir=initial)
        if folder:
            self.set_target_dir(folder)

    def set_target_dir(self, folder) -> None:
        self.target_var.set(str(folder))
        self.config.target_dir = str(folder)
        LOGGER.info("设置目标目录：%s", folder)
        self.status_var.set("目标目录已设置")

    # ---------- 机制联动 ----------
    def _on_mechanism_change(self) -> None:
        if self.running:
            return
        self._sync_mechanism_ui()
        self._update_start_button_text()

    def _on_verify_change(self) -> None:
        if self.mechanism_var.get() == "copy":
            self._verify_pref = bool(self.verify_var.get())
        self._update_verify_note()

    def _sync_mechanism_ui(self) -> None:
        move = self.mechanism_var.get() == "move"
        if move:
            self.verify_var.set(False)
            self.verify_check.state(["disabled"])
            self.verify_check.configure(text="校验（剪切模式不执行校验）")
        else:
            self.verify_check.configure(text="启用 MD5 + SHA1 双校验（仅复制模式）")
            if not self.running:
                self.verify_check.state(["!disabled"])
                self.verify_var.set(self._verify_pref)
        self._update_verify_note()

    def _update_verify_note(self) -> None:
        move = self.mechanism_var.get() == "move"
        if move:
            note = "剪切模式不执行校验：同盘直接 rename；跨盘复制后仅确认目标存在且大小一致，再删除源文件。"
            self.verify_note.configure(text=note, style="Warn.TLabel")
        elif self.verify_var.get():
            note = "复制前后分别计算 MD5 与 SHA1；任一项不一致则丢弃副本、保留源文件并记为失败。"
            self.verify_note.configure(text=note, style="Muted.TLabel")
        else:
            note = "校验已关闭：仅复制并检查目标大小，不做哈希比对（源文件始终保留）。"
            self.verify_note.configure(text=note, style="Muted.TLabel")

    def _update_start_button_text(self) -> None:
        if self._current_mode() == "rules":
            if self.rules_dry_run_var.get():
                self.start_btn.configure(text="预览规则（不修改磁盘）")
            else:
                self.start_btn.configure(text="执行规则")
            return
        if self.mechanism_var.get() == "move":
            self.start_btn.configure(text="开始剪切（成功后删除源）")
        else:
            self.start_btn.configure(text="开始复制（源文件保留）")

    # ---------- 任务 ----------
    def _collect_options(self) -> RunOptions:
        return RunOptions(
            mechanism=self.mechanism_var.get(),
            recursion=self.recursion_var.get(),
            cleanup_empty=bool(self.cleanup_var.get()),
            conflict=self.conflict_var.get(),
            verify=bool(self._verify_pref) if self.mechanism_var.get() == "copy" else False,
            ignore_ds_store=bool(self.ds_store_var.get()),
            dry_run=bool(self.dry_run_var.get()),
        ).normalized()

    def start_task(self) -> None:
        if self.running:
            return
        if self._current_mode() == "rules":
            self.start_rules()
            return
        if not self.folders:
            self.status_var.set("请先添加至少一个来源文件夹")
            messagebox.showwarning("缺少来源", "请先拖入或添加至少一个文件夹。")
            return

        target_text = self.target_var.get().strip()
        if not target_text:
            self.status_var.set("请先选择目标目录")
            messagebox.showwarning("缺少目标目录", "请先选择目标目录。")
            return
        target = Path(target_text).expanduser()
        if not target.exists():
            if not messagebox.askyesno("目标目录不存在", f"{target}\n\n是否创建该目录？"):
                return
        if target.exists() and not target.is_dir():
            messagebox.showerror("目标无效", "目标路径不是文件夹，请重新选择。")
            return
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("目标不可用", f"无法创建目标目录：{exc}")
            return

        options = self._collect_options()
        self.config.target_dir = str(target)
        self.config.options = options
        save_config(self.config)

        for key in self.stats:
            self.stats[key].set("0")
        self.current_var.set("正在扫描…")
        self.speed_var.set("速度 — ｜ 剩余 —")
        self._set_running(True)
        self.progress.stop()
        self.progress.configure(mode="indeterminate", maximum=1, value=0)
        self.progress.start(12)
        self.status_var.set("正在扫描文件…")

        self.worker = CutWorker(self.folders, target, options, self.events)
        self.worker.start()

    def cancel_task(self) -> None:
        if not self.running or not self.worker:
            return
        self.worker.cancel()
        self.cancel_btn.state(["disabled"])
        self.status_var.set("已请求取消：将在当前文件处理完成后停止，已完成文件不回滚")
        LOGGER.warning("用户请求取消任务")

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.start_btn.state(["disabled"] if running else ["!disabled"])
        self.cancel_btn.state(["!disabled"] if running else ["disabled"])
        for widget in self._editable_widgets:
            widget.state(["disabled"] if running else ["!disabled"])
        if not running:
            self._sync_mechanism_ui()
            self._update_start_button_text()
        self.current_var.set("—" if not running else self.current_var.get())

    # ---------- 事件轮询 ----------
    def _poll(self) -> None:
        self._drain_logs()
        self._drain_events()
        self.root.after(120, self._poll)

    def _drain_logs(self) -> None:
        processed = 0
        while processed < 300:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
            processed += 1

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        tag = ""
        if "| ERROR" in line:
            tag = "error"
        elif "| WARNING" in line:
            tag = "warn"
        elif "| DEBUG" in line:
            tag = "debug"
        elif "校验通过" in line or "已删除空目录" in line:
            tag = "success"
        if tag:
            self.log_text.insert("end", line + "\n", tag)
        else:
            self.log_text.insert("end", line + "\n")

        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 4000:
            self.log_text.delete("1.0", f"{line_count - 3500}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "started":
            self.current_var.set("正在扫描…")
            return
        if kind == "scanned":
            total = int(event.get("total") or 0)
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)
            self.stats["total"].set(str(total))
            self.status_var.set(
                f"扫描完成：{total} 个文件，共 {human_size(event.get('total_bytes', 0))}，"
                f"跳过 {event.get('scan_skipped', 0)} 个条目"
            )
            return
        if kind == "file_start":
            index = event.get("index")
            total = event.get("total")
            name = _elide(str(event.get("name") or ""), 64)
            self.current_var.set(f"[{index}/{total}] {name}")
            return
        if kind == "progress":
            self._update_progress(event)
            return
        if kind == "cleanup":
            self.status_var.set(
                f"清理空目录：已删除 {event.get('removed', 0)} 个，失败 {event.get('failed', 0)} 个"
            )
            return
        if kind == "error":
            self.status_var.set(f"出错：{event.get('message')}")
            return
        if kind == "finished":
            self._on_finished(event["summary"])
            return

    def _update_progress(self, event: dict) -> None:
        total = int(event.get("total") or 0)
        index = int(event.get("index") or 0)
        self.progress.configure(maximum=max(total, 1), value=index)
        self.stats["total"].set(str(total))
        self.stats["done"].set(str(event.get("done", 0)))
        self.stats["skipped"].set(str(event.get("skipped", 0)))
        self.stats["failed"].set(str(event.get("failed", 0)))

        total_bytes = float(event.get("total_bytes") or 0)
        processed = float(event.get("processed_bytes") or 0)
        elapsed = float(event.get("elapsed") or 0)
        if elapsed > 0.3 and processed > 0:
            speed = processed / elapsed
            remaining = max(total_bytes - processed, 0)
            eta = remaining / speed if speed > 0 else 0
            self.speed_var.set(
                f"速度 {human_size(speed)}/s ｜ 剩余 {human_size(remaining)} ｜ 预计还需 {human_duration(eta)}"
            )
        else:
            self.speed_var.set("速度计算中…")

    def _on_finished(self, summary: TaskSummary) -> None:
        self.progress.stop()
        total = max(summary.total, 1)
        if summary.dry_run:
            self.progress.configure(mode="determinate", maximum=max(summary.planned, 1), value=summary.planned)
        else:
            self.progress.configure(
                mode="determinate", maximum=total,
                value=summary.done + summary.skipped + summary.failed,
            )
        self.stats["total"].set(str(summary.total))
        self.stats["done"].set(str(summary.done))
        self.stats["skipped"].set(str(summary.skipped))
        self.stats["failed"].set(str(summary.failed))
        self.current_var.set("—")
        if summary.mechanism == "rules":
            extra = getattr(summary, "extracted", 0)
            matched = getattr(summary, "matched", 0)
            self.speed_var.set(
                f"总耗时 {human_duration(summary.duration)} ｜ 命中规则 {matched} 个 ｜ 解压 {extra} 个"
            )
            if summary.cancelled:
                self.status_var.set(
                    f"已取消：完成 {summary.done} 个，跳过 {summary.skipped} 个，失败 {summary.failed} 个"
                )
            elif summary.dry_run:
                self.status_var.set(
                    f"规则预览完成：命中 {matched} 个文件，计划 {summary.planned} 个动作，未修改磁盘"
                )
            else:
                self.status_var.set(
                    f"规则执行完成：完成 {summary.done} 个，跳过 {summary.skipped} 个，"
                    f"失败 {summary.failed} 个，清理空目录 {summary.cleanup_removed} 个"
                )
            self.worker = None
            self._set_running(False)
            return

        self.speed_var.set(
            f"总耗时 {human_duration(summary.duration)} ｜ 校验通过 {summary.verified_count} 个"
        )
        if summary.cancelled:
            self.status_var.set(
                f"已取消：已完成 {summary.done} 个，跳过 {summary.skipped} 个，失败 {summary.failed} 个；"
                "已完成不回滚，未开始的不动"
            )
        elif summary.dry_run:
            self.status_var.set(f"预览完成：共 {summary.planned} 个文件，未修改磁盘")
        else:
            verb = "复制" if summary.mechanism == "copy" else "移动"
            self.status_var.set(
                f"任务完成：{verb} {summary.done} 个，跳过 {summary.skipped} 个，"
                f"失败 {summary.failed} 个，用时 {human_duration(summary.duration)}"
            )
        self.worker = None
        self._set_running(False)
        self.config.target_dir = self.target_var.get().strip()
        save_config(self.config)

    # ---------- 日志工具 ----------
    def export_log(self) -> None:
        default_name = f"folder-ops_{time.strftime('%Y%m%d_%H%M%S')}.log"
        path = filedialog.asksaveasfilename(
            title="导出日志", defaultextension=".log", initialfile=default_name
        )
        if not path:
            return
        try:
            content = self.log_text.get("1.0", "end-1c")
            Path(path).write_text(content, encoding="utf-8")
            self.status_var.set(f"日志已导出：{path}")
            LOGGER.info("导出界面日志到 %s", path)
        except OSError as exc:
            messagebox.showerror("导出失败", f"写入日志失败：{exc}")

    def open_log_dir(self) -> None:
        directory = self.log_path.parent
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)])
            elif os.name == "nt":
                os.startfile(str(directory))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(directory)])
            self.status_var.set(f"已打开日志目录：{directory}")
        except Exception as exc:
            messagebox.showerror("无法打开", f"打开日志目录失败：{exc}")

    def clear_log_panel(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------- 关闭 ----------
    def on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno("任务进行中", "任务仍在运行，退出会中断任务（当前文件处理完后停止）。确定退出？"):
                return
            if self.worker:
                self.worker.cancel()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        if width > 200 and height > 200:
            self.config.window.width = width
            self.config.window.height = height
        self.config.target_dir = self.target_var.get().strip()
        self.config.options = self._collect_options()
        save_config(self.config)
        LOGGER.info("界面关闭，配置已保存")
        self.root.destroy()


def launch(root, config, log_path, log_queue) -> FolderOpsApp:
    return FolderOpsApp(root, config, log_path, log_queue)
