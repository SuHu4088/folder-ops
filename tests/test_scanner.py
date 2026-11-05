"""扫描与递归范围测试。"""
from __future__ import annotations

import os

import pytest

from folder_ops.scanner import ScanOptions, normalize_roots, scan_folders


def test_level1_only_top_files(nested_tree):
    result = scan_folders([nested_tree["src"]], ScanOptions(recursion="level1"))
    assert [f.source.name for f in result.files] == ["a.txt"]
    assert result.cleanup_dirs == []


def test_level2_top_plus_first_level_subdirs(nested_tree):
    result = scan_folders([nested_tree["src"]], ScanOptions(recursion="level2"))
    names = sorted(f.source.name for f in result.files)
    assert names == ["a.txt", "b.txt"]
    assert len(result.cleanup_dirs) == 1
    assert result.cleanup_dirs[0].name == "lvl1"


def test_full_recursion_all_levels(nested_tree):
    result = scan_folders([nested_tree["src"]], ScanOptions(recursion="full"))
    names = sorted(f.source.name for f in result.files)
    assert names == ["a.txt", "b.txt", "c.txt", "d.txt"]
    assert {p.name for p in result.cleanup_dirs} == {"lvl1", "lvl2", "lvl3"}


def test_macos_metadata_ignored_by_default(nested_tree):
    (nested_tree["src"] / ".DS_Store").write_bytes(b"meta")
    result = scan_folders([nested_tree["src"]], ScanOptions(recursion="level1"))
    assert [f.source.name for f in result.files] == ["a.txt"]
    assert any(item.path.name == ".DS_Store" for item in result.skipped)


def test_macos_metadata_included_when_disabled(nested_tree):
    (nested_tree["src"] / ".DS_Store").write_bytes(b"meta")
    result = scan_folders(
        [nested_tree["src"]], ScanOptions(recursion="level1", ignore_ds_store=False)
    )
    names = sorted(f.source.name for f in result.files)
    assert names == [".DS_Store", "a.txt"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="平台不支持符号链接")
def test_symlink_skipped(nested_tree):
    link = nested_tree["src"] / "link.txt"
    try:
        os.symlink(nested_tree["src"] / "a.txt", link)
    except OSError:
        pytest.skip("当前文件系统不允许创建符号链接")
    result = scan_folders([nested_tree["src"]], ScanOptions(recursion="level1"))
    assert all(f.source.name != "link.txt" for f in result.files)
    assert any(item.path.name == "link.txt" for item in result.skipped)


def test_nested_roots_are_deduplicated(nested_tree):
    roots, skipped = normalize_roots(
        [nested_tree["src"], nested_tree["src"] / "lvl1"]
    )
    assert roots == [nested_tree["src"]]
    assert skipped[0].path == nested_tree["src"] / "lvl1"


def test_invalid_root_reported(tmp_path):
    result = scan_folders([tmp_path / "missing"], ScanOptions())
    assert result.files == []
    assert result.skipped[0].reason == "不是有效文件夹"
