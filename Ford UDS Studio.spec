# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('config', 'config'), ('ford', 'ford'), ('studio', 'studio'), ('fordlink', 'fordlink')]
binaries = []
hiddenimports = ['can.interfaces.gs_usb', 'can.interfaces.gs_usb.gs_usb', 'can.interfaces.gs_usb.gs_usb_bus', 'usb.core', 'usb.util', 'usb.backend.libusb1', 'usb.backend.libusb0', 'usb.backend.openusb', 'serial', 'serial.tools.list_ports']
hiddenimports += collect_submodules('can.interfaces')
tmp_ret = collect_all('can')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('usb')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['ford_uds_studio.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Ford UDS Studio',
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
    icon=['MyIcon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Ford UDS Studio',
)
app = BUNDLE(
    coll,
    name='Ford UDS Studio.app',
    icon='MyIcon.icns',
    bundle_identifier='pl.forduds.studio',
)
