"""压缩包子系统：7-Zip 调用、清单解析、CRC 三重校验、密码库。

算法移植自 archive-auto-extractor（MIT），未重写已验证的校验逻辑。
"""
from .models import ArchiveInfo, ArchiveOutcome, ExtractionResult, ManifestEntry, VerifyResult
from .service import extract_archive, seven_zip_path
from .seven_zip import SevenZipError, run_7z

__all__ = [
    "ArchiveInfo",
    "ArchiveOutcome",
    "ExtractionResult",
    "ManifestEntry",
    "VerifyResult",
    "SevenZipError",
    "extract_archive",
    "run_7z",
    "seven_zip_path",
]
