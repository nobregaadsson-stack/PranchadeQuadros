# -*- mode: python ; coding: utf-8 -*-
# Especificação do PyInstaller — gera dist\PranchaQuadros\PranchaQuadros.exe (pasta autocontida).
# Uso: .venv\Scripts\pyinstaller.exe --noconfirm PranchaQuadros.spec   (ou execute build.ps1)

import sys

block_cipher = None

# Módulos do Qt que o aplicativo NÃO usa (reduz o pacote em centenas de MB)
QT_EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtWebView", "PySide6.QtWebSockets", "PySide6.QtHttpServer",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets", "PySide6.QtQuick3D", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSerialBus", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvgWidgets",
    "PySide6.QtCanvasPainter",
]

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=["PySide6.QtMultimedia"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=QT_EXCLUDES + ["tkinter", "numpy", "pytest", "IPython", "matplotlib"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PranchaQuadros",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # aplicativo de janela (sem console)
    icon="assets/icone.ico" if sys.platform == "win32" else None,
    version="version_info.txt" if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PranchaQuadros")

# macOS (compilação futura): descomente para gerar o pacote .app
# app = BUNDLE(coll, name="PranchaQuadros.app", icon="assets/icone.icns", bundle_identifier="br.prancha.quadros")
