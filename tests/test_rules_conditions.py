"""触发条件单元测试：扩展名 / 大小 / 日期 / 正则 / 通配 / 压缩包。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from folder_ops.rules.conditions import evaluate
from folder_ops.rules.engine import RuleEngine
from folder_ops.rules.models import Condition, Rule


def make_file(tmp_path: Path, name: str, content: bytes = b"x") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def check(kind: str, path: Path, **params) -> bool:
    return evaluate(Condition(kind, params), path, path.stat())


def test_extension_matches_case_and_dot(tmp_path):
    path = make_file(tmp_path, "photo.PNG")
    assert check("extension", path, values=["png", ".jpeg"])
    assert not check("extension", path, values=["jpg"])


def test_extension_supports_double_suffix(tmp_path):
    path = make_file(tmp_path, "backup.tar.gz")
    assert check("extension", path, values=["tar.gz"])


def test_size_range(tmp_path):
    path = make_file(tmp_path, "data.bin", b"a" * 100)
    assert check("size", path, min_bytes=50, max_bytes=200)
    assert not check("size", path, min_bytes=101)
    assert not check("size", path, max_bytes=99)


def test_date_older_and_newer(tmp_path):
    path = make_file(tmp_path, "old.txt")
    old = time.time() - 40 * 86400
    os.utime(path, (old, old))
    assert check("date", path, older_than_days=30)
    assert not check("date", path, newer_than_days=30)
    assert check("date", path, before="2030-01-01")
    assert not check("date", path, after="2030-01-01")


def test_name_regex(tmp_path):
    path = make_file(tmp_path, "IMG_2024.JPG")
    assert check("name_regex", path, pattern=r"^img_\d{4}\.jpg$", ignore_case=True)
    assert not check("name_regex", path, pattern=r"^img_\d{4}\.jpg$", ignore_case=False)


def test_name_glob_and_archive(tmp_path):
    zip_path = make_file(tmp_path, "bundle.ZIP")
    assert check("name_glob", zip_path, pattern="bundle.*")
    assert check("is_archive", zip_path)
    assert not check("is_archive", make_file(tmp_path, "notes.txt"))


def test_rule_match_mode_any_and_all(tmp_path):
    path = make_file(tmp_path, "photo.png", b"abc")
    rule_any = Rule(
        id="any", name="any", match_mode="any",
        conditions=[Condition("extension", {"values": ["png"]}),
                    Condition("size", {"min_bytes": 999})],
        actions=[],
    )
    rule_all = Rule(
        id="all", name="all", match_mode="all",
        conditions=[Condition("extension", {"values": ["png"]}),
                    Condition("size", {"min_bytes": 999})],
        actions=[],
    )
    stat_result = path.stat()
    assert RuleEngine.rule_matches(rule_any, path, stat_result)
    assert not RuleEngine.rule_matches(rule_all, path, stat_result)


def test_invalid_condition_rejected():
    with pytest.raises(Exception):
        Condition.from_dict({"type": "not-a-condition"})
