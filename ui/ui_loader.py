# ui/ui_loader.py — load Qt Designer .ui files at runtime
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from app_paths import resource_path

_FORMS_DIR = Path(resource_path('ui', 'forms'))


def forms_dir() -> Path:
    return _FORMS_DIR


def form_path(name: str) -> Path:
    p = Path(name)
    if p.suffix.lower() != '.ui':
        p = _FORMS_DIR / f'{name}.ui'
    return p


def list_forms() -> list[str]:
    if not _FORMS_DIR.is_dir():
        return []
    return sorted(f.stem for f in _FORMS_DIR.glob('*.ui'))


def load_form(name: str, parent: QWidget | None = None) -> QWidget:
    """Load a .ui file from ui/forms/ (name with or without .ui extension)."""
    path = form_path(name)
    if not path.is_file():
        raise FileNotFoundError(f'UI form not found: {path}')
    f = QFile(str(path))
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        raise OSError(f'Cannot open UI form: {path}')
    loader = QUiLoader()
    widget = loader.load(f, parent)
    f.close()
    if widget is None:
        raise RuntimeError(f'Qt Designer failed to load: {path}')
    return widget


def bind(widget: QWidget, ui: QWidget) -> QWidget:
    """Attach loaded ui root into host widget (full bleed)."""
    from PySide6.QtWidgets import QVBoxLayout
    lay = QVBoxLayout(widget)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(ui)
    return ui
