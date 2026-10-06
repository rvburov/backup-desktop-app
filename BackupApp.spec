# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller BackupApp.spec
# Windows и Linux: один файл dist/BackupApp.exe (на Linux dist/BackupApp), все библиотеки
# и ресурсы внутри, запускается без окна консоли.
# macOS: приложение dist/BackupApp.app. Программа для macOS всегда папка-бандл, одним файлом
# ее не сделать, поэтому там сборка папкой (COLLECT) внутри бандла (BUNDLE).
# Номер версии берется из backup_app/backend/constants.py: он попадает в свойства exe
# и в Info.plist, по нему сборку проверяет .github/workflows/release.yml.
import os
import re
import sys

block_cipher = None

with open(os.path.join(SPECPATH, "backup_app", "backend", "constants.py"), encoding="utf-8") as handle:
    match = re.search(r'^VERSION = "(\d+\.\d+\.\d+)"$', handle.read(), re.MULTILINE)
if match is None:
    raise SystemExit("В backup_app/backend/constants.py нет строки VERSION = \"X.Y.Z\"")
VERSION = match.group(1)

datas = [
    ("icon.ico", "."),
    ("icons/files_icon.png", "icons"),
    ("icons/settings_icon.png", "icons"),
]

a = Analysis(
    ["backup-app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["PyQt5.QtNetwork"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="BackupApp",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,  # архитектура того Python, которым идет сборка
        codesign_identity=None,  # ad-hoc подпись, без нее Apple Silicon не запустит программу
        entitlements_file=None,
        icon="icon.icns",
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BackupApp")
    app = BUNDLE(
        coll,
        name="BackupApp.app",
        icon="icon.icns",
        # Тот же идентификатор, что у автозапуска на macOS (MACOS_LABEL в backend/autostart.py).
        bundle_identifier="com.mycompany.backupapp",
        version=VERSION,
        info_plist={"CFBundleVersion": VERSION, "NSHighResolutionCapable": True},
    )
else:
    version_info = None
    if sys.platform == "win32":
        # Версия в свойствах файла (вкладка «Подробно»). Модуль есть только в PyInstaller для Windows.
        from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                         StringTable, VarFileInfo, VarStruct, VSVersionInfo)

        numbers = tuple(int(part) for part in VERSION.split(".")) + (0,)
        version_info = VSVersionInfo(
            ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
            kids=[
                StringFileInfo([StringTable("041904B0", [
                    StringStruct("FileDescription", "BackupApp"),
                    StringStruct("FileVersion", VERSION),
                    StringStruct("InternalName", "BackupApp"),
                    StringStruct("OriginalFilename", "BackupApp.exe"),
                    StringStruct("ProductName", "BackupApp"),
                    StringStruct("ProductVersion", VERSION),
                ])]),
                VarFileInfo([VarStruct("Translation", [0x0419, 1200])]),
            ],
        )

    # Режим onefile: библиотеки и ресурсы передаются прямо в EXE, отдельной папки (COLLECT) нет.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="BackupApp",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # без окна консоли
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon="icon.ico" if sys.platform == "win32" else None,
        version=version_info,
    )
