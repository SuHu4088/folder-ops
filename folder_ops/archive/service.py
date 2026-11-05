"""单压缩包端到端流程：探测 → 解密 → 解压 → CRC 校验 → 可选删源。

状态机移植自 archive-auto-extractor，去掉 Qt 依赖，供规则引擎与 GUI 复用。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from . import archive_info, extractor, verifier
from .models import ArchiveOutcome, STATUS_FAILED, STATUS_OK, STATUS_SKIPPED, STATUS_UNSOLVED
from .seven_zip import SevenZipError, discover, run_7z
from .vault import PasswordVault

LOGGER = logging.getLogger(__name__)


def seven_zip_path() -> Path | None:
    """返回可用的 7z 路径；未安装时返回 None（调用方据此给出明确失败）。"""
    try:
        return discover()
    except SevenZipError:
        return None


def _unique_dest(root: Path, archive: Path) -> Path:
    """同名子文件夹；已存在且非空时追加 _1、_2…，避免混入旧内容。"""
    root.mkdir(parents=True, exist_ok=True)
    base = archive.stem
    for index in range(0, 9999):
        name = base if index == 0 else f"{base}_{index}"
        candidate = root / name
        if not candidate.exists():
            return candidate
        try:
            if not [item for item in candidate.iterdir() if not item.name.startswith(".")]:
                return candidate
        except OSError:
            return candidate
    return root / f"{base}_{os.getpid()}"


def _delete_original(path: Path) -> bool:
    try:
        from send2trash import send2trash  # type: ignore[import-not-found]

        send2trash(str(path))
    except ImportError:
        path.unlink()
    except Exception as exc:  # noqa: BLE001 - 删除失败不应中断批次
        LOGGER.error("删除原压缩包失败：%s | %s", path, exc)
        return False
    return True


def extract_archive(
    archive: Path,
    output_root: Path,
    *,
    seven_zip: Path | None = None,
    vault: PasswordVault | None = None,
    password_module_enabled: bool = True,
    delete_original: bool = False,
) -> ArchiveOutcome:
    """处理单个压缩包；所有可预期异常都转为失败结果。"""
    archive = Path(archive)
    dest = Path(output_root)

    if not archive.is_file():
        return ArchiveOutcome(archive, STATUS_FAILED, "压缩包不存在")

    try:
        info = archive_info.detect(seven_zip, archive)
    except SevenZipError as exc:
        return ArchiveOutcome(archive, STATUS_FAILED, f"7-Zip 不可用：{exc}")

    if info.is_password_protected:
        if not password_module_enabled or vault is None:
            return ArchiveOutcome(archive, STATUS_SKIPPED, "受密码保护，已跳过（密码模块未启用）")
        return _try_passwords(archive, dest, info, seven_zip, vault, delete_original)

    return _extract_and_verify(archive, dest, None, info, seven_zip, delete_original)


def _try_passwords(
    archive: Path,
    root: Path,
    info,
    seven_zip: Path | None,
    vault: PasswordVault,
    delete_original: bool,
) -> ArchiveOutcome:
    candidates = list(vault.iter_passwords())
    if not candidates:
        vault.record_failure_all(archive.name)
        return ArchiveOutcome(archive, STATUS_UNSOLVED, "密码库为空，已尝试所有密码仍无法打开")

    for entry, password in candidates:
        test = run_7z(seven_zip, archive, ["t"], password=password)
        if test.ok:
            if info.header_encrypted:
                info = archive_info.list_with_password(seven_zip, archive, password)
            vault.record_success(entry.id, archive.name)
            return _extract_and_verify(archive, root, password, info, seven_zip, delete_original)
        if test.corrupt:
            return ArchiveOutcome(archive, STATUS_FAILED, "压缩包已损坏，无法解压")

    vault.record_failure_all(archive.name)
    return ArchiveOutcome(archive, STATUS_UNSOLVED, "已尝试所有密码仍无法打开")


def _extract_and_verify(
    archive: Path,
    root: Path,
    password: str | None,
    info,
    seven_zip: Path | None,
    delete_original: bool,
) -> ArchiveOutcome:
    dest = _unique_dest(root, archive)
    try:
        extraction = extractor.extract(seven_zip, archive, dest, password=password)
        if not extraction.ok:
            return ArchiveOutcome(archive, STATUS_FAILED, f"解压失败：{extraction.error}", dest=dest)

        verification = verifier.verify(seven_zip, archive, dest, password=password, info=info)
        if not verification.ok:
            return ArchiveOutcome(
                archive, STATUS_FAILED, f"CRC 校验失败：{verification.detail}",
                dest=dest, extracted_count=len(extraction.extracted_files),
                password_used=password,
            )
    except SevenZipError as exc:
        return ArchiveOutcome(archive, STATUS_FAILED, f"7-Zip 调用失败：{exc}", dest=dest)

    deleted = False
    if delete_original and _delete_original(archive):
        deleted = True
    message = (
        f"已解压 {len(extraction.extracted_files)} 个文件，CRC 校验通过，"
        + ("已删除原压缩包" if deleted else "保留原压缩包")
    )
    return ArchiveOutcome(
        archive, STATUS_OK, message,
        dest=dest, extracted_count=len(extraction.extracted_files),
        password_used=password, verified=True, deleted_original=deleted,
    )
