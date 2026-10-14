"""Ponto de entrada da interface gráfica."""

from __future__ import annotations

import datetime as _dt
import os
import sys
import traceback

STYLE = """
QWidget { font-size: 10pt; }
QGroupBox { font-weight: 600; border: 1px solid #c9ced3; border-radius: 6px; margin-top: 12px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #23313f; }
QPushButton#primary, QToolButton#primary { background: #1f6fb2; color: white; border: none; border-radius: 5px;
    padding: 7px 14px; font-weight: 600; }
QPushButton#primary:hover, QToolButton#primary:hover { background: #2a82cc; }
QPushButton#primary:disabled, QToolButton#primary:disabled { background: #a9b9c8; }
QLabel#hint { color: #5b6670; }
QLabel#warn { color: #8a5300; background: #fff4dc; border: 1px solid #f0d290; border-radius: 4px; padding: 4px 8px; }
QLabel#dims { color: #23313f; padding: 2px 4px; }
QLabel#timeLabel { font-family: Consolas, 'Courier New', monospace; font-size: 11pt; }
QLabel#offlineBadge { color: #1d6b38; background: #e3f4e8; border: 1px solid #9fd3ae; border-radius: 10px;
    padding: 3px 10px; font-weight: 600; margin-right: 8px; }
QTabBar::tab { padding: 8px 18px; font-weight: 600; }
QListView { background: #f7f8fa; }
"""


def _log_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PranchaQuadros")
    os.makedirs(d, exist_ok=True)
    return d


def _excepthook(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(os.path.join(_log_dir(), "erros.log"), "a", encoding="utf-8") as fh:
            fh.write(f"\n[{_dt.datetime.now():%d/%m/%Y %H:%M:%S}]\n{text}")
    except OSError:
        pass
    try:
        from PySide6.QtWidgets import QApplication

        from .gui.dialogs import error_box

        if QApplication.instance():
            error_box(None, "Erro inesperado",
                      "Ocorreu um erro inesperado. O aplicativo continua em execução e o arquivo de vídeo original "
                      "não foi alterado. Se o problema persistir, salve seu trabalho e reinicie o aplicativo.\n\n"
                      f"Um registro do erro foi gravado em: {os.path.join(_log_dir(), 'erros.log')}", text)
    except Exception:  # noqa: BLE001
        sys.__excepthook__(exc_type, exc, tb)


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--autoteste" in argv:
        from .selftest import run_selftest

        return run_selftest()

    from PySide6.QtCore import QLocale, Qt, QTranslator, QLibraryInfo
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, ORG_NAME
    from .gui.main_window import MainWindow

    sys.excepthook = _excepthook
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    QLocale.setDefault(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil))
    tr = QTranslator(app)
    if tr.load(QLocale(), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)
    icon_path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "assets", "icone.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    w = MainWindow()
    w.resize(1500, 920)
    w.showMaximized()
    files = [a for a in argv[1:] if not a.startswith("-") and os.path.isfile(a)]
    if files:
        w.load_video(files[0])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
