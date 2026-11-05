#!/usr/bin/env python3
"""folder-ops 启动入口。

GUI：
    python3 main.py
命令行（默认 dry-run 预览，加 --apply 才真正执行）：
    python3 main.py --source ~/Downloads --dry-run
    python3 main.py --source ~/Downloads --apply --json-report report.json
    python3 main.py --print-default-rules
"""
from __future__ import annotations

import argparse
import json
import logging
import queue
import sys
from pathlib import Path

from folder_ops import APP_TITLE, __version__
from folder_ops.logging_setup import setup_logging
from folder_ops.rules import RuleEngine, RuleError, RuleSettings, default_rules_payload, load_rules

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="folder-ops",
        description="规则驱动的文件夹运维套件：分类、转移、解压、清理空目录。",
    )
    parser.add_argument("--version", action="version", version=f"folder-ops {__version__}")
    parser.add_argument("--rules", type=Path, help="规则文件路径（默认使用应用数据目录下的 rules.json）")
    parser.add_argument("--source", type=Path, action="append", default=[], help="来源文件夹，可重复")
    parser.add_argument("--dry-run", action="store_true", help="只预览不修改磁盘（命令行默认行为）")
    parser.add_argument("--apply", action="store_true", help="真正执行动作")
    parser.add_argument("--json-report", type=Path, help="把执行报告写入 JSON 文件")
    parser.add_argument("--print-default-rules", action="store_true", help="输出默认规则 JSON 后退出")
    parser.add_argument("--gui", action="store_true", help="强制启动图形界面（默认无参数即 GUI）")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if args.print_default_rules:
        print(json.dumps(default_rules_payload(), ensure_ascii=False, indent=2))
        return 0

    if not args.source:
        print("缺少 --source 参数；如需图形界面请直接运行 python3 main.py", file=sys.stderr)
        return 2
    for folder in args.source:
        if not folder.is_dir():
            print(f"来源不是有效文件夹：{folder}", file=sys.stderr)
            return 2

    try:
        rules, settings, _ = load_rules(args.rules)
    except RuleError as exc:
        print(f"规则文件非法：{exc}", file=sys.stderr)
        return 2

    dry_run = not args.apply
    engine = RuleEngine(rules, settings)
    report = engine.run(args.source, dry_run=dry_run)
    print(f"扫描 {report.scanned} 个文件，命中规则 {report.matched} 个，未命中 {report.unmatched} 个")
    print(
        f"移动 {report.moved} / 复制 {report.copied} / 解压 {report.extracted} / "
        f"跳过 {report.skipped} / 失败 {report.failed} / 预览 {report.planned}"
    )
    if report.cleanup_removed:
        print(f"清理空目录 {report.cleanup_removed} 个")
    print("DRY-RUN：未修改磁盘" if dry_run else "已执行全部动作")

    if args.json_report:
        args.json_report.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"报告已写入：{args.json_report}")
    elif dry_run:
        print(json.dumps(report.as_dict(), ensure_ascii=False))
    return 1 if report.failed else 0


def run_gui() -> int:
    import tkinter as tk

    from folder_ops import macos
    from folder_ops.config import load_config
    from folder_ops.ui import DND_AVAILABLE, FolderOpsApp

    sys.argv[:] = macos.normalize_argv(sys.argv)
    log_queue: "queue.Queue[str]" = queue.Queue()
    log_path = setup_logging(log_queue=log_queue)
    LOGGER.info("应用启动：argv=%s frozen=%s", sys.argv[1:], getattr(sys, "frozen", False))

    root, dnd_ready = _create_root(tk)
    root.title(APP_TITLE)
    FolderOpsApp(root, load_config(), log_path, log_queue)
    if not dnd_ready:
        LOGGER.warning("未安装 tkinterdnd2，拖拽已降级为按钮选择")
        if not getattr(sys, "frozen", False):
            print("提示：未安装 tkinterdnd2，拖拽已降级为按钮选择（pip install tkinterdnd2）")
    root.mainloop()
    LOGGER.info("应用退出")
    return 0


def _create_root(tk_module):
    if DND_AVAILABLE:
        try:
            from tkinterdnd2 import TkinterDnD

            return TkinterDnD.Tk(), True
        except Exception:  # pragma: no cover - 依赖运行环境
            pass
    return tk_module.Tk(), False


def main() -> int:
    for arg in sys.argv[1:]:
        if arg in ("-h", "--help", "--version"):
            build_parser().parse_args()
            return 0
    args = build_parser().parse_args()
    cli_mode = any(
        [args.source, args.print_default_rules, args.json_report, args.rules, args.apply]
    )
    if args.gui or not cli_mode:
        return run_gui()
    setup_logging()
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
