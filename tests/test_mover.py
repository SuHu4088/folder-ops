"""两种执行机制 + 双校验 + 冲突策略的单元测试。"""
from __future__ import annotations

import hashlib

import folder_ops.mover as mover
from folder_ops.mover import (
    MODE_COPY,
    MODE_MOVE,
    TransferResult,
    resolve_destination,
    transfer_file,
)
from folder_ops.scanner import FileTask


def make_task(path):
    return FileTask(source=path, top=path.parent, rel_dir="", size=path.stat().st_size)


def md5_of(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def sha1_of(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


# ---------- copy 模式 ----------
def test_copy_mode_keeps_source_and_records_hashes(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("hello folder cut", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    result = transfer_file(make_task(src), target, MODE_COPY, "rename", verify=True)

    assert isinstance(result, TransferResult)
    assert result.status == "copied"
    assert result.verified is True
    assert src.exists(), "copy 模式绝不删除源文件"
    dest = target / "a.txt"
    assert dest.exists()
    assert result.md5_source == result.md5_target == md5_of(dest)
    assert result.sha1_source == result.sha1_target == sha1_of(dest)


def test_copy_verify_mismatch_keeps_source_and_drops_target(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("content", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()

    real_hash = mover.hash_file
    calls = {"n": 0}

    def fake_hash(path):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_hash(path)
        return ("0" * 32, "0" * 40)

    monkeypatch.setattr(mover, "hash_file", fake_hash)
    result = transfer_file(make_task(src), target, MODE_COPY, "rename", verify=True)

    assert result.status == "failed"
    assert "MD5" in result.reason
    assert src.exists()
    assert not (target / "a.txt").exists()
    assert not list(target.glob(".foldercut_tmp_*")), "临时副本必须清理"


def test_copy_without_verify_does_not_hash(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("abc", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    calls = []
    monkeypatch.setattr(mover, "hash_file", lambda p: calls.append(p) or ("x", "y"))

    result = transfer_file(make_task(src), target, MODE_COPY, "rename", verify=False)
    assert result.status == "copied"
    assert calls == []
    assert src.exists()


# ---------- move 模式 ----------
def test_move_same_device_uses_rename_without_hash(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("move me", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    calls = []
    monkeypatch.setattr(mover, "hash_file", lambda p: calls.append(p) or ("x", "y"))

    result = transfer_file(make_task(src), target, MODE_MOVE, "rename", verify=True)
    assert result.status == "moved"
    assert result.cross_device is False
    assert not src.exists()
    assert (target / "a.txt").read_text(encoding="utf-8") == "move me"
    assert calls == [], "剪切模式不允许触发哈希计算"


def test_move_cross_device_copy_then_delete(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("cross device", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    calls = []
    monkeypatch.setattr(mover, "hash_file", lambda p: calls.append(p) or ("x", "y"))
    monkeypatch.setattr(mover, "same_device", lambda a, b: False)

    result = transfer_file(make_task(src), target, MODE_MOVE, "rename", verify=True)
    assert result.status == "moved"
    assert result.cross_device is True
    assert not src.exists()
    assert (target / "a.txt").exists()
    assert calls == []


def test_move_cross_device_existing_target_keeps_source(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("source", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "a.txt").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(mover, "same_device", lambda a, b: False)

    result = transfer_file(make_task(src), target, MODE_MOVE, "skip", verify=False)
    assert result.status == "skipped"
    assert src.exists()
    assert (target / "a.txt").read_text(encoding="utf-8") == "existing"


def test_move_cross_device_copy_failure_keeps_source(tmp_path, monkeypatch):
    src = tmp_path / "a.txt"
    src.write_text("source data", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setattr(mover, "same_device", lambda a, b: False)

    def broken_copy(source, temp):
        temp.write_bytes(b"trunc")  # 模拟复制不完整
        return None

    monkeypatch.setattr(mover, "_copy_once", broken_copy)
    result = transfer_file(make_task(src), target, MODE_MOVE, "rename", verify=False)
    assert result.status == "failed"
    assert "大小" in result.reason
    assert src.exists()
    assert not (target / "a.txt").exists()


# ---------- 同名冲突 ----------
def test_skip_conflict_keeps_existing_file(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("new", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "a.txt").write_text("old", encoding="utf-8")

    result = transfer_file(make_task(src), target, MODE_COPY, "skip", verify=False)
    assert result.status == "skipped"
    assert (target / "a.txt").read_text(encoding="utf-8") == "old"
    assert src.exists()


def test_rename_conflict_increments_counter(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "report.txt").write_text("one", encoding="utf-8")
    dest, renamed = resolve_destination(target, "report.txt", "rename")
    assert renamed is True
    assert dest.name == "report_1.txt"

    (target / "report_1.txt").write_text("two", encoding="utf-8")
    dest2, renamed2 = resolve_destination(target, "report.txt", "rename")
    assert renamed2 is True
    assert dest2.name == "report_2.txt"


def test_rename_keeps_extension_and_handles_no_extension(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "archive.tar.gz").write_text("x", encoding="utf-8")
    (target / "noext").write_text("x", encoding="utf-8")
    assert resolve_destination(target, "archive.tar.gz", "rename")[0].name == "archive.tar_1.gz"
    assert resolve_destination(target, "noext", "rename")[0].name == "noext_1"


def test_dry_run_reserved_names_avoid_duplicate_preview(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    reserved = set()
    first, _ = resolve_destination(target, "same.txt", "rename", reserved)
    reserved.add(mover.name_key(first.name))
    second, renamed = resolve_destination(target, "same.txt", "rename", reserved)
    assert renamed is True
    assert second.name == "same_1.txt"
