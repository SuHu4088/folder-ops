"""动作执行层：移动 / 复制 / 解压 / 删除空目录。

所有动作都复用已验证的底层实现：
- 移动与复制 → mover.transfer_file（双校验、同名策略、跨盘安全路径）；
- 解压 → archive.service.extract_archive（CRC 三重校验 + 密码库）；
- 删除空目录 → cleanup.remove_empty_dirs（保护顶层目录）。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..archive.service import extract_archive
from ..archive.vault import PasswordVault
from ..mover import MODE_COPY, MODE_MOVE, name_key, resolve_destination, transfer_file
from ..scanner import FileTask
from .models import Action, RuleSettings

LOGGER = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_PLANNED = "planned"


@dataclass
class ActionResult:
    status: str
    message: str = ""
    dest: Path | None = None


def resolve_target(action: Action, settings: RuleSettings, task: FileTask) -> Path:
    """动作目标目录：绝对路径原样使用，相对路径挂到 target_root 或来源根。"""
    raw = str(action.params.get("target") or "").strip()
    if raw:
        candidate = Path(os.path.expandvars(raw)).expanduser()
        if candidate.is_absolute():
            return candidate
        root = Path(settings.target_root).expanduser() if settings.target_root else task.top
        return root / candidate
    if settings.target_root:
        return Path(settings.target_root).expanduser()
    return task.top


def preload_reserved(target: Path) -> set:
    """把目标目录已有文件名加入预占集合，供 dry-run 预览同名冲突。"""
    reserved: set = set()
    try:
        for name in os.listdir(target):
            reserved.add(name_key(name))
    except OSError:
        pass
    return reserved


def execute_transfer(
    action: Action,
    task: FileTask,
    settings: RuleSettings,
    *,
    dry_run: bool,
    reserved: set | None = None,
) -> ActionResult:
    target = resolve_target(action, settings, task)
    conflict = str(action.params.get("conflict") or "rename")
    mechanism = MODE_MOVE if action.type == "move" else MODE_COPY
    verify = bool(action.params.get("verify", action.type == "copy"))

    # 目标就是源文件所在目录时无需动作，避免自我重命名（photo.jpg → photo_1.jpg）。
    try:
        if task.source.parent.resolve() == target.resolve():
            return ActionResult(STATUS_SKIPPED, "源文件已在目标目录，无需移动/复制")
    except OSError:
        pass

    if dry_run:
        try:
            dest, renamed = resolve_destination(target, task.source.name, conflict, reserved)
        except FileExistsError as exc:
            return ActionResult(STATUS_FAILED, f"预览冲突：{exc}")
        if reserved is not None:
            reserved.add(name_key(dest.name))
        label = "移动" if mechanism == MODE_MOVE else "复制"
        return ActionResult(
            STATUS_PLANNED,
            f"计划{label}到 {dest}" + ("（重命名）" if renamed else ""),
            dest,
        )

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ActionResult(STATUS_FAILED, f"目标目录不可用：{exc}")

    result = transfer_file(
        task, target, mechanism=mechanism, conflict=conflict, verify=verify
    )
    status = STATUS_OK if result.status in ("copied", "moved") else (
        STATUS_SKIPPED if result.status == "skipped" else STATUS_FAILED
    )
    return ActionResult(status, result.reason, result.dest)


def execute_extract(
    action: Action,
    task: FileTask,
    settings: RuleSettings,
    vault: PasswordVault | None,
    *,
    dry_run: bool,
) -> ActionResult:
    raw_root = str(action.params.get("target") or "").strip()
    if raw_root:
        root = Path(raw_root).expanduser()
        if not root.is_absolute():
            root = (Path(settings.target_root).expanduser() if settings.target_root else task.top) / root
    elif settings.archive_output_root:
        root = Path(settings.archive_output_root).expanduser()
    else:
        root = task.source.parent

    password_module = bool(
        action.params.get("password_module", settings.password_module_enabled)
    )
    delete_original = bool(
        action.params.get("delete_original", settings.delete_archive_after_verify)
    )

    if dry_run:
        dest = root / task.source.stem
        return ActionResult(
            STATUS_PLANNED,
            f"计划解压到 {dest}，CRC 校验后{'删除' if delete_original else '保留'}原压缩包",
            dest,
        )

    outcome = extract_archive(
        task.source,
        root,
        vault=vault if password_module else None,
        password_module_enabled=password_module,
        delete_original=delete_original,
    )
    mapped = {
        "ok": STATUS_OK,
        "skipped": STATUS_SKIPPED,
        "failed": STATUS_FAILED,
        "unsolved": STATUS_FAILED,
    }.get(outcome.status, STATUS_FAILED)
    return ActionResult(mapped, outcome.message, outcome.dest)
