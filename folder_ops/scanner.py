"""扫描：按递归范围生成待转移文件清单与可清理目录清单。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Tuple

from .platform_utils import is_macos_metadata, is_symlink, long_path, same_path_key

LOGGER = logging.getLogger(__name__)

RECURSION_LABELS = {
    "level1": "仅第一层文件",
    "level2": "所选文件夹 + 二级子文件夹",
    "full": "全递归（所有层级）",
}


@dataclass
class ScanOptions:
    recursion: str = "full"
    ignore_ds_store: bool = True


@dataclass
class FileTask:
    source: Path
    top: Path
    rel_dir: str
    size: int = 0

    @property
    def display_source(self) -> str:
        return str(self.source)


@dataclass
class SkippedItem:
    path: Path
    reason: str


@dataclass
class ScanResult:
    files: List[FileTask] = field(default_factory=list)
    skipped: List[SkippedItem] = field(default_factory=list)
    cleanup_dirs: List[Path] = field(default_factory=list)
    tops: List[Path] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.files)


def _strip_long_prefix(path: Path) -> Path:
    r"""去掉 Windows \\?\ 前缀，便于界面展示与 pathlib 运算。"""
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + text[8:])
    if text.startswith("\\\\?\\"):
        return Path(text[4:])
    return path


def _scandir(dirpath: Path):
    try:
        return os.scandir(str(dirpath))
    except OSError:
        return os.scandir(long_path(dirpath))


def _entry_path(entry: os.DirEntry) -> Path:
    return _strip_long_prefix(Path(entry.path))


def normalize_roots(folders: Iterable[Path]) -> Tuple[List[Path], List[SkippedItem]]:
    """去重并剔除已被上级选中目录覆盖的重复项。"""
    roots: List[Path] = []
    skipped: List[SkippedItem] = []
    seen = set()
    candidates = []
    for folder in folders:
        path = Path(folder)
        if not path.is_dir():
            skipped.append(SkippedItem(path, "不是有效文件夹"))
            continue
        key = same_path_key(path)
        if key in seen:
            skipped.append(SkippedItem(path, "重复添加，已忽略"))
            continue
        seen.add(key)
        candidates.append(path)

    candidates.sort(key=lambda p: len(os.path.abspath(str(p))))
    kept: List[Path] = []
    for path in candidates:
        key = same_path_key(path)
        nested_in = None
        for parent in kept:
            parent_key = same_path_key(parent)
            if key == parent_key or key.startswith(parent_key.rstrip(os.sep) + os.sep):
                nested_in = parent
                break
        if nested_in is not None:
            skipped.append(SkippedItem(path, f"已被上级所选文件夹覆盖：{nested_in}"))
            continue
        kept.append(path)
    roots = kept
    return roots, skipped


def _collect_file(
    entry: os.DirEntry,
    top: Path,
    rel_dir: str,
    options: ScanOptions,
    result: ScanResult,
) -> None:
    path = _entry_path(entry)
    name = entry.name
    if is_symlink(path):
        result.skipped.append(SkippedItem(path, "符号链接（按策略不跟随、不移动）"))
        return
    if options.ignore_ds_store and is_macos_metadata(name):
        result.skipped.append(SkippedItem(path, "macOS 元数据文件，按设置忽略"))
        return
    try:
        if not entry.is_file(follow_symlinks=False):
            result.skipped.append(SkippedItem(path, "非普通文件（设备/管道等）"))
            return
        size = entry.stat(follow_symlinks=False).st_size
    except OSError as exc:
        result.skipped.append(SkippedItem(path, f"读取属性失败：{exc}"))
        return
    result.files.append(FileTask(source=path, top=top, rel_dir=rel_dir, size=size))


def _scan_level1(top: Path, options: ScanOptions, result: ScanResult) -> None:
    try:
        with _scandir(top) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    # 第一层子文件夹本身不进入、不纳入清理范围
                    continue
                _collect_file(entry, top, "", options, result)
    except OSError as exc:
        result.skipped.append(SkippedItem(top, f"目录读取失败：{exc}"))


def _scan_level2(top: Path, options: ScanOptions, result: ScanResult) -> None:
    try:
        with _scandir(top) as entries:
            subdirs = []
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    subdir = _entry_path(entry)
                    if is_symlink(subdir):
                        result.skipped.append(SkippedItem(subdir, "符号链接目录（不跟随）"))
                        continue
                    subdirs.append(subdir)
                else:
                    _collect_file(entry, top, "", options, result)
    except OSError as exc:
        result.skipped.append(SkippedItem(top, f"目录读取失败：{exc}"))
        return

    for subdir in subdirs:
        result.cleanup_dirs.append(subdir)
        try:
            with _scandir(subdir) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        continue  # 二级以下不进入
                    _collect_file(entry, top, subdir.name, options, result)
        except OSError as exc:
            result.skipped.append(SkippedItem(subdir, f"子目录读取失败：{exc}"))


def _scan_full(top: Path, options: ScanOptions, result: ScanResult) -> None:
    stack: List[Tuple[Path, str]] = [(top, "")]
    while stack:
        dirpath, rel_dir = stack.pop()
        try:
            with _scandir(dirpath) as entries:
                for entry in entries:
                    path = _entry_path(entry)
                    if entry.is_dir(follow_symlinks=False):
                        if is_symlink(path):
                            result.skipped.append(SkippedItem(path, "符号链接目录（不跟随）"))
                            continue
                        next_rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                        result.cleanup_dirs.append(path)
                        stack.append((path, next_rel))
                    else:
                        _collect_file(entry, top, rel_dir, options, result)
        except OSError as exc:
            result.skipped.append(SkippedItem(dirpath, f"目录读取失败：{exc}"))


def scan_folders(folders: Iterable[Path], options: ScanOptions) -> ScanResult:
    """扫描入口：返回文件清单（按路径排序保证可复现）。"""
    roots, root_skips = normalize_roots(folders)
    result = ScanResult(tops=list(roots))
    result.skipped.extend(root_skips)

    for top in roots:
        if options.recursion == "level1":
            _scan_level1(top, options, result)
        elif options.recursion == "level2":
            _scan_level2(top, options, result)
        else:
            _scan_full(top, options, result)

    result.files.sort(key=lambda item: (str(item.top).casefold(), item.rel_dir.casefold(), item.source.name.casefold()))
    result.cleanup_dirs = sorted(set(result.cleanup_dirs), key=lambda p: len(str(p)), reverse=True)
    LOGGER.debug(
        "扫描完成：根目录=%s，文件=%s，跳过=%s，可清理目录=%s，范围=%s",
        len(result.tops), len(result.files), len(result.skipped),
        len(result.cleanup_dirs), options.recursion,
    )
    return result
