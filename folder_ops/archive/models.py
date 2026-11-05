"""压缩包子系统的数据模型（纯数据，无 I/O）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_UNSOLVED = "unsolved"


@dataclass(frozen=True)
class ManifestEntry:
    """压缩包内一个文件：归档内路径、原始大小、存储的 CRC32（可为空）。"""

    path: str
    size: int
    crc: str | None = None


@dataclass
class ArchiveInfo:
    """压缩包探测结果。"""

    path: Path
    format: str
    is_password_protected: bool
    header_encrypted: bool
    manifest: list[ManifestEntry] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.manifest)


@dataclass
class ExtractionResult:
    """解压结果。"""

    ok: bool
    dest: Path
    extracted_files: list[Path] = field(default_factory=list)
    error: str = ""


@dataclass
class VerifyResult:
    """CRC 三重校验结果；ok 为 True 才允许删除原压缩包。"""

    ok: bool
    file_count_match: bool = False
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    size_mismatches: list[str] = field(default_factory=list)
    crc_mismatches: list[str] = field(default_factory=list)
    test_exit_code: int = 0
    detail: str = ""


@dataclass
class ArchiveOutcome:
    """单个压缩包的最终结果。"""

    path: Path
    status: str
    message: str
    dest: Path | None = None
    extracted_count: int = 0
    password_used: str | None = None
    verified: bool = False
    deleted_original: bool = False
