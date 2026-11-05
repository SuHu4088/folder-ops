"""pytest 共享夹具：构造三级嵌套目录。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def nested_tree(tmp_path: Path):
    """src/a.txt + lvl1/b.txt + lvl1/lvl2/c.txt + lvl1/lvl2/lvl3/d.txt"""
    src = tmp_path / "src"
    (src / "lvl1" / "lvl2" / "lvl3").mkdir(parents=True)
    (src / "a.txt").write_text("A", encoding="utf-8")
    (src / "lvl1" / "b.txt").write_text("B", encoding="utf-8")
    (src / "lvl1" / "lvl2" / "c.txt").write_text("C", encoding="utf-8")
    (src / "lvl1" / "lvl2" / "lvl3" / "d.txt").write_text("D", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    return {"root": tmp_path, "src": src, "target": target}
