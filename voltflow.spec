# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — VoltFlow single-file executable (Windows)
# Build:  .venv\Scripts\python.exe -m PyInstaller voltflow.spec --noconfirm
# Output: dist\VoltFlow.exe

import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(ROOT, 'theme'), 'theme'),
    (os.path.join(ROOT, 'ui', 'forms'), os.path.join('ui', 'forms')),
    (os.path.join(ROOT, 'assets', 'blocks'), os.path.join('assets', 'blocks')),
]
for name in (
    'panel_schedule_12.xlsx',
    'panel_schedule_42.xlsx',
    'panel_schedule_template.xlsx',
):
    p = os.path.join(ROOT, 'ui', name)
    if os.path.isfile(p):
        datas.append((p, 'ui'))

cable_dir = os.path.join(ROOT, 'VSEngCableSelector')
for name in os.listdir(cable_dir):
    if name.lower().endswith('.png'):
        datas.append((os.path.join(cable_dir, name), 'VSEngCableSelector'))

dark_qss = os.path.join(cable_dir, 'theme', 'dark.qss')
if os.path.isfile(dark_qss):
    datas.append((dark_qss, os.path.join('VSEngCableSelector', 'theme')))

hiddenimports = [
    'app_paths',
    'version',
    'win32com',
    'win32com.client',
    'win32timezone',
    'pythoncom',
    'pywintypes',
    'ezdxf',
    'PySide6.QtUiTools',
    'motor_class',
    'feeder_class',
    'cb_class',
    'switchboard_class',
    'project_class',
    'vdrop_optimizer',
    'vdrop_settings',
] + collect_submodules('ui') + collect_submodules('VSEngCableSelector')

a = Analysis(
    [os.path.join(ROOT, 'switchboard.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VoltFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
