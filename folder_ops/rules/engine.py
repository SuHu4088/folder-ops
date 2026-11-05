"""规则引擎主流程：扫描 → 匹配 → 执行动作 → 汇总（可选清理空目录）。

线程安全：每个实例只在一个任务线程内使用；Vault 自身加锁。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ..archive.vault import PasswordVault
from ..cleanup import remove_empty_dirs
from ..platform_utils import human_size
from ..scanner import FileTask, ScanOptions, ScanResult, scan_folders
from . import actions as actions_mod
from .conditions import evaluate
from .models import Rule, RuleSettings

LOGGER = logging.getLogger(__name__)


@dataclass
class RuleOutcome:
    """单个文件在单条动作上的结果。"""

    source: Path
    rule_id: str
    rule_name: str
    action: str
    status: str
    dest: Path | None = None
    message: str = ""
    elapsed: float = 0.0


@dataclass
class EngineReport:
    scanned: int = 0
    scanned_bytes: int = 0
    matched: int = 0
    unmatched: int = 0
    executed: int = 0
    moved: int = 0
    copied: int = 0
    extracted: int = 0
    skipped: int = 0
    failed: int = 0
    planned: int = 0
    cleanup_removed: int = 0
    cleanup_failed: int = 0
    dry_run: bool = False
    cancelled: bool = False
    duration: float = 0.0
    outcomes: list[RuleOutcome] = field(default_factory=list)

    @property
    def done(self) -> int:
        return self.moved + self.copied + self.extracted

    def summary(self) -> dict:
        return {
            "scanned": self.scanned,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "executed": self.executed,
            "moved": self.moved,
            "copied": self.copied,
            "extracted": self.extracted,
            "skipped": self.skipped,
            "failed": self.failed,
            "planned": self.planned,
            "cleanup_removed": self.cleanup_removed,
            "dry_run": self.dry_run,
            "duration": round(self.duration, 3),
        }

    def as_dict(self) -> dict:
        data = self.summary()
        data["outcomes"] = [
            {
                "source": str(item.source),
                "rule": item.rule_id,
                "action": item.action,
                "status": item.status,
                "dest": str(item.dest) if item.dest else "",
                "message": item.message,
            }
            for item in self.outcomes
        ]
        return data


@dataclass
class RuleSummary:
    """供 GUI 复用 CutWorker 的汇总字段命名。"""

    total: int
    done: int
    skipped: int
    failed: int
    planned: int
    cleanup_removed: int
    duration: float
    dry_run: bool
    cancelled: bool
    mechanism: str = "rules"
    verified_count: int = 0
    extracted: int = 0
    matched: int = 0
    unmatched: int = 0


class RuleEngine:
    """按优先级顺序匹配规则，首个命中的规则执行其全部动作。"""

    def __init__(
        self,
        rules: Iterable[Rule],
        settings: RuleSettings | None = None,
        vault: Optional[PasswordVault] = None,
        cancel_event=None,
        on_file_start=None,
        on_progress=None,
    ):
        self.rules = sorted(
            [rule for rule in rules if rule.enabled], key=lambda item: (item.priority, item.id)
        )
        self.settings = settings or RuleSettings()
        self.vault = vault
        self._created_vault = False
        self.cancel_event = cancel_event
        self.on_file_start = on_file_start
        self.on_progress = on_progress

    # -- 匹配 --------------------------------------------------------------
    @staticmethod
    def rule_matches(rule: Rule, path: Path, stat_result) -> bool:
        results = [evaluate(condition, path, stat_result) for condition in rule.conditions]
        if rule.match_mode == "all":
            return all(results)
        return any(results)

    def match_rule(self, task: FileTask) -> Rule | None:
        try:
            stat_result = task.source.stat()
        except OSError as exc:
            LOGGER.warning("无法读取文件属性：%s | %s", task.source, exc)
            return None
        for rule in self.rules:
            if self.rule_matches(rule, task.source, stat_result):
                return rule
        return None

    # -- 执行 --------------------------------------------------------------
    def run(self, folders: Iterable[Path], dry_run: bool = False) -> EngineReport:
        started = time.monotonic()
        report = EngineReport(dry_run=dry_run)
        scan = scan_folders(
            folders,
            ScanOptions(
                recursion=self.settings.recursion,
                ignore_ds_store=self.settings.ignore_ds_store,
            ),
        )
        report.scanned = len(scan.files)
        report.scanned_bytes = scan.total_bytes
        LOGGER.info(
            "规则引擎启动 | 规则=%d | 文件=%d | 合计=%s | dry-run=%s",
            len(self.rules), report.scanned, human_size(scan.total_bytes), dry_run,
        )

        reserved: dict[str, set] = {}
        needs_cleanup = self.settings.cleanup_empty

        try:
            for index, task in enumerate(scan.files, start=1):
                if self._cancelled():
                    report.cancelled = True
                    break
                if self.on_file_start:
                    self.on_file_start(index, report.scanned, task)
                rule = self.match_rule(task)
                if rule is None:
                    report.unmatched += 1
                    self._emit_progress(report, index, task, None)
                    continue

                report.matched += 1
                if any(action.type == "cleanup_empty" for action in rule.actions):
                    needs_cleanup = True

                for action in rule.actions:
                    if self._cancelled():
                        report.cancelled = True
                        break
                    if action.type == "cleanup_empty":
                        continue
                    outcome = self._execute(rule, action, task, reserved, dry_run)
                    report.outcomes.append(outcome)
                    if outcome.status == actions_mod.STATUS_OK:
                        if action.type == "move":
                            report.moved += 1
                        elif action.type == "copy":
                            report.copied += 1
                        elif action.type == "extract":
                            report.extracted += 1
                        report.executed += 1
                    elif outcome.status == actions_mod.STATUS_PLANNED:
                        report.planned += 1
                    elif outcome.status == actions_mod.STATUS_SKIPPED:
                        report.skipped += 1
                    else:
                        report.failed += 1
                    # 移动成功后源文件已不在原位，后续动作没有意义。
                    if action.type == "move" and outcome.status in (
                        actions_mod.STATUS_OK, actions_mod.STATUS_PLANNED
                    ):
                        break
                self._emit_progress(report, index, task, rule)
        finally:
            if needs_cleanup and not report.cancelled and not dry_run:
                report.cleanup_removed, report.cleanup_failed = self._cleanup(scan)
            if self._created_vault and self.vault is not None:
                self.vault.close()

        report.duration = time.monotonic() - started
        LOGGER.info(
            "规则引擎结束 | 命中=%d | 执行=%d | 移动=%d | 复制=%d | 解压=%d | "
            "跳过=%d | 失败=%d | 清理目录=%d | 取消=%s | 耗时=%.2fs",
            report.matched, report.executed, report.moved, report.copied,
            report.extracted, report.skipped, report.failed,
            report.cleanup_removed, report.cancelled, report.duration,
        )
        return report

    # -- 内部 --------------------------------------------------------------
    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _vault_for_extract(self) -> PasswordVault | None:
        if self.vault is None and self.settings.password_module_enabled:
            self.vault = PasswordVault(
                Path(self.settings.vault_path).expanduser() if self.settings.vault_path else None
            )
            self.vault.open()
            self._created_vault = True
        return self.vault

    def _execute(self, rule, action, task, reserved, dry_run) -> RuleOutcome:
        started = time.monotonic()
        if action.type in ("move", "copy"):
            target = actions_mod.resolve_target(action, self.settings, task)
            key = str(target)
            if key not in reserved:
                reserved[key] = actions_mod.preload_reserved(target)
            result = actions_mod.execute_transfer(
                action, task, self.settings,
                dry_run=dry_run, reserved=reserved[key],
            )
        elif action.type == "extract":
            # dry-run 不应创建/写密码库，保持“预览零副作用”
            vault = None if dry_run else self._vault_for_extract()
            result = actions_mod.execute_extract(
                action, task, self.settings, vault, dry_run=dry_run
            )
        else:
            result = actions_mod.ActionResult(
                actions_mod.STATUS_SKIPPED, f"未知动作：{action.type}"
            )

        outcome = RuleOutcome(
            source=task.source, rule_id=rule.id, rule_name=rule.name,
            action=action.type, status=result.status, dest=result.dest,
            message=result.message, elapsed=time.monotonic() - started,
        )
        level = logging.WARNING if result.status == actions_mod.STATUS_FAILED else logging.INFO
        LOGGER.log(
            level, "规则动作 | 文件=%s | 规则=%s | 动作=%s | 目标=%s | 状态=%s | %s",
            task.source.name, rule.name, action.type,
            result.dest or "-", result.status, result.message,
        )
        return outcome

    def _cleanup(self, scan: ScanResult) -> tuple[int, int]:
        protected = list(scan.tops)
        if self.settings.target_root:
            protected.append(Path(self.settings.target_root).expanduser())
        if self.settings.archive_output_root:
            protected.append(Path(self.settings.archive_output_root).expanduser())
        LOGGER.info("清理空目录：候选 %d 个（顶层目录受保护）", len(scan.cleanup_dirs))
        report = remove_empty_dirs(
            scan.cleanup_dirs, protected=protected,
            ignore_metadata=self.settings.ignore_ds_store,
        )
        return len(report.removed), len(report.failed)

    def _emit_progress(self, report: EngineReport, index: int, task: FileTask, rule) -> None:
        if not self.on_progress:
            return
        self.on_progress({
            "index": index,
            "total": report.scanned,
            "done": report.done,
            "skipped": report.skipped,
            "failed": report.failed,
            "planned": report.planned,
            "name": task.source.name,
            "path": str(task.source),
            "rule": rule.name if rule else "",
        })
