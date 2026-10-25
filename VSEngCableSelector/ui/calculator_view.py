# ui/calculator_view.py
import math
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QWidget, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QScrollArea, QButtonGroup,
    QRadioButton, QGroupBox, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtGui import QTextDocument

from ..cable_class import C_Cable, ConductorRow


class CalculatorView(QDialog):
    def __init__(self, cable: C_Cable, parent=None):
        super().__init__(parent)
        self._cable = cable
        self.setWindowTitle("VoltFlow Cable Calculator — KSA")
        self.setMinimumSize(980, 720)
        self._build_ui()
        self._sync_inputs()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setStyleSheet("background:#ffffff;")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:#1a3a5c;border-bottom:2px solid #f0a500;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 10, 20, 10)
        logo = QLabel("VoltFlow")
        logo.setStyleSheet(
            "background:#f0a500;color:#000;font-size:9pt;"
            "font-weight:bold;padding:3px 10px;letter-spacing:2px;")
        t1 = QLabel("Cable Calculator")
        t1.setStyleSheet(
            "font-size:10pt;font-weight:bold;letter-spacing:2px;color:#ffffff;")
        t2 = QLabel("LV cables · 0.6/1 kV · 60 Hz")
        t2.setStyleSheet("font-size:8pt;color:#a0c4e0;letter-spacing:1px;")
        tb = QVBoxLayout(); tb.setSpacing(2); tb.addWidget(t1); tb.addWidget(t2)
        hl.addWidget(logo); hl.addLayout(tb); hl.addStretch()

        c = self._cable
        summary = f"{c.core_config} · CU/{c.insulation} · {c.install_method.upper()} · k = {c.k:.3f}"
        badge = QLabel(summary)
        badge.setStyleSheet(
            "background:#eef2f7;color:#1a3a5c;font-size:9pt;"
            "font-family:'Courier New';padding:4px 12px;border:1px solid #d0d0d0;")
        hl.addWidget(badge)
        root.addWidget(hdr)

        # Scroll area for body
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setStyleSheet("background:#ffffff;")
        bl = QVBoxLayout(body); bl.setContentsMargins(24, 20, 24, 20); bl.setSpacing(14)

        bl.addWidget(self._build_input_panel())

        calc_btn = QPushButton("CALCULATE")
        calc_btn.setStyleSheet(
            "background:#f0a500;color:#000;font-size:9pt;font-weight:bold;"
            "padding:10px 28px;border:none;letter-spacing:1px;")
        calc_btn.clicked.connect(self._run_calculation)
        calc_btn.setCursor(Qt.PointingHandCursor)
        hl2 = QHBoxLayout(); hl2.addStretch(); hl2.addWidget(calc_btn); hl2.addStretch()
        bl.addLayout(hl2)

        self._result_widget = QWidget(); self._result_widget.hide()
        rl = QVBoxLayout(self._result_widget); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(10)
        self._result_summary = self._build_result_summary()
        rl.addWidget(self._result_summary)
        self._result_table_widget = QWidget()
        rl.addWidget(self._result_table_widget)
        bl.addWidget(self._result_widget)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Bottom bar
        bot = QWidget()
        bot.setStyleSheet("background:#f5f5f5;border-top:1px solid #d0d0d0;")
        botl = QHBoxLayout(bot); botl.setContentsMargins(16, 8, 16, 8); botl.setSpacing(8)
        pr_btn = QPushButton("Print Report")
        pr_btn.setStyleSheet(
            "background:#f5f5f5;border:1px solid #c0c0c0;color:#444;"
            "padding:6px 14px;font-size:9pt;")
        pr_btn.clicked.connect(self._print_report)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "background:#f5f5f5;border:1px solid #c0c0c0;color:#444;"
            "padding:6px 14px;font-size:9pt;")
        close_btn.clicked.connect(self.accept)
        botl.addStretch(); botl.addWidget(pr_btn); botl.addWidget(close_btn)
        root.addWidget(bot)

    # ─────────────────────────────────────────────────────────────────────────
    # INPUT PANEL
    # ─────────────────────────────────────────────────────────────────────────

    def _build_input_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background:#f5f5f5;border:1px solid #d0d0d0;")
        pl = QVBoxLayout(panel); pl.setContentsMargins(18, 14, 18, 14); pl.setSpacing(12)

        title = QLabel("CIRCUIT PARAMETERS")
        title.setStyleSheet(
            "font-size:9pt;font-weight:bold;color:#1a3a5c;letter-spacing:2px;"
            "border-bottom:1px solid #d0d0d0;padding-bottom:6px;")
        pl.addWidget(title)

        # Row 1: Phases + Voltage + Length + Max Vdrop
        r1 = QHBoxLayout(); r1.setSpacing(20)

        ph_box = QVBoxLayout(); ph_box.setSpacing(4)
        ph_box.addWidget(self._flabel("System phases:"))
        ph_row = QHBoxLayout(); ph_row.setSpacing(6)
        self._btn_1ph = QPushButton("1φ  Single Phase"); self._btn_1ph.setCheckable(True)
        self._btn_3ph = QPushButton("3φ  Three Phase");  self._btn_3ph.setCheckable(True)
        for btn in [self._btn_1ph, self._btn_3ph]:
            btn.setStyleSheet(
                "QPushButton{background:#ffffff;border:1px solid #c0c0c0;color:#1a1a1a;"
                "font-size:9pt;font-weight:600;padding:6px 12px;}"
                "QPushButton:hover{border-color:#1a3a5c;color:#1a3a5c;background:#eef2f7;}"
                "QPushButton:checked{background:#d4edda;border-color:#107c10;color:#107c10;}"
            )
            btn.setCursor(Qt.PointingHandCursor)
        self._btn_1ph.clicked.connect(lambda: self._sel_phase(1))
        self._btn_3ph.clicked.connect(lambda: self._sel_phase(3))
        ph_row.addWidget(self._btn_1ph); ph_row.addWidget(self._btn_3ph); ph_row.addStretch()
        ph_box.addLayout(ph_row)
        r1.addLayout(ph_box)

        v_box = QVBoxLayout(); v_box.setSpacing(4)
        v_box.addWidget(self._flabel("System voltage (V):"))
        self._sb_voltage = self._dspin(50, 35000, 400, 1)
        v_row = QHBoxLayout(); v_row.addWidget(self._sb_voltage); v_row.addWidget(self._unit("V")); v_row.addStretch()
        v_box.addLayout(v_row)
        r1.addLayout(v_box)

        l_box = QVBoxLayout(); l_box.setSpacing(4)
        l_box.addWidget(self._flabel("Cable length (m):"))
        self._sb_length = self._dspin(1, 100000, 100, 1)
        l_row = QHBoxLayout(); l_row.addWidget(self._sb_length); l_row.addWidget(self._unit("m")); l_row.addStretch()
        l_box.addLayout(l_row)
        r1.addLayout(l_box)

        vd_box = QVBoxLayout(); vd_box.setSpacing(4)
        vd_box.addWidget(self._flabel("Max voltage drop (%):"))
        self._sb_vdrop = self._dspin(0.1, 20, 3.0, 0.1)
        vd_row = QHBoxLayout(); vd_row.addWidget(self._sb_vdrop); vd_row.addWidget(self._unit("%")); vd_row.addStretch()
        vd_box.addLayout(vd_row)
        r1.addLayout(vd_box)
        r1.addStretch()
        pl.addLayout(r1)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border-top:1px solid #d0d0d0;")
        pl.addWidget(sep)

        psf_title = QLabel("POWER PARAMETERS  —  Select which two you know:")
        psf_title.setStyleSheet("font-size:8pt;color:#555555;letter-spacing:1px;text-transform:uppercase;")
        pl.addWidget(psf_title)

        radio_row = QHBoxLayout(); radio_row.setSpacing(16)
        self._bg = QButtonGroup(self)
        for i, (label, val) in enumerate([("P + PF", "P+PF"), ("S + PF", "S+PF"), ("P + S", "P+S")]):
            rb = QRadioButton(label)
            rb.setStyleSheet("color:#1a1a1a;font-size:9pt;")
            rb.setProperty("mode", val)
            self._bg.addButton(rb, i)
            radio_row.addWidget(rb)
            if i == 0: rb.setChecked(True)
        radio_row.addStretch()
        pl.addLayout(radio_row)
        self._bg.buttonClicked.connect(self._on_mode_change)

        r2 = QHBoxLayout(); r2.setSpacing(20)

        p_box = QVBoxLayout(); p_box.setSpacing(4)
        p_box.addWidget(self._flabel("Active Power P (kW):"))
        self._sb_P = self._dspin(0, 100000, 0, 0.1); self._sb_P.setSpecialValueText("")
        p_row = QHBoxLayout(); p_row.addWidget(self._sb_P); p_row.addWidget(self._unit("kW")); p_row.addStretch()
        p_box.addLayout(p_row)
        self._lbl_P_auto = QLabel("")
        self._lbl_P_auto.setStyleSheet("color:#888888;font-size:9pt;font-style:italic;")
        p_box.addWidget(self._lbl_P_auto)
        r2.addLayout(p_box)

        s_box = QVBoxLayout(); s_box.setSpacing(4)
        s_box.addWidget(self._flabel("Apparent Power S (kVA):"))
        self._sb_S = self._dspin(0, 100000, 0, 0.1); self._sb_S.setSpecialValueText("")
        s_row = QHBoxLayout(); s_row.addWidget(self._sb_S); s_row.addWidget(self._unit("kVA")); s_row.addStretch()
        s_box.addLayout(s_row)
        self._lbl_S_auto = QLabel("")
        self._lbl_S_auto.setStyleSheet("color:#888888;font-size:9pt;font-style:italic;")
        s_box.addWidget(self._lbl_S_auto)
        r2.addLayout(s_box)

        pf_box = QVBoxLayout(); pf_box.setSpacing(4)
        pf_box.addWidget(self._flabel("Power Factor PF:"))
        self._sb_PF = self._dspin(0.01, 1.0, 0.9, 0.01)
        pf_row = QHBoxLayout(); pf_row.addWidget(self._sb_PF); pf_row.addWidget(self._unit("—")); pf_row.addStretch()
        pf_box.addLayout(pf_row)
        self._lbl_PF_auto = QLabel("")
        self._lbl_PF_auto.setStyleSheet("color:#888888;font-size:9pt;font-style:italic;")
        pf_box.addWidget(self._lbl_PF_auto)
        r2.addLayout(pf_box)
        r2.addStretch()
        pl.addLayout(r2)

        self._on_mode_change()
        return panel

    # ─────────────────────────────────────────────────────────────────────────
    # RESULT SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

    def _build_result_summary(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(
            "background:#f5f5f5;border:1px solid #d0d0d0;border-left:3px solid #f0a500;")
        pl = QVBoxLayout(panel); pl.setContentsMargins(18, 14, 18, 14); pl.setSpacing(8)

        title = QLabel("CALCULATION RESULTS")
        title.setStyleSheet(
            "font-size:9pt;font-weight:bold;color:#1a3a5c;letter-spacing:2px;"
            "padding-bottom:6px;border-bottom:1px solid #d0d0d0;")
        pl.addWidget(title)

        grid = QHBoxLayout(); grid.setSpacing(28)

        left = QVBoxLayout(); left.setSpacing(6)
        self._lbl_Ib       = self._result_row(left, "Load Current Ib")
        self._lbl_rec_code = self._result_row(left, "Recommended Cable")
        self._lbl_rec_size = self._result_row(left, "Conductor Size")
        self._lbl_Iz       = self._result_row(left, "Derated Ampacity Iz = Iₙ × k")
        grid.addLayout(left)

        right = QVBoxLayout(); right.setSpacing(6)
        self._lbl_vdrop_v   = self._result_row(right, "Voltage Drop")
        self._lbl_vdrop_pct = self._result_row(right, "Voltage Drop %")
        self._lbl_amp_ok    = self._result_row(right, "Ampacity Check")
        self._lbl_vd_ok     = self._result_row(right, "Voltage Drop Check")
        grid.addLayout(right)

        pl.addLayout(grid)

        self._warn_lbl = QLabel("")
        self._warn_lbl.setStyleSheet(
            "font-size:9pt;color:#856404;font-style:italic;"
            "padding:5px 10px;background:#fff3cd;border-left:3px solid #f0a500;"
        )
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.hide()
        pl.addWidget(self._warn_lbl)

        pr = QPushButton("Print Report")
        pr.setStyleSheet(
            "background:#f5f5f5;border:1px solid #c0c0c0;color:#444;"
            "padding:5px 14px;font-size:9pt;max-width:140px;")
        pr.clicked.connect(self._print_report)
        pl.addWidget(pr, alignment=Qt.AlignRight)
        return panel

    def _result_row(self, parent_layout: QVBoxLayout, label: str) -> QLabel:
        row = QHBoxLayout(); row.setSpacing(10)
        lbl_k = QLabel(f"{label}:")
        lbl_k.setStyleSheet("font-size:9pt;color:#555555;min-width:200px;")
        lbl_v = QLabel("—")
        lbl_v.setStyleSheet(
            "font-family:'Courier New';font-size:9pt;color:#1a1a1a;font-weight:bold;")
        row.addWidget(lbl_k); row.addWidget(lbl_v); row.addStretch()
        parent_layout.addLayout(row)
        return lbl_v

    # ─────────────────────────────────────────────────────────────────────────
    # CALCULATION
    # ─────────────────────────────────────────────────────────────────────────

    def _run_calculation(self):
        c = self._cable
        mode = self._bg.checkedButton().property("mode")

        if mode == "P+PF":
            c.P  = self._sb_P.value()  or None
            c.PF = self._sb_PF.value() or None
            c.S  = None
        elif mode == "S+PF":
            c.S  = self._sb_S.value()  or None
            c.PF = self._sb_PF.value() or None
            c.P  = None
        elif mode == "P+S":
            c.P  = self._sb_P.value()  or None
            c.S  = self._sb_S.value()  or None
            c.PF = None

        c.phases        = 1 if self._btn_1ph.isChecked() else 3
        c.voltage       = self._sb_voltage.value()
        c.cable_length  = self._sb_length.value()
        c.max_vdrop_pct = self._sb_vdrop.value()

        ok, errs = c.is_valid_calculation()
        if not ok:
            QMessageBox.warning(self, "Input Error", "\n".join(errs))
            return

        c.calculate_load()
        self._update_auto_labels()
        self._populate_results()
        self._populate_result_table()
        self._result_widget.show()

    def _populate_results(self):
        c = self._cable
        self._lbl_Ib.setText(f"{c.Ib:.2f} A")

        if c.recommended:
            r = c.recommended
            self._lbl_rec_code.setText(r.cable_code)
            self._lbl_rec_code.setStyleSheet(
                "font-family:'Courier New';font-size:9pt;color:#1a3a5c;font-weight:bold;")
            self._lbl_rec_size.setText(
                f"{r.size_mm2} mm²  ({r.shape})" if r.shape != '-' else f"{r.size_mm2} mm²")
            self._lbl_Iz.setText(f"{r.Iz:.2f} A")
            self._lbl_vdrop_v.setText(f"{r.vdrop_v:.3f} V")
            self._lbl_vdrop_pct.setText(f"{r.vdrop_pct:.3f} %")

            def check_lbl(lbl, ok):
                if ok:
                    lbl.setText("PASS")
                    lbl.setStyleSheet(
                        "font-family:'Courier New';font-size:9pt;color:#107c10;font-weight:bold;")
                else:
                    lbl.setText("FAIL")
                    lbl.setStyleSheet(
                        "font-family:'Courier New';font-size:9pt;color:#c42b1c;font-weight:bold;")

            check_lbl(self._lbl_amp_ok,  c.passes_ampacity)
            check_lbl(self._lbl_vd_ok,   c.passes_vdrop)

        if c.warnings:
            self._warn_lbl.setText("\n".join(c.warnings))
            self._warn_lbl.show()
        else:
            self._warn_lbl.hide()

    def _populate_result_table(self):
        while self._result_table_widget.layout() and self._result_table_widget.layout().count():
            item = self._result_table_widget.layout().takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if not self._result_table_widget.layout():
            self._result_table_widget.setLayout(QVBoxLayout())
        rtl = self._result_table_widget.layout()
        rtl.setContentsMargins(0, 0, 0, 0)

        title = QLabel("CONDUCTOR COMPARISON TABLE")
        title.setStyleSheet(
            "font-size:9pt;font-weight:bold;color:#1a3a5c;letter-spacing:2px;"
            "padding:6px 0 4px 0;")
        rtl.addWidget(title)

        tbl = QTableWidget()
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setAlternatingRowColors(False)
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(True)
        tbl.setStyleSheet(
            "QTableWidget{background:#ffffff;gridline-color:#e0e0e0;}"
            "QHeaderView::section{background:#f0f4f8;color:#1a1a1a;font-size:8pt;"
            "font-weight:bold;padding:4px;border:1px solid #d0d0d0;}"
        )

        headers = ["mm²", "Cable Code", "Iₙ (A)", "Iz = Iₙ×k (A)",
                   "Vdrop (V)", "Vdrop (%)", "Amp", "Vdrop"]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.horizontalHeader().setStretchLastSection(True)

        rows = self._cable.conductor_table
        rec  = self._cable.recommended
        tbl.setRowCount(len(rows))

        mono = QFont("Courier New", 9)
        for ri, row in enumerate(rows):
            is_rec = rec and row.cable_code == rec.cable_code
            bg = QColor("#d4edda") if is_rec else (QColor("#ffffff") if ri % 2 == 0 else QColor("#f5f5f5"))

            vals = [
                str(int(row.size_mm2)) if row.size_mm2 == int(row.size_mm2) else str(row.size_mm2),
                row.cable_code,
                str(row.In),
                f"{row.Iz:.1f}",
                f"{row.vdrop_v:.3f}",
                f"{row.vdrop_pct:.3f}",
                "PASS" if row.passes_amp   else "FAIL",
                "PASS" if row.passes_vdrop else "FAIL",
            ]
            for ci, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setFont(mono)
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QBrush(bg))

                if ci == 1:  # cable code
                    item.setForeground(QBrush(QColor("#1a3a5c" if is_rec else "#1a1a1a")))
                elif v == "PASS":
                    item.setForeground(QBrush(QColor("#107c10")))
                elif v == "FAIL":
                    item.setForeground(QBrush(QColor("#c42b1c")))
                else:
                    item.setForeground(QBrush(QColor("#1a1a1a")))

                tbl.setItem(ri, ci, item)
            tbl.setRowHeight(ri, 24)

        for i, w in enumerate([50, 180, 60, 100, 80, 80, 60, 70]):
            tbl.setColumnWidth(i, w)

        total_h = (sum(tbl.rowHeight(i) for i in range(len(rows)))
                   + tbl.horizontalHeader().height() + 4)
        tbl.setFixedHeight(min(total_h, 400))
        rtl.addWidget(tbl)

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _sel_phase(self, ph: int):
        self._cable.phases = ph
        self._btn_1ph.setChecked(ph == 1)
        self._btn_3ph.setChecked(ph == 3)

    def _on_mode_change(self):
        btn = self._bg.checkedButton()
        if not btn: return
        mode = btn.property("mode")
        self._sb_P.setEnabled("P" in mode)
        self._sb_S.setEnabled("S" in mode)
        self._sb_PF.setEnabled("PF" in mode)
        self._lbl_P_auto.setText("" if "P" in mode else "(auto-calculated)")
        self._lbl_S_auto.setText("" if "S" in mode else "(auto-calculated)")
        self._lbl_PF_auto.setText("" if "PF" in mode else "(auto-calculated)")

    def _update_auto_labels(self):
        c = self._cable
        if c.P  is not None: self._sb_P.setValue(c.P)
        if c.S  is not None: self._sb_S.setValue(c.S)
        if c.PF is not None: self._sb_PF.setValue(c.PF)

    def _sync_inputs(self):
        c = self._cable
        self._sel_phase(c.phases)
        self._sb_voltage.setValue(c.voltage)
        self._sb_length.setValue(c.cable_length)
        self._sb_vdrop.setValue(c.max_vdrop_pct)
        if c.P  is not None: self._sb_P.setValue(c.P)
        if c.S  is not None: self._sb_S.setValue(c.S)
        if c.PF is not None: self._sb_PF.setValue(c.PF)

    def _dspin(self, mn, mx, default, step) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(mn, mx); sb.setValue(default); sb.setSingleStep(step)
        sb.setDecimals(2 if step < 1 else 0)
        sb.setStyleSheet(
            "background:#ffffff;border:1px solid #d0d0d0;color:#1a1a1a;"
            "padding:5px 8px;font-family:'Courier New';font-size:9pt;min-width:90px;"
        )
        return sb

    def _flabel(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:9pt;color:#555555;")
        return lbl

    def _unit(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:9pt;color:#555555;font-family:'Courier New';")
        return lbl

    # ─────────────────────────────────────────────────────────────────────────
    # PRINT REPORT
    # ─────────────────────────────────────────────────────────────────────────

    def _print_report(self):
        c = self._cable
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QPrintDialog.Accepted:
            doc = QTextDocument()
            doc.setHtml(self._build_report_html())
            doc.print_(printer)

    def _build_report_html(self) -> str:
        c = self._cable
        rec = c.recommended

        rows_html = ""
        for r in c.conductor_table:
            is_rec = rec and r.cable_code == rec.cable_code
            bg = "#d4edda" if is_rec else ("white" if c.conductor_table.index(r) % 2 == 0 else "#f8f8f8")
            amp_ok = "PASS" if r.passes_amp else "FAIL"
            vd_ok  = "PASS" if r.passes_vdrop else "FAIL"
            rows_html += f"""<tr style="background:{bg}">
                <td>{r.size_mm2}</td>
                <td style="font-family:monospace;font-size:10px">{r.cable_code}</td>
                <td>{r.In}</td><td>{r.Iz:.1f}</td>
                <td>{r.vdrop_v:.3f}</td><td>{r.vdrop_pct:.3f}</td>
                <td style="color:{'green' if r.passes_amp else 'red'}">{amp_ok}</td>
                <td style="color:{'green' if r.passes_vdrop else 'red'}">{vd_ok}</td>
            </tr>"""

        warnings_html = ""
        if c.warnings:
            warnings_html = ("<h3 style='color:orange'>Warnings</h3><ul>"
                             + "".join(f"<li>{w}</li>" for w in c.warnings) + "</ul>")

        rec_html = ""
        if rec:
            rec_html = f"""
            <h3>Recommended Conductor</h3>
            <table border="1" cellpadding="4" style="border-collapse:collapse">
            <tr><td><b>Cable Code</b></td><td>{rec.cable_code}</td></tr>
            <tr><td><b>Size</b></td><td>{rec.size_mm2} mm²</td></tr>
            <tr><td><b>Derated Ampacity Iz</b></td><td>{rec.Iz:.2f} A</td></tr>
            <tr><td><b>Voltage Drop</b></td><td>{rec.vdrop_v:.3f} V  ({rec.vdrop_pct:.3f}%)</td></tr>
            <tr><td><b>Ampacity</b></td>
                <td style="color:{'green' if c.passes_ampacity else 'red'}">
                {'PASS' if c.passes_ampacity else 'FAIL'}</td></tr>
            <tr><td><b>Voltage Drop</b></td>
                <td style="color:{'green' if c.passes_vdrop else 'red'}">
                {'PASS' if c.passes_vdrop else 'FAIL'}</td></tr>
            </table>"""

        return f"""<html><body style="font-family:Arial;font-size:12px">
        <h2>VoltFlow — LV Power Cables · Calculation Report</h2>
        <h3>Cable Selection</h3>
        <p>{c.core_config} · CU/{c.insulation}/PVC · 0.6/1 kV · {c.install_method.upper()}</p>
        <p>k1 = {c.k1:.3f} &nbsp;×&nbsp; k2 = {c.k2:.3f} &nbsp;×&nbsp;
           k3 = {c.k3:.3f} &nbsp;=&nbsp; <b>k = {c.k:.3f}</b></p>
        <hr>
        <h3>Circuit Parameters</h3>
        <table border="1" cellpadding="4" style="border-collapse:collapse">
        <tr><td><b>System</b></td><td>{c.phases}φ &nbsp;·&nbsp; {c.voltage} V</td></tr>
        <tr><td><b>P / S / PF</b></td><td>{c.P} kW &nbsp;/&nbsp; {c.S} kVA &nbsp;/&nbsp; {c.PF}</td></tr>
        <tr><td><b>Load Current Ib</b></td><td>{c.Ib:.2f} A</td></tr>
        <tr><td><b>Cable Length</b></td><td>{c.cable_length} m</td></tr>
        <tr><td><b>Max Voltage Drop</b></td><td>{c.max_vdrop_pct} %</td></tr>
        </table>
        <hr>
        {rec_html}
        {warnings_html}
        <hr>
        <h3>Full Conductor Comparison</h3>
        <table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse;width:100%">
        <tr style="background:#ddd">
            <th>mm²</th><th>Cable Code</th><th>Iₙ (A)</th><th>Iz (A)</th>
            <th>Vdrop (V)</th><th>Vdrop (%)</th><th>Amp</th><th>Vdrop</th>
        </tr>
        {rows_html}
        </table>
        <p style="font-size:10px;color:#666;margin-top:12px">
        Laying Conditions: Ambient air 40°C · Ground 35°C ·
        Soil resistivity 1.5 K·m/W · Depth 0.5m<br>
        Voltage drop formula: {'√3 × Ib × L × (R·cosφ + X·sinφ)'
                               if c.phases == 3 else '2 × Ib × L × (R·cosφ + X·sinφ)'}
        </p>
        </body></html>"""
