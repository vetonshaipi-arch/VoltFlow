# ui/stub_dialog.py
# StubSpecDialog  — set interface spec on a SubPanel feeder
# ImportResultDialog — strict-validation failure detail (blocks import)

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox,
    QDoubleSpinBox, QLineEdit, QFormLayout, QFrame, QTextEdit,
    QPushButton, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


# ─────────────────────────────────────────────────────────────────────────────
class StubSpecDialog(QDialog):
    """
    Dialog to define (or edit) the interface specification for a SubPanel stub.
    The spec is the allocation contract that constrains the child engineer's design.

    Returns accepted() if OK; call spec() to get the dict.
    """

    def __init__(self, feeder_name: str, board_voltage: float,
                 board_isc: float, existing_spec: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Set Interface Spec — {feeder_name}')
        self.setMinimumWidth(440)
        self._build(feeder_name, board_voltage, board_isc, existing_spec or {})

    # ──────────────────────────────────────────────────────────────────────────
    def _build(self, name, board_v, board_isc, s):
        vl = QVBoxLayout(self); vl.setSpacing(10)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet('background:#1a3a5c;border-radius:3px;')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 8, 12, 8)
        title = QLabel(f'Interface Specification — {name}')
        title.setStyleSheet('color:#fff;font-size:10pt;font-weight:bold;')
        sub = QLabel('These values are the MAXIMUM the child design may not exceed.')
        sub.setStyleSheet('color:#a0c4e0;font-size:8pt;')
        col = QVBoxLayout(); col.setSpacing(2)
        col.addWidget(title); col.addWidget(sub)
        hl.addLayout(col)
        vl.addWidget(hdr)

        # Form
        form = QFormLayout(); form.setSpacing(8); form.setContentsMargins(8, 4, 8, 4)

        def _sp(mn, mx, val, step, dec=1):
            w = QDoubleSpinBox()
            w.setRange(mn, mx); w.setValue(val)
            w.setSingleStep(step); w.setDecimals(dec)
            w.setButtonSymbols(QDoubleSpinBox.NoButtons)
            w.setStyleSheet('background:#fff;border:1px solid #c0c0c0;'
                            'padding:3px 6px;font-size:9pt;')
            return w

        self._S   = _sp(0, 100000, s.get('S_kVA', 0),   10, 1)
        self._Ib  = _sp(0, 100000, s.get('Ib_A',  0),   10, 1)
        self._Isc = _sp(0, 200,    s.get('Isc_kA', board_isc), 1, 2)
        self._V   = _sp(0, 35000,  s.get('voltage', board_v),  1, 0)
        self._Vd  = _sp(0.1, 10,   s.get('max_vd_pct', 3.0),  0.5, 2)

        self._notes = QLineEdit(s.get('notes', ''))
        self._notes.setPlaceholderText('Optional — e.g. "Level B1 distribution"')
        self._notes.setStyleSheet('background:#fff;border:1px solid #c0c0c0;'
                                  'padding:3px 6px;font-size:9pt;')

        def lbl(t): return QLabel(t)

        form.addRow(lbl('Allocated S [kVA] :'),    self._S)
        form.addRow(lbl('Allocated Ib [A] :'),      self._Ib)
        form.addRow(lbl('Isc at incomer [kA] :'),   self._Isc)
        form.addRow(lbl('Source voltage [V] :'),    self._V)
        form.addRow(lbl('Max voltage drop [%] :'),  self._Vd)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('color:#d0d0d0;')

        form.addRow(sep)
        form.addRow(lbl('Notes :'), self._notes)
        vl.addLayout(form)

        # Info note
        note = QLabel(
            'The child engineer will receive a .swb file pre-loaded with these\n'
            'constraints. Import will be BLOCKED if any limit is exceeded.')
        note.setStyleSheet(
            'font-size:8pt;color:#856404;background:#fff3cd;'
            'padding:6px 10px;border-left:3px solid #f0a500;')
        note.setWordWrap(True)
        vl.addWidget(note)

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._validate)
        bb.rejected.connect(self.reject)
        ok = bb.button(QDialogButtonBox.Ok)
        ok.setText('Confirm Spec')
        ok.setStyleSheet('background:#107c10;color:#fff;font-weight:bold;'
                         'padding:5px 14px;border:none;')
        vl.addWidget(bb)

    def _validate(self):
        if self._S.value() <= 0 or self._Ib.value() <= 0:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Incomplete',
                                'S [kVA] and Ib [A] must be greater than zero.')
            return
        self.accept()

    def spec(self) -> dict:
        return {
            'S_kVA':      self._S.value(),
            'Ib_A':       self._Ib.value(),
            'Isc_kA':     self._Isc.value(),
            'voltage':    self._V.value(),
            'max_vd_pct': self._Vd.value(),
            'notes':      self._notes.text().strip(),
        }


