# DataAnnotationSpec · 数据与规则标注规范

本文件定义 folder-ops 中「分类标签、规则字段、测试样本」三类标注口径，保证规则、文档、测试使用同一套语义。

## 1. 分类标签口径

内置 `builtin_classifier` 的 10 个标签：

| 标签 | 判定口径 | 扩展名 |
| --- | --- | --- |
| 图片 | 静态图像 / 相机原始格式 | jpg, jpeg, png, gif, webp, heic, tiff, bmp, svg, raw, cr2, nef |
| 视频 | 视频容器 | mp4, mkv, avi, mov, wmv, flv, webm, m4v, ts, mpg, mpeg |
| 音频 | 音频编码 | mp3, flac, wav, aac, m4a, ogg, wma, opus, aiff |
| 文档 | 办公/阅读/纯文本 | pdf, doc, docx, xls, xlsx, ppt, pptx, txt, md, rtf, csv, pages, numbers, key |
| 代码 | 源码与配置 | py, js, ts, tsx, jsx, java, c, h, cpp, go, rs, rb, php, sh, json, yaml, yml, toml, html, css, sql |
| 压缩包 | 归档容器 | zip, rar, 7z, tar, gz, bz2, xz, tgz |
| 安装包 | 安装/分发介质 | dmg, pkg, exe, msi, deb, rpm, apk |
| 字体 | 字体文件 | ttf, otf, woff, woff2 |
| 电子书 | 电子书格式 | epub, mobi, azw3, pdf |

标注规则：

1. 扩展名一律小写、无前导点。
2. 一个扩展名只能出现在一个主分类；`pdf` 同时出现在文档与电子书是**历史兼容例外**，规则引擎按优先级先命中者生效，默认“文档”优先（priority 较小）。
3. 新增分类必须同时更新：`plugins.py`、本文件、`APISpec.md`、`test_rules_store.py` 的规则数量断言。

## 2. 规则字段标注

每条规则在评审时必须标注以下信息：

| 字段 | 标注要求 |
| --- | --- |
| `id` | `builtin.<插件>.<语义>` 或 `user.<主题>.<语义>`，全局唯一 |
| `name` | 面向用户的中文短名，不超过 20 字 |
| `priority` | 内置解压固定 1；分类从 10 递增；用户规则建议 ≥ 50 |
| `match_mode` | 默认 `any`；需要“同时满足”时显式 `all` |
| `conditions` | 每个条件写清参数单位（字节 / 天 / 日期格式） |
| `actions` | 写明目标根、冲突策略、是否删源 |
| `notes` | 一句话说明业务意图与风险 |

## 3. 测试样本标注

每个引擎测试的样本目录必须满足：

- 文件内容最小化（几字节即可），但**同名冲突用例**需保证大小不同以便区分。
- 样本不写入用户目录；统一使用 `tmp_path`。
- 解压用例的压缩包由 `zipfile` 现造，避免二进制入库。
- 断言必须覆盖：动作计数、目标路径、源是否保留、失败状态。
- 篡改检测用例必须保持文件大小不变，仅修改内容，以验证 CRC 而非大小分支。

## 4. 规则来源与迁移

| 规则来源 | 迁移方式 |
| --- | --- |
| file-auto-classifier 的分类映射 | 原扩展名表 → `CATEGORY_EXTENSIONS` |
| archive-auto-extractor 的压缩包后缀 | 原检测逻辑 → `is_archive` / `extension` 条件 |
| FolderCut 的递归/冲突/清理选项 | 映射为 `settings.recursion`、`conflict`、`cleanup_empty` |

迁移原则：**保留原有语义，不扩大匹配范围**；如需扩大，必须新增规则并在 CHANGELOG 标注。

## 5. 版本与口径同步

- 分类数量、默认规则条数变化时，`README.md`、`RequirementsSpec.md`、`TestPlan.md`、`CHANGELOG.md` 必须同步。
- 规则 JSON 字段新增/删除时，`APISpec.md` 与 `rules.example.json` 必须同步。
