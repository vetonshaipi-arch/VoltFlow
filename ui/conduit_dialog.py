# ui/conduit_dialog.py
# Conduit sizing form — fill based on cable OUTER DIAMETER from catalogue
# IEC fill rules: 1 cable→54%, 2 cables→31%, >2 cables→40%

import os, sys, math
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QSpinBox, QPushButton, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtGui import QTextDocument

from conduit_class import C_Conduit, CONDUIT_SIZES_MM, CONDUIT_TYPES, cable_od_area

N_ROWS = 10


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def _collect_project_cables(root_board) -> list:
    """
    Return sorted list of (label, od_mm) for every unique cable type
    that appears in the project (has a selected conductor with a known OD).
    Keyed by (size_mm2, core_config, insulation) to de-duplicate.
    """
    seen = {}   # key → (label, od_mm)
    if root_board:
        for b in root_board.all_boards():
            for f in b.feeders:
                rec = f.cable.recommended
                if rec and rec.diameter and rec.diameter > 0:
                    key = (rec.size_mm2, f.cable.core_config, f.cable.insulation)
                    if key not in seen:
                        # Short label: e.g. "1C 150mm² XLPE  OD=20.1mm"
                        s     = _fmt(rec.size_mm2)
                        cc    = '1C' if f.cable.core_config == '1C' else f.cable.core_config
                        ins   = f.cable.insulation
                        label = f'{cc} {s}mm² {ins}  (OD {rec.diameter}mm)'
                        seen[key] = (label, rec.diameter)
    # Sort by OD ascending
    return sorted(seen.values(), key=lambda x: x[1])


