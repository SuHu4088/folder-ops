"""深色主题：集中定义配色、字体与 ttk 样式，适配 macOS / Windows。"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

DARK_COLORS = {
    "bg": "#1b1d21",
    "panel": "#23262c",
    "panel_alt": "#2a2e35",
    "field": "#16181c",
    "border": "#3a3f48",
    "fg": "#e8eaed",
    "muted": "#9aa1ab",
    "accent": "#4c9dff",
    "accent_hover": "#6fb2ff",
    "accent_pressed": "#2f7fdc",
    "success": "#3fb950",
    "warning": "#d29922",
    "danger": "#f85149",
    "danger_active": "#3a2a2a",
    "danger_pressed": "#4a2b2b",
    "selection": "#2f5d91",
}

LIGHT_COLORS = {
    "bg": "#eceef1",
    "panel": "#ffffff",
    "panel_alt": "#e3e6eb",
    "field": "#ffffff",
    "border": "#c4cad4",
    "fg": "#1b1f24",
    "muted": "#5b636e",
    "accent": "#2563eb",
    "accent_hover": "#3b82f6",
    "accent_pressed": "#1d4ed8",
    "success": "#15803d",
    "warning": "#b45309",
    "danger": "#dc2626",
    "danger_active": "#fde8e8",
    "danger_pressed": "#fbd5d5",
    "selection": "#bfdbfe",
}

COLORS = DARK_COLORS

IS_MACOS = sys.platform == "darwin"


def ui_font(root: tk.Misc, size: int = 12, weight: str = "normal") -> tuple:
    families = set(tkfont.families(root))
    candidates = (
        ("SF Pro Text", "PingFang SC", "Helvetica Neue", "Arial")
        if IS_MACOS
        else ("Microsoft YaHei UI", "Segoe UI", "Arial")
    )
    for name in candidates:
        if name in families:
            return (name, size, weight)
    return ("TkDefaultFont", size, weight)


def mono_font(root: tk.Misc, size: int = 10) -> tuple:
    families = set(tkfont.families(root))
    for name in ("SF Mono", "Menlo", "Consolas", "Courier New"):
        if name in families:
            return (name, size)
    return ("TkFixedFont", size)


def apply_theme(root: tk.Misc, base_size: int = 12, appearance: str = "dark") -> dict:
    """应用 clam 主题并返回字体字典，供 Text 等原生控件使用。

    appearance 取 dark / light，由调用方（macOS 下读取系统外观）决定，
    切换后全局 COLORS 同步指向对应调色板。
    """
    global COLORS
    COLORS = LIGHT_COLORS if appearance == "light" else DARK_COLORS
    c = COLORS
    root.configure(bg=c["bg"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    font_base = ui_font(root, base_size)
    font_small = ui_font(root, base_size - 1)
    font_tiny = ui_font(root, base_size - 2)
    font_title = ui_font(root, base_size + 8, "bold")
    font_value = ui_font(root, base_size + 5, "bold")
    font_button = ui_font(root, base_size, "bold")

    style.configure(".", background=c["bg"], foreground=c["fg"], font=font_base)
    style.configure("TFrame", background=c["bg"])
    style.configure("Panel.TFrame", background=c["panel"])
    style.configure("Card.TFrame", background=c["panel"], relief="flat")

    style.configure("TLabel", background=c["bg"], foreground=c["fg"], font=font_base)
    style.configure("Panel.TLabel", background=c["panel"], foreground=c["fg"])
    style.configure("Title.TLabel", background=c["bg"], foreground=c["fg"], font=font_title)
    style.configure("Subtitle.TLabel", background=c["bg"], foreground=c["muted"], font=font_small)
    style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"], font=font_small)
    style.configure("Tiny.TLabel", background=c["bg"], foreground=c["muted"], font=font_tiny)
    style.configure("StatName.TLabel", background=c["panel"], foreground=c["muted"], font=font_tiny)
    style.configure("StatValue.TLabel", background=c["panel"], foreground=c["fg"], font=font_value)
    style.configure("Success.TLabel", background=c["bg"], foreground=c["success"], font=font_small)
    style.configure("Warn.TLabel", background=c["bg"], foreground=c["warning"], font=font_small)
    style.configure("Field.TLabel", background=c["panel"], foreground=c["muted"], font=font_small)

    style.configure(
        "TLabelframe",
        background=c["bg"],
        bordercolor=c["border"],
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=c["bg"],
        foreground=c["muted"],
        font=font_small,
    )

    style.configure(
        "TButton",
        background=c["panel_alt"],
        foreground=c["fg"],
        bordercolor=c["border"],
        focusthickness=0,
        relief="flat",
        padding=(12, 7),
        font=font_small,
    )
    style.map(
        "TButton",
        background=[("disabled", c["panel"]), ("pressed", c["border"]), ("active", c["border"])],
        foreground=[("disabled", c["muted"])],
    )
    style.configure(
        "Accent.TButton",
        background=c["accent"],
        foreground="#ffffff",
        bordercolor=c["accent"],
        padding=(16, 8),
        font=font_button,
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", c["panel_alt"]), ("pressed", c["accent_pressed"]), ("active", c["accent_hover"])],
        foreground=[("disabled", c["muted"]), ("!disabled", "#ffffff")],
    )
    style.configure(
        "Danger.TButton",
        background=c["panel_alt"],
        foreground=c["danger"],
        bordercolor=c["border"],
        padding=(16, 8),
        font=font_button,
    )
    style.map(
        "Danger.TButton",
        background=[("disabled", c["panel"]), ("active", c["danger_active"]), ("pressed", c["danger_pressed"])],
        foreground=[("disabled", c["muted"])],
    )

    style.configure(
        "TRadiobutton",
        background=c["panel"],
        foreground=c["fg"],
        font=font_small,
        indicatorcolor=c["field"],
        focuscolor=c["panel"],
        padding=(2, 1),
    )
    style.map(
        "TRadiobutton",
        background=[("active", c["panel"])],
        foreground=[("disabled", c["muted"])],
        indicatorcolor=[("selected", c["accent"]), ("disabled", c["border"])],
    )
    style.configure(
        "TCheckbutton",
        background=c["panel"],
        foreground=c["fg"],
        font=font_small,
        indicatorcolor=c["field"],
        focuscolor=c["panel"],
        padding=(2, 1),
    )
    style.map(
        "TCheckbutton",
        background=[("active", c["panel"])],
        foreground=[("disabled", c["muted"])],
        indicatorcolor=[("selected", c["accent"]), ("disabled", c["border"])],
    )

    style.configure(
        "TEntry",
        fieldbackground=c["field"],
        foreground=c["fg"],
        insertcolor=c["fg"],
        bordercolor=c["border"],
        lightcolor=c["field"],
        darkcolor=c["field"],
        padding=(8, 6),
        font=font_small,
    )
    style.map("TEntry", bordercolor=[("focus", c["accent"])])

    style.configure(
        "Treeview",
        background=c["field"],
        fieldbackground=c["field"],
        foreground=c["fg"],
        bordercolor=c["border"],
        lightcolor=c["border"],
        darkcolor=c["border"],
        rowheight=26,
        font=font_small,
    )
    style.map(
        "Treeview",
        background=[("selected", c["selection"])],
        foreground=[("selected", c["fg"])],
    )
    style.configure(
        "Treeview.Heading",
        background=c["panel_alt"],
        foreground=c["muted"],
        bordercolor=c["border"],
        relief="flat",
        font=font_small,
        padding=(8, 6),
    )
    style.map("Treeview.Heading", background=[("active", c["panel_alt"])])

    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=c["field"],
        background=c["accent"],
        bordercolor=c["border"],
        lightcolor=c["accent"],
        darkcolor=c["accent"],
        thickness=14,
    )
    style.configure(
        "Vertical.TScrollbar",
        background=c["panel_alt"],
        troughcolor=c["bg"],
        bordercolor=c["border"],
        arrowcolor=c["muted"],
        relief="flat",
    )
    style.map("Vertical.TScrollbar", background=[("active", c["border"])])
    style.configure("TSeparator", background=c["border"])

    # 模式切换标签页：足够的水平内边距，避免两个中文标签互相挤压
    style.configure(
        "TNotebook",
        background=c["bg"],
        bordercolor=c["border"],
        tabmargins=(0, 4, 0, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=c["panel"],
        foreground=c["muted"],
        bordercolor=c["border"],
        padding=(16, 7),
        font=font_small,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", c["panel_alt"]), ("active", c["panel_alt"])],
        foreground=[("selected", c["fg"]), ("active", c["fg"])],
    )

    return {
        "base": font_base,
        "small": font_small,
        "tiny": font_tiny,
        "mono": mono_font(root, 10),
        "title": font_title,
        "value": font_value,
        "colors": c,
    }
