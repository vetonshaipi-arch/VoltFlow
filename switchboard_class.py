# switchboard_class.py
# C_Switchboard — main switchboard object
# Contains: global board data, transformer data, primary feeder,
#           list of C_Feeder, list of C_CB
# Performs: Isc chain calculation from transformer → busbars → each feeder end

from __future__ import annotations
import math
import json
import uuid
from typing import Optional
from dataclasses import dataclass, field

from project_class import PROJECT_STANDARD, KSA_FREQUENCY_HZ, normalize_project_standard


def std_frequency(standard: str | None = None) -> float:
    """VoltFlow KSA edition — fixed 60 Hz network frequency."""
    return KSA_FREQUENCY_HZ

import sys, os
if not getattr(sys, 'frozen', False):
    _HERE  = os.path.dirname(os.path.abspath(__file__))
    _CABLE = os.path.join(_HERE, 'VSEngCableSelector')
    # Project root must stay ahead of VSEngCableSelector — otherwise `import ui`
    # resolves to VSEngCableSelector/ui and breaks reports (SLD, etc.).
    if _HERE in sys.path:
        sys.path.remove(_HERE)
    sys.path.insert(0, _HERE)
    if _CABLE not in sys.path:
        sys.path.insert(1, _CABLE)
from VSEngCableSelector.cable_class import C_Cable
from feeder_class import C_Feeder
from cb_class import C_CB, IEC_MCCB_SIZES, IEC_ACB_SIZES
from vdrop_settings import VdropProjectSettings, apply_vdrop_limits_tree

# ─── FRAME TYPES ──────────────────────────────────────────────────────────────
FRAME_TYPES  = ['MDB', 'SMDB', 'MCC', 'PDB', 'DB', 'MLDB', 'Custom']
IP_RATINGS   = ['IP20', 'IP31', 'IP41', 'IP42', 'IP43', 'IP44',
                'IP54', 'IP55', 'IP56', 'IP65', 'IP66']
MOUNTING     = ['Floor Standing', 'Wall Mounted', 'Pole Mounted', 'Rack Mounted']
BUSBAR_STD_A = [160, 250, 400, 630, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000]
PANEL_SIZES  = [12, 18, 24, 36, 42, 48, 54, 60, 72]  # standard pole counts


@dataclass
class C_Transformer:
    """Transformer nameplate and source impedance data."""
    Sn_kVA:    float = 1000.0   # rated power (kVA)
    Vk_pct:    float = 6.0      # short-circuit impedance (%)
    Un_HV:     float = 11000.0  # HV voltage (V)
    Un_LV:     float = 400.0    # LV voltage (V)
    Pk_kW:     float = 0.0      # load losses (kW) — for R/X ratio
    vector:    str   = 'Dyn11'  # winding configuration
    manufacturer: str = ''

    def Z_trafo_ohm(self) -> float:
        """Transformer impedance referred to LV side (Ω)."""
        if self.Sn_kVA <= 0:
            return 0.0
        return (self.Vk_pct / 100.0) * (self.Un_LV ** 2) / (self.Sn_kVA * 1000.0)

    def Isc_lv_kA(self) -> float:
        """Prospective short-circuit current at LV terminals (kA)."""
        Z = self.Z_trafo_ohm()
        if Z <= 0:
            return 0.0
        return round((self.Un_LV / (math.sqrt(3) * Z)) / 1000.0, 3)

    def to_dict(self) -> dict:
        return {
            'Sn_kVA': self.Sn_kVA, 'Vk_pct': self.Vk_pct,
            'Un_HV': self.Un_HV,   'Un_LV': self.Un_LV,
            'Pk_kW': self.Pk_kW,   'vector': self.vector,
            'manufacturer': self.manufacturer,
        }

    @staticmethod
    def from_dict(d: dict) -> 'C_Transformer':
        obj = C_Transformer()
        for k, v in d.items():
            if hasattr(obj, k): setattr(obj, k, v)
        return obj


