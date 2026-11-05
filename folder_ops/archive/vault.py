"""密码库：唯一的读写入口，每次变更自动 Git 提交（移植自 archive-auto-extractor）。

设计要点：
- 库文件位于项目外（默认 ~/.folder_ops/password_vault），本身是一个 Git 仓库；
- 读取返回副本，写入先写临时文件再 os.replace；
- 删除必须两步确认（prepare_delete → delete_password）；
- 所有变更产生可追溯的提交信息。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

LOGGER = logging.getLogger(__name__)

VAULT_FILENAME = "passwords.json"
VAULT_README_FILENAME = "README.md"
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_VAULT_README = """# folder-ops 密码库

该目录由 folder-ops 自动管理，位于项目之外，并作为独立 Git 仓库保存。
每次新增、修改、启停、删除密码都会产生一条可追溯的提交。
"""


@dataclass
class VaultEntry:
    """一条密码记录。"""

    id: str
    value: str
    label: str = ""
    enabled: bool = True
    use_count: int = 0
    created_at: str = ""
    last_used: str | None = None
    notes: str = ""

    @staticmethod
    def new(value: str, label: str = "", notes: str = "") -> "VaultEntry":
        return VaultEntry(
            id=str(uuid.uuid4()),
            value=value,
            label=label or value[:3] + "***",
            enabled=True,
            use_count=0,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            last_used=None,
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "VaultEntry":
        return VaultEntry(
            id=data.get("id") or str(uuid.uuid4()),
            value=data.get("value", ""),
            label=data.get("label", ""),
            enabled=bool(data.get("enabled", True)),
            use_count=int(data.get("use_count", 0) or 0),
            created_at=data.get("created_at", ""),
            last_used=data.get("last_used"),
            notes=data.get("notes", ""),
        )


def _empty_vault() -> dict:
    return {"version": 1, "metadata": {}, "passwords": [], "audit": []}


def default_vault_dir() -> Path:
    return Path.home() / ".folder_ops" / "password_vault"


class VaultGit:
    """密码库目录的本地 Git 包装；Git 失败只记录日志，不阻塞写库。"""

    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)

    def _git(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.vault_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )

    def ensure_repo(self) -> None:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        if (self.vault_dir / ".git").exists():
            return
        self._git(["init"])
        if not self._git(["config", "user.name"]).stdout.strip():
            self._git(["config", "user.name", "folder-ops vault"])
        if not self._git(["config", "user.email"]).stdout.strip():
            self._git(["config", "user.email", "vault@folder-ops.local"])
        (self.vault_dir / VAULT_README_FILENAME).write_text(_VAULT_README, encoding="utf-8")
        vault_file = self.vault_dir / VAULT_FILENAME
        if not vault_file.exists():
            vault_file.write_text(json.dumps(_empty_vault(), ensure_ascii=False), encoding="utf-8")
        self._git(["add", VAULT_FILENAME, VAULT_README_FILENAME])
        result = self._git(["commit", "-m", "初始化密码库"])
        if result.returncode != 0:
            LOGGER.warning("密码库初始化提交失败：%s", (result.stderr or "").strip())

    def commit(self, message: str, allow_empty: bool = False) -> bool:
        self._git(["add", VAULT_FILENAME, VAULT_README_FILENAME])
        cmd = ["commit", "-m", message]
        if allow_empty:
            cmd.append("--allow-empty")
        result = self._git(cmd)
        if result.returncode == 0:
            LOGGER.info("密码库提交：%s", message)
            return True
        low = (result.stdout + result.stderr).lower()
        if "nothing to commit" in low or "no changes" in low:
            return False
        LOGGER.warning("密码库提交失败（%s）：%s", message, (result.stderr or "").strip())
        return False

    def log(self, limit: int = 20) -> list[str]:
        result = self._git(["log", f"-{limit}", "--pretty=%s"])
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]


class PasswordVault:
    """线程安全的密码库。"""

    def __init__(self, vault_dir: Path | None = None, git: VaultGit | None = None):
        self.vault_dir = Path(vault_dir or default_vault_dir())
        self.vault_file = self.vault_dir / VAULT_FILENAME
        self._git = git or VaultGit(self.vault_dir)
        self._lock = threading.Lock()
        self._pending_delete: dict[str, str] = {}

    # -- 生命周期 ----------------------------------------------------------
    def open(self) -> None:
        with self._lock:
            self._git.ensure_repo()
            if not self.vault_file.exists():
                self._write_locked(_empty_vault(), "初始化密码库文件")
            self._git.commit("密码库会话开始", allow_empty=True)

    def close(self) -> None:
        self._git.commit("密码库会话结束", allow_empty=True)

    # -- 读 ---------------------------------------------------------------
    def _read_locked(self) -> dict:
        if not self.vault_file.exists():
            return _empty_vault()
        try:
            return json.loads(self.vault_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.error("密码库不可读（%s），按空库处理", exc)
            return _empty_vault()

    def list_entries(self, enabled_only: bool = False) -> list[VaultEntry]:
        with self._lock:
            data = self._read_locked()
        entries = [VaultEntry.from_dict(item) for item in data.get("passwords", [])]
        return [item for item in entries if item.enabled] if enabled_only else entries

    def iter_passwords(self) -> Iterator[tuple[VaultEntry, str]]:
        """按成功率与最近使用排序，逐个产出（条目副本, 密码）。"""
        entries = self.list_entries(enabled_only=True)
        entries.sort(key=lambda item: item.last_used or "", reverse=True)
        entries.sort(key=lambda item: item.use_count, reverse=True)
        for entry in entries:
            yield entry, entry.value

    # -- 写 ---------------------------------------------------------------
    def _write_locked(self, data: dict, message: str) -> None:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.vault_file.with_suffix(self.vault_file.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.vault_file)
        self._git.commit(message)

    def add_password(self, value: str, label: str = "", notes: str = "") -> VaultEntry:
        with self._lock:
            data = self._read_locked()
            entry = VaultEntry.new(value=value, label=label, notes=notes)
            data.setdefault("passwords", []).append(entry.to_dict())
            self._write_locked(data, f"新增密码 {entry.label}")
        return entry

    def bulk_add(self, passwords: list[str], label_prefix: str = "") -> tuple[int, int]:
        """批量导入，去重；返回 (新增数, 跳过数)。"""
        added = skipped = 0
        with self._lock:
            data = self._read_locked()
            values = {item.get("value", "") for item in data.get("passwords", [])}
            seen: set[str] = set()
            for index, password in enumerate(passwords, 1):
                password = password.strip()
                if not password or password in values or password in seen:
                    skipped += 1
                    continue
                label = f"{label_prefix}-{index}" if label_prefix else ""
                data.setdefault("passwords", []).append(
                    VaultEntry.new(value=password, label=label).to_dict()
                )
                values.add(password)
                seen.add(password)
                added += 1
            if added:
                self._write_locked(data, f"批量导入密码：+{added}，跳过 {skipped}")
        return added, skipped

    def set_enabled(self, entry_id: str, enabled: bool) -> bool:
        with self._lock:
            data = self._read_locked()
            for item in data.get("passwords", []):
                if item.get("id") == entry_id:
                    item["enabled"] = enabled
                    self._write_locked(
                        data, f"{'启用' if enabled else '停用'}密码 {item.get('label', '')}"
                    )
                    return True
        return False

    # -- 删除（两步确认）---------------------------------------------------
    def prepare_delete(self, entry_id: str) -> str | None:
        with self._lock:
            data = self._read_locked()
            if not any(item.get("id") == entry_id for item in data.get("passwords", [])):
                return None
            token = secrets.token_urlsafe(8)
            self._pending_delete[entry_id] = token
            return token

    def delete_password(self, entry_id: str, token: str) -> bool:
        with self._lock:
            expected = self._pending_delete.get(entry_id)
            if not expected or not secrets.compare_digest(expected, token):
                LOGGER.warning("删除密码被拒绝：%s（令牌无效）", entry_id)
                return False
            data = self._read_locked()
            label = "unknown"
            for item in data.get("passwords", []):
                if item.get("id") == entry_id:
                    label = item.get("label", "unknown")
                    break
            before = len(data.get("passwords", []))
            data["passwords"] = [
                item for item in data.get("passwords", []) if item.get("id") != entry_id
            ]
            self._pending_delete.pop(entry_id, None)
            if len(data["passwords"]) == before:
                return False
            self._write_locked(data, f"删除密码 {label}")
            return True

    # -- 使用统计 ---------------------------------------------------------
    def record_success(self, entry_id: str, archive_name: str) -> None:
        with self._lock:
            data = self._read_locked()
            label = "unknown"
            for item in data.get("passwords", []):
                if item.get("id") == entry_id:
                    item["use_count"] = int(item.get("use_count", 0)) + 1
                    item["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    label = item.get("label", "unknown")
                    break
            data.setdefault("audit", []).append(
                {"action": "success", "entry": label, "archive": archive_name}
            )
            self._write_locked(data, f"记录成功密码 {label} ← {archive_name}")

    def record_failure_all(self, archive_name: str) -> None:
        with self._lock:
            data = self._read_locked()
            data.setdefault("audit", []).append(
                {"action": "all_failed", "archive": archive_name}
            )
            self._write_locked(data, f"全部密码失败 ← {archive_name}")

    def commit_log(self, limit: int = 20) -> list[str]:
        return self._git.log(limit)
