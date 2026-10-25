# ui/motor_circuit_sizing.py — Motor MOTOR + CIRCUIT BREAKER (inline in props bar)
# Feeder cable: standard CABLE section on the same row (Light/HVAC/Socket parity).
from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QDoubleSpinBox, QComboBox,
    QMessageBox, QSizePolicy, QHBoxLayout, QVBoxLayout, QGridLayout,
    QFrame, QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QLocale
from motor_class import (
    C_Motor, START_METHODS, DEFAULT_APPLICATION_PROFILE,
    PROFILE_LABELS, PD_TYPES, ISOLATOR_MODES,
)
from feeder_class import C_Feeder

_RES_SS = (
    'background:#f0f0f0;color:#5c2d91;font-weight:bold;'
    'border:1px solid #d0d0d0;padding:2px 4px;'
    'font-family:"Courier New";font-size:9pt;')
_RES_CB = (
    'color:#107c10;font-weight:bold;font-size:9pt;'
    'font-family:"Courier New";border:none;background:transparent;')


class MotorCircuitSizingPanel(QWidget):
    """Motor MOTOR + CB sections; cable stays in the shared CABLE section."""

    motor_applied = Signal(object)
    feeder_fields_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('motorCircuitSizingHost')
        self._feeder: C_Feeder | None = None
        self._row = -1
        self._board = None
        self._busy = False
        self._build_ui()
        self._init_controls()
        self._wire_signals()
        self.setEnabled(False)

    # ── UI (matches switchboard_window._mk_props sections) ───────────────────

    def _build_ui(self):
        self.setStyleSheet('background:#f5f5f5;border:none;')
        self.setMinimumHeight(125)
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)

        p_load, ll = self._mk_section(
            'MOTOR', '#003d8f', '#0078d4', '#c8daea', '#eef4fb')
        g = QGridLayout()
        g.setHorizontalSpacing(5)
        g.setVerticalSpacing(4)
        g.setColumnStretch(1, 1)

        def gl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet('font-size:9pt;color:#555;')
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lbl

        self._le_name = self._le()
        self._le_ref = self._le()
        self._le_ref.setFixedWidth(44)
        self._cb_profile = self._cb()

        g.addWidget(gl('Name'), 0, 0)
        g.addWidget(self._le_name, 0, 1)
        g.addWidget(gl('Ref'), 0, 2)
        g.addWidget(self._le_ref, 0, 3)
        g.addWidget(gl('Profile'), 0, 4)
        g.addWidget(self._cb_profile, 0, 5)

        self._sb_pn = self._sp(0.1, 5000, 15, 0.1, 2)
        self._sb_eta = self._sp(0.5, 1.0, 0.9, 0.01, 3)
        self._sb_sf = self._sp(1.0, 1.25, 1.0, 0.05, 2)
        g.addWidget(gl('Pn kW'), 1, 0)
        g.addWidget(self._sb_pn, 1, 1)
        g.addWidget(gl('η'), 1, 2)
        g.addWidget(self._sb_eta, 1, 3)
        g.addWidget(gl('SF'), 1, 4)
        g.addWidget(self._sb_sf, 1, 5)

        self._sb_pf = self._sp(0.5, 1.0, 0.85, 0.01, 3)
        self._sb_ist = self._sp(3, 12, 6.5, 0.1, 1)
        self._cb_ph = self._cb()
        g.addWidget(gl('cos φ'), 2, 0)
        g.addWidget(self._sb_pf, 2, 1)
        g.addWidget(gl('Ist/In'), 2, 2)
        g.addWidget(self._sb_ist, 2, 3)
        g.addWidget(gl('Ph'), 2, 4)
        g.addWidget(self._cb_ph, 2, 5)

        self._sb_len = self._sp(1, 5000, 10, 1, 0)
        self._sb_vd = self._sp(0.1, 20, 3, 0.5, 1)
        g.addWidget(gl('L[m]'), 3, 0)
        g.addWidget(self._sb_len, 3, 1)
        g.addWidget(gl('ΔU%'), 3, 2)
        g.addWidget(self._sb_vd, 3, 3)
        self._sb_df = self._sp(0, 100, 100, 1, 0)
        self._sb_df.setFixedWidth(56)
        g.addWidget(gl('D.F. %'), 3, 4)
        g.addWidget(self._sb_df, 3, 5)
        ll.addLayout(g)
        ll.addStretch()
        root.addWidget(p_load, 5)

        p_cb, cl = self._mk_section(
            'CIRCUIT BREAKER', '#107c10', '#107c10', '#b8ddb8', '#edf8ed')
        self._lbl_summary = QLabel('Motor: —')
        self._lbl_summary.setStyleSheet(_RES_CB)
        cl.addWidget(self._lbl_summary)

        cg = QGridLayout()
        cg.setHorizontalSpacing(5)
        cg.setVerticalSpacing(4)
        self._cb_start = self._cb()
        self._lbl_starter = self._result_lbl()
        self._cb_pd = self._cb()
        self._lbl_pd = self._result_lbl()
        self._cb_iso = self._cb()
        self._lbl_iso = self._result_lbl()
        cg.addWidget(gl('Start'), 0, 0)
        cg.addWidget(self._cb_start, 0, 1)
        cg.addWidget(self._lbl_starter, 0, 2, 1, 4)
        cg.addWidget(gl('CB'), 1, 0)
        cg.addWidget(self._cb_pd, 1, 1)
        cg.addWidget(self._lbl_pd, 1, 2, 1, 4)
        cg.addWidget(gl('Isolator'), 2, 0)
        cg.addWidget(self._cb_iso, 2, 1)
        cg.addWidget(self._lbl_iso, 2, 2, 1, 4)
        cl.addLayout(cg)

        row_btn = QHBoxLayout()
        row_btn.addStretch()
        self._btn_calc = QPushButton('Calculate Motor')
        self._btn_calc.setStyleSheet(
            'QPushButton{background:#107c10;color:#fff;border:none;'
            'font-weight:bold;padding:4px 12px;font-size:9pt;}'
            'QPushButton:hover{background:#0a5e0a;}')
        self._btn_calc.setFixedHeight(24)
        row_btn.addWidget(self._btn_calc)
        cl.addLayout(row_btn)
        self._p_stat = QLabel('Select a Motor row, then Calculate')
        self._p_stat.setStyleSheet(
            'color:#888;font-size:8pt;font-style:italic;'
            'border:none;background:transparent;')
        self._p_stat.setWordWrap(True)
        cl.addWidget(self._p_stat)
        cl.addStretch()
        root.addWidget(p_cb, 4)

    @staticmethod
    def _mk_section(title, txt_color, line_color, border_col, bg_col):
        frm = QFrame()
        frm.setStyleSheet(
            f'QFrame{{border:1px solid {border_col};'
            f'border-radius:3px;background:{bg_col};}}')
        outer = QVBoxLayout(frm)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        hdr_strip = QWidget()
        hdr_strip.setFixedHeight(20)
        hdr_strip.setStyleSheet(
            f'background:transparent;border:none;'
            f'border-bottom:2px solid {line_color};')
        hs = QHBoxLayout(hdr_strip)
        hs.setContentsMargins(8, 1, 8, 1)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f'font-size:9pt;font-weight:bold;color:{txt_color};'
            f'letter-spacing:2px;border:none;background:transparent;')
        hs.addWidget(lbl)
        hs.addStretch()
        outer.addWidget(hdr_strip)
        content = QWidget()
        content.setStyleSheet('background:transparent;border:none;')
        cl = QVBoxLayout(content)
        cl.setContentsMargins(8, 5, 8, 4)
        cl.setSpacing(4)
        outer.addWidget(content, 1)
        return frm, cl

    @staticmethod
    def _le():
        w = QLineEdit()
        w.setStyleSheet(
            'background:#fff;border:1px solid #c0c0c0;'
            'border-radius:2px;padding:2px 4px;font-size:9pt;')
        return w

    @staticmethod
    def _cb():
        w = QComboBox()
        w.setStyleSheet(
            'background:#fff;border:1px solid #c0c0c0;'
            'border-radius:2px;padding:2px 4px;font-size:9pt;')
        return w

    @staticmethod
    def _sp(mn, mx, default, step, decimals):
        w = QDoubleSpinBox()
        w.setRange(mn, mx)
        w.setValue(default)
        w.setSingleStep(step)
        w.setDecimals(decimals)
        w.setButtonSymbols(QDoubleSpinBox.NoButtons)
        w.setKeyboardTracking(True)
        # Force '.' decimal separator (avoids locale comma blocking "0.4" on Windows).
        w.setLocale(QLocale(QLocale.Language.C))
        w.setFixedWidth(72)
        w.setStyleSheet(
            'background:#fff;border:1px solid #c0c0c0;'
            'border-radius:2px;padding:2px 4px;font-size:9pt;')
        return w

    @staticmethod
    def _ro(text, width):
        w = QLineEdit(text)
        w.setReadOnly(True)
        w.setFixedWidth(width)
        w.setStyleSheet(_RES_SS)
        return w

    @staticmethod
    def _result_lbl():
        w = QLabel('—')
        w.setStyleSheet(_RES_CB)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return w

    # ── Data binding ─────────────────────────────────────────────────────────

    def bind_feeder(self, feeder: C_Feeder, row: int, board) -> None:
        self._feeder = feeder
        self._row = row
        self._board = board
        if not feeder.motor_configured:
            feeder.motor.ensure_default_profile()
        nom_v = self._nominal_line_voltage(feeder)
        if not feeder.motor_configured or feeder.motor.Un_v < 100:
            feeder.motor.Un_v = nom_v
        feeder.motor.manufacturer = 'Generic'
        feeder.motor.apply_from_network(
            0, board.frequency if board else 60.0,
            board.Isc_board_kA if board else 0.0,
            set_un=False,
        )
        if not feeder.motor.tag:
            feeder.motor.tag = feeder.name or feeder.circuit_ref
        self._apply_feeder_to_motor()
        self._sync_from_motor()
        self.setEnabled(True)

    def clear_feeder(self) -> None:
        self._feeder = None
        self._row = -1
        self._le_name.clear()
        self._le_ref.clear()
        self._lbl_starter.setText('—')
        self._lbl_pd.setText('—')
        self._lbl_iso.setText('—')
        self._lbl_summary.setText('Motor: —')
        self._p_stat.setText('Select a Motor row, then Calculate')
        self.setEnabled(False)

    def get_board_context(self):
        return self._board

    def _init_controls(self):
        self._cb_profile.clear()
        for key in ('a', 'b', 'c'):
            self._cb_profile.addItem(PROFILE_LABELS[key], key)
        self._cb_ph.clear()
        self._cb_ph.addItem('3φ', 3)
        self._cb_ph.addItem('1φ', 1)
        self._cb_start.clear()
        self._cb_start.addItems(START_METHODS)
        self._cb_pd.clear()
        self._cb_pd.addItems(PD_TYPES)
        self._cb_iso.clear()
        self._cb_iso.addItems(ISOLATOR_MODES)

    def _wire_signals(self):
        self._le_name.textChanged.connect(self._on_name_changed)
        self._le_ref.textChanged.connect(self._on_ref_changed)
        self._cb_profile.currentIndexChanged.connect(self._on_profile_changed)
        self._cb_start.currentTextChanged.connect(self._on_start_changed)
        self._cb_pd.currentTextChanged.connect(self._on_pd_changed)
        self._cb_iso.currentTextChanged.connect(self._on_iso_changed)
        for sb in (self._sb_pn, self._sb_eta, self._sb_sf, self._sb_pf,
                   self._sb_ist):
            sb.valueChanged.connect(self._on_motor_field_changed)
        self._cb_ph.currentIndexChanged.connect(self._on_motor_field_changed)
        self._sb_len.valueChanged.connect(self._on_len_vd_changed)
        self._sb_vd.valueChanged.connect(self._on_len_vd_changed)
        self._sb_df.valueChanged.connect(self._on_df_changed)
        self._btn_calc.clicked.connect(self._calculate_and_save)

    def _on_name_changed(self, text: str):
        if self._busy or not self._feeder:
            return
        self._feeder.name = text.strip()
        self._emit_feeder_fields()

    def _on_ref_changed(self, text: str):
        if self._busy or not self._feeder:
            return
        self._feeder.circuit_ref = text.strip()
        self._emit_feeder_fields()

    @staticmethod
    def _phases_from_feeder(f: C_Feeder) -> int:
        if f.phases in (1, 3):
            return f.phases
        if f.phase_str == 'L123':
            return 3
        return 1

    def _apply_feeder_to_motor(self) -> None:
        """Pull grid / feeder P, PF, phase, cable fields into the motor model."""
        if not self._feeder:
            return
        f, m = self._feeder, self._feeder.motor
        p_kw = f.P or 0
        if p_kw > 0:
            sf = max(m.service_factor or 1.0, 0.01)
            m.Pn_kW = round(p_kw / sf, 3)
        pf = f.PF or 0
        if pf > 0:
            m.cos_phi = pf
        m.phases = self._phases_from_feeder(f)
        m.Un_v = self._nominal_line_voltage(f)

    def _push_feeder_fields(self) -> None:
        """Motor panel → feeder row (grid columns P, PF, phase, L, ΔU%)."""
        if self._busy or not self._feeder:
            return
        f, m = self._feeder, self._feeder.motor
        f.name = self._le_name.text().strip() or f.name
        f.circuit_ref = self._le_ref.text().strip() or f.circuit_ref
        m.tag = f.name or f.circuit_ref
        m.Pn_kW = self._sb_pn.value()
        m.efficiency = self._sb_eta.value()
        m.service_factor = self._sb_sf.value()
        m.cos_phi = self._sb_pf.value()
        m.ist_ratio = self._sb_ist.value()
        m.phases = int(self._cb_ph.currentData())
        m.Un_v = self._nominal_line_voltage(f)
        sf = max(m.service_factor or 1.0, 0.01)
        f.P = round(m.Pn_kW * sf, 3)
        f.PF = m.cos_phi
        f.phases = m.phases
        if m.phases == 3:
            f.phase_str = 'L123'
        elif f.phase_str not in ('L1', 'L2', 'L3'):
            f.phase_str = 'L1'
        self._sync_len_vd_to_feeder()

    def set_df_enabled(self, enabled: bool) -> None:
        self._sb_df.setEnabled(enabled)

    def _on_df_changed(self, value: float) -> None:
        if self._busy or not self._feeder:
            return
        self._feeder.demand_factor_pct = max(0.0, min(100.0, float(value)))
        self._emit_feeder_fields()

    def _emit_feeder_fields(self) -> None:
        if self._feeder:
            self.feeder_fields_changed.emit(self._feeder)

    def _on_motor_field_changed(self, *_a) -> None:
        if self._busy or not self._feeder:
            return
        self._push_feeder_fields()
        self._emit_feeder_fields()

    def _nominal_line_voltage(self, f: C_Feeder) -> float:
        if self._board and self._board.voltage > 0:
            return round(self._board.voltage, 0)
        if f.voltage >= 200:
            return round(f.voltage, 0)
        return 400.0

    def _on_profile_changed(self, _idx=None):
        if self._busy or not self._feeder:
            return
        key = self._cb_profile.currentData()
        if key:
            self._feeder.motor.apply_application_profile(key)
            self._auto_recalc()

    def _on_start_changed(self, _t=None):
        if self._busy or not self._feeder:
            return
        self._feeder.motor.start_method = self._cb_start.currentText()
        self._auto_recalc()

    def _on_pd_changed(self, _t=None):
        if self._busy or not self._feeder:
            return
        self._feeder.motor.apply_pd_type(self._cb_pd.currentText())
        self._auto_recalc()

    def _on_iso_changed(self, _t=None):
        if self._busy or not self._feeder:
            return
        self._feeder.motor.apply_isolator_mode(self._cb_iso.currentText())
        self._auto_recalc()

    def _auto_recalc(self) -> None:
        """Re-run motor sizing when inputs change after an initial Calculate."""
        if not self._feeder:
            return
        m = self._feeder.motor
        if m.Ib_A <= 0 and not self._feeder.motor_configured:
            return
        self._collect()
        m.calculate()
        m.sync_to_feeder(self._feeder)
        self._show_results()
        self._update_status_label()
        self.feeder_fields_changed.emit(self._feeder)

    def _collect(self):
        if not self._feeder:
            return
        m, f = self._feeder.motor, self._feeder
        f.name = self._le_name.text().strip() or f.name
        f.circuit_ref = self._le_ref.text().strip() or f.circuit_ref
        m.tag = f.name or f.circuit_ref
        m.Pn_kW = self._sb_pn.value()
        m.Un_v = self._nominal_line_voltage(f)
        m.phases = int(self._cb_ph.currentData())
        m.efficiency = self._sb_eta.value()
        m.cos_phi = self._sb_pf.value()
        m.ist_ratio = self._sb_ist.value()
        m.service_factor = self._sb_sf.value()
        m.duty_type = 'S1'
        m.starts_per_hour = 6
        m.thermistor_required = False
        m.manufacturer = 'Generic'
        m.apply_isolator_mode(self._cb_iso.currentText())
        m.Isc_3ph_kA = self._board.Isc_board_kA if self._board else 25.0
        key = self._cb_profile.currentData()
        if key:
            m.application_profile = key
            m.apply_application_profile(key)
        m.start_method = self._cb_start.currentText()
        m.apply_pd_type(self._cb_pd.currentText())
        f.phases = m.phases
        f.voltage = m.Un_v
        f.frequency = self._board.frequency if self._board else 60.0
        self._sync_len_vd_to_feeder()

    def _sync_len_vd_to_feeder(self) -> None:
        if not self._feeder:
            return
        f = self._feeder
        f.cable_length = self._sb_len.value()
        f.max_vdrop_pct = self._sb_vd.value()
        f.cable.cable_length = f.cable_length
        f.cable.max_vdrop_pct = f.max_vdrop_pct

    def _on_len_vd_changed(self, *_a) -> None:
        if self._busy or not self._feeder:
            return
        self._sync_len_vd_to_feeder()
        self._emit_feeder_fields()

    def _update_status_label(self) -> None:
        if not self._feeder:
            return
        f = self._feeder
        m = f.motor
        if m.Ib_A > 0:
            stat = f'Ib = {m.Ib_A:.1f} A'
            if m.passes_all:
                stat += '  |  ✓ Motor checks passed'
            self._p_stat.setText(stat)
        else:
            self._p_stat.setText(
                'Press Calculate Motor — use Select Cable on the right')

    def _calculate_and_save(self):
        if not self._feeder:
            return
        self._collect()
        m = self._feeder.motor
        ok, errs = m.is_valid()
        if not ok:
            QMessageBox.warning(self, 'Motor', '\n'.join(errs))
            return
        c = self._feeder.cable
        if c.conductor_table:
            try:
                c.calculate_derating()
            except Exception:
                pass
        elif c.is_valid_selection()[0]:
            try:
                c.calculate_derating()
            except Exception:
                pass
        m.calculate()
        if not m.passes_all and m.warnings:
            if QMessageBox.question(
                self, 'Motor',
                '\n'.join(m.warnings[:5]) + '\n\nContinue?',
            ) != QMessageBox.Yes:
                return
        m.sync_to_feeder(self._feeder)
        self._feeder.motor_configured = True
        self._feeder.load_type = 'Motor'
        self._show_results()
        self._update_status_label()
        self.motor_applied.emit(self._feeder)

    def _show_results(self):
        m = self._feeder.motor
        st = self._starter_text(m)
        pd = self._pd_text(m)
        iso = self._iso_text(m)
        self._lbl_starter.setText(st)
        self._lbl_pd.setText(pd)
        self._lbl_iso.setText(iso)
        prof = PROFILE_LABELS.get(m.application_profile, '')
        ol = f'OL Class {m.ol_class_used}'
        if m.start_time_s:
            ol += f', ts={m.start_time_s:g}s'
        self._lbl_summary.setText(
            f'Motor: {st}  ·  {pd}  ·  {iso}  ·  {ol}  ({prof})')

    def _sync_from_motor(self):
        if not self._feeder:
            return
        f, m = self._feeder, self._feeder.motor
        self._busy = True
        self._le_name.setText(f.name or '')
        self._le_ref.setText(f.circuit_ref or '')
        self._sb_pn.setValue(m.Pn_kW)
        for i in range(self._cb_ph.count()):
            if self._cb_ph.itemData(i) == m.phases:
                self._cb_ph.setCurrentIndex(i)
                break
        self._sb_eta.setValue(m.efficiency)
        self._sb_pf.setValue(m.cos_phi)
        self._sb_ist.setValue(m.ist_ratio)
        self._sb_sf.setValue(m.service_factor)
        prof = (m.application_profile if m.application_profile in PROFILE_LABELS
                else DEFAULT_APPLICATION_PROFILE)
        for i in range(self._cb_profile.count()):
            if self._cb_profile.itemData(i) == prof:
                self._cb_profile.setCurrentIndex(i)
                break
        i = self._cb_start.findText(m.start_method)
        if i >= 0:
            self._cb_start.setCurrentIndex(i)
        pd = m.pd_type if m.pd_type in PD_TYPES else 'MPCB'
        self._cb_pd.setCurrentText(pd)
        mode = m.isolator_mode if m.isolator_mode in ISOLATOR_MODES else 'Yes'
        self._cb_iso.setCurrentText(mode)
        self._sync_len_vd_from_feeder()
        if m.Ib_A > 0:
            self._show_results()
        else:
            self._lbl_starter.setText('—')
            self._lbl_pd.setText('—')
            self._lbl_iso.setText('—')
            self._lbl_summary.setText('Motor: —')
        self._busy = False

    def _sync_len_vd_from_feeder(self):
        if not self._feeder:
            return
        f = self._feeder
        self._sb_len.setValue(f.cable_length or 10)
        self._sb_vd.setValue(f.max_vdrop_pct or 3.0)
        self._sb_df.setValue(int(round(f.demand_factor_pct)))
        self._update_status_label()

    @staticmethod
    def _fmt_a(amps: float) -> str:
        if amps <= 0:
            return '—'
        if abs(amps - round(amps)) < 0.05:
            return f'{int(round(amps))} A'
        return f'{amps:g} A'

    @staticmethod
    def _starter_text(m: C_Motor) -> str:
        if m.start_method in ('Soft-starter', 'VFD') and m.starter_rated_A:
            return MotorCircuitSizingPanel._fmt_a(m.starter_rated_A)
        if m.start_method == 'Y-Δ':
            parts = []
            if m.contactor_line_A:
                parts.append(
                    f'L {MotorCircuitSizingPanel._fmt_a(m.contactor_line_A)}')
            if m.contactor_star_A and m.contactor_delta_A:
                parts.append(
                    f'Y {MotorCircuitSizingPanel._fmt_a(m.contactor_star_A)}'
                    f' / Δ {MotorCircuitSizingPanel._fmt_a(m.contactor_delta_A)}')
            return '  '.join(parts) if parts else '—'
        if m.contactor_line_A:
            return MotorCircuitSizingPanel._fmt_a(m.contactor_line_A)
        if m.starter_rated_A:
            return MotorCircuitSizingPanel._fmt_a(m.starter_rated_A)
        return '—'

    @staticmethod
    def _pd_text(m: C_Motor) -> str:
        if not m.In_device_A:
            return '—'
        ol = ''
        if m.ol_relay_ref and m.ol_relay_ref != '—':
            ol = m.ol_relay_ref
        base = f'{MotorCircuitSizingPanel._fmt_a(m.In_device_A)} {m.pd_type}'
        if ol:
            return f'{base} · {ol}'
        return base

    @staticmethod
    def _iso_text(m: C_Motor) -> str:
        if not m.isolator_required:
            return 'Not required'
        if m.isolator_size_A > 0:
            return f'{MotorCircuitSizingPanel._fmt_a(m.isolator_size_A)} (≥1.25×Ib)'
        return '—'
