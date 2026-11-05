"""日志初始化：轮转文件日志 + 界面日志队列。

每行日志包含时间戳、级别、任务 ID。
"""
from __future__ import annotations

import logging
import queue
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .platform_utils import default_log_dir

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | task=%(task_id)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5


class TaskIdFilter(logging.Filter):
    """为没有 task_id 的日志补默认值，避免格式化异常。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "task_id", None):
            record.task_id = getattr(record, "task_id", "-")
        return True


class QueueLogHandler(logging.Handler):
    """把格式化后的日志行推给 Tk 主线程消费，线程安全。"""

    def __init__(self, log_queue: "queue.Queue[str]"):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self.log_queue.put(message)
        except Exception:  # pragma: no cover - 日志失败不应影响主流程
            self.handleError(record)


def setup_logging(
    log_dir: Optional[Path] = None,
    log_queue: Optional["queue.Queue[str]"] = None,
    level: int = logging.DEBUG,
) -> Path:
    """配置根日志器，返回日志文件路径。重复调用会先清理旧 handler。"""
    directory = Path(log_dir) if log_dir else default_log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "folder-ops.log"

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    file_handler = RotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    file_handler.addFilter(TaskIdFilter())
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    console.addFilter(TaskIdFilter())
    root.addHandler(console)

    if log_queue is not None:
        queue_handler = QueueLogHandler(log_queue)
        queue_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        queue_handler.addFilter(TaskIdFilter())
        root.addHandler(queue_handler)

    logging.captureWarnings(True)
    return log_file