# ─────────────────────────────────────────────────────────────────────────────
class ImportResultDialog(QDialog):
    """
    Shown after a strict-validation failure during import.
    Displays each violated check clearly and BLOCKS import.
    """

    def __init__(self, package_path: str, board_name: str,
                 spec: dict, errors: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import Blocked — Specification Violated')
        self.setMinimumWidth(560)
        self._build(package_path, board_name, spec, errors)

    def _build(self, path, name, spec, errors):
        vl = QVBoxLayout(self); vl.setSpacing(10)

        # Error header
        hdr = QWidget()
        hdr.setStyleSheet('background:#c42b1c;border-radius:3px;')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 10, 12, 10)
        ico = QLabel('✘'); ico.setStyleSheet(
            'color:#fff;font-size:18pt;font-weight:bold;')
        col = QVBoxLayout(); col.setSpacing(2)
        t1 = QLabel('Import Blocked')
        t1.setStyleSheet('color:#fff;font-size:11pt;font-weight:bold;')
        t2 = QLabel(f'{name}  ·  {path}')
        t2.setStyleSheet('color:#ffcccc;font-size:8pt;')
        col.addWidget(t1); col.addWidget(t2)
        hl.addWidget(ico); hl.addLayout(col, 1)
        vl.addWidget(hdr)

        # Spec summary
        spec_lbl = QLabel(
            f"Allocated:  S ≤ {spec.get('S_kVA',0):.0f} kVA  |  "
            f"Ib ≤ {spec.get('Ib_A',0):.0f} A  |  "
            f"Vd ≤ {spec.get('max_vd_pct',0):.2f} %")
        spec_lbl.setStyleSheet(
            'font-size:9pt;color:#555;background:#f5f5f5;'
            'padding:5px 10px;border:1px solid #d0d0d0;')
        vl.addWidget(spec_lbl)

        # Violations list
        err_box = QTextEdit()
        err_box.setReadOnly(True)
        err_box.setFixedHeight(120)
        err_box.setStyleSheet(
            'background:#fff5f5;border:1px solid #e0a0a0;'
            'font-size:9pt;font-family:"Courier New";color:#c42b1c;')
        err_box.setPlainText('\n'.join(f'  ✘  {e}' for e in errors))
        vl.addWidget(err_box)

        # Instruction
        instr = QLabel(
            'The child engineer must reduce loads or cable voltage drop to meet '
            'the allocated specification before this package can be imported.\n\n'
            'To change the allocation, use "Set Stub Spec" on the parent board.')
        instr.setStyleSheet(
            'font-size:8pt;color:#555;background:#f0f4f8;'
            'padding:6px 10px;border-left:3px solid #1a3a5c;')
        instr.setWordWrap(True)
        vl.addWidget(instr)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        vl.addWidget(bb)


# ─────────────────────────────────────────────────────────────────────────────
class ImportSuccessDialog(QDialog):
    """
    Confirmation shown after a successful import.
    """

    def __init__(self, board_name: str, spec: dict,
                 actual_S: float, actual_Ib: float,
                 actual_vd: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Package Imported Successfully')
        self.setMinimumWidth(460)
        self._build(board_name, spec, actual_S, actual_Ib, actual_vd)

    def _build(self, name, spec, aS, aIb, aVd):
        vl = QVBoxLayout(self); vl.setSpacing(10)

        hdr = QWidget()
        hdr.setStyleSheet('background:#107c10;border-radius:3px;')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 10, 12, 10)
        ico = QLabel('✔')
        ico.setStyleSheet('color:#fff;font-size:18pt;font-weight:bold;')
        col = QVBoxLayout(); col.setSpacing(2)
        t1 = QLabel('Package Accepted')
        t1.setStyleSheet('color:#fff;font-size:11pt;font-weight:bold;')
        t2 = QLabel(f'Sub-board  {name}  attached to hierarchy')
        t2.setStyleSheet('color:#ccffcc;font-size:8pt;')
        col.addWidget(t1); col.addWidget(t2)
        hl.addWidget(ico); hl.addLayout(col, 1)
        vl.addWidget(hdr)

        # Comparison table
        def _row(label, allocated, actual, unit=''):
            ok = actual <= allocated * 1.01
            clr = '#107c10' if ok else '#c42b1c'
            mark = '✔' if ok else '✘'
            return (f'  {mark}  {label:<20} '
                    f'Actual: {actual:.1f}{unit}   '
                    f'Allocated: {allocated:.1f}{unit}')

        lines = [
            _row('Apparent Power', spec.get('S_kVA', 0), aS, ' kVA'),
            _row('Load Current',   spec.get('Ib_A',  0), aIb, ' A'),
        ]
        if spec.get('max_vd_pct') and aVd > 0:
            lines.append(_row('Voltage Drop', spec['max_vd_pct'], aVd, ' %'))

        tbl = QTextEdit()
        tbl.setReadOnly(True); tbl.setFixedHeight(90)
        tbl.setStyleSheet('background:#f0fff0;border:1px solid #b8ddb8;'
                          'font-size:9pt;font-family:"Courier New";color:#107c10;')
        tbl.setPlainText('\n'.join(lines))
        vl.addWidget(tbl)

        note = QLabel('Run "Calc All" to propagate the imported loads through '
                      'the full distribution hierarchy.')
        note.setStyleSheet(
            'font-size:8pt;color:#555;background:#f0f4f8;'
            'padding:6px 10px;border-left:3px solid #1a3a5c;')
        note.setWordWrap(True)
        vl.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        vl.addWidget(bb)
