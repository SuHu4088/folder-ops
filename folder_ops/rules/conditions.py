"""触发条件实现：扩展名 / 大小 / 日期 / 文件名正则 / 文件名通配 / 路径正则 / 压缩包。"""
from __future__ import annotations

import fnmatch
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from .models import Condition

LOGGER = logging.getLogger(__name__)

ARCHIVE_EXTENSIONS = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz"}


def _extension(params: Mapping[str, Any], path: Path, stat_result) -> bool:
    values = {str(item).lower().lstrip(".") for item in params.get("values", [])}
    suffix = path.suffix.lower().lstrip(".")
    if suffix in values:
        return True
    # 支持 tar.gz 这类双后缀
    return suffix and path.name.lower().endswith(tuple(f".{item}" for item in values))


def _size(params: Mapping[str, Any], path: Path, stat_result) -> bool:
    size = stat_result.st_size
    minimum = params.get("min_bytes")
    maximum = params.get("max_bytes")
    if minimum is not None and size < int(minimum):
        return False
    if maximum is not None and size > int(maximum):
        return False
    return True


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            LOGGER.warning("日期条件无法解析：%s", value)
            return None


def _date(params: Mapping[str, Any], path: Path, stat_result) -> bool:
    modified = datetime.fromtimestamp(stat_result.st_mtime)
    older = params.get("older_than_days")
    newer = params.get("newer_than_days")
    after = _parse_date(params.get("after"))
    before = _parse_date(params.get("before"))
    now = datetime.now()
    if older is not None and modified >= now - timedelta(days=int(older)):
        return False
    if newer is not None and modified <= now - timedelta(days=int(newer)):
        return False
    if after is not None and modified < after:
        return False
    if before is not None and modified > before:
        return False
    return True


def _name_regex(params: Mapping[str, Any], path: Path, stat_result) -> bool:
    flags = re.IGNORECASE if params.get("ignore_case", True) else 0
    return re.search(str(params["pattern"]), path.name, flags) is not None


def _name_glob(params: Mapping[str, Any], path: Path, stat_result) -> bool:
    pattern = str(params.get("pattern", ""))
    return fnmatch.fnmatch(path.name.lower(), pattern.lower())


def _path_regex(params: Mapping[str, Any], path: Path, stat_result) -> bool:
    flags = re.IGNORECASE if params.get("ignore_case", True) else 0
    return re.search(str(params["pattern"]), path.as_posix(), flags) is not None


def _is_archive(params: Mapping[str, Any], path: Path, stat_result) -> bool:
    return path.suffix.lower().lstrip(".") in ARCHIVE_EXTENSIONS


CONDITIONS: dict[str, Callable[[Mapping[str, Any], Path, Any], bool]] = {
    "extension": _extension,
    "size": _size,
    "date": _date,
    "name_regex": _name_regex,
    "name_glob": _name_glob,
    "path_regex": _path_regex,
    "is_archive": _is_archive,
}


def evaluate(condition: Condition, path: Path, stat_result: Any) -> bool:
    handler = CONDITIONS.get(condition.type)
    if handler is None:
        LOGGER.warning("条件类型未实现：%s", condition.type)
        return False
    try:
        return bool(handler(condition.params, path, stat_result))
    except (OSError, ValueError, re.error) as exc:
        LOGGER.warning("条件求值失败（%s）：%s", condition.type, exc)
        return False
