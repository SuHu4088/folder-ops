# CHANGELOG

## [0.2.0] - 2026-11-05

首个合并版本：把 FolderCut、archive-auto-extractor、file-auto-classifier 的能力收敛为「规则引擎」套件。

### 新增

- 规则引擎：7 类触发条件（扩展名、大小、日期、文件名正则、文件名通配、路径正则、压缩包）与 4 类动作（移动、复制、解压、删除空目录）。
- 规则优先级、`any`/`all` 匹配模式、首命中生效、dry-run 预览、同名冲突 `rename`/`skip`。
- 内置插件 `builtin_classifier`（10 个分类）与 `builtin_archive_extractor`（解压 + CRC 校验）。
- 压缩包子系统：跨平台 7z 自动发现、`7z l -slt` 清单解析、CRC 三重校验、密码库（Git 审计、两步删除）。
- GUI「规则引擎」标签页：规则文件加载/选择/恢复默认/JSON 预览、规则清单、dry-run 开关、执行与取消。
- CLI：`--rules`、`--source`、`--dry-run`、`--apply`、`--json-report`、`--print-default-rules`。
- `rules.example.json` 与全套中文文档（ProjectPlan、RequirementsSpec、SystemDesign、APISpec、TestPlan、运维与打包）。
- 新增 35 个测试（条件、规则存储、引擎、压缩包），总数 72。

### 变更

- 包名 `folder_cutter` → `folder_ops`，应用名 FolderCut → folder-ops，版本号 0.1.0 → 0.2.0。
- 应用数据目录迁移到 `FolderOps`（配置、日志、默认规则）。
- 日志文件名 `foldercut.log` → `folder-ops.log`。
- 「执行设置」放入滚动容器，避免小屏裁切；新增 Notebook 标签样式。
- 打包配置改为 `packaging/FolderOps.spec`，产物 `FolderOps.app`，Bundle ID `io.folderops.app`。
- 文档：README 新增「本地打包 / 自行构建」，明确 ad-hoc 签名、未公证、仅 arm64、首次打开的两种放行方式，以及 Intel Mac 重打包的前置依赖；TestPlan 同步补充签名/架构手工项。

### 修复

- 规则把文件移动到其所在目录时不再自我重命名（直接跳过）。
- `_unique_dest` 对非空同名目录的处理修正，正确追加 `_1`。
- dry-run 不再创建或写入密码库，保证预览零副作用。

### 构建

- `script/build_app.sh` 一键构建并 ad-hoc 签名。
- `.app` 内置 `vendor/macos-arm64/7zz`（7-Zip 26.05，LGPL），解压开箱可用。
- 发布产物仅 arm64、未公证；Intel Mac 需在本地重打包，Windows / Linux 直接源码运行。

## [0.1.0] - 2026-11-05

FolderCut 基础版：

- 深色 Tkinter GUI，拖拽/选择文件夹。
- 复制/剪切两种机制，MD5 + SHA1 双校验，校验通过才删除源。
- 递归范围（第一层 / 两层 / 全递归）、同名冲突策略、空目录清理。
- 37 个测试，PyInstaller `.app` 打包。
