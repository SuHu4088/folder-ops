# TestPlan · folder-ops V0.2.0

## 1. 测试目标

验证规则引擎在真实文件系统上的正确性、安全边界（校验通过才删除）、dry-run 零副作用，以及原有 FolderCut 能力无回归。

## 2. 测试环境

| 项目 | 值 |
| --- | --- |
| 系统 | macOS（arm64） |
| 运行测试的解释器 | Python 3.9.6（系统 python3） |
| 打包解释器 | Python 3.14.8（Homebrew） |
| 7-Zip | 26.05（`vendor/macos-arm64/7zz`） |
| 测试框架 | pytest |
| 执行命令 | `python3 -m pytest -q` |
| 发布产物 | `FolderOps.app`：ad-hoc 签名、未公证、仅 arm64（Intel 需本地重打包） |

## 3. 测试分层

| 层级 | 范围 | 文件 |
| --- | --- | --- |
| 单元 | 条件求值、规则校验、CRC、清单解析 | `test_rules_conditions.py`、`test_rules_store.py`、`test_archive_core.py` |
| 集成 | 引擎扫描→匹配→动作→清理 | `test_rules_engine.py` |
| 回归 | FolderCut 扫描/移动/清理/配置/UI 联动 | `test_scanner.py`、`test_mover.py`、`test_cleanup.py`、`test_config.py`、`test_worker.py`、`test_ui_linkage.py` |
| 手工 | GUI 双标签页、预览/执行、`.app` 启动 | 见第 6 节 |

## 4. 自动化用例

### 4.1 条件（test_rules_conditions.py）

| 用例 | 断言 |
| --- | --- |
| 扩展名大小写与前导点 | `photo.PNG` 命中 `png` |
| 双后缀 | `backup.tar.gz` 命中 `tar.gz` |
| 大小闭区间 | 100 字节命中 [50,200]，101 不命中 min=101 |
| 日期 | 40 天前命中 `older_than_days=30`，不命中 `newer_than_days=30` |
| 文件名正则 | 大小写敏感/不敏感两种 |
| 通配与压缩包 | `bundle.*`、`.ZIP` 命中 `is_archive` |
| any/all | 同一组条件，any 命中、all 不命中 |
| 非法条件 | 抛出异常 |

### 4.2 规则存储（test_rules_store.py）

| 用例 | 断言 |
| --- | --- |
| 默认规则 | 10 条；首条为解压；含“图片”分类 |
| 保存/加载往返 | 10 条；条件参数为扁平结构 |
| 缺失文件 | 自动生成默认规则 |
| 复制插件 | 动作为 copy，目标 `sorted/图片` |
| 解压插件 | 动作序列 `extract` → `cleanup_empty` |
| 非法载荷 | 空规则、重复 id、未知条件、非法 conflict 均抛 `RuleError` |

### 4.3 引擎（test_rules_engine.py）

| 用例 | 断言 |
| --- | --- |
| 移动图片 | 4 个文件扫描，移动 2，非图片保留 |
| 复制 | 源保留且目标存在 |
| dry-run | 计划 2，磁盘无变化，状态均为 planned |
| 优先级 | 低 priority 规则先命中，目标进入“先/” |
| 停用规则 | 命中 0，未命中 4 |
| 清理空目录 | 删除嵌套空目录，顶层受保护 |
| all 模式 | 扩展名+大小需同时满足 |
| 解压插件 | 调用注入的 extract 服务，路径与输出根正确 |
| 解压失败 | 失败计数 1，不产生解压成功 |
| 同名冲突 | `photo.jpg` 与 `photo_1.jpg` 并存 |
| 规则校验 | 无条件规则抛 `RuleError` |

### 4.4 压缩包（test_archive_core.py）

| 用例 | 断言 |
| --- | --- |
| 清单解析 | 解析格式、路径、大小、CRC、加密标记 |
| CRC | 与 `zipfile` 元数据一致 |
| 真实解压 | 3 个文件成功，`verified=True`，原包删除 |
| 篡改检测 | 同大小改内容 → `ok=False`，`crc_mismatches` 命中文件 |
| 目标重名 | 已存在非空 `bundle/` 时输出到 `bundle_1/` |
| 包不存在 | `status=failed`，消息含“不存在” |

### 4.5 回归（原有 37 个）

覆盖扫描递归范围、MD5+SHA1 双校验、跨盘移动安全路径、同名策略、空目录保护、配置读写、任务线程事件、UI 与 Worker 联动。

## 5. 实际执行结果

```text
$ python3 -m pytest -q
72 passed in 0.42s
```

- 通过：72
- 失败：0
- 跳过：0（本机存在 7zz，真实解压用例全部执行）

真实解压链路（v0.2.0 手工验证）：

```text
输入：a.jpg / note.txt / docs/clip.mp4 / bundle.zip
dry-run：扫描 4，命中 4，计划 4，未修改磁盘
apply：移动 3、解压 1、清理空目录 1，CRC 校验通过，原包保留
```

## 6. 手工测试清单

| # | 步骤 | 预期 |
| --- | --- | --- |
| 1 | 启动 `python3 main.py` | 窗口居中，深色主题，两个标签页 |
| 2 | 切换到「规则引擎」 | 目标目录区隐藏；显示规则清单 10 条 |
| 3 | 点「预览规则」 | 进度条运行、日志逐条、结束后提示“未修改磁盘” |
| 4 | 关闭 dry-run 再执行 | 弹确认框；确认后真实移动/解压 |
| 5 | 取消任务 | 当前文件完成后停止，状态提示已取消 |
| 6 | 修改规则文件为非法 JSON 并加载 | 明确错误弹窗，不崩溃 |
| 7 | 双击 `dist/FolderOps.app` | 可启动；被 Gatekeeper 拦截时右键「打开」或 `xattr -dr com.apple.quarantine` 后可用；内置 7zz 可用 |
| 8 | 无 7-Zip 环境执行解压规则 | 该文件失败并提示安装，其他动作继续 |
| 9 | `codesign -dv dist/FolderOps.app` | 输出 `Signature=adhoc`，架构为 arm64；`spctl` 拒绝属预期 |
| 10 | Intel Mac 按 README「本地打包」执行 `bash script/build_app.sh` | 生成对应架构 `.app`；仍为 ad-hoc 签名、未公证，首次需右键打开 |

## 7. 回归门槛

发布前必须满足：

1. `pytest` 全绿且数量不少于 72。
2. 真实 zip 解压 + 篡改检测通过。
3. `script/build_app.sh` 成功，`codesign --verify` 通过。
4. GUI 手工清单 1–5 通过。
5. CHANGELOG 与版本号一致。
6. README「本地打包 / 自行构建」中的签名、公证、架构描述与产物实际一致。
