"""界面机制/校验实时联动测试（需要可用的 Tk 显示环境）。"""
from __future__ import annotations

import queue

import pytest

tk = pytest.importorskip("tkinter")

from folder_ops.config import AppConfig, RunOptions
from folder_ops.logging_setup import setup_logging
from folder_ops.ui import FolderOpsApp


@pytest.fixture
def app(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("当前环境没有可用的显示服务")
    root.withdraw()
    log_path = setup_logging(tmp_path / "logs", log_queue=queue.Queue())
    instance = FolderOpsApp(
        root,
        AppConfig(options=RunOptions(mechanism="copy", verify=True)),
        log_path,
        queue.Queue(),
    )
    yield instance
    root.destroy()


def test_switch_to_move_disables_verify(app):
    app.mechanism_var.set("move")
    app._on_mechanism_change()
    assert app.verify_var.get() is False
    assert app.verify_check.instate(["disabled"])
    assert "不执行校验" in app.verify_note.cget("text")
    assert "剪切" in app.start_btn.cget("text")


def test_switch_back_to_copy_restores_verify_preference(app):
    app.mechanism_var.set("move")
    app._on_mechanism_change()
    app.mechanism_var.set("copy")
    app._on_mechanism_change()
    assert app.verify_var.get() is True
    assert not app.verify_check.instate(["disabled"])
    assert "MD5" in app.verify_note.cget("text")
    assert "复制" in app.start_btn.cget("text")


def test_user_can_disable_verify_in_copy_mode(app):
    app.verify_var.set(False)
    app._on_verify_change()
    app.mechanism_var.set("move")
    app._on_mechanism_change()
    app.mechanism_var.set("copy")
    app._on_mechanism_change()
    assert app.verify_var.get() is False
