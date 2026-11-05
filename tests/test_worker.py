"""后台任务测试：整任务流程、取消安全点、dry-run、move 模式零哈希。"""
from __future__ import annotations

import queue

import folder_ops.mover as mover
import folder_ops.worker as worker_module
from folder_ops.config import RunOptions
from folder_ops.worker import CutWorker


def run_worker(worker):
    events = queue.Queue()
    worker.event_queue = events
    worker.start()
    worker.join(timeout=15)
    assert not worker.is_alive(), "工作线程必须结束"
    collected = []
    while True:
        try:
            collected.append(events.get_nowait())
        except queue.Empty:
            break
    finished = [e for e in collected if e["type"] == "finished"]
    assert finished, f"应产生 finished 事件，实际：{collected}"
    return finished[-1]["summary"], collected


def test_copy_task_copies_all_and_keeps_sources(nested_tree):
    options = RunOptions(mechanism="copy", recursion="full", verify=True)
    summary, events = run_worker(
        CutWorker([nested_tree["src"]], nested_tree["target"], options, queue.Queue())
    )
    assert summary.copied == 4
    assert summary.moved == 0
    assert summary.verified_count == 4
    assert summary.failed == 0
    for task in ("a.txt", "lvl1/b.txt", "lvl1/lvl2/c.txt", "lvl1/lvl2/lvl3/d.txt"):
        assert (nested_tree["src"] / task).exists(), "copy 模式源文件必须保留"
        assert (nested_tree["target"] / task.split("/")[-1]).exists()


def test_move_task_moves_and_cleans_empty_dirs(nested_tree):
    options = RunOptions(mechanism="move", recursion="full", cleanup_empty=True)
    summary, _ = run_worker(
        CutWorker([nested_tree["src"]], nested_tree["target"], options, queue.Queue())
    )
    assert summary.moved == 4
    assert summary.cleanup_removed >= 3
    assert nested_tree["src"].exists(), "顶层所选文件夹本身绝不能被删除"
    assert not (nested_tree["src"] / "lvl1").exists()
    assert sorted(p.name for p in nested_tree["target"].iterdir()) == [
        "a.txt", "b.txt", "c.txt", "d.txt",
    ]


def test_move_task_never_hashes(nested_tree, monkeypatch):
    calls = []
    monkeypatch.setattr(mover, "hash_file", lambda p: calls.append(p) or ("x", "y"))
    options = RunOptions(mechanism="move", recursion="level2", verify=True, cleanup_empty=False)
    summary, _ = run_worker(
        CutWorker([nested_tree["src"]], nested_tree["target"], options, queue.Queue())
    )
    assert summary.moved == 2
    assert summary.verify is False, "剪切模式的有效校验必须为关闭"
    assert calls == []


def test_cancel_stops_at_safe_point(nested_tree, monkeypatch):
    real_transfer = worker_module.transfer_file
    holder = {}

    def cancel_after_first(*args, **kwargs):
        result = real_transfer(*args, **kwargs)
        if "worker" in holder:
            holder["worker"].cancel()
        return result

    monkeypatch.setattr(worker_module, "transfer_file", cancel_after_first)
    options = RunOptions(mechanism="move", recursion="full", cleanup_empty=False)
    worker = CutWorker([nested_tree["src"]], nested_tree["target"], options, queue.Queue())
    holder["worker"] = worker
    summary, events = run_worker(worker)

    assert summary.cancelled is True
    assert summary.moved == 1
    remaining = list((nested_tree["src"] / "lvl1" / "lvl2" / "lvl3").glob("*.txt"))
    assert len(remaining) >= 1, "未开始的文件必须原样保留"
    progress = [e for e in events if e["type"] == "progress"]
    assert progress, "取消前应已上报进度"


def test_dry_run_does_not_touch_disk(nested_tree):
    options = RunOptions(mechanism="move", recursion="full", dry_run=True)
    summary, _ = run_worker(
        CutWorker([nested_tree["src"]], nested_tree["target"], options, queue.Queue())
    )
    assert summary.dry_run is True
    assert summary.planned == 4
    assert list(nested_tree["target"].iterdir()) == []
    assert (nested_tree["src"] / "a.txt").exists()
    assert (nested_tree["src"] / "lvl1" / "lvl2" / "lvl3" / "d.txt").exists()


def test_no_files_finishes_cleanly(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    options = RunOptions(mechanism="copy", recursion="full")
    summary, _ = run_worker(CutWorker([empty], target, options, queue.Queue()))
    assert summary.total == 0
    assert summary.failed == 0
