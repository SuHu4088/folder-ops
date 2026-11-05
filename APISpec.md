# APISpec · folder-ops V0.2.0

本规格描述三部分接口：规则 JSON、命令行、Python 顶层 API 与线程事件。

## 1. 规则 JSON

根节点：

```json
{ "version": 1, "settings": { ... }, "rules": [ ... ] }
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `version` | int | 否 | 当前固定为 1，保留扩展 |
| `settings` | object | 否 | 全局设置，缺省用默认值 |
| `rules` | array | 是 | 非空；`id` 必须唯一 |

### 1.1 settings

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `target_root` | string | `""` | 相对动作目标的根目录；空则用来源顶层目录 |
| `archive_output_root` | string | `""` | 解压输出根；空则用压缩包所在目录 |
| `vault_path` | string | `""` | 密码库目录；空则 `~/.folder_ops/password_vault` |
| `password_module_enabled` | bool | `true` | 是否尝试密码库 |
| `delete_archive_after_verify` | bool | `false` | 校验通过后删除原压缩包（可被动作覆盖） |
| `cleanup_empty` | bool | `false` | 批次结束后清理空目录 |
| `recursion` | string | `full` | `level1` / `level2` / `full` |
| `ignore_ds_store` | bool | `true` | 忽略 `.DS_Store` 等元数据 |

### 1.2 rule

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 必填 | 唯一标识 |
| `name` | string | 同 id | 展示名 |
| `enabled` | bool | `true` | 停用后不参与匹配 |
| `priority` | int | `100` | 升序执行，数值越小越先 |
| `match_mode` | string | `any` | `any`（任一条件）/ `all`（全部条件） |
| `conditions` | array | 必填 | 至少 1 个 |
| `actions` | array | 必填 | 至少 1 个 |
| `stop_on_match` | bool | `true` | 预留字段；当前实现首命中即停止 |
| `notes` | string | `""` | 备注 |

### 1.3 条件

| type | 参数 | 语义 |
| --- | --- | --- |
| `extension` | `values`: string[] | 扩展名匹配，忽略大小写与前导点；支持 `tar.gz` |
| `size` | `min_bytes` / `max_bytes`: int | 闭区间；缺省不限制 |
| `date` | `older_than_days` / `newer_than_days`: int；`after` / `before`: `YYYY-MM-DD` 或 ISO | 基于 mtime，可组合 |
| `name_regex` | `pattern`: string，`ignore_case`: bool（默认 true） | 对文件名 `re.search` |
| `name_glob` | `pattern`: string | `fnmatch`，忽略大小写 |
| `path_regex` | `pattern`: string，`ignore_case`: bool | 对完整 POSIX 路径 `re.search` |
| `is_archive` | 无 | 后缀属于 zip/rar/7z/tar/gz/bz2/xz/tgz |

### 1.4 动作

| type | 参数 | 语义 |
| --- | --- | --- |
| `move` | `target`: string；`conflict`: `rename`\|`skip`；`verify`: bool（默认 false） | 移动到目标目录；成功后删源 |
| `copy` | 同上；`verify` 默认 true | 复制并可选双校验 |
| `extract` | `target`: string；`delete_original`: bool；`password_module`: bool | 解压 + CRC 三重校验 |
| `cleanup_empty` | 无 | 批后清理嵌套空目录 |

约束：

- `conflict` 非 `rename` / `skip` → `RuleError`。
- 目标目录等于源文件父目录时，移动/复制动作直接跳过，避免自我重命名。
- `extract` 的目标已存在且非空时，自动追加 `_1`、`_2`。

## 2. 命令行

```text
python3 main.py [--rules PATH] [--source PATH ...] [--dry-run | --apply]
                [--json-report PATH] [--print-default-rules] [--gui] [--version]
```

| 参数 | 说明 |
| --- | --- |
| `--rules` | 规则文件路径，默认 `~/Library/Application Support/FolderOps/rules.json` |
| `--source` | 来源文件夹，可重复 |
| `--dry-run` | 预览；命令行默认行为 |
| `--apply` | 真实执行 |
| `--json-report` | 报告写入文件；未指定时 dry-run 输出到 stdout |
| `--print-default-rules` | 打印默认规则 JSON |
| `--gui` | 无参数或显式指定时启动 GUI |
| `--version` | 打印版本 |

退出码：`0` 成功；`1` 存在失败动作；`2` 参数或规则错误。

## 3. Python API

```python
from folder_ops.rules import RuleEngine, load_rules, RuleSettings

