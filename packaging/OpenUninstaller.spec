# PyInstaller spec - builds dist/OpenUninstaller/OpenUninstaller.exe (one-folder, no console).
# Run from the project root:  .venv\Scripts\python -m PyInstaller packaging\OpenUninstaller.spec --noconfirm
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Qt modules the app never uses - keeps the build small
EXCLUDES = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtTextToSpeech", "PySide6.QtHelp", "PySide6.QtSpatialAudio", "PySide6.QtHttpServer",
    "PySide6.QtNetworkAuth", "PySide6.QtNfc", "PySide6.QtWebSockets", "PySide6.QtVirtualKeyboard",
]

a = Analysis(
    [os.path.join(ROOT, "OpenUninstaller.pyw")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "openuninstaller", "gui", "resources"), "openuninstaller/gui/resources")],
    hiddenimports=["win32timezone", "openuninstaller.cli"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="OpenUninstaller",
    console=False,
    icon=os.path.join(ROOT, "packaging", "OpenUninstaller.ico"),
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="OpenUninstaller", upx=False)
