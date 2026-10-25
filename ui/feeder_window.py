# ui/feeder_window.py
import sys, os
_HERE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
_CABLE = os.path.join(_HERE, 'VSEngCableSelector')
if _HERE in sys.path:
    sys.path.remove(_HERE)
sys.path.insert(0, _HERE)
if _CABLE not in sys.path:
    sys.path.insert(1, _CABLE)

from PySide6.QtWidgets import (
    QDialog, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QDoubleSpinBox, QSpinBox,
    QComboBox, QFrame, QScrollArea, QGroupBox, QRadioButton,
    QButtonGroup, QCheckBox, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtGui import QTextDocument

from feeder_class import C_Feeder
from cb_class import (C_CB, CB_TYPES, CB_STANDARDS, TRIP_CURVES,
                      IEC_MCB_SIZES, IEC_MCCB_SIZES, IEC_ACB_SIZES,
                      MCB_ICU, MCCB_ICU, ACB_ICU, DIVERSITY_STEPS)
from VSEngCableSelector.cable_class import C_Cable


class FeederWindow(QDialog):
    """
    Feeder editor dialog.
    Can be opened standalone or from SwitchboardWindow.
    Emits feeder_saved(C_Feeder) when user saves/confirms.
    """
    feeder_saved = Signal(object)   # C_Feeder

    def __init__(self, feeder: C_Feeder = None,
                 Isc_board_kA: float = 0.0,
                 min_conductor_mm2: float = 1.5,
                 parent=None):
        super().__init__(parent)
        self._feeder = feeder if feeder else C_Feeder()
        self._Isc_board_kA = Isc_board_kA
        self._min_conductor_mm2 = min_conductor_mm2
        self.setWindowTitle(f"Feeder — {self._feeder.name}")
        self.setMinimumSize(980, 760)
        # Apply comprehensive light theme directly — overrides any inherited dark styles
        self.setStyleSheet("""
            QDialog, QWidget { background-color: #f5f5f5; color: #1a1a1a; }
            QLineEdit {
                background: #ffffff; color: #1a1a1a;
                border: 1px solid #c0c0c0; border-radius: 2px;
                padding: 5px 8px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #0078d4; background: #f0f8ff; }
            QDoubleSpinBox, QSpinBox {
                background: #ffffff; color: #1a1a1a;
                border: 1px solid #c0c0c0; border-radius: 2px;
                padding: 4px 6px; font-size: 12px;
            }
            QDoubleSpinBox:focus, QSpinBox:focus { border-color: #0078d4; }
            QDoubleSpinBox::up-button, QSpinBox::up-button,
            QDoubleSpinBox::down-button, QSpinBox::down-button {
                background: #f0f0f0; border-left: 1px solid #c0c0c0; width: 16px;
            }
            QComboBox {
                background: #ffffff; color: #1a1a1a;
                border: 1px solid #c0c0c0; border-radius: 2px;
                padding: 4px 8px; font-size: 12px;
            }
            QComboBox:focus { border-color: #0078d4; }
            QComboBox::drop-down { border-left: 1px solid #d0d0d0; width: 20px; background: #f0f0f0; }
            QComboBox QAbstractItemView {
                background: #ffffff; color: #1a1a1a;
                selection-background-color: #cce4ff; border: 1px solid #0078d4;
            }
            QGroupBox {
                background: #ffffff; border: 1px solid #d0d0d0;
                border-radius: 3px; margin-top: 10px; padding: 8px 6px 6px 6px;
            }
            QGroupBox::title {
                color: #f0a500; font-weight: bold; font-size: 11px;
                letter-spacing: 2px; text-transform: uppercase;
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 4px; left: 8px;
            }
            QLabel { color: #1a1a1a; background: transparent; }
            QPushButton {
                background: #e8e8e8; border: 1px solid #b0b0b0;
                border-radius: 2px; padding: 4px 12px; color: #1a1a1a;
            }
            QPushButton:hover { background: #d0e4f8; border-color: #0078d4; color: #0078d4; }
            QPushButton:checked { background: #d0ecd0; border-color: #107c10; color: #107c10; }
            QRadioButton { color: #1a1a1a; background: transparent; }
            QCheckBox { color: #1a1a1a; background: transparent; }
            QScrollArea { background: #f5f5f5; border: none; }
            QScrollBar:vertical { background: #f0f0f0; width: 10px; border: none; }
            QScrollBar::handle:vertical { background: #c0c0c0; border-radius: 5px; min-height: 20px; }
            QScrollBar::handle:vertical:hover { background: #0078d4; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._power_mode = 'P+PF'
        self._build_ui()
        self._sb_P.valueChanged.connect(
            lambda v: self._power_spin_changed('P', v))
        self._sb_S.valueChanged.connect(
            lambda v: self._power_spin_changed('S', v))
        self._sb_PF.valueChanged.connect(
            lambda v: self._power_spin_changed('PF', v))
        self._sync_from_feeder()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # stylesheet set in __init__
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Header
        root.addWidget(self._build_header())

        # Scrollable body
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 20); bl.setSpacing(16)

        bl.addWidget(self._build_identity_panel())
        bl.addWidget(self._build_circuit_panel())
        bl.addWidget(self._build_cb_panel())
        bl.addWidget(self._build_cable_panel())

        # Calculate button
        calc_btn = QPushButton("⚡  CALCULATE FEEDER")
        calc_btn.setStyleSheet(
            "background:#f0a500;color:#000;font-size:14px;"
            "font-weight:bold;padding:13px;border:none;letter-spacing:1px;")
        calc_btn.clicked.connect(self._calculate)
        calc_btn.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(); hl.addStretch()
        hl.addWidget(calc_btn); hl.addStretch()
        bl.addLayout(hl)

        # Result panel
        self._result_panel = self._build_result_panel()
        self._result_panel.hide()
        bl.addWidget(self._result_panel)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        root.addWidget(self._build_bottom_bar())

    # ─────────────────────────────────────────────────────────────────────────
    # HEADER
    # ─────────────────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setStyleSheet("background:#1a3a5c;border-bottom:2px solid #f0a500;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 12, 20, 12)
        logo = QLabel("VoltFlow")
        logo.setStyleSheet(
            "background:#f0a500;color:#000;font-size:16px;"
            "font-weight:bold;padding:4px 12px;letter-spacing:2px;")
        t1 = QLabel("FEEDER")
        t1.setStyleSheet(
            "font-size:20px;font-weight:bold;letter-spacing:3px;color:#e6edf3;")
        t2 = QLabel("Cable sizing & circuit breaker selection")
        t2.setStyleSheet("font-size:11px;color:#7d8590;letter-spacing:1px;")
        tb = QVBoxLayout(); tb.setSpacing(2)
        tb.addWidget(t1); tb.addWidget(t2)
        hl.addWidget(logo); hl.addLayout(tb); hl.addStretch()
        if self._Isc_board_kA > 0:
            isc_badge = QLabel(f"Isc Board: {self._Isc_board_kA:.2f} kA")
            isc_badge.setStyleSheet(
                "background:#1a2030;color:#f0a500;font-size:12px;"
                "font-family:'Courier New';padding:6px 14px;border:1px solid #d0d0d0;background:#f0f8ff;color:#003d8f;")
            hl.addWidget(isc_badge)
        return hdr

    # ─────────────────────────────────────────────────────────────────────────
    # IDENTITY PANEL
    # ─────────────────────────────────────────────────────────────────────────

    def _build_identity_panel(self) -> QWidget:
        panel, pl = self._panel("FEEDER IDENTITY")
        row = QHBoxLayout(); row.setSpacing(20)

        for label, attr in [
            ("Circuit Ref:", 'circuit_ref'),
            ("Feeder Name:", 'name'),
            ("Load Description:", 'load_description'),
            ("Destination Panel:", 'panel_ref'),
        ]:
            col = QVBoxLayout(); col.setSpacing(4)
            col.addWidget(self._flabel(label))
            le = QLineEdit()
            le.setStyleSheet(self._input_style())
            le.setObjectName(attr)
            col.addWidget(le)
            row.addLayout(col)

        pl.addLayout(row)
        return panel

    # ─────────────────────────────────────────────────────────────────────────
    # CIRCUIT PARAMETERS PANEL
    # ─────────────────────────────────────────────────────────────────────────

    def _build_circuit_panel(self) -> QWidget:
        panel, pl = self._panel("CIRCUIT PARAMETERS")

        # Row 1: Phases, Voltage, Length, Vdrop, Neutral
        r1 = QHBoxLayout(); r1.setSpacing(20)

        # Phases
        ph_col = QVBoxLayout(); ph_col.setSpacing(6)
        ph_col.addWidget(self._flabel("System phases:"))
        ph_row = QHBoxLayout(); ph_row.setSpacing(6)
        self._btn_1ph = self._sel_btn("1φ  Single Phase")
        self._btn_3ph = self._sel_btn("3φ  Three Phase")
        self._btn_1ph.clicked.connect(lambda: self._sel_phase(1))
        self._btn_3ph.clicked.connect(lambda: self._sel_phase(3))
        ph_row.addWidget(self._btn_1ph); ph_row.addWidget(self._btn_3ph)
        ph_row.addStretch()
        ph_col.addLayout(ph_row)
        r1.addLayout(ph_col)

        # Voltage
        v_col = QVBoxLayout(); v_col.setSpacing(4)
        v_col.addWidget(self._flabel("Voltage (V):"))
        self._sb_voltage = self._dspin(50, 35000, 400, 10)
        v_col.addWidget(self._with_unit(self._sb_voltage, "V"))
        r1.addLayout(v_col)

        # Length
        l_col = QVBoxLayout(); l_col.setSpacing(4)
        l_col.addWidget(self._flabel("Cable length (m):"))
        self._sb_length = self._dspin(1, 100000, 10, 1)
        l_col.addWidget(self._with_unit(self._sb_length, "m"))
        r1.addLayout(l_col)

        # Max Vdrop
        vd_col = QVBoxLayout(); vd_col.setSpacing(4)
        vd_col.addWidget(self._flabel("Max Vdrop (%):"))
        self._sb_vdrop = self._dspin(0.1, 20, 3.0, 0.5)
        vd_col.addWidget(self._with_unit(self._sb_vdrop, "%"))
        r1.addLayout(vd_col)

        # Neutral
        n_col = QVBoxLayout(); n_col.setSpacing(4)
        n_col.addWidget(self._flabel("Neutral switched:"))
        self._chk_neutral = QCheckBox("4P CB (with N)")
        self._chk_neutral.setStyleSheet("color:#1a1a1a;font-size:12px;")
        n_col.addWidget(self._chk_neutral)
        r1.addLayout(n_col)
        r1.addStretch()
        pl.addLayout(r1)

        self._add_sep(pl)

        # Row 2: P / S / PF with mode selection
        mode_lbl = QLabel("Power inputs — select which two you know:")
        mode_lbl.setStyleSheet(
            "font-size:11px;color:#7d8590;letter-spacing:1px;text-transform:uppercase;")
        pl.addWidget(mode_lbl)

        mode_row = QHBoxLayout(); mode_row.setSpacing(16)
        self._mode_bg = QButtonGroup(self)
        for i, (lbl, val) in enumerate([("P + PF","P+PF"),
                                         ("S + PF","S+PF"),
                                         ("P + S", "P+S")]):
            rb = QRadioButton(lbl)
            rb.setStyleSheet("color:#1a1a1a;font-size:12px;")
            rb.setProperty("mode", val)
            self._mode_bg.addButton(rb, i)
            mode_row.addWidget(rb)
            if i == 0: rb.setChecked(True)
        mode_row.addStretch()
        pl.addLayout(mode_row)
        self._mode_bg.buttonClicked.connect(self._on_mode_change)

        r2 = QHBoxLayout(); r2.setSpacing(20)

        p_col = QVBoxLayout(); p_col.setSpacing(4)
        p_col.addWidget(self._flabel("Active Power P (kW):"))
        self._sb_P = self._dspin(0, 100000, 0, 1)
        self._lbl_P_auto = QLabel("")
        self._lbl_P_auto.setStyleSheet("font-size:10px;color:#7d8590;font-style:italic;")
        p_col.addWidget(self._with_unit(self._sb_P, "kW"))
        p_col.addWidget(self._lbl_P_auto)
        r2.addLayout(p_col)

        s_col = QVBoxLayout(); s_col.setSpacing(4)
        s_col.addWidget(self._flabel("Apparent Power S (kVA):"))
        self._sb_S = self._dspin(0, 100000, 0, 1)
        self._lbl_S_auto = QLabel("")
        self._lbl_S_auto.setStyleSheet("font-size:10px;color:#7d8590;font-style:italic;")
        s_col.addWidget(self._with_unit(self._sb_S, "kVA"))
        s_col.addWidget(self._lbl_S_auto)
        r2.addLayout(s_col)

        pf_col = QVBoxLayout(); pf_col.setSpacing(4)
        pf_col.addWidget(self._flabel("Power Factor PF:"))
        self._sb_PF = self._dspin(0.01, 1.0, 0.9, 0.01)
        self._lbl_PF_auto = QLabel("")
        self._lbl_PF_auto.setStyleSheet("font-size:10px;color:#7d8590;font-style:italic;")
        pf_col.addWidget(self._with_unit(self._sb_PF, "—"))
        pf_col.addWidget(self._lbl_PF_auto)
        r2.addLayout(pf_col)
        r2.addStretch()
        pl.addLayout(r2)

        self._on_mode_change()
        return panel

    # ─────────────────────────────────────────────────────────────────────────
    # CB PANEL
    # ─────────────────────────────────────────────────────────────────────────

    def _build_cb_panel(self) -> QWidget:
        panel, pl = self._panel("CIRCUIT BREAKER PARAMETERS")

        # ── Sizing mode toggle ────────────────────────────────────────────────
        mode_row = QHBoxLayout(); mode_row.setSpacing(8)
        mode_row.addWidget(self._flabel("Sizing:"))
        self._cb_btn_auto   = QPushButton("⚡  Auto")
        self._cb_btn_manual = QPushButton("🔒  Manual")
        for btn in (self._cb_btn_auto, self._cb_btn_manual):
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton{background:#f0f4f8;border:1px solid #b0b8c0;"
                "color:#1a3a5c;font-size:9pt;padding:2px 12px;font-weight:bold;}"
                "QPushButton:checked{background:#1a3a5c;color:#ffffff;"
                "border:1px solid #1a3a5c;}"
                "QPushButton:hover:!checked{background:#e0e8f0;}")
        self._cb_btn_auto.setChecked(True)
        self._cb_btn_auto.clicked.connect(lambda: self._set_cb_mode(False))
        self._cb_btn_manual.clicked.connect(lambda: self._set_cb_mode(True))
        mode_row.addWidget(self._cb_btn_auto)
        mode_row.addWidget(self._cb_btn_manual)

        # Manual size picker (visible only in Manual mode)
        self._cb_size_lbl = self._flabel("Rating (A):")
        self._cb_size = QComboBox()
        self._cb_size.setStyleSheet(self._combo_style())
        self._cb_size.setMinimumWidth(90)
        mode_row.addSpacing(16)
        mode_row.addWidget(self._cb_size_lbl)
        mode_row.addWidget(self._cb_size)
        mode_row.addStretch()
        pl.addLayout(mode_row)

        # ── CB parameters row ─────────────────────────────────────────────────
        r1 = QHBoxLayout(); r1.setSpacing(20)

        # CB Type
        t_col = QVBoxLayout(); t_col.setSpacing(4)
        t_col.addWidget(self._flabel("CB Type:"))
        self._cb_type = QComboBox()
        self._cb_type.addItems(CB_TYPES)
        self._cb_type.setStyleSheet(self._combo_style())
        self._cb_type.currentTextChanged.connect(self._on_cb_type_change)
        t_col.addWidget(self._cb_type)
        r1.addLayout(t_col)

        # Standard
        std_col = QVBoxLayout(); std_col.setSpacing(4)
        std_col.addWidget(self._flabel("Standard:"))
        self._cb_std = QComboBox()
        self._cb_std.addItems(CB_STANDARDS)
        self._cb_std.setStyleSheet(self._combo_style())
        std_col.addWidget(self._cb_std)
        r1.addLayout(std_col)

        # Trip curve (MCB only)
        tc_col = QVBoxLayout(); tc_col.setSpacing(4)
        tc_col.addWidget(self._flabel("Trip Curve (MCB):"))
        self._cb_curve = QComboBox()
        self._cb_curve.addItems(TRIP_CURVES)
        self._cb_curve.setStyleSheet(self._combo_style())
        tc_col.addWidget(self._cb_curve)
        r1.addLayout(tc_col)

        # Icu
        icu_col = QVBoxLayout(); icu_col.setSpacing(4)
        icu_col.addWidget(self._flabel("Breaking capacity Icu (kA):"))
        self._sb_Icu = self._dspin(1, 200, 25, 1)
        icu_col.addWidget(self._with_unit(self._sb_Icu, "kA"))
        r1.addLayout(icu_col)

        # Diversity
        div_col = QVBoxLayout(); div_col.setSpacing(4)
        div_col.addWidget(self._flabel("Diversity factor:"))
        self._cb_div = QComboBox()
        for d in DIVERSITY_STEPS:
            self._cb_div.addItem(f"{int(d*100)}%", d)
        self._cb_div.setStyleSheet(self._combo_style())
        div_col.addWidget(self._cb_div)
        r1.addLayout(div_col)
        r1.addStretch()
        pl.addLayout(r1)

        self._set_cb_mode(False)   # start in Auto, hides size picker
        return panel

    def _set_cb_mode(self, manual: bool):
        self._cb_btn_auto.setChecked(not manual)
        self._cb_btn_manual.setChecked(manual)
        self._cb_size_lbl.setVisible(manual)
        self._cb_size.setVisible(manual)
        if manual:
            self._refresh_cb_sizes()

    def _refresh_cb_sizes(self):
        """Populate the manual size picker based on current CB type."""
        cb_type = self._cb_type.currentText()
        if cb_type == 'MCB':
            sizes = IEC_MCB_SIZES
        elif cb_type == 'ACB':
            sizes = IEC_ACB_SIZES
        else:
            sizes = IEC_MCCB_SIZES
        current = self._cb_size.currentData()
        self._cb_size.blockSignals(True)
        self._cb_size.clear()
        for s in sizes:
            self._cb_size.addItem(f"{int(s)} A", s)
        # restore previous selection if still in list
        if current is not None:
            for i in range(self._cb_size.count()):
                if self._cb_size.itemData(i) == current:
                    self._cb_size.setCurrentIndex(i)
                    break
        self._cb_size.blockSignals(False)

    # ─────────────────────────────────────────────────────────────────────────
    # CABLE PANEL
    # ─────────────────────────────────────────────────────────────────────────

    def _build_cable_panel(self) -> QWidget:
        panel, pl = self._panel("CABLE SELECTION")

        # Summary of selected cable
        self._cable_summary = QLabel("No cable selected — click 'Select Cable' to open Cable Selector.")
        self._cable_summary.setStyleSheet(
            "font-size:12px;color:#555;font-style:italic;"
            "padding:10px;background:#f8f8f8;border:1px solid #d0d0d0;")
        self._cable_summary.setWordWrap(True)
        pl.addWidget(self._cable_summary)

        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        sel_btn = QPushButton("🔌  Select Cable →")
        sel_btn.setStyleSheet(
            "background:#1a2030;border:1px solid #f0a500;color:#f0a500;"
            "font-size:13px;font-weight:bold;padding:10px 20px;letter-spacing:1px;")
        sel_btn.clicked.connect(self._open_cable_selector)
        sel_btn.setCursor(Qt.PointingHandCursor)
        btn_row.addWidget(sel_btn)
        btn_row.addStretch()
        pl.addLayout(btn_row)
        return panel

    # ─────────────────────────────────────────────────────────────────────────
    # RESULT PANEL
    # ─────────────────────────────────────────────────────────────────────────

    def _build_result_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(
            "background:#f0f8ff;border:1px solid #d0d0d0;"
            "border-left:3px solid #0078d4;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(20, 16, 20, 16); pl.setSpacing(12)

        title = QLabel("CALCULATION RESULTS")
        title.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#0078d4;"
            "letter-spacing:1px;padding-bottom:8px;border-bottom:1px solid #d0d0d0;")
        pl.addWidget(title)

        # Results grid
        grid = QHBoxLayout(); grid.setSpacing(40)

        left = QVBoxLayout(); left.setSpacing(8)
        self._r_Ib        = self._res_row(left, "Load Current  Ib")
        self._r_Ib_design = self._res_row(left, "Design Current  Ib × diversity")
        self._r_CB        = self._res_row(left, "Circuit Breaker  In_CB")
        self._r_prot      = self._res_row(left, "Protection  Ib ≤ In_CB ≤ Iz")
        grid.addLayout(left)

        right = QVBoxLayout(); right.setSpacing(8)
        self._r_conductor = self._res_row(right, "Recommended Conductor")
        self._r_Iz        = self._res_row(right, "Derated Ampacity  Iz = Iₙ × k")
        self._r_vdrop     = self._res_row(right, "Voltage Drop")
        self._r_Isc_end   = self._res_row(right, "Isc at Load End")
        grid.addLayout(right)
        pl.addLayout(grid)

        # Warnings
        self._warn_lbl = QLabel("")
        self._warn_lbl.setStyleSheet(
            "font-size:11px;color:#f0a500;padding:6px 10px;"
            "background:#1a1600;border-left:3px solid #f0a500;")
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.hide()
        pl.addWidget(self._warn_lbl)
        return panel

    def _res_row(self, layout: QVBoxLayout, label: str) -> QLabel:
        row = QHBoxLayout(); row.setSpacing(12)
        lk = QLabel(f"{label}:")
        lk.setStyleSheet("font-size:11px;color:#555;min-width:220px;")
        lv = QLabel("—")
        lv.setStyleSheet(
            "font-family:'Courier New';font-size:14px;"
            "color:#e6edf3;font-weight:bold;")
        row.addWidget(lk); row.addWidget(lv); row.addStretch()
        layout.addLayout(row)
        return lv

    # ─────────────────────────────────────────────────────────────────────────
    # BOTTOM BAR
    # ─────────────────────────────────────────────────────────────────────────

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            "background:#f0f0f0;border-top:1px solid #d0d0d0;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 8, 16, 8); bl.setSpacing(8)

        save_btn = QPushButton("💾  Save & Close")
        save_btn.setStyleSheet(
            "background:#107c10;color:#fff;font-weight:bold;"
            "padding:8px 18px;border:none;font-size:12px;")
        save_btn.clicked.connect(self._save_and_close)

        pr_btn = QPushButton("🖨  Print Report")
        pr_btn.setStyleSheet(self._action_btn_style())
        pr_btn.clicked.connect(self._print_report)

        close_btn = QPushButton("✕  Cancel")
        close_btn.setStyleSheet(self._action_btn_style())
        close_btn.clicked.connect(self.reject)

        bl.addStretch()
        bl.addWidget(save_btn)
        bl.addWidget(pr_btn)
        bl.addWidget(close_btn)
        return bar

    # ─────────────────────────────────────────────────────────────────────────
    # CABLE SELECTOR
    # ─────────────────────────────────────────────────────────────────────────

    def _open_cable_selector(self):
        """Open Cable Selector in embedded mode with Proceed callback.
        Only one instance allowed — brings existing to front if already open."""
        # If already open, bring to front
        if hasattr(self, '_selector') and self._selector is not None:
            try:
                self._selector.show()
                self._selector.raise_()
                self._selector.activateWindow()
                return
            except RuntimeError:
                self._selector = None  # window was deleted, open fresh

        from VSEngCableSelector.ui.main_window import MainWindow

        qss_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'theme', 'light.qss')

        def on_proceed(cable: C_Cable):
            from vdrop_settings import apply_feeder_cable_from_selector
            apply_feeder_cable_from_selector(self._feeder, cable)
            self._update_cable_summary()
            self._selector = None

        def on_close():
            self._selector = None

        self._selector = MainWindow(
            cable=self._feeder.cable,
            on_proceed=on_proceed,
            min_conductor_mm2=self._min_conductor_mm2,
            parent=self
        )
        self._selector.destroyed.connect(on_close)

        if os.path.exists(qss_path):
            with open(qss_path) as f_qss:
                self._selector.setStyleSheet(f_qss.read())

        self._selector.show()

    def _update_cable_summary(self):
        c = self._feeder.cable
        if c.conductor_table:
            arr_labels = {
                'a':'Trefoil Buried','b':'Flat Touched Buried',
                'c':'Trefoil Duct',  'd':'Flat Touched Duct',
                'e':'Trefoil Air',   'f':'Flat Touched Air',
                'g':'Flat Spaced Air',
            }
            arr = arr_labels.get(c.arrangement,'') if c.core_config=='1C' else ''
            self._cable_summary.setText(
                f"✔  {c.core_config} · CU/{c.insulation}/PVC · "
                f"{c.install_method.upper()} {arr}  ·  "
                f"k = {c.k:.3f}  ·  "
                f"{len(c.conductor_table)} conductor sizes available"
            )
            self._cable_summary.setStyleSheet(
                "font-size:12px;color:#3fb950;font-weight:bold;"
                "padding:10px;background:#f0fff0;border:1px solid #107c10;color:#107c10;font-weight:bold;")
        else:
            self._cable_summary.setText(
                "No cable selected — click 'Select Cable'.")
            self._cable_summary.setStyleSheet(
                "font-size:12px;color:#7d8590;font-style:italic;"
                "padding:10px;background:#f8f8f8;border:1px solid #d0d0d0;color:#555;font-style:italic;")

    # ─────────────────────────────────────────────────────────────────────────
    # CALCULATE
    # ─────────────────────────────────────────────────────────────────────────

    def _calculate(self):
        self._collect_inputs()
        ok, errs = self._feeder.is_valid()
        if not ok:
            QMessageBox.warning(self, "Input Error", "\n".join(errs))
            return

        self._feeder.calculate(self._Isc_board_kA)
        self._populate_results()
        self._result_panel.show()

    def _live_derive(self, mode, changed, val):
        """Auto-derive third of P/S/PF. mode captures which two are inputs."""
        try:
            # Read all current values regardless of enabled state
            P  = self._sb_P.value()
            S  = self._sb_S.value()
            PF = self._sb_PF.value()

            def set_S(v):
                self._sb_S.blockSignals(True)
                self._sb_S.setValue(round(v, 3))
                self._sb_S.blockSignals(False)
            def set_P(v):
                self._sb_P.blockSignals(True)
                self._sb_P.setValue(round(v, 3))
                self._sb_P.blockSignals(False)
            def set_PF(v):
                self._sb_PF.blockSignals(True)
                self._sb_PF.setValue(min(1.0, round(v, 3)))
                self._sb_PF.blockSignals(False)

            if mode == "P+PF":
                # P and PF are inputs → derive S
                if PF > 0: set_S(P / PF)
            elif mode == "S+PF":
                # S and PF are inputs → derive P
                set_P(S * PF)
            elif mode == "P+S":
                # P and S are inputs → derive PF
                if S > 0: set_PF(P / S)
        except (ZeroDivisionError, TypeError, ValueError):
            pass

    def _collect_inputs(self):
        f = self._feeder
        # Identity
        for attr in ['circuit_ref','name','load_description','panel_ref']:
            w = self.findChild(QLineEdit, attr)
            if w: setattr(f, attr, w.text())

        # Circuit
        f.phases       = 1 if self._btn_1ph.isChecked() else 3
        f.voltage      = self._sb_voltage.value()
        f.cable_length = self._sb_length.value()
        f.max_vdrop_pct = self._sb_vdrop.value()
        f.has_neutral   = self._chk_neutral.isChecked()

        mode = self._mode_bg.checkedButton().property("mode")
        if mode == "P+PF":
            f.P = self._sb_P.value() or None
            f.PF = self._sb_PF.value() or None
            f.S  = None
        elif mode == "S+PF":
            f.S  = self._sb_S.value() or None
            f.PF = self._sb_PF.value() or None
            f.P  = None
        elif mode == "P+S":
            f.P  = self._sb_P.value() or None
            f.S  = self._sb_S.value() or None
            f.PF = None

        # CB
        f.cb.cb_type    = self._cb_type.currentText()
        f.cb.standard   = self._cb_std.currentText()
        f.cb.trip_curve = self._cb_curve.currentText()
        f.cb.Icu_kA     = self._sb_Icu.value()
        f.cb.diversity  = self._cb_div.currentData()
        f.user_locked_cb = self._cb_btn_manual.isChecked()
        if f.user_locked_cb and self._cb_size.currentData() is not None:
            f.cb.In_CB = self._cb_size.currentData()

        # Cable params
        f.cable.phases       = f.phases
        f.cable.voltage      = f.voltage
        f.cable.cable_length = f.cable_length
        f.cable.max_vdrop_pct = f.max_vdrop_pct

    def _populate_results(self):
        f = self._feeder

        def set_val(lbl, text, ok=None):
            lbl.setText(text)
            if ok is True:
                lbl.setStyleSheet(
                    "font-family:'Courier New';font-size:14px;"
                    "color:#3fb950;font-weight:bold;")
            elif ok is False:
                lbl.setStyleSheet(
                    "font-family:'Courier New';font-size:14px;"
                    "color:#e05c00;font-weight:bold;")
            else:
                lbl.setStyleSheet(
                    "font-family:'Courier New';font-size:14px;"
                    "color:#e6edf3;font-weight:bold;")

        set_val(self._r_Ib, f"{f.Ib:.2f} A")
        set_val(self._r_Ib_design,
                f"{f.cb.Ib_design:.2f} A  (diversity {int(f.cb.diversity*100)}%)")
        set_val(self._r_CB,
                f"{f.cb.In_CB:.0f} A  {f.cb.cb_type}  "
                f"{f.cb.poles}P  Icu={f.cb.Icu_kA}kA",
                ok=f.cb.passes_protection and f.cb.passes_Isc)

        prot_str = ("✔ PASS" if f.cb.passes_protection else "✘ FAIL")
        isc_str  = (f"  |  Isc ✔ ({f.cb.Icu_kA}kA ≥ {self._Isc_board_kA:.1f}kA)"
                    if f.cb.passes_Isc and self._Isc_board_kA > 0
                    else (f"  |  Isc ✘ ({f.cb.Icu_kA}kA < {self._Isc_board_kA:.1f}kA)"
                          if not f.cb.passes_Isc and self._Isc_board_kA > 0 else ""))
        set_val(self._r_prot, prot_str + isc_str,
                ok=f.cb.passes_protection and f.cb.passes_Isc)

        rec = f.cable.recommended
        if rec:
            set_val(self._r_conductor,
                    f"{rec.size_mm2} mm²  {rec.cable_code}",
                    ok=f.cable.passes_ampacity)
            set_val(self._r_Iz,
                    f"{f.Iz:.1f} A  (Iₙ={rec.In}A × k={f.cable.k:.3f})",
                    ok=f.cable.passes_ampacity)
            vd_ok = f.cable.passes_vdrop
            set_val(self._r_vdrop,
                    f"{f.result_vdrop_pct:.3f}%  ({f.result_vdrop_v:.3f} V)  "
                    f"{'✔' if vd_ok else '✘'} (max {f.max_vdrop_pct}%)",
                    ok=vd_ok)
        else:
            set_val(self._r_conductor, "No conductor found", ok=False)

        if f.Isc_end_kA > 0:
            set_val(self._r_Isc_end, f"{f.Isc_end_kA:.3f} kA")
        else:
            set_val(self._r_Isc_end, "Isc source not defined")

        if f.warnings:
            self._warn_lbl.setText("\n".join(f.warnings))
            self._warn_lbl.show()
        else:
            self._warn_lbl.hide()

    # ─────────────────────────────────────────────────────────────────────────
    # SAVE + PRINT
    # ─────────────────────────────────────────────────────────────────────────

    def _save_and_close(self):
        self._collect_inputs()
        self.feeder_saved.emit(self._feeder)
        self.accept()

    def _print_report(self):
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QPrintDialog.Accepted:
            doc = QTextDocument()
            doc.setHtml(self._build_report_html())
            doc.print_(printer)

    def _build_report_html(self) -> str:
        f  = self._feeder
        cb = f.cb
        rec = f.cable.recommended
        c   = f.cable
        return f"""<html><body style='font-family:Arial;font-size:12px'>
        <h2>Feeder Calculation Report</h2>
        <h3>{f.circuit_ref} — {f.name}</h3>
        <p>{f.load_description}  |  Destination: {f.panel_ref}</p>
        <hr>
        <h3>Circuit Parameters</h3>
        <table border='1' cellpadding='4' style='border-collapse:collapse'>
        <tr><td><b>System</b></td><td>{f.phases}φ · {f.voltage}V</td></tr>
        <tr><td><b>P / S / PF</b></td>
            <td>{f.P} kW / {f.S} kVA / {f.PF}</td></tr>
        <tr><td><b>Load Current Ib</b></td><td>{f.Ib:.2f} A</td></tr>
        <tr><td><b>Design Current</b></td>
            <td>{cb.Ib_design:.2f} A (diversity {int(cb.diversity*100)}%)</td></tr>
        <tr><td><b>Cable Length</b></td><td>{f.cable_length} m</td></tr>
        <tr><td><b>Max Vdrop</b></td><td>{f.max_vdrop_pct} %</td></tr>
        </table>
        <h3>Cable</h3>
        <p>{c.core_config} · CU/{c.insulation}/PVC · {c.install_method.upper()} ·
           k={c.k:.3f}</p>
        {'<p>Recommended: <b>' + rec.cable_code + '</b>  ' +
          str(rec.size_mm2) + 'mm²  Iz=' + str(f.Iz) + 'A</p>' if rec else '<p>No conductor found</p>'}
        <h3>Circuit Breaker</h3>
        <table border='1' cellpadding='4' style='border-collapse:collapse'>
        <tr><td><b>Type</b></td><td>{cb.cb_type} {cb.poles}P</td></tr>
        <tr><td><b>Rated Current In</b></td><td>{cb.In_CB:.0f} A</td></tr>
        <tr><td><b>Breaking Capacity Icu</b></td><td>{cb.Icu_kA} kA</td></tr>
        <tr><td><b>Protection Check</b></td>
            <td style='color:{"green" if cb.passes_protection else "red"}'>
            {"PASS ✔" if cb.passes_protection else "FAIL ✘"}</td></tr>
        <tr><td><b>Isc Check</b></td>
            <td style='color:{"green" if cb.passes_Isc else "red"}'>
            {"PASS ✔" if cb.passes_Isc else "FAIL ✘"}</td></tr>
        </table>
        <h3>Voltage Drop</h3>
        <p>{f.result_vdrop_pct:.3f}%  ({f.result_vdrop_v:.3f} V)  
           {'PASS ✔' if f.cable.passes_vdrop else 'FAIL ✘'}</p>
        {'<h3>Warnings</h3><ul>' +
          ''.join(f'<li>{w}</li>' for w in f.warnings) + '</ul>'
          if f.warnings else ''}
        </body></html>"""

    # ─────────────────────────────────────────────────────────────────────────
    # SYNC FROM FEEDER OBJECT
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_from_feeder(self):
        f = self._feeder
        for attr in ['circuit_ref','name','load_description','panel_ref']:
            w = self.findChild(QLineEdit, attr)
            if w: w.setText(getattr(f, attr, ''))

        self._sel_phase(f.phases)
        self._sb_voltage.setValue(f.voltage)
        self._sb_length.setValue(f.cable_length)
        self._sb_vdrop.setValue(f.max_vdrop_pct)
        self._chk_neutral.setChecked(f.has_neutral)

        if f.P is not None:  self._sb_P.setValue(f.P)
        if f.S is not None:  self._sb_S.setValue(f.S)
        if f.PF is not None: self._sb_PF.setValue(f.PF)

        idx = self._cb_type.findText(f.cb.cb_type)
        if idx >= 0: self._cb_type.setCurrentIndex(idx)
        idx = self._cb_std.findText(f.cb.standard)
        if idx >= 0: self._cb_std.setCurrentIndex(idx)
        idx = self._cb_curve.findText(f.cb.trip_curve)
        if idx >= 0: self._cb_curve.setCurrentIndex(idx)
        self._sb_Icu.setValue(f.cb.Icu_kA)

        # Diversity
        for i in range(self._cb_div.count()):
            if abs(self._cb_div.itemData(i) - f.cb.diversity) < 0.01:
                self._cb_div.setCurrentIndex(i); break

        # CB sizing mode
        self._set_cb_mode(f.user_locked_cb)
        if f.user_locked_cb and f.cb.In_CB > 0:
            for i in range(self._cb_size.count()):
                if self._cb_size.itemData(i) == f.cb.In_CB:
                    self._cb_size.setCurrentIndex(i)
                    break

        self._update_cable_summary()

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _sel_phase(self, ph):
        self._btn_1ph.setChecked(ph == 1)
        self._btn_3ph.setChecked(ph == 3)
        self._chk_neutral.setEnabled(ph == 3)

    def _power_spin_changed(self, which: str, val: float) -> None:
        """Live P/S/PF derivation — inputs depend on selected power mode."""
        mode = getattr(self, '_power_mode', 'P+PF')
        if which == 'P' and 'P' not in mode:
            return
        if which == 'S' and 'S' not in mode:
            return
        if which == 'PF' and 'PF' not in mode:
            return
        self._live_derive(mode, which, val)

    def _on_mode_change(self):
        btn = self._mode_bg.checkedButton()
        if not btn:
            return
        mode = btn.property("mode")
        self._power_mode = mode
        self._sb_P.setEnabled("P" in mode)
        self._sb_S.setEnabled("S" in mode)
        self._sb_PF.setEnabled("PF" in mode)
        self._lbl_P_auto.setText("" if "P" in mode else "(auto-calculated)")
        self._lbl_S_auto.setText("" if "S" in mode else "(auto-calculated)")
        self._lbl_PF_auto.setText("" if "PF" in mode else "(auto-calculated)")

    def _on_cb_type_change(self, cb_type):
        is_mcb = cb_type == 'MCB'
        self._cb_curve.setEnabled(is_mcb)
        self._cb_std.setCurrentText('MCB' if is_mcb else 'MCCB')
        if self._cb_btn_manual.isChecked():
            self._refresh_cb_sizes()

    def _panel(self, title: str) -> tuple:
        panel = QWidget()
        panel.setStyleSheet("background:#ffffff;border:1px solid #d0d0d0;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 14, 16, 14); pl.setSpacing(12)
        t = QLabel(title)
        t.setStyleSheet(
            "font-size:13px;font-weight:bold;color:#f0a500;"
            "letter-spacing:2px;text-transform:uppercase;"
            "border-bottom:1px solid #d0d0d0;padding-bottom:8px;")
        pl.addWidget(t)
        return panel, pl

    def _flabel(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:11px;color:#7d8590;")
        return lbl

    def _input_style(self):
        return "font-size:12px;"

    def _combo_style(self):
        return "font-size:12px;"


    def _action_btn_style(self):
        return "font-size:12px;padding:7px 14px;"

    def _sel_btn(self, text):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "font-size:12px;font-weight:600;padding:8px 14px;")
        return btn

    def _dspin(self, mn, mx, default, step):
        sb = QDoubleSpinBox()
        sb.setRange(mn, mx); sb.setValue(default); sb.setSingleStep(step)
        sb.setDecimals(2 if step < 1 else 0)
        sb.setButtonSymbols(QDoubleSpinBox.NoButtons)
        sb.setMinimumWidth(90)
        return sb

    def _with_unit(self, widget, unit):
        w = QWidget()
        hl = QHBoxLayout(w); hl.setContentsMargins(0,0,0,0); hl.setSpacing(4)
        hl.addWidget(widget)
        lbl = QLabel(unit)
        lbl.setStyleSheet("font-size:11px;color:#7d8590;"
                          "font-family:'Courier New';")
        hl.addWidget(lbl); hl.addStretch()
        return w

    def _add_sep(self, layout):
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border:none;border-top:1px solid #d0d0d0;")
        layout.addWidget(sep)
