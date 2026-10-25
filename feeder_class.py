# feeder_class.py
# C_Feeder — one outgoing feeder from a switchboard
# Contains C_Cable + C_CB, performs Ib/CB/Vdrop calculations

from __future__ import annotations
import math
import json
from dataclasses import dataclass, field
from typing import Optional

import sys, os
if not getattr(sys, 'frozen', False):
    _HERE  = os.path.dirname(os.path.abspath(__file__))
    _CABLE = os.path.join(_HERE, 'VSEngCableSelector')
    if _HERE in sys.path:
        sys.path.remove(_HERE)
    sys.path.insert(0, _HERE)
    if _CABLE not in sys.path:
        sys.path.insert(1, _CABLE)
from VSEngCableSelector.cable_class import C_Cable, ConductorRow, MAX_PARALLEL_SETS
from cb_class import C_CB, CB_TYPES, DIVERSITY_STEPS
from motor_class import C_Motor
from vdrop_settings import feeder_cable_locked


@dataclass
class C_Feeder:
    # ── IDENTITY ──────────────────────────────────────────────────────────────
    name:            str   = 'Feeder-1'
    circuit_ref:     str   = 'F1'
    load_description: str  = ''
    panel_ref:       str   = ''         # destination panel/load ref

    # ── LOAD TYPE & PHASE ─────────────────────────────────────────────────────
    load_type:   str = 'Other'   # 'Motor'|'Light'|'Socket'|'HVAC'|'SubPanel'|'Other'
    phase_str:   str = 'L123'    # 'L1'|'L2'|'L3'|'L123'
    subpanel_id: str = ''        # id of child C_Switchboard if SubPanel

    # ── CIRCUIT PARAMETERS ────────────────────────────────────────────────────
    phases:          int   = 3          # 1 = L-N | 2 = L-L | 3 = 3-phase
    voltage:         float = 400.0      # V (LV)
    frequency:       float = 60.0       # Hz — KSA network (fixed)
    P:               Optional[float] = None   # kW (connected / nameplate)
    S:               Optional[float] = None   # kVA
    PF:              Optional[float] = 0.9    # power factor
    demand_factor_pct: float = 100.0  # user enters 80 → factor 0.8; Pdf = P × DF
    cable_length:    float = 10.0      # m
    max_vdrop_pct:   float = 3.0        # % — segment ΔU limit
    vd_user_override: bool = False       # True = user set ΔU%; skip category defaults
    has_neutral:     bool  = False      # 4P CB flag

    # ── CABLE (populated by Cable Selector) ───────────────────────────────────
    cable: C_Cable = field(default_factory=C_Cable)

    # ── CB ────────────────────────────────────────────────────────────────────
    cb: C_CB = field(default_factory=C_CB)

    # ── MOTOR (IEC 60947-4-1 Type 2 — when load_type == 'Motor') ───────────────
    motor: C_Motor = field(default_factory=C_Motor)
    motor_configured: bool = False   # True after Motor Protection dialog completed

    # ── ISC INPUTS ────────────────────────────────────────────────────────────
    Isc_board_kA: float = 0.0   # fault level at switchboard busbars (from Switchboard)

    # ── OUTPUTS ───────────────────────────────────────────────────────────────
    Ib:              float = 0.0   # design current at 100 % connected load
    P_demand:        Optional[float] = None   # kW after demand factor
    S_demand:        Optional[float] = None   # kVA after demand factor
    Ib_demand:       float = 0.0   # current for upstream board summation
    Iz:              float = 0.0
    result_vdrop_v:  float = 0.0
    result_vdrop_pct: float = 0.0   # ΔU on this segment only (ΔUc in SLD)
    result_vdrop_total_pct: float = 0.0  # ΔUtotal from root nominal (global opt / SLD)
    passes_vdrop_total: bool = True  # ΔUtotal ≤ limit at load point (global mode)
    Isc_end_kA:      float = 0.0   # fault level at end of feeder cable
    passes_all:      bool  = False
    warnings:        list  = field(default_factory=list)

    # ── PROJECT CONSTRAINTS (runtime only, not serialised) ───────────────────
    min_cb_A:       float = 6.0     # project minimum CB rating — set by calculate_all

    # ── USER OVERRIDES (persisted) ────────────────────────────────────────────
    user_locked_cb: bool = False    # True = skip auto-sizing; keep manually set In_CB

    # ── COLLABORATION — federated sub-board stub ──────────────────────────────
    is_stub:        bool  = False   # True = external package; no child board loaded
    stub_package:   str   = ''      # path to the external .swb file
    interface_spec: dict  = field(default_factory=dict)
    # interface_spec keys: S_kVA, Ib_A, Isc_kA, voltage, max_vd_pct, notes

    # ─────────────────────────────────────────────────────────────────────────
    # VALIDATE
    # ─────────────────────────────────────────────────────────────────────────

    def is_valid(self) -> tuple[bool, list[str]]:
        errs = []
        given = sum(x is not None for x in [self.P, self.S, self.PF])
        if given < 2:
            errs.append("At least two of P, S, PF must be provided.")
        if self.voltage <= 0:
            errs.append("Voltage must be > 0.")
        if self.cable_length <= 0:
            errs.append("Cable length must be > 0.")
        if not self.cable.conductor_table:
            errs.append("Cable not selected. Use 'Select Cable' to open Cable Selector.")
        return len(errs) == 0, errs

    # ─────────────────────────────────────────────────────────────────────────
    # DERIVE P/S/PF
    # ─────────────────────────────────────────────────────────────────────────

    def _derive_power(self) -> None:
        P, S, PF = self.P, self.S, self.PF
        if P is None and S is not None and PF is not None:
            self.P = round(S * PF, 4)
        elif S is None and P is not None and PF is not None:
            self.S = round(P / PF, 4) if PF != 0 else None
        elif PF is None and P is not None and S is not None:
            self.PF = round(P / S, 4) if S != 0 else None

    def demand_factor(self) -> float:
        """0.0–1.0 from demand_factor_pct (80 → 0.8)."""
        return max(0.0, min(100.0, self.demand_factor_pct)) / 100.0

    def _ib_from_s_kva(self, s_kva: float) -> float:
        if not s_kva or self.voltage <= 0:
            return 0.0
        if self.phases == 3:
            return round(s_kva * 1000 / (math.sqrt(3) * self.voltage), 2)
        return round(s_kva * 1000 / self.voltage, 2)

    def apply_demand_outputs(self) -> None:
        """Pdf / Sdem / Ib_demand for board totals; feeder sized at 100 % load."""
        if self.load_type in ('Space', 'Spare'):
            self.P_demand = 0.0
            self.S_demand = 0.0
            self.Ib_demand = 0.0
            return
        f = self.demand_factor()
        self.P_demand = round(self.P * f, 4) if self.P is not None else None
        self.S_demand = round(self.S * f, 4) if self.S is not None else None
        if self.S_demand:
            self.Ib_demand = self._ib_from_s_kva(self.S_demand)
        elif self.P_demand is not None and self.PF:
            self.Ib_demand = self._ib_from_s_kva(self.P_demand / self.PF)
        else:
            self.Ib_demand = round(self.Ib * f, 2)

    # ─────────────────────────────────────────────────────────────────────────
    # CALCULATE
    # ─────────────────────────────────────────────────────────────────────────

    def calculate(self, Isc_board_kA: float = 0.0) -> None:
        """
        Full feeder calculation:
        1. Derive missing P/S/PF
        2. Calculate Ib
        3. Pass to C_Cable.calculate_load() → conductor selection
        4. Get Iz from recommended conductor
        5. Auto-select CB type and poles
        6. Size CB (IEC 60364-4-43)
        7. Calculate Isc at end of feeder cable
        8. Check CB breaking capacity
        """
        self.warnings = []
        self.Isc_board_kA = Isc_board_kA

        if self.load_type in ('Space', 'Spare', 'SubPanel'):
            return

        _ph_count = {'L123': 3, 'L12': 2, 'L13': 2, 'L23': 2,
                     'L1': 1, 'L2': 1, 'L3': 1}
        if self.phase_str:
            self.phases = _ph_count.get(self.phase_str, self.phases)

        # Motor path: sync nameplate → feeder power before cable/CB sizing
        if self.load_type == 'Motor' and self.motor_configured:
            self.motor.apply_from_network(
                self.voltage, self.frequency, Isc_board_kA)
            self.motor.calculate()
            self.motor.sync_to_feeder(self)
            self.warnings.extend(
                [f'[Motor] {w}' for w in self.motor.warnings])

        # ── Step 1: Derive power ──
        self._derive_power()

        # ── Step 2: Pass params to C_Cable ──
        c = self.cable
        c.frequency     = self.frequency   # must precede any calculate_derating() call
        c.phases        = self.phases
        c.voltage       = self.voltage
        c.P             = self.P
        c.S             = self.S
        c.PF            = self.PF
        c.cable_length  = self.cable_length
        c.max_vdrop_pct = self.max_vdrop_pct

        c.ensure_conductor_table()

        ok, errs = c.is_valid_calculation()
        if not ok:
            self.warnings.extend(errs)
            return

        # ── Step 3: Conductor selection ──
        c.calculate_load()
        self.warnings.extend(c.warnings)
        self.Ib = c.Ib

        if not c.recommended:
            self.warnings.append("No conductor selected. Cannot size CB.")
            self.passes_all = False
            return

        # ── Step 4: Iz — use value from calculate_load (includes parallel_cables × k_parallel)
        rec    = c.recommended
        n_par  = getattr(c, 'parallel_cables', 1)
        k4     = getattr(c, 'k_parallel', 1.0)
        self.Iz = rec.Iz   # = In × n × k1 × k2 × k3 × k4

        # ── Steps 5 & 6: CB type / size ──────────────────────────────────────
        if self.user_locked_cb and self.cb.In_CB > 0:
            # User locked In_CB — still auto-coordinate Icu to fault level
            self.cb.coordinate_icu(Isc_board_kA)
            self.cb.passes_protection = (
                self.Ib <= self.cb.In_CB <= 1.45 * self.Iz)
            self.warnings.extend(self.cb.warnings)
        else:
            # ── Step 5: Auto CB type and poles ──
            self.cb.cb_type  = C_CB.auto_type(self.Ib)
            from cb_class import cb_standard_for_type
            self.cb.standard = cb_standard_for_type(self.cb.cb_type)
            self.cb.poles    = C_CB.auto_poles(self.phases, self.has_neutral)

            # ── Step 6: Size CB at 100 % Ib (Icu coordinated inside size_cb) ──
            self.cb.diversity = 1.0
            self.cb.size_cb(self.Ib, self.Iz, Isc_board_kA)

        # If CB doesn't fit, upsize conductor (auto path only — not manual cable lock)
        if (not feeder_cable_locked(self)
                and not self.user_locked_cb
                and not self.cb.passes_protection and c.conductor_table):
            cur_idx = next(
                (i for i, r in enumerate(c.conductor_table)
                 if r.cable_code == rec.cable_code), -1)
            for next_idx in range(cur_idx + 1, len(c.conductor_table)):
                next_row = c.conductor_table[next_idx]
                k2_next  = c._k2_for_size(next_row.size_mm2)
                k_next   = round(c.k1 * k2_next * c.k3 * k4, 4)
                iz_next  = round(next_row.In * n_par * k_next, 2)
                vd_v, vd_pct, _ = c._vdrop(next_row, self.Ib / max(n_par, 1))
                next_row.Iz        = iz_next
                next_row.vdrop_v   = vd_v
                next_row.vdrop_pct = vd_pct
                next_row.passes_amp   = iz_next >= self.Ib
                next_row.passes_vdrop = vd_pct <= self.max_vdrop_pct
                cb_test = C_CB()
                cb_test.cb_type  = self.cb.cb_type
                cb_test.standard = self.cb.standard
                cb_test.poles    = self.cb.poles
                cb_test.Icu_kA   = self.cb.Icu_kA
                cb_test.diversity = self.cb.diversity
                cb_test.size_cb(self.Ib, iz_next, Isc_board_kA)
                if cb_test.passes_protection:
                    c.recommended = next_row
                    rec  = next_row
                    self.Iz = iz_next
                    self.cb = cb_test
                    self.result_vdrop_v   = vd_v
                    self.result_vdrop_pct = vd_pct
                    c.passes_ampacity = next_row.passes_amp
                    c.passes_vdrop    = next_row.passes_vdrop
                    break

            # At largest catalogue size — increase parallel sets (up to 6)
            if not self.cb.passes_protection:
                largest = c.conductor_table[-1]
                for n_try in range(n_par + 1, MAX_PARALLEL_SETS + 1):
                    c.set_parallel_count(n_try)
                    k4_try = c.k_parallel
                    k2_l = c._k2_for_size(largest.size_mm2)
                    k_tot = round(c.k1 * k2_l * c.k3 * k4_try, 4)
                    iz_next = round(largest.In * n_try * k_tot, 2)
                    if iz_next < self.Ib:
                        continue
                    vd_v, vd_pct, _ = c._vdrop(largest, self.Ib / n_try)
                    cb_test = C_CB()
                    cb_test.cb_type  = self.cb.cb_type
                    cb_test.standard = self.cb.standard
                    cb_test.poles    = self.cb.poles
                    cb_test.Icu_kA   = self.cb.Icu_kA
                    cb_test.diversity = self.cb.diversity
                    cb_test.size_cb(self.Ib, iz_next, Isc_board_kA)
                    if cb_test.passes_protection:
                        largest.Iz = iz_next
                        largest.vdrop_v = vd_v
                        largest.vdrop_pct = vd_pct
                        largest.passes_amp = True
                        largest.passes_vdrop = vd_pct <= self.max_vdrop_pct
                        c.recommended = largest
                        rec = largest
                        self.Iz = iz_next
                        self.cb = cb_test
                        self.result_vdrop_v = vd_v
                        self.result_vdrop_pct = vd_pct
                        c.passes_ampacity = largest.passes_amp
                        c.passes_vdrop = largest.passes_vdrop
                        break

        self.warnings.extend(self.cb.warnings)

        # Enforce project minimum CB rating
        if not self.user_locked_cb and self.cb.In_CB < self.min_cb_A:
            from cb_class import MCB_SIZES, MCCB_SIZES, ACB_SIZES
            all_sizes = MCB_SIZES + MCCB_SIZES + ACB_SIZES
            compliant = [s for s in all_sizes if s >= self.min_cb_A]
            if compliant:
                self.cb.In_CB = compliant[0]
                if self.cb.In_CB in MCB_SIZES:
                    self.cb.cb_type  = 'MCB';  self.cb.standard = 'MCB'
                elif self.cb.In_CB in MCCB_SIZES:
                    self.cb.cb_type  = 'MCCB'; self.cb.standard = 'MCCB'
                else:
                    self.cb.cb_type  = 'ACB';  self.cb.standard = 'MCCB'

        # ── Step 7: Isc at end of feeder ──
        if Isc_board_kA > 0:
            self.Isc_end_kA = self._calc_isc_end(Isc_board_kA)
        else:
            self.Isc_end_kA = 0.0

        # ── Step 8: Results ──
        self.result_vdrop_v   = rec.vdrop_v
        self.result_vdrop_pct = rec.vdrop_pct
        self.passes_all = (
            c.passes_ampacity and
            c.passes_vdrop and
            self.cb.passes_protection and
            (self.cb.passes_Isc or Isc_board_kA == 0)
        )
        self.apply_demand_outputs()

    # ─────────────────────────────────────────────────────────────────────────
    # ISC AT END OF FEEDER
    # ─────────────────────────────────────────────────────────────────────────

    def _calc_isc_end(self, Isc_board_kA: float) -> float:
        """
        Calculate fault current at the end of feeder cable.
        Uses cable impedance from recommended conductor.

        Zboard = Vn / (√3 × Isc_board)
        Zcable = R + jX  (from cable)
        Ztotal = Zboard + Zcable  (simplified scalar addition — conservative)
        Isc_end = Vn / (√3 × Ztotal)
        """
        if not self.cable.recommended or Isc_board_kA <= 0:
            return 0.0

        Vn      = self.voltage
        Z_board = Vn / (math.sqrt(3) * Isc_board_kA * 1000)  # convert kA → A
        R_cab, X_cab = self.cable.get_impedance()
        Z_cable = math.sqrt(R_cab**2 + X_cab**2)
        Z_total = Z_board + Z_cable
        if Z_total <= 0:
            return 0.0
        Isc_end_A  = Vn / (math.sqrt(3) * Z_total)
        return round(Isc_end_A / 1000, 3)  # return in kA

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY STRING (for Switchboard table)
    # ─────────────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        rec = self.cable.recommended
        return {
            'ref':       self.circuit_ref,
            'name':      self.name,
            'load':      self.load_description,
            'Ib':        f"{self.Ib:.1f}",
            'CB':        f"{self.cb.In_CB:.0f}A {self.cb.cb_type}",
            'size':      f"{rec.size_mm2}mm²" if rec else "—",
            'code':      rec.cable_code if rec else "—",
            'vdrop':     f"{self.result_vdrop_pct:.2f}%",
            'passes':    self.passes_all,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # SERIALISE
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            'name':            self.name,
            'circuit_ref':     self.circuit_ref,
            'load_description': self.load_description,
            'panel_ref':       self.panel_ref,
            'load_type':       self.load_type,
            'phase_str':       self.phase_str,
            'subpanel_id':     self.subpanel_id,
            'phases':          self.phases,
            'voltage':         self.voltage,
            'frequency':       self.frequency,
            'P': self.P, 'S': self.S, 'PF': self.PF,
            'demand_factor_pct': self.demand_factor_pct,
            'P_demand': self.P_demand,
            'S_demand': self.S_demand,
            'Ib_demand': self.Ib_demand,
            'cable_length':    self.cable_length,
            'max_vdrop_pct':   self.max_vdrop_pct,
            'vd_user_override': self.vd_user_override,
            'has_neutral':     self.has_neutral,
            'cable':           self.cable.to_dict(),
            'cb':              self.cb.to_dict(),
            'Isc_board_kA':    self.Isc_board_kA,
            'Ib':              self.Ib,
            'Iz':              self.Iz,
            'result_vdrop_v':  self.result_vdrop_v,
            'result_vdrop_pct': self.result_vdrop_pct,
            'result_vdrop_total_pct': self.result_vdrop_total_pct,
            'passes_vdrop_total': self.passes_vdrop_total,
            'Isc_end_kA':      self.Isc_end_kA,
            'passes_all':      self.passes_all,
            'warnings':        self.warnings,
            'user_locked_cb':  self.user_locked_cb,
            'is_stub':         self.is_stub,
            'stub_package':    self.stub_package,
            'interface_spec':  self.interface_spec,
            'motor':           self.motor.to_dict(),
            'motor_configured': self.motor_configured,
        }

    @staticmethod
    def from_dict(d: dict) -> 'C_Feeder':
        obj = C_Feeder()
        for key in ['name','circuit_ref','load_description','panel_ref',
                    'load_type','phase_str','subpanel_id',
                    'phases','voltage','frequency','P','S','PF',
                    'demand_factor_pct','P_demand','S_demand','Ib_demand',
                    'cable_length',
                    'max_vdrop_pct','vd_user_override','has_neutral','Isc_board_kA',
                    'Ib','Iz','result_vdrop_v','result_vdrop_pct',
                    'result_vdrop_total_pct','passes_vdrop_total',
                    'Isc_end_kA','passes_all','warnings','user_locked_cb',
                    'is_stub','stub_package','interface_spec',
                    'motor_configured']:
            if key in d:
                setattr(obj, key, d[key])
        if 'motor' in d:
            obj.motor = C_Motor.from_dict(d['motor'])
        if 'cable' in d:
            obj.cable = C_Cable.from_dict(d['cable'])
        if 'cb' in d:
            obj.cb = C_CB.from_dict(d['cb'])
        if 'demand_factor_pct' not in d and obj.cb.diversity not in (0.0, 1.0):
            obj.demand_factor_pct = round(obj.cb.diversity * 100.0, 1)
        elif 'demand_factor_pct' not in d:
            obj.demand_factor_pct = 100.0
        return obj

    def __repr__(self) -> str:
        return (f"C_Feeder({self.circuit_ref} '{self.name}' | "
                f"Ib={self.Ib:.1f}A CB={self.cb.In_CB}A | "
                f"{'✔' if self.passes_all else '✘'})")
