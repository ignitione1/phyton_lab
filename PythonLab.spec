# -*- mode: python ; coding: utf-8 -*-
"""Сборка приложения в .exe.

Запуск:  .venv/Scripts/pyinstaller PythonLab.spec --noconfirm

Два решения, о которых стоит знать заранее.

**Режим — одна папка, а не один файл.** Приложение запускает само себя
дочерним процессом на каждый запуск кода ученика. В режиме «один файл»
каждый такой запуск распаковывал бы весь архив во временную папку —
секунды ожидания вместо мгновенного результата. В режиме папки дочерний
процесс стартует сразу.

**Лишнее вырезано.** PySide6 тянет браузерный движок, 3D, видеокодеки
и конструктор интерфейсов — вместе больше 300 МБ. Нам нужны только окна,
шрифты и рисование.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH)

# Файлы, которые читаются во время работы: курс, правила разбора ошибок,
# оформление и схема базы.
datas = [
    (str(PROJECT / "app" / "course" / "content"), "app/course/content"),
    (str(PROJECT / "app" / "runner" / "error_patterns.yaml"), "app/runner"),
    (str(PROJECT / "app" / "ui" / "styles.qss"), "app/ui"),
    (str(PROJECT / "app" / "ui" / "icon.ico"), "app/ui"),
    (str(PROJECT / "app" / "db" / "schema.sql"), "app/db"),
]

# keyring находит хранилище паролей через механизм подключаемых модулей —
# PyInstaller сам такие связи не видит, перечисляем явно.
hiddenimports = collect_submodules("keyring.backends") + [
    "keyring.backends.Windows",
]

# Всё, что нам не нужно. Основной вес — в первых трёх строках.
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    # Научные библиотеки иногда затягиваются за компанию — они нам не нужны.
    "numpy",
    "matplotlib",
    "scipy",
    "pandas",
    "PIL",
    "tkinter",
    "unittest",
    "pydoc_data",
]

analysis = Analysis(
    ["run.py"],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Часть библиотек Qt приходит не импортом, а зависимостью соседних
# библиотек, поэтому список excludes их не ловит — убираем вручную.
UNWANTED_BINARIES = (
    "Qt6WebEngine",
    "Qt6Quick",
    "Qt6Qml",
    "Qt6Pdf",
    "Qt63D",
    "Qt6Multimedia",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Designer",
    "Qt6Sql",
    "Qt6Test",
    "Qt6Bluetooth",
    "Qt6Nfc",
    "Qt6Positioning",
    "Qt6Sensors",
    "Qt6SerialPort",
    "Qt6WebSockets",
    "Qt6WebChannel",
    "avcodec",
    "avformat",
    "avutil",
    "swresample",
    "swscale",
    "opengl32sw",
)


def _is_unwanted(entry) -> bool:
    name = entry[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return any(name.startswith(prefix) for prefix in UNWANTED_BINARIES)


analysis.binaries = TOC(
    entry for entry in analysis.binaries if not _is_unwanted(entry)
)
analysis.datas = TOC(
    entry for entry in analysis.datas if not _is_unwanted(entry)
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PythonLab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # окно консоли не нужно: у нас своя
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT / "app" / "ui" / "icon.ico"),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PythonLab",
)
