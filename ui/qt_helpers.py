# ui/qt_helpers.py — small Qt utilities shared across VoltFlow UI
from __future__ import annotations

import warnings

from PySide6.QtGui import QFont


def disconnect_signal(signal, slot=None) -> None:
    """Disconnect without RuntimeWarning when nothing was connected."""
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=RuntimeWarning)
        try:
            if slot is None:
                signal.disconnect()
            else:
                signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass


def app_font(family: str = 'Segoe UI', point_size: int = 10, bold: bool = False) -> QFont:
    """Build a QFont with a guaranteed positive point size."""
    f = QFont(family)
    f.setPointSize(max(1, int(point_size)))
    f.setBold(bold)
    return f
