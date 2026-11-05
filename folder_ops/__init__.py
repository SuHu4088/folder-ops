"""folder-ops：以规则引擎驱动的文件夹运维套件。

核心原则：
1. 未经 MD5 + SHA1 双校验通过，绝不删除源文件；
2. 压缩包未经 CRC 三重校验通过，绝不删除原压缩包；
3. 规则只做声明，执行统一走可审计的动作层。
"""

__version__ = "0.2.0"
APP_NAME = "FolderOps"
APP_TITLE = "folder-ops 文件夹规则引擎"
APP_SUBTITLE = "规则驱动：分类 / 转移 / 解压 / 空目录清理"
