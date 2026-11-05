"""压缩包探测与清单构建（`7z l -slt`）。

移植自 archive-auto-extractor。可区分头部加密、数据加密与明文压缩包，
并解析出每个文件的原始大小与存储 CRC32，供校验阶段使用。
"""
from __future__ import annotations

import logging
from pathlib import Path

from .models import ArchiveInfo, ManifestEntry
from .seven_zip import run_7z

LOGGER = logging.getLogger(__name__)

_ENCRYPTED_MARKERS = ("wrong password", "cannot open encrypted", "enter password")


def parse_slt(stdout: str) -> tuple[list[ManifestEntry], str, bool]:
    """解析 `7z l -slt` 输出，返回 (清单, 格式, 是否见加密条目)。"""
    manifest: list[ManifestEntry] = []
    archive_format = "unknown"
    encrypted_seen = False

    for block in stdout.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
        if "Type" in fields and archive_format == "unknown":
            archive_format = fields["Type"].strip().lower()
        if "Path" in fields and "Type" not in fields:
            entry_path = fields["Path"].strip()
            if not entry_path or fields.get("Folder", "-").strip() == "+":
                continue
            if fields.get("Encrypted", "-").strip() == "+":
                encrypted_seen = True
            try:
                size = int(fields.get("Size", "0").strip() or 0)
            except ValueError:
                size = 0
            crc = fields.get("CRC", "").strip() or None
            manifest.append(ManifestEntry(path=entry_path, size=size, crc=crc))
    return manifest, archive_format, encrypted_seen


def detect(seven_zip: Path | None, archive: Path, password: str | None = None) -> ArchiveInfo:
    """探测压缩包：格式、加密状态、可用清单。"""
    result = run_7z(seven_zip, archive, ["l", "-slt"], password=password)
    fallback_format = Path(archive).suffix.lstrip(".").lower()

    if result.ok:
        manifest, fmt, encrypted = parse_slt(result.stdout)
        return ArchiveInfo(
            path=archive,
            format=fmt if fmt != "unknown" else fallback_format,
            is_password_protected=encrypted,
            header_encrypted=False,
            manifest=manifest,
        )

    low = (result.stderr or "").lower()
    if any(marker in low for marker in _ENCRYPTED_MARKERS) or result.wrong_password:
        LOGGER.info("压缩包头部加密，无法直接列出：%s", archive.name)
        return ArchiveInfo(archive, fallback_format, True, True, [])

    LOGGER.warning("压缩包不可读：%s | %s", archive.name, (result.stderr or "").strip())
    return ArchiveInfo(archive, fallback_format, False, False, [])


def list_with_password(seven_zip: Path | None, archive: Path, password: str) -> ArchiveInfo:
    """已知密码后重新列出清单（头部加密包校验前必须调用）。"""
    result = run_7z(seven_zip, archive, ["l", "-slt"], password=password)
    fallback_format = Path(archive).suffix.lstrip(".").lower()
    if result.ok:
        manifest, fmt, encrypted = parse_slt(result.stdout)
        return ArchiveInfo(
            path=archive,
            format=fmt if fmt != "unknown" else fallback_format,
            is_password_protected=encrypted,
            header_encrypted=False,
            manifest=manifest,
        )
    LOGGER.warning("带密码列出失败：%s | %s", archive.name, (result.stderr or "").strip())
    return ArchiveInfo(archive, fallback_format, True, True, [])
