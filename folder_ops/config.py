"""配置持久化：窗口尺寸、目标目录、执行机制与各项开关。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict

from .platform_utils import config_path

LOGGER = logging.getLogger(__name__)

VALID_RECURSION = ("level1", "level2", "full")
VALID_CONFLICT = ("skip", "rename")
VALID_MECHANISM = ("copy", "move")


@dataclass
class WindowState:
    width: int = 1120
    height: int = 880


@dataclass
class RunOptions:
    """执行机制 + 各项开关。"""

    mechanism: str = "copy"          # copy（只复制，默认校验） | move（移动，不校验）
    recursion: str = "full"          # level1 | level2 | full
    cleanup_empty: bool = True       # 转移后清理空目录
    conflict: str = "rename"         # skip | rename
    verify: bool = True              # MD5 + SHA1 双校验（仅 copy 模式生效）
    ignore_ds_store: bool = True     # 忽略 macOS 元数据文件
    dry_run: bool = False            # 仅预览，不执行

    def normalized(self) -> "RunOptions":
        data = asdict(self)
        if data["mechanism"] not in VALID_MECHANISM:
            data["mechanism"] = "copy"
        if data["recursion"] not in VALID_RECURSION:
            data["recursion"] = "full"
        if data["conflict"] not in VALID_CONFLICT:
            data["conflict"] = "rename"
        for key in ("cleanup_empty", "verify", "ignore_ds_store", "dry_run"):
            data[key] = bool(data[key])
        return RunOptions(**data)


@dataclass
class AppConfig:
    window: WindowState = field(default_factory=WindowState)
    target_dir: str = ""
    options: RunOptions = field(default_factory=RunOptions)

    def normalized(self) -> "AppConfig":
        width = max(900, min(int(self.window.width or 1120), 4000))
        height = max(620, min(int(self.window.height or 800), 3000))
        return AppConfig(
            window=WindowState(width=width, height=height),
            target_dir=self.target_dir or "",
            options=self.options.normalized(),
        )


def load_config(path: Path = None) -> AppConfig:
    path = path or config_path()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()
    try:
        window_raw = raw.get("window") or {}
        options_raw = raw.get("options") or {}
        window = WindowState(
            width=int(window_raw.get("width", 1120)),
            height=int(window_raw.get("height", 880)),
        )
        options = RunOptions(
            mechanism=str(options_raw.get("mechanism", "copy")),
            recursion=str(options_raw.get("recursion", "full")),
            cleanup_empty=bool(options_raw.get("cleanup_empty", True)),
            conflict=str(options_raw.get("conflict", "rename")),
            verify=bool(options_raw.get("verify", True)),
            ignore_ds_store=bool(options_raw.get("ignore_ds_store", True)),
            dry_run=bool(options_raw.get("dry_run", False)),
        )
        config = AppConfig(
            window=window,
            target_dir=str(raw.get("target_dir") or ""),
            options=options,
        )
        return config.normalized()
    except (TypeError, ValueError):
        LOGGER.warning("配置文件内容异常，已回退默认值: %s", path)
        return AppConfig()


def save_config(config: AppConfig, path: Path = None) -> bool:
    path = Path(path or config_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = asdict(config.normalized())
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except OSError as exc:
        LOGGER.error("保存配置失败: %s", exc)
        return False
