"""压缩包子系统测试：清单解析、CRC、真实解压与篡改检测。"""
from __future__ import annotations

import zipfile
import zlib
from pathlib import Path

import pytest

from folder_ops.archive import seven_zip_path
from folder_ops.archive.archive_info import detect, parse_slt
from folder_ops.archive.service import extract_archive
from folder_ops.archive.verifier import crc32_of_file, verify

HAS_7Z = seven_zip_path() is not None
requires_7z = pytest.mark.skipif(not HAS_7Z, reason="本机未安装 7-Zip")


def make_zip(path: Path, count: int = 2) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(count):
            archive.writestr(f"docs/file-{index}.txt", f"内容 {index}".encode("utf-8"))
        archive.writestr("readme.md", b"# folder-ops")
    return path


def test_parse_slt_extracts_manifest_and_format():
    sample = """
7-Zip 26.05 (arm64)

Listing archive: sample.zip

--
Path = sample.zip
Type = zip

--------

Path = docs/a.txt
Folder = -
Size = 12
CRC = A1B2C3D4
Encrypted = +

Path = docs/sub
Folder = +

Path = docs/b.txt
Folder = -
Size = 100
CRC =
"""
    manifest, fmt, encrypted = parse_slt(sample)
    assert fmt == "zip"
    assert [item.path for item in manifest] == ["docs/a.txt", "docs/b.txt"]
    assert manifest[0].size == 12
    assert manifest[0].crc == "A1B2C3D4"
    assert manifest[1].crc is None
    assert encrypted is True


def test_crc32_matches_zipfile_metadata(tmp_path):
    archive = make_zip(tmp_path / "sample.zip")
    with zipfile.ZipFile(archive) as handle:
        info = handle.getinfo("readme.md")
        # 解压后单个文件的 CRC 应与清单一致
        extracted = tmp_path / "readme.md"
        extracted.write_bytes(handle.read("readme.md"))
    assert f"{info.CRC:08x}" == crc32_of_file(extracted)
    assert f"{info.CRC:08x}" == f"{zlib.crc32(b'# folder-ops') & 0xFFFFFFFF:08x}"


@requires_7z
def test_real_extract_verify_and_delete_original(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    archive = make_zip(source / "bundle.zip")
    out = tmp_path / "out"
    outcome = extract_archive(archive, out, password_module_enabled=False, delete_original=True)
    assert outcome.status == "ok", outcome.message
    assert outcome.verified is True
    assert outcome.extracted_count == 3
    assert (outcome.dest / "readme.md").exists()
    assert not archive.exists()


@requires_7z
def test_tampered_extraction_detected(tmp_path):
    archive = make_zip(tmp_path / "bundle.zip")
    out = tmp_path / "out"
    outcome = extract_archive(archive, out, password_module_enabled=False)
    assert outcome.status == "ok"
    info = detect(seven_zip_path(), archive)
    target = outcome.dest / "docs" / "file-0.txt"
    original = target.read_bytes()
    # 保持大小不变，只改内容，专门验证 CRC 比对而非大小比对
    target.write_bytes(b"X" * len(original))
    result = verify(seven_zip_path(), archive, outcome.dest, info=info)
    assert result.ok is False
    assert result.crc_mismatches == ["docs/file-0.txt"]


@requires_7z
def test_unique_destination_when_name_exists(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    archive = make_zip(source / "bundle.zip")
    out = tmp_path / "out"
    existing = out / "bundle"
    existing.mkdir(parents=True)
    (existing / "old.txt").write_text("old", encoding="utf-8")
    outcome = extract_archive(archive, out, password_module_enabled=False)
    assert outcome.dest.name == "bundle_1"
    assert (existing / "old.txt").exists()


def test_missing_archive_reports_failure(tmp_path):
    outcome = extract_archive(tmp_path / "nope.zip", tmp_path / "out", password_module_enabled=False)
    assert outcome.status == "failed"
    assert "不存在" in outcome.message
