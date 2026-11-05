"""规则引擎端到端测试：移动 / 复制 / 优先级 / dry-run / 空目录清理 / 解压插件。"""
from __future__ import annotations

from pathlib import Path

import pytest

from folder_ops.archive.models import ArchiveOutcome
from folder_ops.rules import Rule, RuleEngine, RuleSettings
from folder_ops.rules import actions as actions_mod
from folder_ops.rules.models import Action, Condition, RuleError
from folder_ops.rules.plugins import builtin_archive_extractor_rule


def make_tree(tmp_path: Path) -> Path:
    src = tmp_path / "source"
    (src / "子目录").mkdir(parents=True)
    (src / "photo.jpg").write_bytes(b"jpg-data")
    (src / "photo.png").write_bytes(b"png-data")
    (src / "note.txt").write_bytes(b"text")
    (src / "子目录" / "clip.mp4").write_bytes(b"video")
    return src


def image_rule(mechanism: str = "move", target: str = "图片") -> Rule:
    return Rule(
        id="images", name="图片", priority=10, match_mode="any",
        conditions=[Condition("extension", {"values": ["jpg", "png"]})],
        actions=[Action(mechanism, {"target": target, "conflict": "rename", "verify": True})],
    )


def test_move_images_and_leave_others(tmp_path):
    src = make_tree(tmp_path)
    report = RuleEngine([image_rule()]).run([src])
    assert report.scanned == 4
    assert report.moved == 2
    assert (src / "图片" / "photo.jpg").exists()
    assert (src / "图片" / "photo.png").exists()
    assert not (src / "photo.jpg").exists()
    assert (src / "note.txt").exists()
    assert report.failed == 0


def test_copy_keeps_source(tmp_path):
    src = make_tree(tmp_path)
    report = RuleEngine([image_rule("copy")]).run([src])
    assert report.copied == 2
    assert (src / "photo.jpg").exists()
    assert (src / "图片" / "photo.jpg").exists()


def test_dry_run_changes_nothing(tmp_path):
    src = make_tree(tmp_path)
    rules = [image_rule()]
    report = RuleEngine(rules).run([src], dry_run=True)
    assert report.planned == 2
    assert report.moved == 0
    assert not (src / "图片").exists()
    assert len(report.outcomes) == 2
    assert all(item.status == "planned" for item in report.outcomes)


def test_priority_first_match_wins(tmp_path):
    src = make_tree(tmp_path)
    loud = Rule(
        id="first", name="先命中", priority=1,
        conditions=[Condition("name_regex", {"pattern": "photo"})],
        actions=[Action("move", {"target": "先", "conflict": "rename"})],
    )
    late = image_rule()
    report = RuleEngine([late, loud]).run([src])
    assert (src / "先" / "photo.jpg").exists()
    assert not (src / "图片" / "photo.jpg").exists()
    assert report.matched == 2


def test_disabled_rule_ignored(tmp_path):
    src = make_tree(tmp_path)
    disabled = image_rule()
    disabled.enabled = False
    report = RuleEngine([disabled]).run([src])
    assert report.matched == 0
    assert report.unmatched == 4


def test_cleanup_empty_dirs_with_protected_top(tmp_path):
    src = make_tree(tmp_path)
    empty_dir = src / "空目录" / "更深"
    empty_dir.mkdir(parents=True)
    rule = Rule(
        id="cleanup", name="清理", priority=1,
        conditions=[Condition("extension", {"values": ["mp4"]})],
        actions=[Action("move", {"target": "视频"}), Action("cleanup_empty")],
    )
    report = RuleEngine([rule]).run([src])
    assert report.moved == 1
    assert report.cleanup_removed >= 2
    assert not (src / "空目录").exists()
    assert (src / "视频" / "clip.mp4").exists()


def test_all_condition_mode_requires_all(tmp_path):
    src = make_tree(tmp_path)
    rule = Rule(
        id="both", name="全满足", match_mode="all",
        conditions=[Condition("extension", {"values": ["jpg"]}),
                    Condition("size", {"min_bytes": 1000})],
        actions=[Action("move", {"target": "大图"})],
    )
    report = RuleEngine([rule]).run([src])
    assert report.matched == 0


def test_extract_plugin_uses_archive_service(tmp_path, monkeypatch):
    src = tmp_path / "source"
    src.mkdir()
    archive = src / "bundle.zip"
    archive.write_bytes(b"PK\x03\x04-fake")
    out = tmp_path / "out"
    captured = {}

    def fake_extract(path, output_root, **kwargs):
        captured["path"] = Path(path)
        captured["root"] = Path(output_root)
        return ArchiveOutcome(path=Path(path), status="ok", message="CRC 校验通过",
                              dest=output_root / "bundle", extracted_count=2, verified=True)

    monkeypatch.setattr(actions_mod, "extract_archive", fake_extract)
    rule = builtin_archive_extractor_rule(output_root=str(out), cleanup_empty=False)
    report = RuleEngine([rule], RuleSettings(password_module_enabled=False)).run([src])
    assert report.extracted == 1
    assert report.outcomes[0].action == "extract"
    assert captured["path"] == archive
    assert captured["root"] == out


def test_extract_failure_is_reported(tmp_path, monkeypatch):
    src = tmp_path / "source"
    src.mkdir()
    (src / "bad.rar").write_bytes(b"not-a-rar")

    def fake_extract(path, output_root, **kwargs):
        return ArchiveOutcome(path=Path(path), status="failed", message="压缩包已损坏")

    monkeypatch.setattr(actions_mod, "extract_archive", fake_extract)
    report = RuleEngine([builtin_archive_extractor_rule(cleanup_empty=False)]).run([src])
    assert report.failed == 1
    assert report.extracted == 0


def test_conflict_rename_on_same_name(tmp_path):
    src = tmp_path / "source"
    (src / "图片").mkdir(parents=True)
    (src / "图片" / "photo.jpg").write_bytes(b"old")
    (src / "photo.jpg").write_bytes(b"new")
    report = RuleEngine([image_rule()]).run([src])
    assert report.moved == 1
    names = sorted(item.name for item in (src / "图片").iterdir())
    assert names == ["photo.jpg", "photo_1.jpg"]


def test_dry_run_does_not_create_vault(tmp_path, monkeypatch):
    """dry-run 必须零副作用：不创建密码库目录。"""
    src = tmp_path / "source"
    src.mkdir()
    (src / "bundle.zip").write_bytes(b"fake")
    vault_dir = tmp_path / "vault"
    settings = RuleSettings(vault_path=str(vault_dir))

    def fake_extract(path, output_root, **kwargs):
        return ArchiveOutcome(path=Path(path), status="ok", message="计划", verified=True)

    monkeypatch.setattr(actions_mod, "extract_archive", fake_extract)
    report = RuleEngine([builtin_archive_extractor_rule(cleanup_empty=False)], settings).run(
        [src], dry_run=True
    )
    assert report.planned == 1
    assert not vault_dir.exists()


def test_empty_rules_requires_condition():
    with pytest.raises(RuleError):
        Rule.from_dict({"id": "x", "conditions": [], "actions": [{"type": "move"}]})
