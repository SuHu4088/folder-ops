# 运维与故障处理（OPERATIONS）

## 1. 数据位置

| 内容 | macOS | Windows |
| --- | --- | --- |
| 日志 | `~/Library/Application Support/FolderOps/logs/folder-ops.log` | `%APPDATA%\FolderOps\logs\folder-ops.log` |
| 配置 | `~/Library/Application Support/FolderOps/config.json` | `%APPDATA%\FolderOps\config.json` |
| 默认规则 | `~/Library/Application Support/FolderOps/rules.json` | `%APPDATA%\FolderOps\rules.json` |
| 密码库 | `~/.folder_ops/password_vault`（独立 Git 仓库） | `%USERPROFILE%\.folder_ops\password_vault` |

- 日志轮转：单文件 2 MB，保留 5 个备份（`folder-ops.log.1`…）。
- 界面右上角可「打开日志目录」「导出日志」。
- 重置配置：退出后删除 `config.json`，下次启动回到默认窗口尺寸与选项。

## 2. 规则维护

1. 规则文件为 JSON；GUI「规则引擎」页可加载、查看、恢复默认。
2. 修改前先复制备份：`cp rules.json rules.backup.json`。
3. 保存后点「加载」；非法配置会弹窗并写 ERROR 日志，不会执行。
4. 推荐流程：dry-run 预览 → 抽查日志中的目标路径 → 关闭 dry-run 执行。

常用片段：

```json
{
  "id": "big-videos",
  "name": "大于 1GB 的视频归档",
  "priority": 5,
  "match_mode": "all",
  "conditions": [
    { "type": "extension", "values": ["mp4", "mov"] },
    { "type": "size", "min_bytes": 1073741824 }
  ],
  "actions": [
    { "type": "move", "target": "视频/大文件", "conflict": "rename" }
  ]
}
```

## 3. 7-Zip 依赖

- 解压动作需要 `7zz` / `7z`。
- macOS 发布包已内置（`Contents/Frameworks/vendor/macos-arm64/7zz`），无需另装。
- 源码运行：macOS 可 `brew install sevenzip`；Windows 安装 7-Zip 后确保 `7z.exe` 在 PATH。
- 自定义路径：`export FOLDEROPS_7Z=/path/to/7zz`。
- 未找到时日志会出现「7-Zip 不可用」，该压缩包记为失败，其他动作继续。

## 4. 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 首次打开提示“无法验证开发者” | ad-hoc 签名、无公证 | 右键 →「打开」；或在“系统设置 → 隐私与安全性”允许 |
| 解压全部失败 | 7z 未安装/路径错误 | 安装 7-Zip 或设置 `FOLDEROPS_7Z` |
| 加密包显示“未解决” | 密码库无匹配密码 | 在密码库中加入密码后重试 |
| 目标目录被跳过 | 目标=源目录 | 正常保护行为，不会自我重命名 |
| 规则不生效 | 被更高优先级规则先命中 | 调整 `priority`，数值越小越先 |
| 移动后源仍在 | 双校验未通过 | 查看日志中的校验失败原因；源被保留是安全设计 |
| 密码库提交失败 | Git 未配置用户名/邮箱 | 在库目录执行 `git config user.name/user.email` |

## 5. 备份与恢复

- 规则：直接复制 `rules.json`。
- 密码库：整个目录即 Git 仓库，`git log` 可回溯每次变更；恢复用 `git checkout <commit> -- passwords.json`。
- 配置：删除即可重置，不会影响规则与密码库。

## 6. 卸载

1. 退出应用。
2. 删除 `/Applications/FolderOps.app`。
3. 如需彻底清理：删除 `~/Library/Application Support/FolderOps` 与 `~/.folder_ops`（后者含密码库，请先备份）。
