# -*- mode: python ; coding: utf-8 -*-

import os
from os.path import join
import sys

from threecolref import constants


block_cipher = None
appname = f'{constants.APPNAME}-{constants.VERSION}'

if sys.platform.startswith('win'):
    icon = 'logo.ico'
else:
    icon = 'logo.icns'  # For OSX; param gets ignored on Linux


a = Analysis(
    [join('threecolref', '__main__.py')],
    pathex=[os.getcwd()],
    binaries=[],
    datas=[
        (join('threecolref', 'documentation'), join('threecolref', 'documentation')),
        (join('threecolref', 'assets', '*.png'), join('threecolref', 'assets')),
        (join('threecolref', 'assets', '*.svg'), join('threecolref', 'assets'))],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6.QtWebEngine',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtQml',
        'PyQt6.QtQuick',
        'PyQt6.QtQuickWidgets',
        'PyQt6.QtSql',
        'PyQt6.QtTest',
        'PyQt6.QtXml',
        'PyQt6.QtBluetooth',
        'PyQt6.QtNfc',
        'PyQt6.QtPositioning',
        'numpy',
        'tkinter',
        'unittest',
        'pydoc'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=appname,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None ,
    icon=join('threecolref', 'assets', icon))

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name=f'{constants.APPNAME}.app',
        icon=join('threecolref', 'assets', icon),
        bundle_identifier='org.threecolref.app',
        version=f'{constants.VERSION}',
        info_plist={
            'CFBundleDocumentTypes': [
                {
                    'CFBundleTypeExtensions': [ '3col' ],
                    'CFBundleTypeRole': 'Viewer'
                }
            ]
        })
