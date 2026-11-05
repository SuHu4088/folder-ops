"""配置持久化与规范化测试。"""
from __future__ import annotations

import json

from folder_ops.config import AppConfig, RunOptions, load_config, save_config


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(
        target_dir="/tmp/target",
        options=RunOptions(
            mechanism="move", recursion="level2", cleanup_empty=False,
            conflict="skip", verify=False, ignore_ds_store=False, dry_run=True,
        ),
    )
    assert save_config(config, path) is True
    loaded = load_config(path)
    assert loaded.target_dir == "/tmp/target"
    assert loaded.options.mechanism == "move"
    assert loaded.options.recursion == "level2"
    assert loaded.options.cleanup_empty is False
    assert loaded.options.conflict == "skip"
    assert loaded.options.verify is False
    assert loaded.options.ignore_ds_store is False
    assert loaded.options.dry_run is True


def test_invalid_values_fall_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"options": {"mechanism": "bad", "recursion": "x", "conflict": "y"}}),
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded.options.mechanism == "copy"
    assert loaded.options.recursion == "full"
    assert loaded.options.conflict == "rename"


def test_corrupted_config_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    loaded = load_config(path)
    assert loaded.options.mechanism == "copy"
    assert loaded.window.width >= 900
    assert loaded.window.height >= 620


def test_verify_preference_persisted_for_copy_mode(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(
        target_dir="/tmp/x",
        options=RunOptions(mechanism="copy", verify=False),
    )
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.options.verify is False
