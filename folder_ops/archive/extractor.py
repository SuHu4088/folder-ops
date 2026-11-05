"""压缩包解压（`7z x`）。目标目录必须为空，避免多次解压混在一起。"""
from __future__ import annotations

import logging
from pathlib import Path

from .models import ExtractionResult
from .seven_zip import run_7z

LOGGER = logging.getLogger(__name__)


def is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def extract(
    seven_zip: Path | None,
    archive: Path,
    dest: Path,
    password: str | None = None,
) -> ExtractionResult:
    dest.mkdir(parents=True, exist_ok=True)
    existing = [item for item in dest.iterdir() if not is_hidden(item)]
    if existing:
        return ExtractionResult(ok=False, dest=dest, error=f"目标目录非空：{dest}")

    result = run_7z(seven_zip, archive, ["x", f"-o{dest}"], password=password)
    if not result.ok:
        return ExtractionResult(
            ok=False, dest=dest,
            error=(result.stderr or f"7z 退出码 {result.returncode}").strip(),
        )
    extracted = sorted(item for item in dest.rglob("*") if item.is_file())
    LOGGER.info("已从 %s 解压 %d 个文件到 %s", archive.name, len(extracted), dest)
    return ExtractionResult(ok=True, dest=dest, extracted_files=extracted)
