# CONTRIBUTING · 参与 folder-ops

## 开发环境

```bash
git clone https://github.com/SuHu4088/folder-ops.git
cd folder-ops
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

macOS 建议 Python 3.10+。解压相关开发需要 `7zz`（发布包内置，源码开发可 `brew install sevenzip` 或设置 `FOLDEROPS_7Z`）。

## 提交前检查

```bash
python3 -m pytest -q
python3 main.py --print-default-rules > /tmp/rules.json
python3 main.py --rules /tmp/rules.json --source /tmp --dry-run
```

要求：

1. 测试全绿（当前 72 个）。
2. 新增功能必须补测试；安全相关路径必须有失败用例。
3. 规则字段/默认值变更时，同步更新 `APISpec.md`、`rules.example.json`、`CHANGELOG.md`。
4. 版本号变更时同步 `folder_ops/__init__.py`、`CHANGELOG.md`、`ProjectPlan.md`。
5. 不改动用户数据：测试一律使用 `tmp_path`，禁止在测试中写 `~/.folder_ops` 或应用数据目录。

## 代码约定

- Python 3.10+ 语法；模块内 `from __future__ import annotations`。
- 注释与文档使用中文；公共函数写清「输入 / 输出 / 失败行为」。
- 规则引擎不导入 Tkinter；GUI 只消费引擎结果。
- 破坏性动作必须先校验、后删除；校验失败保留源并返回明确原因。
- 日志使用 `logging`，禁止 `print`（CLI 输出除外）。

## 提交信息

采用 Conventional Commits 风格：

```text
feat(rules): 支持按修改时间过滤
fix(archive): 头部加密包重新列清单
docs(test): 补充篡改检测用例
```

## 新增触发条件或动作

1. 在 `rules/models.py` 的 `CONDITION_TYPES` / `ACTION_TYPES` 注册。
2. 条件实现放 `rules/conditions.py`，动作放 `rules/actions.py`。
3. 在 `tests/test_rules_conditions.py` 或 `test_rules_engine.py` 补用例。
4. 更新 `APISpec.md` 的字段表与 `rules.example.json`。

## 报告问题

请附上：系统版本、Python 版本、7z 版本、规则 JSON、复现步骤、日志片段（脱敏）。安全相关问题见 [SECURITY.md](SECURITY.md)。