class ConduitDialog(QDialog):
    def __init__(self, root_board=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Conduit Sizing')
        self.setMinimumWidth(780)
        self._root   = root_board
        self._cables = _collect_project_cables(root_board)  # [(label, od_mm)]
        self._rows   = []   # (type_combo, qty_spin, od_lbl, area_lbl, sub_lbl)
        self._build_ui()
        self._refresh()

    # ── UI BUILD ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(10)

        vl.addLayout(self._build_header())
        vl.addWidget(self._hline())
        vl.addLayout(self._build_table())
        vl.addWidget(self._hline())
        vl.addLayout(self._build_summary())
        vl.addWidget(self._build_status())
        vl.addWidget(self._hline())
        vl.addLayout(self._build_buttons())

    def _build_header(self) -> QHBoxLayout:
        hl = QHBoxLayout(); hl.setSpacing(8)

        hl.addWidget(self._lbl('Type:', bold=True))
        self._type_cb = QComboBox()
        for t in CONDUIT_TYPES:
            self._type_cb.addItem(t.capitalize(), t)
        self._type_cb.currentIndexChanged.connect(self._refresh)
        hl.addWidget(self._type_cb)

        hl.addSpacing(16)
        hl.addWidget(self._lbl('Size:', bold=True))
        self._size_cb = QComboBox()
        for s in CONDUIT_SIZES_MM:
            self._size_cb.addItem(f'Ø{s} mm (ID)', s)
        self._size_cb.setCurrentIndex(1)  # 20 mm default
        self._size_cb.currentIndexChanged.connect(self._refresh)
        hl.addWidget(self._size_cb)

        hl.addSpacing(16)
        auto_btn = QPushButton('⚡ Auto-Size')
        auto_btn.setToolTip('Select the smallest conduit that satisfies the fill rule')
        auto_btn.setFixedHeight(28)
        auto_btn.clicked.connect(self._auto_size)
        hl.addWidget(auto_btn)
        hl.addStretch()
        return hl

    def _build_table(self) -> QGridLayout:
        gl = QGridLayout(); gl.setSpacing(4)
        gl.setColumnStretch(1, 1)

        headers = ['#', 'Cable Type', 'Qty', 'OD (mm)', 'Cable Area (mm²)', 'Subtotal (mm²)']
        for ci, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setStyleSheet(
                'font-weight:bold;color:#fff;background:#1a3a5c;'
                'padding:3px 6px;border-radius:2px;')
            lbl.setAlignment(Qt.AlignCenter)
            gl.addWidget(lbl, 0, ci)

        self._rows.clear()
        for i in range(N_ROWS):
            row_lbl = QLabel(str(i + 1))
            row_lbl.setAlignment(Qt.AlignCenter)
            row_lbl.setStyleSheet('color:#888;font-size:9pt;')

            type_cb = QComboBox()
            type_cb.addItem('—', None)
            for label, od in self._cables:
                type_cb.addItem(label, od)
            type_cb.currentIndexChanged.connect(self._refresh)

            qty_sp = QSpinBox()
            qty_sp.setRange(0, 99); qty_sp.setValue(0)
            qty_sp.setFixedWidth(55)
            qty_sp.valueChanged.connect(self._refresh)

            od_lbl   = QLabel('—'); od_lbl.setAlignment(Qt.AlignCenter)
            od_lbl.setStyleSheet('color:#555;font-family:Courier New;')

            area_lbl = QLabel('—'); area_lbl.setAlignment(Qt.AlignCenter)
            area_lbl.setStyleSheet('color:#555;font-family:Courier New;')

            sub_lbl  = QLabel('—'); sub_lbl.setAlignment(Qt.AlignCenter)
            sub_lbl.setStyleSheet('color:#003d8f;font-weight:bold;font-family:Courier New;')

            gl.addWidget(row_lbl,  i + 1, 0)
            gl.addWidget(type_cb,  i + 1, 1)
            gl.addWidget(qty_sp,   i + 1, 2)
            gl.addWidget(od_lbl,   i + 1, 3)
            gl.addWidget(area_lbl, i + 1, 4)
            gl.addWidget(sub_lbl,  i + 1, 5)

            self._rows.append((type_cb, qty_sp, od_lbl, area_lbl, sub_lbl))

        return gl

    def _build_summary(self) -> QGridLayout:
        gl = QGridLayout(); gl.setSpacing(6)
        fields = [
            ('Conduit Area (mm²)', '_s_nom'),
            ('Filled (mm²)',       '_s_fill'),
            ('Fill %',             '_s_pct'),
            ('Max Fill %',         '_s_max'),
            ('Limit (mm²)',        '_s_lim'),
        ]
        for ci, (title, attr) in enumerate(fields):
            hdr = QLabel(title)
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setStyleSheet('font-size:8pt;color:#555;')
            val = QLabel('—')
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet('font-weight:bold;font-size:10pt;color:#1a3a5c;')
            setattr(self, attr, val)
            gl.addWidget(hdr, 0, ci)
            gl.addWidget(val, 1, ci)
        return gl

    def _build_status(self) -> QLabel:
        lbl = QLabel('—')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedHeight(46)
        from .qt_helpers import app_font
        lbl.setFont(app_font('Segoe UI', 14, bold=True))
        lbl.setStyleSheet('background:#e0e0e0;color:#888;border-radius:6px;')
        self._status_lbl = lbl
        return lbl

    def _build_buttons(self) -> QHBoxLayout:
        hl = QHBoxLayout(); hl.addStretch()
        for label, slot in [('🖨  Print', self._print), ('Close', self.accept)]:
            btn = QPushButton(label); btn.setFixedHeight(30)
            btn.clicked.connect(slot); hl.addWidget(btn)
        return hl

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _lbl(self, text, bold=False):
        l = QLabel(text)
        if bold: l.setStyleSheet('font-weight:bold;')
        return l

    def _hline(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet('color:#d8d8d8;'); return f

    # ── LOGIC ─────────────────────────────────────────────────────────────────

    def _get_conduit(self) -> C_Conduit:
        c = C_Conduit(size_mm=self._size_cb.currentData(),
                      conduit_type=self._type_cb.currentData())
        for type_cb, qty_sp, *_ in self._rows:
            od = type_cb.currentData()
            q  = qty_sp.value()
            if od and q > 0:
                for _ in range(q):
                    c.add_cable(od)
        return c

    def _refresh(self):
        c = self._get_conduit()

        for type_cb, qty_sp, od_lbl, area_lbl, sub_lbl in self._rows:
            od = type_cb.currentData()
            q  = qty_sp.value()
            if od and q > 0:
                a = cable_od_area(od)
                od_lbl.setText(f'{od:.1f}')
                area_lbl.setText(f'{a:.1f}')
                sub_lbl.setText(f'{a * q:.1f}')
            else:
                od_lbl.setText('—'); area_lbl.setText('—'); sub_lbl.setText('—')

        lim = c.nom_area * c.max_fill_pct / 100.0
        self._s_nom.setText(f'{c.nom_area:.1f}')
        self._s_fill.setText(f'{c.filled_area:.1f}')
        self._s_pct.setText(f'{c.fill_pct:.1f} %')
        self._s_max.setText(f'{c.max_fill_pct:.0f} %')
        self._s_lim.setText(f'{lim:.1f}')

        n = len(c.cables)
        if n == 0:
            self._status_lbl.setText('—')
            self._status_lbl.setStyleSheet(
                'background:#e0e0e0;color:#888;border-radius:6px;')
        elif c.is_overfilled:
            self._status_lbl.setText('✘   OVERFILLED')
            self._status_lbl.setStyleSheet(
                'background:#c42b1c;color:#fff;border-radius:6px;')
        else:
            self._status_lbl.setText('✔   PASS')
            self._status_lbl.setStyleSheet(
                'background:#107c10;color:#fff;border-radius:6px;')

    def _auto_size(self):
        c_tmp = self._get_conduit()
        best  = C_Conduit.min_size_for(c_tmp.cables)
        if best in CONDUIT_SIZES_MM:
            self._size_cb.setCurrentIndex(CONDUIT_SIZES_MM.index(best))

    # ── PRINT ─────────────────────────────────────────────────────────────────

    def _print(self):
        c    = self._get_conduit()
        html = self._build_html(c)
        doc  = QTextDocument(); doc.setHtml(html)
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec():
            doc.print_(printer)

    def _build_html(self, c: C_Conduit) -> str:
        rows_html = ''
        idx = 1
        for type_cb, qty_sp, *_ in self._rows:
            od = type_cb.currentData()
            q  = qty_sp.value()
            if not od or q == 0:
                continue
            label = type_cb.currentText()
            a     = cable_od_area(od)
            rows_html += (
                f'<tr>'
                f'<td style="text-align:center">{idx}</td>'
                f'<td>{label}</td>'
                f'<td style="text-align:center">{q}</td>'
                f'<td style="text-align:center">{od:.1f}</td>'
                f'<td style="text-align:center">{a:.1f}</td>'
                f'<td style="text-align:center">{a*q:.1f}</td>'
                f'</tr>'
            )
            idx += 1

        lim = c.nom_area * c.max_fill_pct / 100.0
        n   = len(c.cables)
        sc  = '#c42b1c' if c.is_overfilled else '#107c10'
        st  = 'OVERFILLED' if c.is_overfilled else 'PASS'
        cl  = '1 cable' if n == 1 else f'{n} cables'

        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  body  {{font-family:Arial,sans-serif;font-size:11pt;margin:28px;color:#1a1a1a;}}
  h2    {{color:#1a3a5c;margin:0 0 4px 0;}}
  p     {{margin:3px 0;font-size:10pt;color:#555;}}
  table {{border-collapse:collapse;width:100%;margin:14px 0;}}
  th    {{background:#1a3a5c;color:#fff;padding:6px 10px;}}
  td    {{border:1px solid #bbb;padding:5px 10px;}}
  tr:nth-child(even) td {{background:#f5f7fa;}}
  .tot  {{font-weight:bold;background:#e8f0f8 !important;}}
  .box  {{display:inline-block;padding:8px 32px;background:{sc};
          color:#fff;font-weight:bold;font-size:14pt;
          border-radius:4px;margin-top:14px;}}
</style></head><body>
<h2>Conduit Sizing Report</h2>
<p><b>Type:</b> {c.conduit_type.capitalize()} &nbsp;|&nbsp;
   <b>Nominal ID:</b> Ø{c.size_mm} mm &nbsp;|&nbsp;
   <b>Bore Area:</b> {c.nom_area:.1f} mm²</p>
<table>
  <tr><th>#</th><th>Cable Type</th><th>Qty</th>
      <th>OD (mm)</th><th>Cable Area (mm²)</th><th>Subtotal (mm²)</th></tr>
  {rows_html}
  <tr class="tot">
    <td colspan="5" style="text-align:right">Total Filled Area:</td>
    <td style="text-align:center">{c.filled_area:.1f} mm²</td>
  </tr>
</table>
<p><b>Fill:</b> {c.fill_pct:.1f}% &nbsp;|&nbsp;
   <b>Rule ({cl}):</b> max {c.max_fill_pct:.0f}% &nbsp;|&nbsp;
   <b>Limit:</b> {lim:.1f} mm²</p>
<p style="font-size:9pt;color:#888;margin-top:8px;">
   Ref: BS 7671:2018 Appendix 5, Table 5A — fill based on cable OD (IEC 61386 conduit series)
</p>
<div class="box">{st}</div>
</body></html>"""
