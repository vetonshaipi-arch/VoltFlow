# app_paths.py — project root for dev runs and PyInstaller bundles
import os
import sys


def app_root() -> str:
    """Directory containing bundled resources (theme, ui/forms, templates)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts: str) -> str:
    return os.path.join(app_root(), *parts)
