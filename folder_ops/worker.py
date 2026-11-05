"""后台任务线程：扫描 → 转移 → 空目录清理 → 汇总。

通过队列向主线程汇报，保证 Tk 界面不假死；取消只在文件边界的安全点生效。
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from .cleanup import remove_empty_dirs
from .config import RunOptions
from .mover import MODE_MOVE, name_key, resolve_destination, transfer_file
from .platform_utils import human_size, long_path
from .scanner import ScanResult, ScanOptions, scan_folders

LOGGER = logging.getLogger(__name__)

RECURSION_TEXT = {
    "level1": "仅第一层文件",
    "level2": "所选文件夹 + 二级子文件夹",
    "full": "全递归",
}


@dataclass
class TaskSummary:
    task_id: str
    mechanism: str
    verify: bool
    total: int
    copied: int
    moved: int
    skipped: int
    failed: int
    total_bytes: int
    processed_bytes: int
    duration: float
    verified_count: int
    verify_failed: int
    scan_skipped: int
    cleanup_removed: int
    cleanup_failed: int
    cancelled: bool
    dry_run: bool
    planned: int = 0

    @property
    def done(self) -> int:
        return self.copied + self.moved

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


class CutWorker(threading.Thread):
    """一个任务一个线程；同一时刻只允许一个任务。"""

    def __init__(
        self,
        folders: List[Path],
        target_dir: Path,
        options: RunOptions,
        event_queue: "queue.Queue[dict]",
    ):
        super().__init__(daemon=True, name="FolderCutWorker")
        self.folders = [Path(p) for p in folders]
        self.target_dir = Path(target_dir)
        self.options = options.normalized()
        self.event_queue = event_queue
        self.cancel_event = threading.Event()
        self.task_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.log = logging.LoggerAdapter(LOGGER, {"task_id": self.task_id})
        self.effective_verify = bool(
            self.options.verify and self.options.mechanism != MODE_MOVE
        )

    # ---------- 对外控制 ----------
    def cancel(self) -> None:
        self.cancel_event.set()

    def _emit(self, event_type: str, **payload) -> None:
        payload["type"] = event_type
        self.event_queue.put(payload)

    # ---------- 主流程 ----------
    def run(self) -> None:
        started = time.monotonic()
        summary = TaskSummary(
            task_id=self.task_id,
            mechanism=self.options.mechanism,
            verify=self.effective_verify,
            total=0,
            copied=0,
            moved=0,
            skipped=0,
            failed=0,
            total_bytes=0,
            processed_bytes=0,
            duration=0.0,
            verified_count=0,
            verify_failed=0,
            scan_skipped=0,
            cleanup_removed=0,
            cleanup_failed=0,
            cancelled=False,
            dry_run=self.options.dry_run,
        )
        try:
            self._log_start()
            self._emit(
                "started",
                task_id=self.task_id,
                mechanism=self.options.mechanism,
                verify=self.effective_verify,
            )
            if not self._prepare_target():
                summary.duration = time.monotonic() - started
                self._emit("finished", summary=summary)
                return

            scan = scan_folders(
                self.folders,
                ScanOptions(
                    recursion=self.options.recursion,
                    ignore_ds_store=self.options.ignore_ds_store,
                ),
            )
            summary.total = len(scan.files)
            summary.total_bytes = scan.total_bytes
            summary.scan_skipped = len(scan.skipped)
            self._log_scan(scan)
            self._emit(
                "scanned",
                total=len(scan.files),
                total_bytes=scan.total_bytes,
                scan_skipped=len(scan.skipped),
                cleanup_dirs=len(scan.cleanup_dirs),
            )

            if self.options.dry_run:
                summary.planned = self._preview(scan)
            elif not scan.files:
                self.log.warning("没有需要处理的文件，任务结束")
            else:
                self._transfer_all(scan, summary)

            if (
                not self.options.dry_run
                and not self.cancel_event.is_set()
                and self.options.cleanup_empty
                and scan.cleanup_dirs
            ):
                self._cleanup(scan, summary)
            elif self.options.cleanup_empty and self.cancel_event.is_set():
                self.log.warning("任务被取消，跳过空目录清理")

            summary.cancelled = self.cancel_event.is_set()
            summary.duration = time.monotonic() - started
            self._log_finish(summary)
            self._emit("finished", summary=summary)
        except Exception as exc:  # 兜底，避免线程静默死亡
            summary.duration = time.monotonic() - started
            self.log.exception("任务异常终止: %s", exc)
            self._emit("error", message=f"任务异常终止：{exc}")
            self._emit("finished", summary=summary)

    def _log_start(self) -> None:
        mech = "copy（只复制，不删源）" if self.options.mechanism != MODE_MOVE else "move（移动并删除源）"
        verify_text = "开启（MD5+SHA1）" if self.effective_verify else "关闭"
        if self.options.mechanism == MODE_MOVE:
            verify_text = "关闭（剪切模式强制不校验）"
        self.log.info(
            "任务开始 | 机制=%s | 校验=%s | 递归=%s | 同名=%s | 清理空目录=%s | "
            "忽略.DS_Store=%s | dry-run=%s | 目标目录=%s",
            mech, verify_text, RECURSION_TEXT.get(self.options.recursion),
            "跳过" if self.options.conflict == "skip" else "递增重命名",
            self.options.cleanup_empty, self.options.ignore_ds_store,
            self.options.dry_run, self.target_dir,
        )
        for folder in self.folders:
            self.log.info("来源文件夹：%s", folder)

    def _prepare_target(self) -> bool:
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.log.error("目标目录不可用：%s（%s）", self.target_dir, exc)
            self._emit("error", message=f"目标目录不可用：{exc}")
            return False
        if not self.target_dir.is_dir():
            self.log.error("目标路径不是文件夹：%s", self.target_dir)
            self._emit("error", message="目标路径不是文件夹")
            return False
        return True

    def _log_scan(self, scan: ScanResult) -> None:
        self.log.info(
            "扫描完成 | 文件夹=%d | 文件=%d | 合计=%s | 跳过=%d | 可清理目录=%d",
            len(scan.tops), len(scan.files), human_size(scan.total_bytes),
            len(scan.skipped), len(scan.cleanup_dirs),
        )
        for item in scan.skipped:
            self.log.info("扫描跳过 | 路径=%s | 原因=%s", item.path, item.reason)

    def _preview(self, scan: ScanResult) -> int:
        reserved = set()
        try:
            for name in os.listdir(long_path(self.target_dir)):
                reserved.add(name_key(name))
        except OSError:
            pass

        for index, task in enumerate(scan.files, start=1):
            if self.cancel_event.is_set():
                break
            try:
                dest, renamed = resolve_destination(
                    self.target_dir, task.source.name, self.options.conflict, reserved
                )
            except FileExistsError as exc:
                self.log.warning("预览冲突无法解决 | %s | %s", task.source, exc)
                continue
            reserved.add(name_key(dest.name))
            self.log.info(
                "预览 | 序号=%d/%d | 源=%s | 目标=%s | 重命名=%s",
                index, len(scan.files), task.source, dest, renamed,
            )
            self._emit(
                "file_start",
                index=index,
                total=len(scan.files),
                name=task.source.name,
                path=str(task.source),
            )
            self._emit(
                "progress",
                index=index,
                total=len(scan.files),
                done=0,
                skipped=0,
                failed=0,
                processed_bytes=sum(item.size for item in scan.files[:index]),
                total_bytes=scan.total_bytes,
                elapsed=0.0,
            )
        self.log.info("dry-run 预览结束，共列出 %d 个文件，未做任何修改", len(scan.files))
        return len(scan.files)

    def _transfer_all(self, scan: ScanResult, summary: TaskSummary) -> None:
        total = len(scan.files)
        processed_bytes = 0
        started = time.monotonic()
        idle_since = started

        for index, task in enumerate(scan.files, start=1):
            if self.cancel_event.is_set():
                self.log.warning("收到取消请求，在第 %d/%d 个文件前停止", index, total)
                break

            self.log.info(
                "开始处理 | 序号=%d/%d | 源=%s | 大小=%s",
                index, total, task.source, human_size(task.size),
            )
            self._emit(
                "file_start",
                index=index,
                total=total,
                name=task.source.name,
                path=str(task.source),
            )

            result = transfer_file(
                task,
                self.target_dir,
                mechanism=self.options.mechanism,
                conflict=self.options.conflict,
                verify=self.effective_verify,
            )
            processed_bytes += task.size

            if result.status == "copied":
                summary.copied += 1
            elif result.status == "moved":
                summary.moved += 1
            elif result.status == "skipped":
                summary.skipped += 1
            else:
                summary.failed += 1

            if result.verified:
                summary.verified_count += 1
            if result.status == "failed" and result.md5_source and (
                result.md5_target or result.sha1_target
            ):
                summary.verify_failed += 1

            self._log_file_result(result)
            self._emit(
                "progress",
                index=index,
                total=total,
                done=summary.done,
                skipped=summary.skipped,
                failed=summary.failed,
                processed_bytes=min(processed_bytes, scan.total_bytes),
                total_bytes=scan.total_bytes,
                elapsed=time.monotonic() - started,
                current_name=task.source.name,
                status=result.status,
            )

        summary.processed_bytes = processed_bytes
        self.log.info("文件处理阶段结束 | 成功=%d | 跳过=%d | 失败=%d", summary.done, summary.skipped, summary.failed)

    def _log_file_result(self, result) -> None:
        if result.status in ("copied", "moved"):
            if result.verified:
                self.log.info(
                    "校验通过 | 源=%s | 目标=%s | MD5源=%s | MD5目标=%s | "
                    "SHA1源=%s | SHA1目标=%s | 耗时=%.3fs",
                    result.source, result.dest, result.md5_source, result.md5_target,
                    result.sha1_source, result.sha1_target, result.elapsed,
                )
            else:
                reason = "剪切模式不校验" if self.options.mechanism == MODE_MOVE else "用户关闭校验"
                self.log.info(
                    "完成 | 状态=%s | %s | 源=%s | 目标=%s | 大小=%s | 耗时=%.3fs",
                    result.status, reason, result.source, result.dest,
                    human_size(result.size), result.elapsed,
                )
        elif result.status == "skipped":
            self.log.info(
                "跳过 | 源=%s | 目标=%s | 原因=%s",
                result.source, result.dest or "-", result.reason,
            )
        else:
            self.log.error(
                "失败 | 源=%s | 目标=%s | 原因=%s | MD5源=%s | SHA1源=%s",
                result.source, result.dest or "-", result.reason,
                result.md5_source or "-", result.sha1_source or "-",
            )

    def _cleanup(self, scan: ScanResult, summary: TaskSummary) -> None:
        self.log.info("开始清理空目录，候选 %d 个（顶层所选文件夹不会被删除）", len(scan.cleanup_dirs))
        protected = list(scan.tops) + [self.target_dir]
        report = remove_empty_dirs(
            scan.cleanup_dirs,
            protected=protected,
            ignore_metadata=self.options.ignore_ds_store,
        )
        summary.cleanup_removed = len(report.removed)
        summary.cleanup_failed = len(report.failed)
        for path in report.removed:
            self.log.info("已删除空目录：%s", path)
        for path, reason in report.failed:
            self.log.warning("空目录未删除 | 路径=%s | 原因=%s", path, reason)
        self._emit(
            "cleanup",
            removed=len(report.removed),
            failed=len(report.failed),
            kept=len(report.kept),
        )

    def _log_finish(self, summary: TaskSummary) -> None:
        verify_text = "开启" if summary.verify else "关闭"
        if summary.mechanism == MODE_MOVE:
            verify_text = "关闭（剪切模式）"
        self.log.info(
            "任务结束 | 任务ID=%s | 机制=%s | 校验=%s | 总数=%d | 复制=%d | 移动=%d | "
            "跳过=%d | 失败=%d | 校验通过=%d | 校验失败=%d | 清理目录=%d | 取消=%s | 耗时=%.2fs",
            summary.task_id, summary.mechanism, verify_text, summary.total,
            summary.copied, summary.moved, summary.skipped, summary.failed,
            summary.verified_count, summary.verify_failed,
            summary.cleanup_removed, summary.cancelled, summary.duration,
        )
        if summary.dry_run:
            self.log.info("本次为 dry-run 预览，共列出 %d 个文件，未修改磁盘", summary.planned)
