"""空目录清理：自底向上，仅删除扫描范围内的空目录。

绝不允许删除用户选中的顶层文件夹，也不会删除目标目录。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from .platform_utils import is_macos_metadata, is_symlink, long_path, same_path_key

LOGGER = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    removed: List[Path] = field(default_factory=list)
    kept: List[Path] = field(default_factory=list)
    failed: List[Tuple[Path, str]] = field(default_factory=list)


def _list_entries(dirpath: Path) -> List[str]:
    try:
        return os.listdir(str(dirpath))
    except OSError:
        return os.listdir(long_path(dirpath))


def _remove(path: Path) -> None:
    os.remove(long_path(path))


def remove_empty_dirs(
    dirs: Iterable[Path],
    protected: Optional[Iterable[Path]] = None,
    ignore_metadata: bool = True,
) -> CleanupReport:
    """自底向上删除变空的目录。

    protected 中的路径（顶层所选文件夹、目标目录）及其祖先永不被删除。
    若目录仅剩 macOS 元数据文件且 ignore_metadata=True，先移除元数据再删目录。
    """
    report = CleanupReport()
    protected_keys: Set[str] = set()
    for path in protected or ():
        key = same_path_key(path)
        protected_keys.add(key)
        parent = os.path.dirname(key)
        while parent and parent not in protected_keys:
            protected_keys.add(parent)
            next_parent = os.path.dirname(parent)
            if next_parent == parent:
                break
            parent = next_parent

    ordered = sorted(dirs, key=lambda p: len(str(p)), reverse=True)
    for dirpath in ordered:
        key = same_path_key(dirpath)
        if key in protected_keys:
            report.kept.append(dirpath)
            continue
        if is_symlink(dirpath) or not dirpath.is_dir():
            report.kept.append(dirpath)
            continue
        try:
            names = _list_entries(dirpath)
        except OSError as exc:
            report.failed.append((dirpath, f"无法列出目录：{exc}"))
            continue

        leftovers = names
        if ignore_metadata:
            metadata = [n for n in names if is_macos_metadata(n)]
            leftover_names = [n for n in names if n not in metadata]
            if not leftover_names:
                # 目录只有元数据：先删元数据文件（仅限普通文件）
                for name in metadata:
                    candidate = dirpath / name
                    try:
                        if candidate.is_file() and not is_symlink(candidate):
                            _remove(candidate)
                    except OSError as exc:
                        report.failed.append((candidate, f"移除元数据失败：{exc}"))
                try:
                    names = _list_entries(dirpath)
                except OSError:
                    names = leftover_names
                leftovers = names

        if leftovers:
            report.kept.append(dirpath)
            continue

        try:
            os.rmdir(long_path(dirpath))
            report.removed.append(dirpath)
            LOGGER.debug("已删除空目录：%s", dirpath)
        except OSError as exc:
            report.failed.append((dirpath, f"删除空目录失败：{exc}"))

    return report
