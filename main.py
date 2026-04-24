"""
CD_SCOPE v1.0 — Entry point
-----------------------------
Works in all three modes:

  python main.py                         (run directly from inside cd_scope/)
  python cd_scope/main.py                (run from parent folder)
  python -m cd_scope                     (run as package — recommended)
  pip install -e . && cd_scope           (installed entry-point)
"""
from __future__ import annotations
import sys
import os


def _ensure_package_on_path() -> None:
    """
    When main.py is run directly (not as part of a package),
    Python does not know about the parent package.

    This function adds the parent directory of the cd_scope/ folder
    to sys.path so that  `import cd_scope`  works regardless of how
    the script was invoked.
    """
    # __file__ is  .../cd_scope/main.py
    # parent  is  .../cd_scope/
    # grandparent is  .../   ← this needs to be on sys.path
    here        = os.path.dirname(os.path.abspath(__file__))
    grandparent = os.path.dirname(here)
    if grandparent not in sys.path:
        sys.path.insert(0, grandparent)


def run_gui() -> None:
    # Ensure the package is importable no matter how we were launched
    _ensure_package_on_path()

    # Now we can always use absolute imports
    from cd_scope.constants import (BG_PANEL, BG_DEEP, BG_CARD,
                                     TEXT_BR, TEXT_MID,
                                     CYAN_DIM, CYAN, STYLESHEET)
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui     import QPalette, QColor

    app = QApplication(sys.argv)
    app.setApplicationName("CD_SCOPE")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")

    # Dark palette for native widgets
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(BG_PANEL))
    pal.setColor(QPalette.WindowText,      QColor(TEXT_BR))
    pal.setColor(QPalette.Base,            QColor(BG_DEEP))
    pal.setColor(QPalette.AlternateBase,   QColor(BG_CARD))
    pal.setColor(QPalette.Text,            QColor(TEXT_BR))
    pal.setColor(QPalette.Button,          QColor(BG_CARD))
    pal.setColor(QPalette.ButtonText,      QColor(TEXT_MID))
    pal.setColor(QPalette.Highlight,       QColor(CYAN_DIM))
    pal.setColor(QPalette.HighlightedText, QColor(CYAN))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)

    from cd_scope.ui import MainWindow
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    run_gui()