rules, settings, payload = load_rules(path=None)
report = RuleEngine(rules, settings).run([Path("~/Downloads")], dry_run=True)
print(report.summary(), report.as_dict())
```

### 3.1 `folder_ops.rules`

| 符号 | 签名 | 说明 |
| --- | --- | --- |
| `load_rules` | `(path: Path \| None = None) -> (list[Rule], RuleSettings, dict)` | 不存在时写默认规则 |
| `parse_rules` | `(payload: Any) -> (list[Rule], RuleSettings)` | 纯校验，不落盘 |
| `save_rules` | `(payload: dict, path: Path \| None = None) -> Path` | 写 JSON |
| `RuleEngine` | `(rules, settings=None, vault=None, cancel_event=None, on_file_start=None, on_progress=None)` | 引擎 |
| `RuleEngine.run` | `(folders: Iterable[Path], dry_run: bool = False) -> EngineReport` | 扫描+执行 |
| `builtin_classifier_rules` | `(mechanism="move", target_root="", priorities=None, verify=False) -> list[Rule]` | 分类插件 |
| `builtin_archive_extractor_rule` | `(output_root="", delete_original=False, password_module=True, priority=1, cleanup_empty=True) -> Rule` | 解压插件 |

### 3.2 `EngineReport`

| 字段/方法 | 说明 |
| --- | --- |
| `scanned` / `scanned_bytes` | 扫描文件数与字节数 |
| `matched` / `unmatched` | 命中/未命中规则的文件数 |
| `executed` / `moved` / `copied` / `extracted` | 成功动作计数 |
| `skipped` / `failed` / `planned` | 跳过/失败/dry-run 计划计数 |
| `cleanup_removed` / `cleanup_failed` | 清理目录结果 |
| `outcomes` | `RuleOutcome` 列表（文件、规则、动作、状态、目标、消息） |
| `summary()` | 汇总字典 |
| `as_dict()` | 含 outcomes 的完整 JSON 字典 |

### 3.3 `folder_ops.archive`

```python
from folder_ops.archive import extract_archive, verify, seven_zip_path, PasswordVault

outcome = extract_archive(
    archive, output_root,
    seven_zip=None, vault=None,
    password_module_enabled=True,
    delete_original=False,
)  # -> ArchiveOutcome
```

`ArchiveOutcome.status`：`ok` / `skipped` / `failed` / `unsolved`。
`verify(...) -> VerifyResult` 字段：`ok`、`file_count_match`、`missing`、`extra`、`size_mismatches`、`crc_mismatches`、`test_exit_code`、`detail`。

## 4. 线程事件（GUI 内部协议）

`RuleWorker` 通过 `queue.Queue[dict]` 发送：

| type | 载荷 |
| --- | --- |
| `started` | `mechanism="rules"`, `verify`, `dry_run` |
| `scanned` | `total`, `total_bytes`, `scan_skipped` |
| `file_start` | `index`, `total`, `name`, `path` |
| `progress` | `index`, `total`, `done`, `skipped`, `failed`, `planned`, `elapsed`, `current_name`, `rule` |
| `finished` | `summary`（`RuleSummary`）, `report`（dict） |
| `error` | `message` |

## 5. 日志格式

```text
2026-11-05 22:10:31 | INFO     | main | 规则引擎启动 | 规则=10 | 文件=4 | 合计=1.2 KB | dry-run=True
2026-11-05 22:10:31 | INFO     | folder_ops.rules.engine | 规则动作 | 文件=a.jpg | 规则=自动分类：图片 | 动作=move | 目标=…/图片/a.jpg | 状态=ok | 已移动
```

字段顺序：时间、级别、任务 ID、模块、消息。规则动作日志固定包含「文件 / 规则 / 动作 / 目标 / 状态 / 说明」。
