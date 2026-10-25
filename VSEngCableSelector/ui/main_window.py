# VoltFlow Cable Selector — main window (embedded or standalone)
# Accepts existing C_Cable; Proceed button + on_proceed callback for embed mode

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QFileDialog,
    QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtGui import QTextDocument
from typing import Optional, Callable

import sys, os
_HERE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # VSEngCableSelector root
_UI_CS = os.path.join(_HERE, 'ui')
for _p in [_HERE, _UI_CS]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
from ..cable_class import C_Cable
from .catalogue_view import CatalogueView
from .kfactor_view import KFactorView
from .calculator_view import CalculatorView


class MainWindow(QMainWindow):
    """
    Cable Selector main window.

    Standalone mode:  MainWindow()
    Embedded mode:    MainWindow(cable=existing_obj, on_proceed=callback_fn)
      — on_proceed(cable: C_Cable) is called when user clicks Proceed
    """

    def __init__(
        self,
        cable: Optional[C_Cable] = None,
        on_proceed: Optional[Callable] = None,
        min_conductor_mm2: float = 1.5,
        parent=None
    ):
        super().__init__(parent)
        self.cable      = cable if cable is not None else C_Cable()
        self.cable.min_conductor_mm2 = min_conductor_mm2
        self._on_proceed = on_proceed
        self._embedded  = on_proceed is not None
        self._current_file = None

        title = "VoltFlow Cable Selector — KSA LV Power Cables"
        if self._embedded:
            title = "Cable Selector  [Select cable and press Proceed]"
        self.setWindowTitle(title)
        self.setMinimumSize(1440, 820)

        self._build_ui()

        # If cable already has data, restore UI state
        if self.cable.conductor_table:
            self._restore_ui_from_cable()
            self._show_results()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget(); central.setObjectName("centralWidget")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("contentScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.content_widget = QWidget(); self.content_widget.setObjectName("contentWidget")
        self.content_widget.setStyleSheet("background:#ffffff;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(28, 28, 28, 28)
        self.content_layout.setSpacing(20)
        self.content_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.content_widget)
        root.addWidget(scroll, 1)

        self._show_placeholder()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        sb = QWidget(); sb.setObjectName("sidebar")
        sb.setFixedWidth(320)
        sb.setStyleSheet("background:#ffffff;")
        layout = QVBoxLayout(sb)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:#1a3a5c;border-bottom:2px solid #f0a500;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16, 12, 16, 12)
        logo = QLabel("VoltFlow")
        logo.setStyleSheet(
            "background:#f0a500;color:#000;font-size:9pt;"
            "font-weight:bold;padding:3px 10px;letter-spacing:2px;")
        tb = QVBoxLayout(); tb.setSpacing(2)
        t1 = QLabel("Cable Selector")
        t1.setStyleSheet(
            "font-size:10pt;font-weight:bold;letter-spacing:2px;color:#ffffff;")
        t2 = QLabel("LV power cables · 0.6/1 kV · 60 Hz (KSA)")
        t2.setStyleSheet("font-size:8pt;color:#a0c4e0;letter-spacing:1px;")
        tb.addWidget(t1); tb.addWidget(t2)
        hl.addWidget(logo); hl.addLayout(tb)
        layout.addWidget(hdr)

        # Embedded mode banner
        if self._embedded:
            banner = QLabel("Select cable type and installation,\n"
                            "complete k-factors, then press PROCEED.")
            banner.setStyleSheet(
                "background:#fff3cd;color:#856404;font-size:9pt;"
                "padding:7px 14px;border-bottom:1px solid #f0a500;")
            banner.setWordWrap(True)
            layout.addWidget(banner)

        # Questions scroll area
        q_scroll = QScrollArea()
        q_scroll.setWidgetResizable(True)
        q_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        q_scroll.setFrameShape(QFrame.NoFrame)
        q_widget = QWidget(); q_widget.setStyleSheet("background:#ffffff;")
        q_layout = QVBoxLayout(q_widget)
        q_layout.setContentsMargins(16, 16, 16, 16); q_layout.setSpacing(20)

        # Q1
        self.btn_pvc  = self._opt_btn("PVC   70°C")
        self.btn_xlpe = self._opt_btn("XLPE  90°C")
        q_layout.addLayout(self._q_block(
            "Q1 · INSULATION", "Select conductor insulation:",
            [self.btn_pvc, self.btn_xlpe]))
        self.btn_pvc.clicked.connect(lambda: self._sel_insulation('PVC'))
        self.btn_xlpe.clicked.connect(lambda: self._sel_insulation('XLPE'))

        # Q2
        self.btn_1c = self._opt_btn("1C — Single Conductor")
        self.btn_2c = self._opt_btn("2C — Two Core")
        self.btn_3c = self._opt_btn("3C — Three Core")
        self.btn_4c = self._opt_btn("4C — Four Core")
        q_layout.addLayout(self._q_block(
            "Q2 · CONFIGURATION", "Single conductor or multi-core?",
            [self.btn_1c, self.btn_2c, self.btn_3c, self.btn_4c]))
        for btn, val in [(self.btn_1c,'1C'),(self.btn_2c,'2C'),
                         (self.btn_3c,'3C'),(self.btn_4c,'4C')]:
            btn.clicked.connect(lambda checked, v=val: self._sel_core(v))

        # Q3
        self.btn_air    = self._opt_btn("In Free Air")
        self.btn_buried = self._opt_btn("Direct Buried in Ground")
        self.btn_duct   = self._opt_btn("Buried in Conduit / Duct")
        q_layout.addLayout(self._q_block(
            "Q3 · INSTALLATION", "How will cable be installed?",
            [self.btn_air, self.btn_buried, self.btn_duct]))
        for btn, val in [(self.btn_air,'air'),
                         (self.btn_buried,'buried'),
                         (self.btn_duct,'duct')]:
            btn.clicked.connect(lambda checked, v=val: self._sel_method(v))

        # Q4 container
        self.q4_container = QVBoxLayout()
        q_layout.addLayout(self.q4_container)
        self.q4_buttons = {}

        # Sizing mode toggle — Auto / Manual
        mode_sep = QFrame(); mode_sep.setFrameShape(QFrame.Shape.HLine)
        mode_sep.setStyleSheet("color:#d0d0d0;")
        q_layout.addWidget(mode_sep)

        mode_lbl = QLabel("SIZING MODE")
        mode_lbl.setStyleSheet(
            "font-size:8pt;color:#1a3a5c;letter-spacing:1.5px;"
            "font-weight:bold;text-transform:uppercase;")
        q_layout.addWidget(mode_lbl)

        mode_row = QHBoxLayout(); mode_row.setSpacing(6)
        self.btn_mode_auto   = QPushButton("⚡  Auto")
        self.btn_mode_manual = QPushButton("🔒  Manual")
        for btn in (self.btn_mode_auto, self.btn_mode_manual):
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton{background:#f0f4f8;border:1px solid #b0b8c0;"
                "color:#1a3a5c;font-size:9pt;padding:6px;font-weight:bold;}"
                "QPushButton:checked{background:#1a3a5c;color:#ffffff;"
                "border:1px solid #1a3a5c;}"
                "QPushButton:hover:!checked{background:#e0e8f0;}")
        self.btn_mode_auto.setChecked(not self.cable.manual_sizing)
        self.btn_mode_manual.setChecked(self.cable.manual_sizing)
        self.btn_mode_auto.clicked.connect(lambda: self._set_sizing_mode('auto'))
        self.btn_mode_manual.clicked.connect(lambda: self._set_sizing_mode('manual'))
        mode_row.addWidget(self.btn_mode_auto)
        mode_row.addWidget(self.btn_mode_manual)
        q_layout.addLayout(mode_row)

        self._mode_hint = QLabel(
            "Click a cable in the table\nto lock manual selection." if self.cable.manual_sizing
            else "Auto selects the smallest\ncable that passes all checks.")
        self._mode_hint.setStyleSheet("font-size:8pt;color:#555555;padding:2px 0;")
        self._mode_hint.setWordWrap(True)
        q_layout.addWidget(self._mode_hint)

        q_layout.addStretch()
        q_scroll.setWidget(q_widget)
        layout.addWidget(q_scroll, 1)

        # Bottom buttons
        btn_bar = QWidget()
        btn_bar.setStyleSheet(
            "background:#f5f5f5;border-top:1px solid #d0d0d0;")
        bbl = QVBoxLayout(btn_bar)
        bbl.setContentsMargins(12, 10, 12, 10); bbl.setSpacing(6)

        if self._embedded:
            # PROCEED — primary action in embedded mode
            self.proceed_btn = QPushButton("PROCEED — Use This Cable")
            self.proceed_btn.setStyleSheet(
                "background:#107c10;color:#ffffff;font-size:10pt;"
                "font-weight:bold;padding:10px;border:none;letter-spacing:1px;")
            self.proceed_btn.clicked.connect(self._on_proceed_clicked)
            self.proceed_btn.setCursor(Qt.PointingHandCursor)
            bbl.addWidget(self.proceed_btn)

            cancel_btn = QPushButton("Cancel")
            cancel_btn.setStyleSheet(
                "background:#f0f0f0;border:1px solid #c0c0c0;"
                "color:#444;font-size:9pt;padding:6px;")
            cancel_btn.clicked.connect(self.close)
            bbl.addWidget(cancel_btn)
        else:
            # Standalone mode buttons
            calc_btn = QPushButton("Open Calculator")
            calc_btn.setStyleSheet(
                "background:#f0a500;color:#000;font-size:9pt;"
                "font-weight:bold;padding:8px;border:none;letter-spacing:1px;")
            calc_btn.clicked.connect(self._open_calculator)
            bbl.addWidget(calc_btn)

            row1 = QHBoxLayout()
            for label, slot in [("Save", self._save),
                                 ("Load", self._load),
                                 ("Save As", self._save_as)]:
                b = QPushButton(label)
                b.setStyleSheet(
                    "background:#f5f5f5;border:1px solid #d0d0d0;"
                    "color:#555555;font-size:9pt;padding:6px;")
                b.clicked.connect(slot)
                row1.addWidget(b)
            bbl.addLayout(row1)

            row2 = QHBoxLayout()
            pr_btn = QPushButton("Print")
            pr_btn.setStyleSheet(
                "background:#f0f0f0;border:1px solid #c0c0c0;"
                "color:#444;font-size:9pt;padding:6px;")
            pr_btn.clicked.connect(self._print)
            reset_btn = QPushButton("Reset")
            reset_btn.setStyleSheet(
                "background:#f0f0f0;border:1px solid #c0c0c0;"
                "color:#c42b1c;font-size:9pt;padding:6px;")
            reset_btn.clicked.connect(self._reset)
            row2.addWidget(pr_btn); row2.addWidget(reset_btn)
            bbl.addLayout(row2)

        layout.addWidget(btn_bar)
        self._set_q_enabled(False, False, False)
        return sb

    # ─────────────────────────────────────────────────────────────────────────
    def _q_block(self, label, title, buttons):
        layout = QVBoxLayout(); layout.setSpacing(5)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            "font-size:8pt;color:#1a3a5c;letter-spacing:1.5px;"
            "font-weight:bold;text-transform:uppercase;")
        ttl = QLabel(title)
        ttl.setStyleSheet("font-size:9pt;color:#555555;")
        layout.addWidget(lbl); layout.addWidget(ttl)
        for btn in buttons: layout.addWidget(btn)
        return layout

    def _opt_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{background:#f5f5f5;border:1px solid #c0c0c0;"
            "color:#1a1a1a;font-size:9pt;font-weight:600;padding:7px 10px;text-align:left;}"
            "QPushButton:hover{border-color:#1a3a5c;color:#1a3a5c;background:#eef2f7;}"
            "QPushButton:checked{background:#d4edda;border-color:#107c10;color:#107c10;}")
        return btn

    def _set_q_enabled(self, q2, q3, q4):
        for btn in [self.btn_1c,self.btn_2c,self.btn_3c,self.btn_4c]:
            btn.setEnabled(q2)
        for btn in [self.btn_air,self.btn_buried,self.btn_duct]:
            btn.setEnabled(q3)

    def _clear_group(self, buttons):
        for b in buttons: b.setChecked(False)

    # ─────────────────────────────────────────────────────────────────────────
    # SELECTIONS
    # ─────────────────────────────────────────────────────────────────────────

    def _sel_insulation(self, val):
        self.cable.insulation = val
        self._clear_group([self.btn_pvc, self.btn_xlpe])
        (self.btn_pvc if val=='PVC' else self.btn_xlpe).setChecked(True)
        self.cable.core_config = '1C'
        self.cable.install_method = 'air'
        self.cable.arrangement = 'e'
        self._clear_group([self.btn_1c,self.btn_2c,self.btn_3c,self.btn_4c])
        self._clear_group([self.btn_air,self.btn_buried,self.btn_duct])
        self._clear_q4()
        self._set_q_enabled(True, False, False)
        self._show_placeholder()

    def _sel_core(self, val):
        self.cable.core_config = val
        self._clear_group([self.btn_1c,self.btn_2c,self.btn_3c,self.btn_4c])
        {'1C':self.btn_1c,'2C':self.btn_2c,
         '3C':self.btn_3c,'4C':self.btn_4c}[val].setChecked(True)
        self._clear_group([self.btn_air,self.btn_buried,self.btn_duct])
        self._clear_q4()
        self._set_q_enabled(True, True, False)
        self._show_placeholder()

    def _sel_method(self, val):
        self.cable.install_method = val
        self._clear_group([self.btn_air,self.btn_buried,self.btn_duct])
        {'air':self.btn_air,'buried':self.btn_buried,
         'duct':self.btn_duct}[val].setChecked(True)
        self._clear_q4()
        if self.cable.core_config == '1C':
            self._build_q4(val)
        else:
            self._run_and_display()

    def _build_q4(self, method):
        self._clear_q4()
        lbl = QLabel("Q4 · ARRANGEMENT")
        lbl.setStyleSheet(
            "font-size:8pt;color:#1a3a5c;letter-spacing:1.5px;"
            "font-weight:bold;text-transform:uppercase;")
        ttl = QLabel({'buried':'Direct buried arrangement:',
                      'duct':'Buried in duct arrangement:',
                      'air':'Free air arrangement:'}[method])
        ttl.setStyleSheet("font-size:9pt;color:#555555;")
        self.q4_container.addWidget(lbl)
        self.q4_container.addWidget(ttl)
        options = {
            'buried': [('a','Fig.(a) Trefoil'),('b','Fig.(b) Flat Touched')],
            'duct':   [('c','Fig.(c) Trefoil'),('d','Fig.(d) Flat Touched')],
            'air':    [('e','Fig.(e) Trefoil ≥0.5Dₑ'),
                       ('f','Fig.(f) Flat Touched'),
                       ('g','Fig.(g) Flat Spaced ≥0.5Dₑ')],
        }[method]
        self.q4_buttons = {}
        for val, label in options:
            btn = self._opt_btn(label)
            btn.clicked.connect(lambda checked, v=val: self._sel_arrangement(v))
            self.q4_container.addWidget(btn)
            self.q4_buttons[val] = btn

    def _clear_q4(self):
        while self.q4_container.count():
            item = self.q4_container.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.q4_buttons = {}

    def _sel_arrangement(self, val):
        self.cable.arrangement = val
        for k, btn in self.q4_buttons.items():
            btn.setChecked(k == val)
        self._run_and_display()

    # ─────────────────────────────────────────────────────────────────────────
    # RUN + DISPLAY
    # ─────────────────────────────────────────────────────────────────────────

    def _run_and_display(self):
        ok, errs = self.cable.is_valid_selection()
        if not ok:
            self._show_placeholder("\n".join(errs))
            return
        self.cable.calculate_derating()
        self._show_results()

    def _show_placeholder(self, msg=''):
        self._clear_content()
        text = msg if msg else "Make selections to filter catalogue"
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "color:#555555;font-size:10pt;letter-spacing:1px;padding:60px;")
        self.content_layout.addWidget(lbl)

    def _set_sizing_mode(self, mode: str):
        """Switch between 'auto' and 'manual' sizing modes."""
        is_manual = (mode == 'manual')
        self.cable.manual_sizing = is_manual
        self.btn_mode_auto.setChecked(not is_manual)
        self.btn_mode_manual.setChecked(is_manual)
        if is_manual:
            self._mode_hint.setText(
                "Click a cable in the table\nto lock manual selection.")
        else:
            self.cable.manual_sizing = False
            # Re-run auto selection so recommended updates immediately
            if self.cable.conductor_table:
                self.cable.calculate_load()
            self._mode_hint.setText(
                "Auto selects the smallest\ncable that passes all checks.")
        if hasattr(self, 'cat_view'):
            self.cat_view.refresh(self.cable)

    def _on_manual_row_selected(self, conductor_row):
        """User clicked a row in the catalogue while in Manual mode."""
        self.cable.recommended = conductor_row
        if hasattr(self, 'cat_view'):
            self.cat_view.refresh(self.cable)

    def _show_results(self):
        self._clear_content()
        self.cat_view = CatalogueView(self.cable)
        self.cat_view.row_selected.connect(self._on_manual_row_selected)
        self.content_layout.addWidget(self.cat_view)
        self.k_view = KFactorView(self.cable)
        self.k_view.k_changed.connect(self._on_k_changed)
        self.content_layout.addWidget(self.k_view)

    def _on_k_changed(self):
        if hasattr(self, 'cat_view'):
            self.cat_view.refresh(self.cable)

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    # ─────────────────────────────────────────────────────────────────────────
    # PROCEED (embedded mode)
    # ─────────────────────────────────────────────────────────────────────────

    def _on_proceed_clicked(self):
        if not self.cable.conductor_table:
            QMessageBox.warning(self, "Incomplete",
                "Please complete all selections (Q1–Q4) and verify k-factors before proceeding.")
            return
        if self.cable.k <= 0:
            QMessageBox.warning(self, "Incomplete",
                "k factor is not calculated. Please complete derating inputs.")
            return
        if self._on_proceed:
            self._on_proceed(self.cable)
        self.close()

    # ─────────────────────────────────────────────────────────────────────────
    # CALCULATOR (standalone only)
    # ─────────────────────────────────────────────────────────────────────────

    def _open_calculator(self):
        if not self.cable.conductor_table:
            QMessageBox.warning(self, "No Data",
                "Please complete cable selection first.")
            return
        dlg = CalculatorView(self.cable, self)
        dlg.exec()

    # ─────────────────────────────────────────────────────────────────────────
    # FILE OPS
    # ─────────────────────────────────────────────────────────────────────────

    def _save(self):
        if not self._current_file:
            self._save_as(); return
        self.cable.save(self._current_file)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "", "Cable Session (*.acc);;All Files (*)")
        if path:
            if not path.endswith('.acc'): path += '.acc'
            self._current_file = path
            self.cable.save(path)
            self.setWindowTitle(f"VoltFlow Cable Selector — {path}")

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "", "Cable Session (*.acc);;All Files (*)")
        if path:
            try:
                self.cable = C_Cable.load(path)
                self._current_file = path
                self._restore_ui_from_cable()
                if self.cable.conductor_table:
                    self._show_results()
            except Exception as e:
                QMessageBox.critical(self, "Load Error", str(e))

    def _restore_ui_from_cable(self):
        c = self.cable
        self._clear_group([self.btn_pvc, self.btn_xlpe])
        (self.btn_pvc if c.insulation=='PVC' else self.btn_xlpe).setChecked(True)
        self._set_q_enabled(True, False, False)
        self._clear_group([self.btn_1c,self.btn_2c,self.btn_3c,self.btn_4c])
        {'1C':self.btn_1c,'2C':self.btn_2c,
         '3C':self.btn_3c,'4C':self.btn_4c}[c.core_config].setChecked(True)
        self._set_q_enabled(True, True, False)
        self._clear_group([self.btn_air,self.btn_buried,self.btn_duct])
        {'air':self.btn_air,'buried':self.btn_buried,
         'duct':self.btn_duct}[c.install_method].setChecked(True)
        self._clear_q4()
        if c.core_config == '1C':
            self._build_q4(c.install_method)
            if c.arrangement in self.q4_buttons:
                self.q4_buttons[c.arrangement].setChecked(True)

    def _print(self):
        if not self.cable.conductor_table:
            QMessageBox.warning(self, "Nothing to Print", "Complete selection first.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QPrintDialog.Accepted:
            doc = QTextDocument()
            doc.setHtml(self._build_print_html())
            doc.print_(printer)

    def _build_print_html(self) -> str:
        c = self.cable
        rows_html = ""
        for r in c.conductor_table:
            x_str = f"{r.X:.3f}" if r.X is not None else "N/A"
            z_str = f"{r.Z:.3f}" if r.Z is not None else "N/A"
            rows_html += (
                f"<tr><td>{r.size_mm2}</td><td>{r.shape}</td>"
                f"<td>{r.dc20:.4f}</td><td>{r.ac70:.4f}</td><td>{r.ac90:.4f}</td>"
                f"<td><b>{r.In}</b></td><td>{x_str}</td><td>{z_str}</td>"
                f"<td>{r.diameter}</td><td>{r.weight}</td>"
                f"<td style='font-family:monospace;font-size:10px'>{r.cable_code}</td></tr>"
            )
        return f"""<html><body style='font-family:Arial;font-size:12px'>
        <h2>VoltFlow — LV Power Cables · KSA 60 Hz</h2>
        <p><b>CU / {c.insulation} / PVC · 0.6/1 kV</b> &nbsp;|&nbsp;
           {c.core_config} &nbsp;|&nbsp;
           {c.install_method.upper()}</p>
        <p>k1={c.k1:.3f} × k2={c.k2:.3f} × k3={c.k3:.3f} = <b>k={c.k:.3f}</b></p>
        <hr>
        <table border='1' cellpadding='4' cellspacing='0'
               style='border-collapse:collapse;width:100%'>
        <tr style='background:#ddd'>
          <th>mm²</th><th>Shape</th><th>DC20</th><th>AC70</th><th>AC90</th>
          <th>Iₙ(A)</th><th>X Ω/km</th><th>Z Ω/km</th>
          <th>Ø mm</th><th>kg/km</th><th>Cable Code</th>
        </tr>
        {rows_html}
        </table>
        <p style='font-size:10px;color:#666;margin-top:12px'>
        Laying Conditions: Ambient air 40°C · Ground 35°C ·
        Soil resistivity 1.5 K·m/W · Depth 0.5m</p>
        </body></html>"""

    def _reset(self):
        self.cable = C_Cable()
        self._current_file = None
        self.setWindowTitle("VoltFlow Cable Selector — KSA LV Power Cables")
        self._clear_group([self.btn_pvc, self.btn_xlpe])
        self._clear_group([self.btn_1c,self.btn_2c,self.btn_3c,self.btn_4c])
        self._clear_group([self.btn_air,self.btn_buried,self.btn_duct])
        self._clear_q4()
        self._set_q_enabled(False, False, False)
        self._show_placeholder()
