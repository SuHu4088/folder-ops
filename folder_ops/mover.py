"""单文件转移：copy 模式只复制，move 模式才删除源。

机制规则：
- copy：复制到目标，源文件保留；校验开启时先对源做 MD5+SHA1，
  再对目标副本做同样哈希并逐项比对，不一致则删除副本、保留源、记为失败。
- move：不做任何哈希。同盘直接 rename；跨盘/跨设备走“复制 → 确认目标
  存在且大小一致 → 删除源”，任一环节失败都保留源文件。
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .platform_utils import IS_MACOS, IS_WINDOWS, long_path
from .scanner import FileTask

LOGGER = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
MAX_RENAME_ATTEMPTS = 9999

MODE_COPY = "copy"
MODE_MOVE = "move"


@dataclass
class TransferResult:
    status: str  # copied | moved | skipped | failed
    source: Path
    dest: Optional[Path] = None
    reason: str = ""
    mechanism: str = MODE_COPY
    md5_source: str = ""
    md5_target: str = ""
    sha1_source: str = ""
    sha1_target: str = ""
    size: int = 0
    elapsed: float = 0.0
    renamed: bool = False
    cross_device: bool = False
    verified: bool = False


def hash_file(path: Path) -> tuple:
    """一次读取同时计算 MD5 与 SHA1。"""
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    with open(long_path(path), "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
    return md5.hexdigest(), sha1.hexdigest()


def destination_exists(path: Path) -> bool:
    return os.path.exists(long_path(path))


def name_key(name: str) -> str:
    """大小写不敏感平台用于预占/比对的键。"""
    return name.casefold() if (IS_WINDOWS or IS_MACOS) else name


def resolve_destination(
    target_dir: Path,
    name: str,
    conflict: str,
    reserved: Optional[set] = None,
) -> tuple:
    """返回 (目标路径, 是否重命名)。conflict: skip | rename。

    reserved 仅用于 dry-run 预览：把本批次已计划占用的文件名也视为冲突。
    重命名规则：主名_1.ext、主名_2.ext … 递增到第一个不冲突的名字。
    """

    def occupied(path: Path) -> bool:
        if destination_exists(path):
            return True
        return reserved is not None and name_key(path.name) in reserved

    candidate = target_dir / name
    if not occupied(candidate):
        return candidate, False
    if conflict == "skip":
        return candidate, False

    stem, ext = os.path.splitext(name)
    for index in range(1, MAX_RENAME_ATTEMPTS + 1):
        candidate = target_dir / f"{stem}_{index}{ext}"
        if not occupied(candidate):
            return candidate, True
    raise FileExistsError(f"重命名尝试 {MAX_RENAME_ATTEMPTS} 次仍冲突：{name}")


def same_device(source: Path, target_dir: Path) -> bool:
    """判断源与目标目录是否在同一设备/卷。判断失败按跨设备更安全的路径处理。"""
    try:
        return os.stat(long_path(source)).st_dev == os.stat(long_path(target_dir)).st_dev
    except OSError:
        return False


def _temp_path(target_dir: Path, suffix: str) -> Path:
    return target_dir / f".foldercut_tmp_{uuid.uuid4().hex}{suffix}"


def _safe_unlink(path: Path) -> None:
    try:
        os.remove(long_path(path))
    except OSError:
        pass


def _file_size(path: Path) -> int:
    return os.stat(long_path(path)).st_size


def _target_ok(path: Path, expected_size: int) -> bool:
    """最小防御：目标存在、是普通文件、大小一致。"""
    try:
        return os.path.isfile(long_path(path)) and _file_size(path) == expected_size
    except OSError:
        return False


def _copy_once(source: Path, temp: Path) -> Optional[str]:
    try:
        shutil.copy2(long_path(source), long_path(temp))
        return None
    except (OSError, PermissionError, shutil.Error) as exc:
        _safe_unlink(temp)
        return f"复制失败：{exc}"


def _do_copy(
    task: FileTask,
    dest: Path,
    renamed: bool,
    verify: bool,
    result: TransferResult,
) -> TransferResult:
    source = task.source
    try:
        source_size = _file_size(source)
    except OSError as exc:
        result.reason = f"读取源文件失败：{exc}"
        return result
    result.size = source_size

    if verify:
        try:
            result.md5_source, result.sha1_source = hash_file(source)
        except OSError as exc:
            result.reason = f"读取源文件失败，未复制：{exc}"
            return result
        result.verified = True

    temp = _temp_path(dest.parent, source.suffix + ".part")
    error = _copy_once(source, temp)
    if error:
        result.reason = error
        return result

    if verify:
        try:
            result.md5_target, result.sha1_target = hash_file(temp)
        except OSError as exc:
            _safe_unlink(temp)
            result.reason = f"读取目标副本失败：{exc}"
            return result
        if result.md5_source != result.md5_target:
            _safe_unlink(temp)
            result.reason = "MD5 校验不一致，已丢弃副本并保留源文件"
            return result
        if result.sha1_source != result.sha1_target:
            _safe_unlink(temp)
            result.reason = "SHA1 校验不一致，已丢弃副本并保留源文件"
            return result
    else:
        result.verified = False

    if not _target_ok(temp, source_size):
        _safe_unlink(temp)
        result.reason = "目标副本大小与源文件不一致，已丢弃副本"
        return result

    try:
        os.replace(long_path(temp), long_path(dest))
    except OSError as exc:
        _safe_unlink(temp)
        result.reason = f"目标文件落盘失败：{exc}"
        return result

    result.status = "copied"
    result.dest = dest
    result.renamed = renamed
    result.reason = "复制成功，源文件保留" + ("（重命名）" if renamed else "")
    return result


def _do_move_same_device(
    task: FileTask,
    dest: Path,
    renamed: bool,
    result: TransferResult,
) -> TransferResult:
    """同盘 rename：原子且无需哈希。"""
    source = task.source
    try:
        source_size = _file_size(source)
    except OSError as exc:
        result.reason = f"读取源文件失败：{exc}"
        return result
    result.size = source_size

    try:
        os.replace(long_path(source), long_path(dest))
    except (OSError, PermissionError) as exc:
        result.reason = f"同盘重命名失败，源文件保留：{exc}"
        return result

    if not _target_ok(dest, source_size):
        # 极罕见：目标校验不过，尝试回滚，最大限度保住源文件
        try:
            os.replace(long_path(dest), long_path(source))
            result.reason = "目标文件异常，已回滚到源位置"
        except OSError as exc:
            result.reason = f"目标文件异常且回滚失败，请手工检查：{exc}"
        return result

    result.status = "moved"
    result.dest = dest
    result.renamed = renamed
    result.reason = "同盘重命名成功" + ("（重命名）" if renamed else "")
    return result


def _do_move_cross_device(
    task: FileTask,
    dest: Path,
    renamed: bool,
    result: TransferResult,
) -> TransferResult:
    """跨设备：复制 → 确认存在且大小一致 → 删除源；不计算哈希。"""
    source = task.source
    try:
        source_size = _file_size(source)
    except OSError as exc:
        result.reason = f"读取源文件失败：{exc}"
        return result
    result.size = source_size
    result.cross_device = True

    temp = _temp_path(dest.parent, source.suffix + ".part")
    error = _copy_once(source, temp)
    if error:
        result.reason = error
        return result

    if not _target_ok(temp, source_size):
        _safe_unlink(temp)
        result.reason = "临时副本不存在或大小不一致，保留源文件"
        return result

    try:
        os.replace(long_path(temp), long_path(dest))
    except OSError as exc:
        _safe_unlink(temp)
        result.reason = f"目标文件落盘失败，保留源文件：{exc}"
        return result

    if not _target_ok(dest, source_size):
        _safe_unlink(dest)
        result.reason = "目标文件大小校验失败，已删除副本并保留源文件"
        return result

    try:
        os.remove(long_path(source))
    except (OSError, PermissionError) as exc:
        result.reason = f"目标已写入但源文件删除失败（源保留，请手工检查）：{exc}"
        return result

    result.status = "moved"
    result.dest = dest
    result.renamed = renamed
    result.reason = "跨设备复制并删除源成功" + ("（重命名）" if renamed else "")
    return result


def transfer_file(
    task: FileTask,
    target_dir: Path,
    mechanism: str = MODE_COPY,
    conflict: str = "rename",
    verify: bool = True,
) -> TransferResult:
    """执行一次文件转移。可预期的文件系统异常都在内部转为失败结果。"""
    started = time.monotonic()
    source = task.source
    result = TransferResult(
        status="failed",
        source=source,
        mechanism=mechanism,
        verified=False,
    )

    if not destination_exists(source):
        result.reason = "源文件不存在"
        result.elapsed = time.monotonic() - started
        return result

    try:
        dest, renamed = resolve_destination(target_dir, source.name, conflict)
    except FileExistsError as exc:
        result.reason = str(exc)
        result.elapsed = time.monotonic() - started
        return result

    if not renamed and destination_exists(dest):
        result.status = "skipped"
        result.dest = dest
        result.reason = "目标目录已存在同名文件，按设置跳过"
        result.elapsed = time.monotonic() - started
        return result

    if os.path.abspath(str(source)) == os.path.abspath(str(dest)):
        result.status = "skipped"
        result.dest = dest
        result.reason = "目标路径与源路径相同（目标目录即源目录），已跳过"
        result.elapsed = time.monotonic() - started
        return result

    if mechanism == MODE_MOVE:
        # 剪切模式绝不计算哈希；verify 参数被忽略
        if same_device(source, target_dir):
            result = _do_move_same_device(task, dest, renamed, result)
        else:
            result = _do_move_cross_device(task, dest, renamed, result)
    else:
        result = _do_copy(task, dest, renamed, verify, result)

    result.elapsed = time.monotonic() - started
    return result
