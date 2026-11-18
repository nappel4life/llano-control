# -*- mode: python ; coding: utf-8 -*-
"""Bau-Vorschrift fuer PyInstaller: ein Ordner, zwei Programmdateien.

``llano``            Kommandozeile, mit Konsole
``llano-control``    Oberflaeche, ohne Konsole (Doppelklick)

Beide teilen sich denselben Satz Bibliotheken im Ordner ``_internal``, damit
nicht zweimal dasselbe Qt im Paket liegt. Aufgerufen wird das so:

    pyinstaller --noconfirm --clean packaging/llano.spec

Aus dem Ergebnis baut ``packaging/build-appimage.sh`` die eine AppImage-Datei
fuer Linux und ``packaging/windows/llano.iss`` den Windows-Installer.
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ICON = os.path.join(ROOT, "assets", "llano.ico")
if not os.path.exists(ICON):
    ICON = None

common = dict(
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "assets"), "assets")],
    hiddenimports=["llanotool.gui"],
    noarchive=False,
)


def analyse(entry):
    a = Analysis(
        [os.path.join(SPECPATH, entry)],
        binaries=[],
        hiddenimports=common["hiddenimports"],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=["tkinter", "matplotlib", "PyQt6.QtWebEngineCore"],
        noarchive=False,
        pathex=common["pathex"],
        datas=common["datas"],
    )
    return a, PYZ(a.pure)


gui, gui_pyz = analyse("entry_gui.py")
cli, cli_pyz = analyse("entry_cli.py")

exe_gui = EXE(
    gui_pyz,
    gui.scripts,
    name="llano-control",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
    disable_windowed_traceback=False,
    exclude_binaries=True,
)

exe_cli = EXE(
    cli_pyz,
    cli.scripts,
    name="llano",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=ICON,
    exclude_binaries=True,
)

coll = COLLECT(
    exe_gui,
    gui.binaries,
    gui.datas,
    exe_cli,
    cli.binaries,
    cli.datas,
    name="llano-control",
    strip=False,
    upx=False,
)
