#!/usr/bin/env python3
"""Load every ui/forms/*.ui with QUiLoader (same path as the app)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from ui.ui_loader import list_forms, load_form


def main() -> int:
    app = QApplication([])
    failed = []
    for name in list_forms():
        try:
            w = load_form(name)
            print(f'OK  {name}.ui  ({w.metaObject().className()})')
        except Exception as exc:
            print(f'FAIL  {name}.ui  {exc}')
            failed.append(name)
    if failed:
        print(f'\n{len(failed)} form(s) failed.')
        return 1
    print(f'\nAll {len(list_forms())} forms loaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
