#!/usr/bin/env bash
# 构建 macOS .app：安装构建依赖 → PyInstaller 打包 → ad-hoc 签名 → 自检
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
VENV="$ROOT/.venv-build"

if [ ! -x "$VENV/bin/pyinstaller" ]; then
  echo "==> 创建构建虚拟环境：$VENV"
  "$PYTHON_BIN" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet pyinstaller -r requirements.txt
fi

echo "==> 清理旧构建产物"
rm -rf "$ROOT/build/FolderOps" "$ROOT/dist/FolderOps.app"

echo "==> PyInstaller 打包"
"$VENV/bin/pyinstaller" --noconfirm --clean packaging/FolderOps.spec

echo "==> ad-hoc 签名"
codesign --force --deep --sign - "$ROOT/dist/FolderOps.app"
codesign --verify --deep --strict "$ROOT/dist/FolderOps.app"

echo "==> 自检：内置 7zz 与关键文件"
test -x "$VENV/bin/python"
find "$ROOT/dist/FolderOps.app" -name 7zz -maxdepth 6 | grep -q 7zz
echo "内置 7zz: $(find "$ROOT/dist/FolderOps.app" -name 7zz -maxdepth 6)"

echo "==> 完成：$ROOT/dist/FolderOps.app"
echo "启动：open \"$ROOT/dist/FolderOps.app\""
