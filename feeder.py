# feeder.py — VoltFlow Feeder standalone entry point
import sys
import os

_HERE  = os.path.dirname(os.path.abspath(__file__))
_CABLE = os.path.join(_HERE, 'VSEngCableSelector')
# Project root must be sys.path[0] so `ui` resolves to SwitchboardSuite/ui/
# (not VSEngCableSelector/ui/, which also has __init__.py).
if _HERE in sys.path:
    sys.path.remove(_HERE)
sys.path.insert(0, _HERE)
if _CABLE not in sys.path:
    sys.path.insert(1, _CABLE)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from feeder_class import C_Feeder
from ui.feeder_window import FeederWindow


def load_stylesheet(app):
    qss = os.path.join(_CABLE, 'theme', 'dark.qss')
    if os.path.exists(qss):
        with open(qss, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("VoltFlow")
    app.setOrganizationName("VoltFlow")
    app.setFont(QFont("Segoe UI", 10))
    load_stylesheet(app)
    f = C_Feeder()
    win = FeederWindow(f, 0.0)
    win.show()
    sys.exit(app.exec())
