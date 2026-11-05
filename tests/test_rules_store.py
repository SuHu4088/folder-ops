"""规则文件加载、默认插件与校验测试。"""
from __future__ import annotations

import json

import pytest

from folder_ops.rules import (
    RuleError,
    builtin_archive_extractor_rule,
    builtin_classifier_rules,
    default_rules_payload,
    load_rules,
    parse_rules,
    save_rules,
)


def test_default_payload_is_valid_and_has_two_plugins():
    payload = default_rules_payload()
    rules, settings = parse_rules(payload)
    assert len(rules) == 10
    assert rules[0].id == "builtin.archive.extract"
    assert any(rule.id == "builtin.classify.图片" for rule in rules)
    assert settings.password_module_enabled is True
    assert settings.cleanup_empty is True


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "rules.json"
    payload = default_rules_payload()
    save_rules(payload, path)
    rules, settings, raw = load_rules(path)
    assert len(rules) == 10
    assert rules[0].conditions[0].type == "extension"
    assert rules[1].actions[0].type == "move"
    assert raw["version"] == 1
    # 保存后不应出现嵌套 params，条件参数是扁平的
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "values" in stored["rules"][1]["conditions"][0]


def test_missing_file_generates_defaults(tmp_path):
    path = tmp_path / "missing" / "rules.json"
    rules, settings, _ = load_rules(path)
    assert path.exists()
    assert len(rules) == 10


def test_builtin_classifier_copy_mode():
    rules = builtin_classifier_rules(mechanism="copy", target_root="sorted")
    assert all(rule.actions[0].type == "copy" for rule in rules)
    assert rules[0].actions[0].params["target"] == "sorted/图片"


def test_archive_rule_actions():
    rule = builtin_archive_extractor_rule(delete_original=True, cleanup_empty=True)
    assert [action.type for action in rule.actions] == ["extract", "cleanup_empty"]
    assert rule.actions[0].params["delete_original"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"rules": []},
        {"rules": [{"id": "a", "conditions": [{"type": "extension", "values": ["zip"]}],
                    "actions": [{"type": "move"}]},
                   {"id": "a", "conditions": [{"type": "is_archive"}],
                    "actions": [{"type": "copy"}]}]},
        {"rules": [{"id": "a", "conditions": [{"type": "bogus"}],
                    "actions": [{"type": "move"}]}]},
        {"rules": [{"id": "a", "conditions": [{"type": "is_archive"}],
                    "actions": [{"type": "move", "conflict": "explode"}]}]},
    ],
)
def test_invalid_payloads(payload):
    with pytest.raises(RuleError):
        parse_rules(payload)
