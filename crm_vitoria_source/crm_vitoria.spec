# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


def safe_collect_submodules(package):
    try:
        return collect_submodules(package)
    except Exception:
        return []


block_cipher = None


a = Analysis(
    ["desktop_launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("static", "static"),
    ],
    hiddenimports=safe_collect_submodules("flask")
    + safe_collect_submodules("werkzeug")
    + safe_collect_submodules("jinja2")
    + safe_collect_submodules("click")
    + safe_collect_submodules("itsdangerous")
    + safe_collect_submodules("markupsafe")
    + safe_collect_submodules("googleapiclient")
    + safe_collect_submodules("google_auth_oauthlib")
    + safe_collect_submodules("google.oauth2")
    + safe_collect_submodules("google.auth"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CRM Vitoria Uardon",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CRM Vitoria Uardon",
)
