"""内置规则插件：自动分类与自动解压。

插件只生成规则数据（Rule 对象），执行仍由 RuleEngine 统一调度。
"""
from __future__ import annotations

from .models import Action, Condition, Rule

CATEGORY_EXTENSIONS: dict[str, list[str]] = {
    "图片": ["jpg", "jpeg", "png", "gif", "webp", "heic", "tiff", "bmp", "svg", "raw", "cr2", "nef"],
    "视频": ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "ts", "mpg", "mpeg"],
    "音频": ["mp3", "flac", "wav", "aac", "m4a", "ogg", "wma", "opus", "aiff"],
    "文档": ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "rtf", "csv", "pages", "numbers", "key"],
    "代码": ["py", "js", "ts", "tsx", "jsx", "java", "c", "h", "cpp", "go", "rs", "rb", "php", "sh", "json", "yaml", "yml", "toml", "html", "css", "sql"],
    "压缩包": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz"],
    "安装包": ["dmg", "pkg", "exe", "msi", "deb", "rpm", "apk"],
    "字体": ["ttf", "otf", "woff", "woff2"],
    "电子书": ["epub", "mobi", "azw3", "pdf"],
}

ARCHIVE_EXTENSIONS = ("zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz")


def builtin_classifier_rules(
    mechanism: str = "move",
    target_root: str = "",
    priorities: dict[str, int] | None = None,
    verify: bool = False,
) -> list[Rule]:
    """生成按扩展名分类的规则组（每个分类一条规则）。"""
    if mechanism not in ("move", "copy"):
        raise ValueError("mechanism 只能是 move 或 copy")
    base = priorities or {}
    rules: list[Rule] = []
    for index, (category, extensions) in enumerate(CATEGORY_EXTENSIONS.items()):
        rules.append(
            Rule(
                id=f"builtin.classify.{category}",
                name=f"自动分类：{category}",
                enabled=True,
                priority=base.get(category, 10 + index),
                match_mode="any",
                conditions=[Condition("extension", {"values": extensions})],
                actions=[
                    Action(
                        mechanism,
                        {
                            "target": f"{target_root}/{category}" if target_root else category,
                            "conflict": "rename",
                            "verify": verify,
                        },
                    )
                ],
                notes=f"内置分类插件：{len(extensions)} 种扩展名 → {category}/",
            )
        )
    return rules


def builtin_archive_extractor_rule(
    output_root: str = "",
    delete_original: bool = False,
    password_module: bool = True,
    priority: int = 1,
    cleanup_empty: bool = True,
) -> Rule:
    """自动解压规则：压缩包 → 解压 + CRC 三重校验 → 可选删源 / 清空目录。"""
    actions = [
        Action(
            "extract",
            {
                "target": output_root,
                "delete_original": delete_original,
                "password_module": password_module,
            },
        )
    ]
    if cleanup_empty:
        actions.append(Action("cleanup_empty"))
    return Rule(
        id="builtin.archive.extract",
        name="自动解压（CRC 校验）",
        enabled=True,
        priority=priority,
        conditions=[Condition("extension", {"values": list(ARCHIVE_EXTENSIONS)})],
        actions=actions,
        notes="内置解压插件：复用 archive-auto-extractor 的 CRC 三重校验与密码库",
    )


def builtin_plugins() -> list[dict]:
    """内置插件元数据（供 GUI / CLI 展示）。"""
    return [
        {
            "id": "builtin.classifier",
            "name": "自动分类",
            "rules": len(CATEGORY_EXTENSIONS),
            "description": "按扩展名把文件移动/复制到分类子目录",
        },
        {
            "id": "builtin.archive_extractor",
            "name": "自动解压",
            "rules": 1,
            "description": "压缩包解压 + CRC 三重校验，可选密码库与删除原包",
        },
    ]
