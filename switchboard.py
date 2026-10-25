# switchboard.py — VoltFlow entry point
import sys, os
from app_paths import app_root, resource_path

_HERE = app_root()
# Ensure the project root is at sys.path[0] so 'ui' resolves to ui/ not
# VSEngCableSelector/ui/ (which also has __init__.py and shadows it).
if _HERE in sys.path:
    sys.path.remove(_HERE)
sys.path.insert(0, _HERE)

from PySide6.QtWidgets import QApplication
from ui.ribbon_window import MainAppWindow
from ui.qt_helpers import app_font
from version import APP_VERSION

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setApplicationName('VoltFlow')
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName('VoltFlow')
    app.setFont(app_font('Segoe UI', 10))

    qss = resource_path('theme', 'light.qss')
    if os.path.exists(qss):
        with open(qss, encoding='utf-8') as f:
            app.setStyleSheet(f.read())

    win = MainAppWindow()
    win.show()
    sys.exit(app.exec())
