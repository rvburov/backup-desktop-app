# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller BackupApp.spec
# Результат: один файл dist/BackupApp.exe, все библиотеки и ресурсы внутри,
# запускается без окна консоли.
import sys

block_cipher = None

datas = [
    ("icon.ico", "."),
    ("icons/files_icon.png", "icons"),
    ("icons/settings_icon.png", "icons"),
    # шрифты интерфейса (frontend/theme.py загружает их из папки fonts) и их лицензии SIL OFL 1.1
    ("fonts/GolosText-Regular.ttf", "fonts"),
    ("fonts/GolosText-Medium.ttf", "fonts"),
    ("fonts/GolosText-SemiBold.ttf", "fonts"),
    ("fonts/JetBrainsMono-Regular.ttf", "fonts"),
    ("fonts/OFL-GolosText.txt", "fonts"),
    ("fonts/OFL-JetBrainsMono.txt", "fonts"),
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

if sys.platform == "win32":
    app_icon = "icon.ico"
elif sys.platform == "darwin":
    app_icon = "icon.icns"
else:
    app_icon = None

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
    icon=app_icon,
)
