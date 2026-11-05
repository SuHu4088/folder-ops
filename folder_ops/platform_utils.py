"""跨平台文件系统辅助函数。

集中处理 Windows 长路径、符号链接/联接点、macOS 元数据文件、
配置与日志目录等内容，避免这些差异散落在业务代码里。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

# Windows 传统路径上限；超过后必须使用 \\?\ 前缀或 \\?\UNC\ 前缀。
WINDOWS_LONG_PATH_THRESHOLD = 240

IGNORED_MACOS_FILES = {".DS_Store", "._.DS_Store"}


def app_data_dir() -> Path:
    """返回平台标准的应用数据目录（不创建）。"""
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif IS_MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "FolderOps"


def config_path() -> Path:
    return app_data_dir() / "config.json"


def default_log_dir() -> Path:
    return app_data_dir() / "logs"


def long_path(path) -> str:
    """返回适合文件系统调用的路径字符串。

    Windows 下对超过阈值或本身就是 UNC 的路径添加长路径前缀（问号前缀形式），
    从而支持超长路径与超过 260 字符的目录名；其他平台原样返回。
    """
    text = str(path)
    if not IS_WINDOWS:
        return text
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):  # UNC: \\server\share\...
        return "\\\\?\\UNC\\" + absolute[2:]
    if len(absolute) >= WINDOWS_LONG_PATH_THRESHOLD:
        return "\\\\?\\" + absolute
    return absolute


def is_symlink(path) -> bool:
    """判断是否为符号链接（含 Windows 目录联接/重解析点）。"""
    try:
        if os.path.islink(long_path(path)):
            return True
    except OSError:
        return False
    if IS_WINDOWS:
        try:
            stat_result = os.lstat(long_path(path))
            attrs = getattr(stat_result, "st_file_attributes", 0)
            # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            return bool(attrs & 0x400)
        except OSError:
            return False
    return False


def is_macos_metadata(name: str) -> bool:
    """.DS_Store 及 AppleDouble 文件（._xxx）。"""
    return name in IGNORED_MACOS_FILES or (name.startswith("._") and len(name) > 2)


def human_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def human_duration(seconds: float) -> str:
    if seconds <= 0 or seconds != seconds:  # 0 或 NaN
        return "—"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {sec:02d} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes:02d} 分"


def same_path_key(path) -> str:
    """用于比较/去重路径的键：大小写不敏感平台统一小写。"""
    text = os.path.abspath(str(path))
    return text.casefold() if (IS_WINDOWS or IS_MACOS) else text


def set_windows_app_user_model_id() -> None:
    """Windows 任务栏图标归属（可选，失败忽略）。"""
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FolderOps.App")
    except Exception:  # pragma: no cover - 仅美化用途
        pass
