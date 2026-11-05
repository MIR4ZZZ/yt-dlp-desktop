# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ui\\yt_dlp_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('devscripts\\logo.ico', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)
# Qt uses Windows' unversioned ICU exports; Poppler's ICU 78 DLL breaks QtCore loading.
a.binaries = [entry for entry in a.binaries if entry[0].lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='yt-dlp-ui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['devscripts\\logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='yt-dlp-ui',
)
