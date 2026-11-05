"""规则引擎后台线程：通过队列向 Tk 主线程汇报，取消在文件边界生效。"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import List

from .rules import Rule, RuleEngine, RuleSettings
from .rules.engine import RuleSummary

LOGGER = logging.getLogger(__name__)


class RuleWorker(threading.Thread):
    """一个规则任务一个线程。"""

    def __init__(
        self,
        folders: List[Path],
        rules: List[Rule],
        settings: RuleSettings,
        event_queue: "queue.Queue[dict]",
        dry_run: bool = False,
    ):
        super().__init__(daemon=True, name="FolderOpsRuleWorker")
        self.folders = [Path(item) for item in folders]
        self.rules = rules
        self.settings = settings
        self.event_queue = event_queue
        self.dry_run = dry_run
        self.cancel_event = threading.Event()
        self._total = 0
        self._total_bytes = 0

    def cancel(self) -> None:
        self.cancel_event.set()

    def _emit(self, event_type: str, **payload) -> None:
        payload["type"] = event_type
        self.event_queue.put(payload)

    def _on_file_start(self, index: int, total: int, task) -> None:
        if not self._total:
            self._total = total
            self._emit("scanned", total=total, total_bytes=self._total_bytes, scan_skipped=0)
        self._emit(
            "file_start", index=index, total=total,
            name=task.source.name, path=str(task.source),
        )

    def _on_progress(self, event: dict) -> None:
        self._emit(
            "progress",
            index=event.get("index", 0),
            total=event.get("total", 0),
            done=event.get("done", 0),
            skipped=event.get("skipped", 0),
            failed=event.get("failed", 0),
            planned=event.get("planned", 0),
            processed_bytes=0,
            total_bytes=0,
            elapsed=time.monotonic() - self._started,
            current_name=event.get("name", ""),
            rule=event.get("rule", ""),
        )

    def run(self) -> None:
        self._started = time.monotonic()
        self._emit("started", mechanism="rules", verify=False, dry_run=self.dry_run)
        LOGGER.info(
            "规则任务开始 | 规则=%d | 文件夹=%d | dry-run=%s",
            len(self.rules), len(self.folders), self.dry_run,
        )
        try:
            engine = RuleEngine(
                self.rules, self.settings,
                cancel_event=self.cancel_event,
                on_file_start=self._on_file_start,
                on_progress=self._on_progress,
            )
            report = engine.run(self.folders, dry_run=self.dry_run)
            summary = RuleSummary(
                total=report.scanned,
                done=report.done,
                skipped=report.skipped,
                failed=report.failed,
                planned=report.planned,
                cleanup_removed=report.cleanup_removed,
                duration=report.duration,
                dry_run=self.dry_run,
                cancelled=report.cancelled,
                extracted=report.extracted,
                matched=report.matched,
                unmatched=report.unmatched,
            )
            self._emit("finished", summary=summary, report=report.as_dict())
        except Exception as exc:  # 兜底，避免线程静默死亡
            LOGGER.exception("规则任务异常终止：%s", exc)
            self._emit("error", message=f"规则任务异常终止：{exc}")
            summary = RuleSummary(
                total=self._total, done=0, skipped=0, failed=1, planned=0,
                cleanup_removed=0, duration=time.monotonic() - self._started,
                dry_run=self.dry_run, cancelled=False,
            )
            self._emit("finished", summary=summary, report={})
