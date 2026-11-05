"""空目录清理测试。"""
from __future__ import annotations

from folder_ops.cleanup import remove_empty_dirs


def test_remove_nested_empty_dirs_bottom_up(tmp_path):
    root = tmp_path / "root"
    (root / "a" / "b" / "c").mkdir(parents=True)
    (root / "a" / "keep.txt").write_text("x", encoding="utf-8")
    dirs = [root / "a" / "b" / "c", root / "a" / "b", root / "a"]
    report = remove_empty_dirs(dirs, protected=[root])
    assert root / "a" / "b" not in [p for p in report.kept]
    assert not (root / "a" / "b").exists()
    assert (root / "a").exists()  # 有文件，保留
    assert root.exists()


def test_top_folder_never_removed(tmp_path):
    root = tmp_path / "top"
    root.mkdir()
    report = remove_empty_dirs([root], protected=[root])
    assert root.exists()
    assert report.kept == [root]


def test_dict_with_only_ds_store_is_removed(tmp_path):
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)
    (sub / ".DS_Store").write_bytes(b"meta")
    report = remove_empty_dirs([sub], protected=[root], ignore_metadata=True)
    assert sub in report.removed
    assert not sub.exists()


def test_dict_with_ds_store_kept_when_metadata_not_ignored(tmp_path):
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)
    (sub / ".DS_Store").write_bytes(b"meta")
    report = remove_empty_dirs([sub], protected=[root], ignore_metadata=False)
    assert sub.exists()
    assert sub in report.kept


def test_protected_target_ancestors_are_kept(tmp_path):
    root = tmp_path / "root"
    target = root / "target"
    target.mkdir(parents=True)
    report = remove_empty_dirs([root], protected=[target])
    assert root.exists()
    assert root in report.kept
