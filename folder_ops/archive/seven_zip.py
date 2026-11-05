"""7-Zip 命令行封装（跨平台自动发现可执行文件）。

移植自 archive-auto-extractor，新增 macOS / Linux 发现逻辑：
环境变量 FOLDEROPS_7Z → 打包内置 → PATH 中的 7zz / 7z / 7za → 常见安装路径。
所有调用统一走 run_7z，始终带 -p 与 -y，避免 7z 等待 stdin 挂起。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..platform_utils import long_path

LOGGER = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FATAL = 2
EXIT_WRONG_PASSWORD = 255

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_CANDIDATES = (
    "7zz", "7z", "7za",
    "/opt/homebrew/bin/7zz",
    "/usr/local/bin/7zz",
    "/opt/homebrew/bin/7z",
    "/usr/local/bin/7z",
    "C:\\Program Files\\7-Zip\\7z.exe",
)

# 项目内置（仅 macOS arm64 发布包随包附带，见 NOTICE）
_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "macos-arm64" / "7zz"


class SevenZipError(RuntimeError):
    """7z 不可用或调用失败。"""

    def __init__(self, returncode: int, stderr: str, command: list[str] | None = None):
        self.returncode = returncode
        self.stderr = stderr
        self.command = command or []
        super().__init__(f"7z exited {returncode}: {stderr.strip()[:200]}")


def discover(seven_zip: Path | str | None = None) -> Path:
    """返回可用的 7z 可执行文件路径；找不到时抛出 SevenZipError。"""
    candidates: list[Path] = []
    if seven_zip:
        candidates.append(Path(str(seven_zip)).expanduser())
    env = os.environ.get("FOLDEROPS_7Z", "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / ("7z.exe" if os.name == "nt" else "7zz"))
    candidates.append(_VENDOR)
    for name in _CANDIDATES:
        found = shutil.which(name) if not os.path.isabs(name) else None
        candidates.append(Path(found) if found else Path(name))

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    raise SevenZipError(-1, "未找到 7-Zip 可执行文件；请安装 7-Zip 或设置 FOLDEROPS_7Z")


@dataclass
class SevenZipResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == EXIT_OK

    @property
    def warning(self) -> bool:
        return self.returncode == 1

    @property
    def wrong_password(self) -> bool:
        if self.returncode == EXIT_WRONG_PASSWORD:
            return True
        if self.returncode == EXIT_FATAL:
            low = (self.stderr or "").lower()
            return "wrong password" in low or "cannot open encrypted" in low
        return False

    @property
    def corrupt(self) -> bool:
        if self.wrong_password:
            return False
        if self.returncode == EXIT_FATAL:
            low = (self.stderr or "").lower()
            return "crc failed" in low or "data error" in low or "cannot open" in low
        return False


def run_7z(
    seven_zip: Path | str | None,
    archive: Path,
    args: list[str],
    password: str | None = None,
    timeout: int | None = None,
) -> SevenZipResult:
    """执行一次 7z 命令。

    args 为操作参数（如 ["x", "-odest"]），压缩包路径会自动追加；
    密码为空时也传 -p""，配合 -y 彻底消除交互等待。
    """
    binary = discover(seven_zip)
    cmd = [
        long_path(binary), *args, long_path(archive),
        f"-p{password if password is not None else ''}", "-y", "-bb1", "-bso0", "-bse2",
    ]
    LOGGER.debug("7z 调用：%s | 密码=%s", " ".join(args), "***" if password else "无")
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise SevenZipError(-1, f"7z 超时（{timeout}s）", cmd) from exc
    return SevenZipResult(proc.returncode, proc.stdout or "", proc.stderr or "")
