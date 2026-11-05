"""CRC 三重校验（移植自 archive-auto-extractor，逻辑未重写）。

三项独立检查全部通过才允许删除原压缩包：
1. 清单比对：`7z l -slt` 存储 CRC 与解压文件 zlib.crc32 逐一比对；
2. 一致性：文件数、路径、大小全部一致；
3. 7z 自检：`7z t` 返回 0（7z 自身的解压后 CRC 测试）。

清单中 CRC 为空的条目（少数固实 RAR4）降级为仅比大小。
"""
from __future__ import annotations

import logging
import zlib
from pathlib import Path

from . import archive_info as archive_info_mod
from .models import ArchiveInfo, ManifestEntry, VerifyResult
from .seven_zip import run_7z

LOGGER = logging.getLogger(__name__)

_CHUNK = 64 * 1024


def crc32_of_file(path: Path) -> str:
    crc = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xFFFFFFFF:08x}"


def _normalize(rel_path: str) -> str:
    return rel_path.replace("\\", "/")


def compute_extracted(dest: Path) -> dict[str, tuple[int, str]]:
    """返回解压目录下每个文件的 (大小, CRC32)。"""
    out: dict[str, tuple[int, str]] = {}
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(dest).as_posix()
        out[_normalize(rel)] = (path.stat().st_size, crc32_of_file(path))
    return out


def verify(
    seven_zip: Path | None,
    archive: Path,
    dest: Path,
    password: str | None = None,
    info: ArchiveInfo | None = None,
) -> VerifyResult:
    """校验解压结果；任何一项不通过都返回 ok=False。"""
    if info is None or not info.manifest:
        if password is not None:
            info = archive_info_mod.list_with_password(seven_zip, archive, password)
        else:
            info = archive_info_mod.detect(seven_zip, archive, password=None)
        if not info.manifest:
            return VerifyResult(ok=False, detail="无法读取压缩包清单，无法校验")

    manifest: list[ManifestEntry] = info.manifest
    extracted = compute_extracted(dest)
    manifest_paths = {_normalize(item.path): item for item in manifest}
    extracted_paths = set(extracted)

    missing = sorted(set(manifest_paths) - extracted_paths)
    extra = sorted(extracted_paths - set(manifest_paths))

    size_mismatches: list[str] = []
    crc_mismatches: list[str] = []
    for rel, entry in manifest_paths.items():
        if rel not in extracted:
            continue
        ex_size, ex_crc = extracted[rel]
        if ex_size != entry.size:
            size_mismatches.append(rel)
            continue
        if entry.crc is None:
            continue
        if ex_crc.lower() != entry.crc.lower():
            crc_mismatches.append(rel)

    file_count_match = len(manifest_paths) == len(extracted_paths)
    test = run_7z(seven_zip, archive, ["t"], password=password)
    test_ok = test.ok

    ok = (
        file_count_match
        and not missing
        and not extra
        and not size_mismatches
        and not crc_mismatches
        and test_ok
    )

    detail_parts: list[str] = []
    if missing:
        detail_parts.append(f"缺失 {len(missing)}")
    if extra:
        detail_parts.append(f"多余 {len(extra)}")
    if size_mismatches:
        detail_parts.append(f"大小不符 {len(size_mismatches)}")
    if crc_mismatches:
        detail_parts.append(f"CRC 不符 {len(crc_mismatches)}")
    if not test_ok:
        detail_parts.append(f"7z t 退出码={test.returncode}")
    detail = "；".join(detail_parts) if detail_parts else "全部校验通过"

    LOGGER.info("校验 %s：ok=%s（%s）", archive.name, ok, detail)
    return VerifyResult(
        ok=ok,
        file_count_match=file_count_match,
        missing=missing,
        extra=extra,
        size_mismatches=size_mismatches,
        crc_mismatches=crc_mismatches,
        test_exit_code=test.returncode,
        detail=detail,
    )
