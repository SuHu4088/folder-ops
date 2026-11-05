"""规则数据结构与校验。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

CONDITION_TYPES = (
    "extension",
    "size",
    "date",
    "name_regex",
    "name_glob",
    "path_regex",
    "is_archive",
)
ACTION_TYPES = ("move", "copy", "extract", "cleanup_empty")
MATCH_MODES = ("any", "all")


class RuleError(ValueError):
    """规则配置非法。"""


@dataclass(frozen=True)
class Condition:
    type: str
    params: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "Condition":
        if not isinstance(data, Mapping):
            raise RuleError("条件必须是对象")
        kind = str(data.get("type", "")).strip()
        if kind not in CONDITION_TYPES:
            raise RuleError(f"未知条件类型：{kind}")
        params = {key: value for key, value in data.items() if key != "type"}
        if kind == "extension" and not params.get("values"):
            raise RuleError("extension 条件缺少 values")
        if kind in ("name_regex", "path_regex") and not params.get("pattern"):
            raise RuleError(f"{kind} 条件缺少 pattern")
        return Condition(kind, params)


@dataclass(frozen=True)
class Action:
    type: str
    params: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "Action":
        if not isinstance(data, Mapping):
            raise RuleError("动作必须是对象")
        kind = str(data.get("type", "")).strip()
        if kind not in ACTION_TYPES:
            raise RuleError(f"未知动作类型：{kind}")
        params = {key: value for key, value in data.items() if key != "type"}
        if kind in ("move", "copy") and "conflict" in params:
            if params["conflict"] not in ("skip", "rename"):
                raise RuleError("conflict 只能是 skip 或 rename")
        return Action(kind, params)


@dataclass
class Rule:
    id: str
    name: str
    enabled: bool = True
    priority: int = 100
    match_mode: str = "any"
    conditions: list[Condition] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    stop_on_match: bool = True
    notes: str = ""

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "Rule":
        if not isinstance(data, Mapping):
            raise RuleError("规则必须是对象")
        rule_id = str(data.get("id") or "").strip()
        if not rule_id:
            raise RuleError("规则缺少 id")
        mode = str(data.get("match_mode", "any")).strip()
        if mode not in MATCH_MODES:
            raise RuleError(f"规则 {rule_id} 的 match_mode 非法：{mode}")
        conditions = [Condition.from_dict(item) for item in data.get("conditions", [])]
        actions = [Action.from_dict(item) for item in data.get("actions", [])]
        if not conditions:
            raise RuleError(f"规则 {rule_id} 至少需要一个条件")
        if not actions:
            raise RuleError(f"规则 {rule_id} 至少需要一个动作")
        try:
            priority = int(data.get("priority", 100))
        except (TypeError, ValueError) as exc:
            raise RuleError(f"规则 {rule_id} 的 priority 必须是整数") from exc
        return Rule(
            id=rule_id,
            name=str(data.get("name") or rule_id),
            enabled=bool(data.get("enabled", True)),
            priority=priority,
            match_mode=mode,
            conditions=conditions,
            actions=actions,
            stop_on_match=bool(data.get("stop_on_match", True)),
            notes=str(data.get("notes") or ""),
        )

    def describe_actions(self) -> str:
        parts = []
        for action in self.actions:
            if action.type in ("move", "copy"):
                parts.append(f"{action.type}→{action.params.get('target') or '来源根'}")
            elif action.type == "extract":
                parts.append("解压+CRC")
            else:
                parts.append("清空目录")
        return " / ".join(parts)


@dataclass
class RuleSettings:
    """规则集级别的全局设置。"""

    target_root: str = ""
    archive_output_root: str = ""
    vault_path: str = ""
    password_module_enabled: bool = True
    delete_archive_after_verify: bool = False
    cleanup_empty: bool = False
    recursion: str = "full"
    ignore_ds_store: bool = True

    @staticmethod
    def from_dict(data: Mapping[str, Any] | None) -> "RuleSettings":
        raw = dict(data or {})
        recursion = str(raw.get("recursion", "full"))
        if recursion not in ("level1", "level2", "full"):
            recursion = "full"
        return RuleSettings(
            target_root=str(raw.get("target_root", "") or ""),
            archive_output_root=str(raw.get("archive_output_root", "") or ""),
            vault_path=str(raw.get("vault_path", "") or ""),
            password_module_enabled=bool(raw.get("password_module_enabled", True)),
            delete_archive_after_verify=bool(raw.get("delete_archive_after_verify", False)),
            cleanup_empty=bool(raw.get("cleanup_empty", False)),
            recursion=recursion,
            ignore_ds_store=bool(raw.get("ignore_ds_store", True)),
        )
