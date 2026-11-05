# macOS 打包与签名说明（PACKAGING）

## 1. 结论

- 打包方式：**PyInstaller 6.x + Homebrew Python 3.14（Tk 8.6）**。
- 产物：`dist/FolderOps.app`，约 35 MB，仅 arm64。
- 签名：**ad-hoc**（`Identifier=io.folderops.app`，`Signature=adhoc`），无 Developer ID、无公证。
- 本机直接双击可用；`spctl -a -vv dist/FolderOps.app` 会 `rejected`，这是未公证的预期结果。

## 2. 一键构建

```bash
bash script/build_app.sh
```

脚本步骤：

1. 若 `.venv-build` 不存在，用 `/opt/homebrew/bin/python3.14` 创建并安装 `pyinstaller -r requirements.txt`。
2. 清理旧的 `build/FolderOps` 与 `dist/FolderOps.app`。
3. `pyinstaller --noconfirm --clean packaging/FolderOps.spec`。
4. `codesign --force --deep --sign - dist/FolderOps.app` 并校验。
5. 自检内置 `7zz` 是否存在。

自定义解释器：`PYTHON_BIN=/path/to/python3 bash script/build_app.sh`。

## 3. Spec 关键点

`packaging/FolderOps.spec`：

- `binaries` 追加 `vendor/macos-arm64/7zz` → 打包后位于 `Contents/Frameworks/vendor/macos-arm64/7zz`。
- `datas` / `hiddenimports` 收集 `tkinterdnd2`，拖拽功能在 `.app` 中可用。
- `BUNDLE` 写入 `CFBundleDisplayName`、版本号（取自 `folder_ops.__version__`）、`LSMinimumSystemVersion=11.0`。
- `argv_emulation=False`：不依赖旧式 Apple Event 打开文件。

## 4. 校验

```bash
codesign --verify --deep --strict dist/FolderOps.app
find dist/FolderOps.app -name 7zz -maxdepth 6
dist/FolderOps.app/Contents/MacOS/FolderOps --version
```

> 直接运行 `Contents/MacOS/FolderOps --version` 会走 CLI 分支并打印版本；无参数则启动 GUI。

## 5. 发布

```bash
ditto -c -k --keepParent dist/FolderOps.app FolderOps-0.2.0-macos-arm64.zip
shasum -a 256 FolderOps-0.2.0-macos-arm64.zip
gh release create v0.2.0 FolderOps-0.2.0-macos-arm64.zip \
  --title "folder-ops v0.2.0" --notes-file CHANGELOG.md
```

## 6. 公证（未完成）

要做 Developer ID 分发，需要：

1. Apple Developer 账号与 Developer ID Application 证书；
2. `codesign --options runtime --timestamp --sign "Developer ID Application: …"`；
3. `xcrun notarytool submit --wait` 与 `xcrun stapler staple`；
4. CI 中安全存放证书与凭据。

当前版本不做公证，README 已明确说明首次右键打开。

## 7. 图标

`packaging/FolderOps.icns` 由 `packaging/FolderOps.iconset` 生成：

```bash
iconutil -c icns packaging/FolderOps.iconset -o packaging/FolderOps.icns
```

## 8. 跨平台

- Windows：用 Windows 版 Python 安装依赖后执行同一 spec（需调整 7zz 为 `7z.exe`），或改 py2exe/Nuitka。
- Linux：无 `.app` 概念，直接源码/CLI 运行。
- Intel Mac：需在 Intel 机器或 `arch -x86_64` 环境重新打包，产物为 x86_64。
