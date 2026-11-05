"""规则文件的默认值、加载与保存。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..platform_utils import app_data_dir
from .models import Rule, RuleError, RuleSettings
from .plugins import builtin_archive_extractor_rule, builtin_classifier_rules

LOGGER = logging.getLogger(__name__)


def default_rules_path() -> Path:
    return app_data_dir() / "rules.json"


def default_rules_payload() -> dict[str, Any]:
    """默认规则集：解压优先，其后按分类移动。"""
    rules = [builtin_archive_extractor_rule(delete_original=False, cleanup_empty=True)]
    rules.extend(builtin_classifier_rules(mechanism="move", verify=False))
    return {
        "version": 1,
        "settings": {
            "target_root": "",
            "archive_output_root": "",
            "vault_path": "",
            "password_module_enabled": True,
            "delete_archive_after_verify": False,
            "cleanup_empty": True,
            "recursion": "full",
            "ignore_ds_store": True,
        },
        "rules": [_rule_to_dict(rule) for rule in rules],
    }


def _rule_to_dict(rule: Rule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "match_mode": rule.match_mode,
        "conditions": [{"type": condition.type, **dict(condition.params)}
                       for condition in rule.conditions],
        "actions": [{"type": action.type, **dict(action.params)}
                    for action in rule.actions],
        "stop_on_match": rule.stop_on_match,
        "notes": rule.notes,
    }


def parse_rules(payload: Any) -> tuple[list[Rule], RuleSettings]:
    """把 JSON 结构解析为规则与设置；非法内容抛 RuleError。"""
    if not isinstance(payload, dict):
        raise RuleError("规则文件根节点必须是对象")
    rules_raw = payload.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise RuleError("规则文件必须包含非空 rules 数组")
    rules = [Rule.from_dict(item) for item in rules_raw]
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise RuleError("规则 id 重复")
    settings = RuleSettings.from_dict(payload.get("settings"))
    return rules, settings


def load_rules(path: Path | None = None) -> tuple[list[Rule], RuleSettings, dict]:
    """加载规则文件；不存在时写出默认规则。返回 (规则, 设置, 原始字典)。"""
    target = Path(path) if path else default_rules_path()
    if not target.exists():
        payload = default_rules_payload()
        save_rules(payload, target)
        LOGGER.info("规则文件不存在，已生成默认规则：%s", target)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuleError(f"规则文件不可读：{exc}") from exc
    rules, settings = parse_rules(payload)
    LOGGER.info("已加载规则 %d 条：%s", len(rules), target)
    return rules, settings, payload


def save_rules(payload: dict, path: Path | None = None) -> Path:
    target = Path(path) if path else default_rules_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info("规则已保存：%s", target)
    return target