@dataclass
class C_Switchboard:
    # ── IDENTITY ──────────────────────────────────────────────────────────────
    # ── HIERARCHY ─────────────────────────────────────────────────────────────
    board_id:     str  = field(default_factory=lambda: __import__('uuid').uuid4().hex[:8])
    parent_id:    str  = ''   # parent board_id, empty = root
    level:        int  = 0    # 0=root, 1=MDB, ..., max 10
    child_boards: list = field(default_factory=list)

    # ── IDENTITY ──────────────────────────────────────────────────────────────
    name:        str = 'MDB-1'
    project:     str = ''
    location:    str = ''
    drawing_ref: str = ''
    date:        str = ''
    engineer:    str = ''

    # ── BOARD ELECTRICAL DATA ─────────────────────────────────────────────────
    voltage:     float = 400.0   # V
    phases:      int   = 3
    frequency:   float = KSA_FREQUENCY_HZ
    standard:    str   = PROJECT_STANDARD
    busbar_A:    float = 1600.0  # busbar ampacity (A)

    # ── ACTUAL BUSBAR VOLTAGE (after upstream Vdrop) ────────────────────────
    actual_voltage_V: float = 400.0  # V — nominal for root, reduced for children

    # ── PANEL SCHEDULE ────────────────────────────────────────────────────────
    panel_size:  int   = 0    # 0 = auto (next standard above used poles)

    # ── COLLABORATION — interface contract imposed by upstream allocation ──────
    # Populated when this board was exported as a sub-board package.
    # Keys: S_kVA, Ib_A, Isc_kA, voltage, max_vd_pct, notes
    interface_spec: dict = field(default_factory=dict)

    # ── PHYSICAL ──────────────────────────────────────────────────────────────
    frame:       str = 'MDB'
    IP:          str = 'IP54'
    mounting:    str = 'Floor Standing'
    manufacturer: str = ''
    model:       str = ''

    # ── TRANSFORMER ───────────────────────────────────────────────────────────
    transformer: C_Transformer = field(default_factory=C_Transformer)

    # ── PRIMARY FEEDER (trafo LV → this switchboard) ──────────────────────────
    # Full C_Feeder — cable selected via Cable Selector, CB auto-sized
    primary_feeder: C_Feeder = field(default_factory=C_Feeder)
    primary_feeder_selected: bool = False   # True once cable has been selected

    # ── MAIN CB (incomer) — sized from primary_feeder.cb ─────────────────────
    main_cb: C_CB = field(default_factory=C_CB)

    # ── ISC AT BUSBARS (calculated) ───────────────────────────────────────────
    Isc_board_kA: float = 0.0

    # ── OUTGOING FEEDERS ──────────────────────────────────────────────────────
    feeders: list = field(default_factory=list)  # list[C_Feeder]

    # ── TOTALS (calculated) ───────────────────────────────────────────────────
    total_Ib:       float = 0.0   # demand total Ib (A) — for busbar / incomer
    total_S_kVA:    float = 0.0   # demand total S (kVA)
    total_Ib_connected: float = 0.0   # sum at 100 % before project-level DF
    composite_PF:   float = 0.9   # kVA-weighted PF across feeders
    composite_pf_override: float | None = None  # user PF on incomer panel
    busbar_loading: float = 0.0   # % of busbar ampacity used
    project_df_applied: bool = False
    project_df_pct:     float = 100.0
    vdrop_opt_applied:  bool  = False
    vdrop_opt_copper_kmm: float = 0.0
    warnings:       list  = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────────
    # ISC CHAIN CALCULATION
    # ─────────────────────────────────────────────────────────────────────────

    def _propagate_isc(self, z_upstream: float, v_nom: float,
                       min_conductor_mm2: float, min_cb_A: float,
                       preserve_cables: bool = False,
                       vd_root: 'C_Switchboard' = None) -> None:
        """
        Top-down Isc propagation — called once from the root board after all
        cables are sized.

        z_upstream : cumulative Z (Ω) of every section upstream of this board.
        v_nom      : nominal line voltage of the root transformer (e.g. 400 V).

        At each level:
            Z_own  = √(R²+X²) of this board's primary cable (n_parallel included)
            Z_ekv  = z_upstream + Z_own        (+ Z_t at level 0)
            Isc    = v_nom / (√3 × Z_ekv)

        The same Z_ekv is passed to every child board as its z_upstream.
        """
        Z_own = 0.0
        if self.primary_feeder_selected and self.primary_feeder.cable.recommended:
            R_c, X_c = self.primary_feeder.cable.get_impedance()
            Z_own = math.sqrt(R_c ** 2 + X_c ** 2)

        if self.level == 0:
            z_ekv = self.transformer.Z_trafo_ohm() + Z_own
        else:
            z_ekv = z_upstream + Z_own

        if z_ekv > 0:
            self.Isc_board_kA = round(v_nom / (math.sqrt(3) * z_ekv * 1000.0), 3)
        else:
            self.Isc_board_kA = 0.0

        self._coordinate_board_cbs()

        # Re-run outgoing feeders with the now-correct Isc
        for feeder in self.feeders:
            if feeder.load_type == 'SubPanel' and feeder.subpanel_id:
                child = self.find_board(feeder.subpanel_id)
                if child:
                    child.actual_voltage_V = self.actual_voltage_V
                    child._propagate_isc(
                        z_ekv, v_nom, min_conductor_mm2, min_cb_A,
                        preserve_cables, vd_root or self)
                    feeder.cb.passes_Isc = child.main_cb.passes_Isc
                    feeder.passes_all = (
                        child.main_cb.passes_protection and
                        child.busbar_loading <= 100 and
                        len([w for w in child.warnings if 'VIOLATION' in w]) == 0
                    )
                if (preserve_cables and vd_root is not None
                        and feeder.cable.conductor_table):
                    from vdrop_optimizer import refresh_feeder_after_isc
                    _ph_v = self.actual_voltage_V
                    refresh_feeder_after_isc(
                        feeder, self, vd_root, min_conductor_mm2, _ph_v)
            elif feeder.load_type not in ('Space', 'Spare'):
                _ph_v = (self.actual_voltage_V / math.sqrt(3)
                         if feeder.phase_str in ('L1', 'L2', 'L3')
                         else self.actual_voltage_V)
                feeder.voltage       = _ph_v
                feeder.cable.voltage = _ph_v
                feeder.cable.min_conductor_mm2 = min_conductor_mm2
                feeder.min_cb_A                = min_cb_A
                feeder.frequency       = self.frequency
                feeder.cable.frequency = self.frequency
                if preserve_cables and vd_root is not None:
                    from vdrop_optimizer import refresh_feeder_after_isc
                    refresh_feeder_after_isc(
                        feeder, self, vd_root, min_conductor_mm2, _ph_v)
                else:
                    feeder.calculate(self.Isc_board_kA)

        self._size_main_cb()

    # ─────────────────────────────────────────────────────────────────────────
    # CALCULATE ALL
    # ─────────────────────────────────────────────────────────────────────────

    def calculate_all(self, min_conductor_mm2: float = 1.5, min_cb_A: float = 6.0,
                      df_mode: str = 'per_load',
                      project_df_pct: float = 100.0,
                      vd_settings: VdropProjectSettings = None) -> None:
        """
        1. Calculate all outgoing feeders → get total_Ib
        2. Calculate primary feeder (Ib = total_Ib, auto CB sizing)
        3. Calculate Isc at busbars (needs primary cable)
        4. Re-run feeders with correct Isc_board
        5. Sum totals
        """
        if vd_settings is None:
            vd_settings = VdropProjectSettings()

        if self.level == 0:
            self.clear_all_warnings()

        apply_vdrop_limits_tree(self, vd_settings, force=False)

        self.vdrop_opt_applied = False
        # Root board: reset actual voltage to nominal before full recalc
        if self.level == 0:
            self.actual_voltage_V = self.voltage

        # Step 1: Calculate outgoing feeders (first pass — no Isc yet)
        for feeder in self.feeders:
            if feeder.load_type == 'SubPanel' and feeder.subpanel_id:
                # Get load from child board totals
                child = self.find_board(feeder.subpanel_id)
                if child:
                    feeder.voltage       = self.actual_voltage_V
                    feeder.cable.voltage = self.actual_voltage_V
                    feeder.cable.min_conductor_mm2 = min_conductor_mm2
                    feeder.min_cb_A                = min_cb_A
                    # Pass THIS board's busbar voltage as the primary-feeder
                    # source for the child.  child._calc_primary_feeder() will
                    # compute the cable drop and write the correct reduced
                    # child-busbar voltage back into child.actual_voltage_V.
                    # Pre-applying the drop here (as before) caused the source
                    # voltage to be wrong on every recalc after the first.
                    child.actual_voltage_V = self.actual_voltage_V
                    child.calculate_all(
                        min_conductor_mm2, min_cb_A, df_mode, project_df_pct,
                        vd_settings)
                    feeder.S   = child.total_S_kVA
                    feeder.PF  = child.composite_PF
                    feeder.P   = round(child.total_S_kVA * child.composite_PF, 2)
                    feeder.Ib  = child.total_Ib
                    feeder.Iz  = child.main_cb.Iz if child.main_cb.Iz else child.busbar_A
                    feeder.cb.In_CB   = child.main_cb.In_CB
                    feeder.cb.cb_type = child.main_cb.cb_type
                    feeder.cb.poles   = child.main_cb.poles
                    feeder.cb.passes_protection = child.main_cb.passes_protection
                    feeder.cb.passes_Isc        = child.main_cb.passes_Isc
                    feeder.result_vdrop_pct = child.primary_feeder.result_vdrop_pct                         if child.primary_feeder_selected else 0.0
                    # Pass if child board has valid CB and no overloaded busbar
                    feeder.passes_all = (
                        child.main_cb.passes_protection and
                        child.busbar_loading <= 100 and
                        len([w for w in child.warnings if 'VIOLATION' in w]) == 0
                    )
            elif feeder.load_type not in ('Space', 'Spare'):
                # L1/L2/L3 are phase-to-neutral: use Vphase = Vline/√3
                _ph_v = (self.actual_voltage_V / math.sqrt(3)
                         if feeder.phase_str in ('L1', 'L2', 'L3')
                         else self.actual_voltage_V)
                feeder.voltage       = _ph_v
                feeder.cable.voltage = _ph_v
                feeder.cable.min_conductor_mm2 = min_conductor_mm2
                feeder.min_cb_A                = min_cb_A
                feeder.frequency       = self.frequency
                feeder.cable.frequency = self.frequency
                feeder.calculate(0.0)
                self.warnings.extend(
                    [f"[{feeder.circuit_ref}] {w}" for w in feeder.warnings]
                )

        # Step 2: Sum totals to get total_Ib (demand-adjusted per settings)
        self._calc_totals(df_mode, project_df_pct)

        # Step 3: Calculate primary feeder using total_Ib
        if self.primary_feeder_selected and self.primary_feeder.cable.conductor_table:
            self.primary_feeder.cable.min_conductor_mm2 = min_conductor_mm2
            self.primary_feeder.min_cb_A                = min_cb_A
            self._calc_primary_feeder()

        # Step 4: First-pass CB sizing (Isc not yet propagated)
        self._size_main_cb()

        # Final totals
        self._calc_totals(df_mode, project_df_pct)

        # Step 5: Top-down Isc propagation — root board only.
        # Each board's Isc = V_nom / (√3 × Zekv) where Zekv accumulates
        # transformer + every cable in the path from transformer to that board.
        if self.level == 0:
            self._propagate_isc(0.0, self.transformer.Un_LV,
                                min_conductor_mm2, min_cb_A)

    def _calc_primary_feeder(self) -> None:
        """
        Calculate primary feeder cable + CB using the same path as outgoing feeders.
        Ib = total_Ib (known); S is back-derived so feeder_class.calculate() produces
        c.Ib = total_Ib exactly (same voltage used in both directions).
        """
        pf          = self.primary_feeder
        pf_source_V = self.actual_voltage_V   # voltage at incomer terminals (source side)

        # ── Populate feeder fields ────────────────────────────────────────────
        pf.phases        = self.phases
        pf.voltage       = pf_source_V
        pf.Ib            = self.total_Ib      # pre-set; calculate() will confirm it
        if self.phases == 3:
            pf.S = round(self.total_Ib * math.sqrt(3) * pf_source_V / 1000, 2)
        else:
            pf.S = round(self.total_Ib * pf_source_V / 1000, 2)
        pf.PF = self.composite_PF
        pf.P  = round(pf.S * self.composite_PF, 2) if pf.S else None

        # Propagate board frequency so X values scale correctly at 50/60 Hz
        pf.frequency       = self.frequency
        pf.cable.frequency = self.frequency

        # Ensure derating table exists (cable selector must have been run first)
        c = pf.cable
        if not c.conductor_table or c.k <= 0:
            c.calculate_derating()

        pf.cb.diversity = 1.0
        # ── Single unified calculation — same path as every outgoing feeder ───
        pf.calculate(self.isc_at_incomer_kA())

        # Root board (directly fed from transformer) incomer must be MCCB/ACB
        if self.level == 0 and pf.cb.cb_type == 'MCB':
            pf.cb.cb_type  = 'MCCB'
            pf.cb.standard = 'MCCB'

        # ── Update this board's actual busbar voltage ─────────────────────────
        if pf.result_vdrop_pct > 0:
            self.actual_voltage_V = pf_source_V * (1.0 - pf.result_vdrop_pct / 100.0)

        self.main_cb = pf.cb

    def _size_main_cb(self) -> None:
        """Size main incomer CB — uses primary feeder CB if available."""
        if self.primary_feeder_selected and self.primary_feeder.cb.In_CB > 0:
            self.main_cb = self.primary_feeder.cb
        else:
            # Fallback: size from total_Ib without cable constraint
            total_Ib = sum(f.Ib for f in self.feeders)
            self.main_cb.cb_type  = C_CB.auto_type(total_Ib)
            self.main_cb.standard = 'MCCB'
            self.main_cb.poles    = C_CB.auto_poles(self.phases)
            self.main_cb.size_cb(total_Ib, self.busbar_A, self.isc_at_incomer_kA())

    def isc_at_incomer_kA(self) -> float:
        """Prospective Isc at the incomer CB line terminals."""
        if self.level == 0:
            return self.transformer.Isc_lv_kA()
        parent = self.find_parent(self.board_id)
        if parent is not None:
            return parent.Isc_board_kA
        return self.Isc_board_kA

    def _coordinate_board_cbs(self) -> None:
        """Auto-set Icu_kA on incomer and outgoing CBs to next size ≥ fault level."""
        isc_bus = self.Isc_board_kA
        isc_inc = self.isc_at_incomer_kA()
        if self.primary_feeder_selected and self.primary_feeder.cb.In_CB > 0:
            self.primary_feeder.cb.coordinate_icu(isc_inc)
        if self.main_cb.In_CB > 0:
            self.main_cb.coordinate_icu(isc_inc)
        for f in self.feeders:
            if f.load_type in ('Space', 'Spare') or f.cb.In_CB <= 0:
                continue
            f.cb.coordinate_icu(isc_bus)

    def _feeder_demand_ib(self, f: C_Feeder) -> float:
        if f.load_type in ('Space', 'Spare'):
            return 0.0
        if f.load_type == 'SubPanel':
            return f.Ib
        if f.Ib_demand > 0:
            return f.Ib_demand
        return round(f.Ib * f.demand_factor(), 2)

    def _feeder_demand_s(self, f: C_Feeder) -> float:
        if f.load_type in ('Space', 'Spare'):
            return 0.0
        if f.load_type == 'SubPanel':
            return f.S or 0.0
        if f.S_demand is not None:
            return f.S_demand
        return round((f.S or 0) * f.demand_factor(), 2)

    def _feeder_demand_p(self, f: C_Feeder) -> float:
        if f.load_type in ('Space', 'Spare'):
            return 0.0
        if f.load_type == 'SubPanel':
            return f.P or 0.0
        if f.P_demand is not None:
            return f.P_demand
        return round((f.P or 0) * f.demand_factor(), 2)

    def _calc_totals(self, df_mode: str = 'per_load',
                     project_df_pct: float = 100.0) -> None:
        self.project_df_applied = False
        ib_conn = round(sum(f.Ib for f in self.feeders), 2)
        s_conn  = round(sum((f.S or 0) for f in self.feeders), 2)
        self.total_Ib_connected = ib_conn

        if df_mode == 'per_load':
            self.total_Ib    = round(sum(self._feeder_demand_ib(f)
                                       for f in self.feeders), 2)
            self.total_S_kVA = round(sum(self._feeder_demand_s(f)
                                         for f in self.feeders), 2)
            total_P = sum(self._feeder_demand_p(f) for f in self.feeders)
        else:
            self.total_Ib    = ib_conn
            self.total_S_kVA = s_conn
            total_P = sum((f.P or 0) for f in self.feeders)

        if (self.level == 0 and df_mode == 'project'
                and project_df_pct < 100.0):
            factor = max(0.0, min(100.0, project_df_pct)) / 100.0
            self.total_Ib_connected = self.total_Ib
            self.total_Ib    = round(self.total_Ib * factor, 2)
            self.total_S_kVA = round(self.total_S_kVA * factor, 2)
            total_P          = round(total_P * factor, 2)
            self.project_df_applied = True
            self.project_df_pct = project_df_pct

        if self.total_S_kVA > 0:
            pf_weighted = sum(
                self._feeder_demand_s(f) * (f.PF if f.PF is not None else 0.9)
                for f in self.feeders
                if f.load_type not in ('Space', 'Spare'))
            self.composite_PF = round(pf_weighted / self.total_S_kVA, 4)
        else:
            self.composite_PF = 0.9
        if self.composite_pf_override is not None:
            self.composite_PF = self.composite_pf_override
        if self.busbar_A > 0:
            self.busbar_loading = round((self.total_Ib / self.busbar_A) * 100, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # FEEDER MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────────

    def add_feeder(self, feeder: C_Feeder = None) -> C_Feeder:
        if feeder is None:
            feeder = C_Feeder()
            idx = len(self.feeders) + 1
            feeder.circuit_ref = f"F{idx}"
            feeder.name        = f"Feeder-{idx}"
            feeder.voltage     = self.voltage
            feeder.phases      = self.phases
            feeder.frequency   = self.frequency
        self.feeders.append(feeder)
        return feeder

    def remove_feeder(self, index: int) -> None:
        if 0 <= index < len(self.feeders):
            self.feeders.pop(index)

    def get_feeder(self, index: int) -> Optional[C_Feeder]:
        if 0 <= index < len(self.feeders):
            return self.feeders[index]
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # REPORT DATA
    # ─────────────────────────────────────────────────────────────────────────

    def feeder_summaries(self) -> list[dict]:
        return [f.summary() for f in self.feeders]

    def board_summary(self) -> dict:
        return {
            'name':           self.name,
            'voltage':        f"{self.voltage}V {self.phases}φ {self.frequency}Hz",
            'busbar':         f"{self.busbar_A}A",
            'frame':          self.frame,
            'IP':             self.IP,
            'mounting':       self.mounting,
            'Isc_board_kA':   f"{self.Isc_board_kA:.2f} kA",
            'total_Ib':       f"{self.total_Ib:.1f} A",
            'total_S_kVA':    f"{self.total_S_kVA:.1f} kVA",
            'busbar_loading': f"{self.busbar_loading:.1f}%",
            'main_CB':        f"{self.main_cb.In_CB:.0f}A {self.main_cb.cb_type}",
            'trafo':          f"{self.transformer.Sn_kVA}kVA Vk={self.transformer.Vk_pct}%",
            'Isc_trafo_kA':   f"{self.transformer.Isc_lv_kA():.2f} kA",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # SAVE / LOAD
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            'name': self.name, 'project': self.project,
            'location': self.location, 'drawing_ref': self.drawing_ref,
            'date': self.date, 'engineer': self.engineer,
            'voltage': self.voltage, 'phases': self.phases,
            'frequency': self.frequency, 'standard': self.standard,
            'busbar_A': self.busbar_A,
            'frame': self.frame, 'IP': self.IP,
            'mounting': self.mounting, 'manufacturer': self.manufacturer,
            'model': self.model,
            'transformer': self.transformer.to_dict(),
            'primary_feeder': self.primary_feeder.to_dict(),
            'primary_feeder_selected': self.primary_feeder_selected,
            'main_cb': self.main_cb.to_dict(),
            'Isc_board_kA': self.Isc_board_kA,
            'actual_voltage_V': self.actual_voltage_V,
            'panel_size': self.panel_size,
            'feeders': [f.to_dict() for f in self.feeders],
            'child_boards': [b.to_dict() for b in self.child_boards],
            'board_id': self.board_id, 'parent_id': self.parent_id,
            'level': self.level,
            'total_Ib': self.total_Ib,
            'total_S_kVA': self.total_S_kVA,
            'composite_pf_override': self.composite_pf_override,
            'busbar_loading': self.busbar_loading,
            'warnings': self.warnings,
            'interface_spec': self.interface_spec,
        }

    def save(self, path: str) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(path: str) -> 'C_Switchboard':
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return C_Switchboard.from_dict(d)

    @staticmethod
    def from_dict(d: dict) -> 'C_Switchboard':
        obj = C_Switchboard()
        for key in ['name','project','location','drawing_ref','date','engineer',
                    'voltage','phases','frequency','standard','busbar_A','frame','IP',
                    'mounting','manufacturer','model','Isc_board_kA',
                    'actual_voltage_V','panel_size',
                    'total_Ib','total_S_kVA','busbar_loading','warnings',
                    'primary_feeder_selected','board_id','parent_id','level',
                    'interface_spec']:
            if key in d: setattr(obj, key, d[key])
        if 'transformer' in d:
            obj.transformer = C_Transformer.from_dict(d['transformer'])
        if 'primary_feeder' in d:
            obj.primary_feeder = C_Feeder.from_dict(d['primary_feeder'])
        if 'main_cb' in d:
            obj.main_cb = C_CB.from_dict(d['main_cb'])
        obj.feeders = [C_Feeder.from_dict(f) for f in d.get('feeders', [])]
        obj.child_boards = [C_Switchboard.from_dict(b) for b in d.get('child_boards', [])]
        for k in ['board_id','parent_id','level']:
            if k in d: setattr(obj, k, d[k])
        obj.standard = normalize_project_standard(obj.standard)
        obj.frequency = KSA_FREQUENCY_HZ
        return obj

    # ─────────────────────────────────────────────────────────────────────────
    # COLLABORATION — federated sub-board packages
    # ─────────────────────────────────────────────────────────────────────────

    def export_subboard(self, feeder_idx: int, path: str) -> 'C_Switchboard':
        """
        Export a SubPanel feeder as a standalone .swb package for another engineer.

        1. Reads interface_spec from the feeder (must be set via set_stub_spec() first).
        2. Creates (or reuses) a child C_Switchboard with those constraints embedded.
        3. Saves the child .swb to path.
        4. Marks the feeder as stub — parent keeps allocated S/Ib for its own calc.
        5. Removes the child board from parent's child_boards (child lives externally).
        """
        import uuid
        f = self.feeders[feeder_idx]
        if f.load_type != 'SubPanel':
            raise ValueError("Only SubPanel feeders can be exported as packages.")
        if not f.interface_spec:
            raise ValueError("Set interface spec first (ribbon → Set Stub Spec).")

        spec = f.interface_spec

        # Find or build the child board
        existing = self.find_board(f.subpanel_id) if f.subpanel_id else None
        if existing:
            child = existing
        else:
            child = C_Switchboard()
            child.board_id   = uuid.uuid4().hex[:8]
            child.name       = f.name
            child.voltage    = spec.get('voltage', self.voltage)
            child.phases     = self.phases
            child.frequency  = self.frequency
            child.standard   = self.standard
            child.Isc_board_kA = spec.get('Isc_kA', 0.0)
            child.busbar_A   = math.ceil(spec.get('Ib_A', 0.0) * 1.25 / 100) * 100 or 400
            child.level      = self.level + 1
            child.parent_id  = self.board_id
            f.subpanel_id    = child.board_id

        child.interface_spec = spec.copy()
        child.save(path)

        # Mark feeder as stub; hold allocated values for parent calculations
        f.is_stub       = True
        f.stub_package  = path
        f.S             = spec.get('S_kVA', f.S or 0)
        f.P             = round(f.S * 0.9, 2)
        f.Ib            = spec.get('Ib_A',  f.Ib or 0)

        # Detach child from parent — it now lives in the external file
        self.child_boards = [b for b in self.child_boards
                             if b.board_id != child.board_id]
        return child

    def set_stub_spec(self, feeder_idx: int, spec: dict) -> None:
        """
        Set the interface specification on a SubPanel feeder.
        spec keys: S_kVA, Ib_A, Isc_kA, voltage, max_vd_pct, notes
        """
        f = self.feeders[feeder_idx]
        if f.load_type != 'SubPanel':
            raise ValueError("Interface spec only applies to SubPanel feeders.")
        f.interface_spec = spec.copy()
        # Pre-fill feeder load values from spec so parent calcs work immediately
        f.S   = spec.get('S_kVA', f.S or 0)
        f.P   = round(f.S * 0.9, 2)
        f.Ib  = spec.get('Ib_A',  f.Ib or 0)
        f.is_stub = True

    STRICT_TOLERANCE = 0.01   # 1 % rounding allowance

    def import_subboard(self, feeder_idx: int, path: str) -> tuple[bool, list[str]]:
        """
        Import an external .swb as the live child board for a stub feeder.

        Strict validation — ALL checks must pass:
          • Apparent power  : child.total_S_kVA  ≤ spec.S_kVA  (+ 1 % tolerance)
          • Load current    : child.total_Ib      ≤ spec.Ib_A   (+ 1 % tolerance)
          • Voltage drop    : primary feeder Vd%  ≤ spec.max_vd_pct (if selected)

        Returns (True, []) on success; (False, [error strings]) when blocked.
        On success the child board is attached and the feeder loses its stub status.
        """
        import uuid
        f = self.feeders[feeder_idx]
        spec = f.interface_spec
        if not spec:
            return False, ["No interface spec set on this feeder. "
                           "Use 'Set Stub Spec' first."]

        child = C_Switchboard.load(path)
        child.calculate_all()          # ensure totals are current

        tol = 1 + self.STRICT_TOLERANCE
        errors = []

        s_alloc = spec.get('S_kVA', 0)
        if s_alloc and child.total_S_kVA > s_alloc * tol:
            over = child.total_S_kVA - s_alloc
            pct  = over / s_alloc * 100
            errors.append(
                f"Apparent Power : actual {child.total_S_kVA:.1f} kVA  "
                f"> allocated {s_alloc:.1f} kVA  (+{pct:.1f} %)  — OVERLOAD")

        ib_alloc = spec.get('Ib_A', 0)
        if ib_alloc and child.total_Ib > ib_alloc * tol:
            over = child.total_Ib - ib_alloc
            pct  = over / ib_alloc * 100
            errors.append(
                f"Load Current   : actual {child.total_Ib:.1f} A  "
                f"> allocated {ib_alloc:.1f} A  (+{pct:.1f} %)  — OVERLOAD")

        vd_budget = spec.get('max_vd_pct', 0)
        if vd_budget and child.primary_feeder_selected:
            vd_actual = child.primary_feeder.result_vdrop_pct
            if vd_actual > vd_budget * tol:
                over = vd_actual - vd_budget
                errors.append(
                    f"Voltage Drop   : actual {vd_actual:.2f} %  "
                    f"> budget {vd_budget:.2f} %  (+{over:.2f} %)  — EXCEEDED")

        if errors:
            return False, errors

        # ── Attach child board ────────────────────────────────────────────────
        child.board_id   = f.subpanel_id or uuid.uuid4().hex[:8]
        f.subpanel_id    = child.board_id
        child.parent_id  = self.board_id
        child.level      = self.level + 1
        self._fix_child_levels(child)

        self.child_boards = [b for b in self.child_boards
                             if b.board_id != child.board_id]
        self.child_boards.append(child)

        f.is_stub      = False
        f.stub_package = path     # keep reference for traceability
        return True, []

    def _fix_child_levels(self, board: 'C_Switchboard') -> None:
        for ch in board.child_boards:
            ch.level = board.level + 1
            self._fix_child_levels(ch)

    # ── CHILD BOARD MANAGEMENT ───────────────────────────────────────────────

    # ── PANEL SIZE HELPERS ────────────────────────────────────────────────────
    @property
    def used_poles(self) -> int:
        """Total pole positions consumed by all feeders."""
        return sum(
            max(1, min(int(f.cb.poles or 1), 4))
            for f in self.feeders
            if f.load_type not in ('Spare', 'Space')
        )

    @property
    def effective_panel_size(self) -> int:
        """User-set panel_size, or next standard size above total poles used
        (including Spare and Space so the XLS sheet is correctly sized)."""
        if self.panel_size > 0:
            return self.panel_size
        # Count ALL poles including spare/space for sheet sizing
        total = sum(
            max(1, min(int(f.cb.poles or 1), 4))
            for f in self.feeders
        )
        for s in PANEL_SIZES:
            if s >= total:
                return s
        # Above largest standard size — use actual pole count (even, min 12)
        even = total if total % 2 == 0 else total + 1
        return max(even, 12)

    def generate_spare_space(self) -> None:
        """
        Remove all existing Spare/Space feeders and regenerate:
          Spare = 20% of circuit count (≥ 1)
          Space = 10% of circuit count (≥ 1)
        Appended after real feeders.
        """
        # Remove old Spare/Space
        self.feeders = [f for f in self.feeders
                        if f.load_type not in ('Spare', 'Space')]

        n_circuits    = len(self.feeders)
        n_spare_poles = max(1, round(n_circuits * 0.20))
        n_space_poles = max(1, round(n_circuits * 0.10))

        # Spare feeders — 20A-1P each (1 pole per feeder)
        for i in range(n_spare_poles):
            f = C_Feeder()
            f.name       = 'SPARE'
            f.load_type  = 'Spare'
            f.phase_str  = 'L1'   # will be balanced by phase balancer
            f.phases     = 1
            f.voltage    = self.voltage
            f.P          = 0.0
            f.S          = 0.0
            f.PF         = 1.0
            f.cable_length  = 10.0
            f.max_vdrop_pct = 3.0
            f.cb.In_CB   = 20.0
            f.cb.poles   = 1
            f.cb.cb_type = 'MCB'
            f.cb.curve   = 'C'
            self.feeders.append(f)

        # Space feeders — no CB, no cable, no load
        for i in range(n_space_poles):
            f = C_Feeder()
            f.name      = 'SPACE'
            f.load_type = 'Space'
            f.phase_str = 'L1'
            f.phases    = 1
            f.voltage   = self.voltage
            f.P         = 0.0
            f.S         = 0.0
            f.PF        = 1.0
            f.cb.In_CB  = 0.0
            f.cb.poles  = 1
            self.feeders.append(f)

    def add_child_board(self, name: str = '') -> Optional['C_Switchboard']:
        if self.level >= 10:
            return None
        child = C_Switchboard()
        child.board_id  = uuid.uuid4().hex[:8]
        child.parent_id = self.board_id
        child.level     = self.level + 1
        child.voltage          = self.voltage
        child.actual_voltage_V = self.actual_voltage_V
        child.phases    = self.phases
        child.frequency = self.frequency
        child.name      = name or f'SDB-{len(self.child_boards)+1}'
        # Mirror as a feeder row
        feeder = C_Feeder()
        feeder.name        = child.name
        feeder.circuit_ref = f'SP{len(self.child_boards)+1}'
        feeder.load_type   = 'SubPanel'
        feeder.subpanel_id = child.board_id
        feeder.phases      = self.phases
        feeder.voltage     = self.voltage
        feeder.phase_str   = 'L123'
        self.feeders.append(feeder)
        self.child_boards.append(child)
        return child

    def remove_child_board(self, board_id: str) -> None:
        self.child_boards = [b for b in self.child_boards if b.board_id != board_id]
        self.feeders = [f for f in self.feeders if f.subpanel_id != board_id]

    def find_board(self, board_id: str) -> Optional['C_Switchboard']:
        if self.board_id == board_id:
            return self
        for child in self.child_boards:
            found = child.find_board(board_id)
            if found:
                return found
        return None

    def find_parent(self, board_id: str) -> Optional['C_Switchboard']:
        for child in self.child_boards:
            if child.board_id == board_id:
                return self
            found = child.find_parent(board_id)
            if found:
                return found
        return None

    def all_boards(self) -> list:
        result = [self]
        for child in self.child_boards:
            result.extend(child.all_boards())
        return result

    def clear_all_warnings(self) -> None:
        """Reset all warning lists before a full recalculation."""
        self.warnings = []
        for board in self.all_boards():
            board.warnings = []
            targets = list(board.feeders)
            if board.primary_feeder_selected:
                targets.append(board.primary_feeder)
            for f in targets:
                f.warnings = []
                f.cable.warnings = []
                f.cb.warnings = []
                if getattr(f, 'motor_configured', False):
                    f.motor.warnings = []

    def __repr__(self) -> str:
        return (f"C_Switchboard('{self.name}' | "
                f"{self.voltage}V {self.phases}φ | "
                f"{len(self.feeders)} feeders | "
                f"Isc={self.Isc_board_kA:.2f}kA | "
                f"Load={self.busbar_loading:.1f}%)")
