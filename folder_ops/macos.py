"""macOS 运行期适配：系统外观、应用菜单、窗口置前、启动参数。

仅在 macOS 生效；其他平台为安全的空实现，保证 Windows/Linux 行为不变。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tkinter as tk

LOGGER = logging.getLogger(__name__)
IS_MACOS = sys.platform == "darwin"

VALID_APPEARANCE = ("dark", "light")


def system_appearance() -> str:
    """返回系统外观：dark / light。

    优先使用 FOLDEROPS_THEME 环境变量覆盖（便于演示与截图），
    其次在 macOS 读取 AppleInterfaceStyle，其他平台沿用项目默认深色。
    """
    override = os.environ.get("FOLDEROPS_THEME", "").strip().lower()
    if override in VALID_APPEARANCE:
        return override
    if not IS_MACOS:
        return "dark"
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.debug("读取 AppleInterfaceStyle 失败，回退浅色：%s", exc)
        return "light"
    value = (result.stdout or "").strip()
    if result.returncode == 0 and value and "dark" in value.lower():
        return "dark"
    return "light"


def configure_app(root: tk.Misc, on_quit) -> None:
    """注册 macOS 应用级命令：Cmd+Q 退出、Dock 点击重新置前、偏好设置入口。"""
    if not IS_MACOS:
        return
    try:  # 应用菜单里显示 folder-ops 而不是 Python/Tk
        root.tk.call("tk", "appname", "folder-ops")
    except tk.TclError:
        pass
    try:
        root.createcommand("tk::mac::Quit", on_quit)
    except tk.TclError as exc:
        LOGGER.debug("注册 tk::mac::Quit 失败：%s", exc)
    try:
        root.createcommand("tk::mac::ReopenApplication", lambda: bring_to_front(root))
    except tk.TclError as exc:
        LOGGER.debug("注册 ReopenApplication 失败：%s", exc)


def bring_to_front(root: tk.Misc, delay_ms: int = 250) -> None:
    """启动后把窗口带到前台（等价 NSApp.activate + orderFront）。"""
    def _raise() -> None:
        try:
            root.deiconify()
            root.lift()
            root.focus_force()
        except tk.TclError:
            pass

    root.after(delay_ms, _raise)


def normalize_argv(argv) -> list:
    """过滤 macOS 通过 Finder 启动时注入的 -psn_xxx 参数。"""
    return [arg for arg in argv if not str(arg).startswith("-psn_")]
