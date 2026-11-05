"""规则引擎：条件匹配 + 动作执行。

规则 = 触发条件（扩展名 / 大小 / 日期 / 文件名正则等）
     + 动作（移动 / 复制 / 解压 / 删除空目录）。

内置插件（builtin_classifier、builtin_archive_extractor）只是生成规则数据，
不参与执行，保证“规则声明”与“动作执行”分离。
"""
from .engine import EngineReport, RuleEngine, RuleOutcome, RuleSummary
from .models import Action, Condition, Rule, RuleError, RuleSettings
from .plugins import builtin_archive_extractor_rule, builtin_classifier_rules, builtin_plugins
from .store import default_rules_payload, load_rules, parse_rules, save_rules

__all__ = [
    "Action",
    "Condition",
    "EngineReport",
    "Rule",
    "RuleEngine",
    "RuleError",
    "RuleOutcome",
    "RuleSettings",
    "RuleSummary",
    "builtin_archive_extractor_rule",
    "builtin_classifier_rules",
    "builtin_plugins",
    "default_rules_payload",
    "load_rules",
    "parse_rules",
    "save_rules",
]
