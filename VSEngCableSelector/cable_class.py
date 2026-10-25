# cable_class.py
# C_Cable and ConductorRow
# IEC 60364-5-52 compliant voltage drop:
#   ≤50mm² non-trefoil : R only (X negligible per IEC)
#   >50mm² trefoil     : R·cosφ + X·sinφ (exact Annex E)
#   >50mm² non-trefoil : R·cosφ + X_trefoil·sinφ (approximation, flagged)

from __future__ import annotations
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional
from .cable_data import (
    DATA_1C, ARR_COL, DATA_1C_XLPE_AMP, ARR_COL_XLPE,
    DATA_MC_2C_PVC, DATA_MC_3C_PVC, DATA_MC_4C_PVC,
    DATA_MC_2C_XLPE, DATA_MC_3C_XLPE, DATA_MC_4C_XLPE,
    MC_METHOD_COL,
    TC1, TC2, TC3, TC4, TC5, TC6, TC7, TC8, TC9,
    TC8_CABLES_IDX, TC9_CIRC_IDX,
    closest_key
)

# ─── CONDUCTOR ROW ────────────────────────────────────────────────────────────

@dataclass
class ConductorRow:
    size_mm2:    float
    shape:       str          # 'rm' | 'sm' | '-' (1C)
    dc20:        float        # Ω/km DC at 20°C
    ac70:        float        # Ω/km AC at 70°C (PVC)
    ac90:        float        # Ω/km AC at 90°C (XLPE)
    In:          float        # Catalogue ampacity (A)
    X:           Optional[float]  # Ω/km reactance (None if non-trefoil 1C)
    X_trefoil:   Optional[float]  # Ω/km trefoil X — always populated for fallback
    Z:           Optional[float]  # Ω/km impedance
    Z_trefoil:   Optional[float]  # Ω/km trefoil Z — always populated for fallback
    C:           Optional[float]  # µF/km
    diameter:    float
    weight:      float
    cable_code:  str

    # Calculated fields
    Iz:           float = 0.0
    vdrop_v:      float = 0.0
    vdrop_pct:    float = 0.0
    passes_amp:   bool  = False
    passes_vdrop: bool  = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> 'ConductorRow':
        # Handle legacy saves missing new fields
        d.setdefault('X_trefoil', d.get('X'))
        d.setdefault('Z_trefoil', d.get('Z'))
        return ConductorRow(**d)


MAX_PARALLEL_SETS = 6


# ─── CABLE CLASS ──────────────────────────────────────────────────────────────

@dataclass
class C_Cable:
    # ── SELECTION INPUTS ──────────────────────────────────────────────────────
    insulation:     str = 'PVC'
    core_config:    str = '1C'
    install_method: str = 'air'
    arrangement:    str = 'e'

    # ── k1 ────────────────────────────────────────────────────────────────────
    ambient_temp:   float = 40.0

    # ── k2 (buried/duct only) ─────────────────────────────────────────────────
    burial_depth:     float = 0.50
    soil_resistivity: float = 1.5

    # ── k3 buried/duct ────────────────────────────────────────────────────────
    num_circuits:  int   = 1
    clearance:     str   = 'touch'

    # ── k3 free air ───────────────────────────────────────────────────────────
    tray_type:       str = 'hperf'
    spacing:         str = 'touch'
    num_trays:       int = 1
    cables_per_tray: int = 1
    parallel_cables: int = 1   # parallel cable sets (1-6)

    # ── MATERIAL ──────────────────────────────────────────────────────────────
    conductor:       str = 'CU'   # 'CU' | 'AL'

    # ── DERATING OUTPUTS ──────────────────────────────────────────────────────
    k1: float = 1.0
    k2: float = 1.0
    k3: float = 1.0
    k_parallel: float = 1.0
    k:  float = 1.0

    # ── CONDUCTOR TABLE ───────────────────────────────────────────────────────
    conductor_table: list = field(default_factory=list)

    # ── FREQUENCY / STANDARD ─────────────────────────────────────────────────
    # Catalogue R/X data at 60 Hz (KSA)
    # X values in DATA_* tables are at 60 Hz; X ∝ f, so scaled on table build.
    frequency:      float = 60.0   # KSA network — fixed 60 Hz

    # ── PROJECT CONSTRAINTS ───────────────────────────────────────────────────
    min_conductor_mm2: float = 1.5   # project minimum — set at runtime, not serialised

    # ── CALCULATION INPUTS ────────────────────────────────────────────────────
    phases:         int   = 3
    voltage:        float = 400.0
    P:              Optional[float] = None
    S:              Optional[float] = None
    PF:             Optional[float] = None
    cable_length:   float = 100.0
    max_vdrop_pct:  float = 3.0

    # ── SIZING MODE ───────────────────────────────────────────────────────────
    manual_sizing:    bool  = False   # True → user locked a cable; auto-select skipped

    # ── CALCULATION OUTPUTS ───────────────────────────────────────────────────
    Ib:               float = 0.0
    recommended:      Optional[ConductorRow] = None
    result_vdrop_v:   float = 0.0
    result_vdrop_pct: float = 0.0
    passes_ampacity:  bool  = False
    passes_vdrop:     bool  = False
    warnings:         list  = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────────────────────────────────────

    def is_valid_selection(self) -> tuple[bool, list[str]]:
        errs = []
        if self.insulation not in ('PVC', 'XLPE'):
            errs.append("Insulation must be PVC or XLPE.")
        if self.core_config not in ('1C', '2C', '3C', '4C'):
            errs.append("Core config must be 1C, 2C, 3C or 4C.")
        if self.install_method not in ('air', 'buried', 'duct'):
            errs.append("Install method must be air, buried or duct.")
        if self.core_config == '1C' and self.arrangement not in tuple('abcdefg'):
            errs.append("Arrangement must be a–g for 1C cables.")
        if self.ambient_temp not in TC1:
            errs.append(f"Ambient temp must be one of: {sorted(TC1.keys())} °C.")
        return len(errs) == 0, errs

    def is_valid_calculation(self) -> tuple[bool, list[str]]:
        errs = []
        given = sum(x is not None for x in [self.P, self.S, self.PF])
        if given < 2:
            errs.append("At least two of P, S, PF must be provided.")
        if self.voltage <= 0:
            errs.append("Voltage must be > 0.")
        if self.cable_length <= 0:
            errs.append("Cable length must be > 0.")
        if self.max_vdrop_pct <= 0:
            errs.append("Max voltage drop must be > 0%.")
        if self.phases not in (1, 2, 3):
            # 1 = L-N single-phase, 2 = L-L single-phase (L12/L13/L23), 3 = 3-phase
            errs.append("Phases must be 1, 2 or 3.")
        if not self.conductor_table:
            errs.append("No conductor table — run calculate_derating() first.")
        return len(errs) == 0, errs

    # ─────────────────────────────────────────────────────────────────────────
    # K1
    # ─────────────────────────────────────────────────────────────────────────

    def _calc_k1(self) -> float:
        col   = 1 if self.insulation == 'XLPE' else 0
        table = TC2 if self.install_method == 'air' else TC1
        key   = closest_key(table, self.ambient_temp)
        return table[key][col]

    # ─────────────────────────────────────────────────────────────────────────
    # K2
    # ─────────────────────────────────────────────────────────────────────────

    def _calc_k2(self) -> float:
        if self.install_method == 'air':
            return 1.0
        depth_key = closest_key(TC3, self.burial_depth)
        depth_f   = TC3[depth_key][1]   # default mid-range col
        res_key   = closest_key(TC4, self.soil_resistivity)
        duct_col  = 1 if self.install_method == 'duct' else 0
        res_f     = TC4[res_key][duct_col]
        return round(depth_f * res_f, 4)

    def _k2_for_size(self, size_mm2: float) -> float:
        if self.install_method == 'air':
            return 1.0
        depth_key = closest_key(TC3, self.burial_depth)
        size_col  = 0 if size_mm2 <= 70 else (1 if size_mm2 <= 240 else 2)
        depth_f   = TC3[depth_key][size_col]
        res_key   = closest_key(TC4, self.soil_resistivity)
        duct_col  = 1 if self.install_method == 'duct' else 0
        res_f     = TC4[res_key][duct_col]
        return round(depth_f * res_f, 4)

    # ─────────────────────────────────────────────────────────────────────────
    # K3
    # ─────────────────────────────────────────────────────────────────────────

    def _calc_k3(self) -> float:
        method = self.install_method
        is_1c  = self.core_config == '1C'
        n      = int(self.num_circuits)
        cpt    = int(self.cables_per_tray)

        if method == 'buried':
            if n <= 1: return 1.0
            clr_map = {'touch':0,'1D':1,'0.125':2,'0.25':3,'0.5':4}
            clr_idx = clr_map.get(str(self.clearance), 0)
            key = closest_key(TC5, n)
            return TC5[key][clr_idx]

        if method == 'duct':
            if n <= 1: return 1.0
            clr_map = {'touch':0,'0.25':1,'0.5':2,'1.0':3}
            clr_idx = clr_map.get(str(self.clearance), 0)
            table   = TC6 if is_1c else TC7
            key     = closest_key(table, n)
            return table[key][clr_idx]

        if method == 'air':
            tray = self.tray_type
            spc  = self.spacing
            nt   = int(self.num_trays)
            if is_1c:
                is_trefoil = self.arrangement in ('a','c','e')
                arr_key    = 'trefoil' if is_trefoil else 'flat'
                tbl        = TC9.get(tray, TC9['hperf']).get(arr_key, {})
                tray_key   = closest_key(tbl, nt)
                # Find closest supported circuit count (no cap at 3)
                circ_n     = closest_key({i:i for i in TC9_CIRC_IDX}, cpt)
                circ_idx   = TC9_CIRC_IDX.index(circ_n) if circ_n in TC9_CIRC_IDX else 0
                vals       = tbl.get(tray_key, [1.0]*3)
                val        = vals[circ_idx] if circ_idx < len(vals) else vals[-1]
                return val if val is not None else 1.0
            else:
                tbl = TC8.get(tray, TC8['hperf']).get(spc, {})
                if not tbl:
                    tbl = TC8.get(tray, TC8['hperf']).get('touch', {})
                tray_key     = closest_key(tbl, nt)
                best_cab_idx = 0
                for i, c in enumerate(TC8_CABLES_IDX):
                    if c <= cpt: best_cab_idx = i
                val = tbl[tray_key][best_cab_idx]
                return val if val is not None else 1.0

        return 1.0

    # ─────────────────────────────────────────────────────────────────────────
    # BUILD CONDUCTOR TABLE
    # ─────────────────────────────────────────────────────────────────────────

    def _build_conductor_table(self) -> list[ConductorRow]:
        rows       = []
        is_xlpe    = self.insulation == 'XLPE'
        is_trefoil = self.arrangement in ('a', 'c', 'e')
        # X ∝ frequency: data tables hold 60 Hz values; scale for IEC 50 Hz etc.
        fq = self.frequency / 60.0

        def _scaled_xz(X60, R):
            """Return (X_f, Z_f) scaled to operating frequency."""
            if X60 is None:
                return None, None
            X_f = round(X60 * fq, 4)
            Z_f = round(math.sqrt(R ** 2 + X_f ** 2), 4) if R else X_f
            return X_f, Z_f

        if self.core_config == '1C':
            arr = self.arrangement
            pvc_col = ARR_COL[arr]
            # Build XLPE ampacity lookup keyed by conductor size
            _xlpe_amp = {row[0]: row for row in DATA_1C_XLPE_AMP}

            for d in DATA_1C:
                size = d[0]
                if is_xlpe:
                    X_t60, _, C_v = d[20], d[21], d[22]   # X_xlpe, Z_xlpe, C_xlpe
                    R    = d[3]                             # ac90 resistance for XLPE
                    xlpe_row = _xlpe_amp.get(size)
                    In   = xlpe_row[ARR_COL_XLPE[arr]] if xlpe_row else d[pvc_col]
                    diam = d[14]; wt = d[15]; code = d[16]  # XLPE physical data
                else:
                    X_t60, _, C_v = d[17], d[18], d[19]   # X_pvc, Z_pvc, C_pvc
                    R    = d[2]                             # ac70 resistance for PVC
                    In   = d[pvc_col]
                    diam = d[11]; wt = d[12]; code = d[13]  # PVC physical data

                X_t, Z_t = _scaled_xz(X_t60, R)
                X_use, Z_use = (X_t, Z_t) if is_trefoil else (None, None)

                rows.append(ConductorRow(
                    size_mm2=size, shape='-',
                    dc20=d[1], ac70=d[2], ac90=d[3],
                    In=In,
                    X=X_use, X_trefoil=X_t,
                    Z=Z_use, Z_trefoil=Z_t,
                    C=C_v,
                    diameter=diam, weight=wt,
                    cable_code=code
                ))
        else:
            ds_map = {
                ('2C', 'PVC'):  DATA_MC_2C_PVC,  ('3C', 'PVC'):  DATA_MC_3C_PVC,
                ('4C', 'PVC'):  DATA_MC_4C_PVC,
                ('2C', 'XLPE'): DATA_MC_2C_XLPE, ('3C', 'XLPE'): DATA_MC_3C_XLPE,
                ('4C', 'XLPE'): DATA_MC_4C_XLPE,
            }
            dataset = ds_map.get((self.core_config, self.insulation), [])
            col     = MC_METHOD_COL[self.install_method]
            for d in dataset:
                if is_xlpe:
                    X_v60, _, C_v = d[14], d[15], d[16]
                    R = d[4]   # ac90
                else:
                    X_v60, _, C_v = d[11], d[12], d[13]
                    R = d[3]   # ac70
                X_v, Z_v = _scaled_xz(X_v60, R)
                rows.append(ConductorRow(
                    size_mm2=d[0], shape=d[1],
                    dc20=d[2], ac70=d[3], ac90=d[4],
                    In=d[col],
                    X=X_v, X_trefoil=X_v,
                    Z=Z_v, Z_trefoil=Z_v,
                    C=C_v,
                    diameter=d[8], weight=d[9],
                    cable_code=d[10]
                ))
        return rows

    # ─────────────────────────────────────────────────────────────────────────
    # CALCULATE DERATING
    # ─────────────────────────────────────────────────────────────────────────

    def _calc_k_parallel(self) -> float:
        """
        IEC 60364-5-52 Table B.52.17 — derating for parallel cable sets.
        Returns derating factor based on number of parallel sets installed together.
        n=1 → 1.0 (no derating needed)
        n=2..6 → IEC values for flat touching or trefoil arrangement
        """
        n = self.parallel_cables
        if n <= 1:
            return 1.0
        is_trefoil = self.arrangement in ('a', 'c', 'e')
        # IEC 60364-5-52 Table B.52.17
        k_flat    = {2: 0.87, 3: 0.82, 4: 0.77, 5: 0.75, 6: 0.73}
        k_trefoil = {2: 0.90, 3: 0.85, 4: 0.79, 5: 0.76, 6: 0.73}
        table = k_trefoil if is_trefoil else k_flat
        return table.get(min(n, 6), 0.73)

    def calculate_derating(self) -> None:
        self.k1         = self._calc_k1()
        self.k2         = self._calc_k2()
        self.k3         = self._calc_k3()
        self.k          = round(self.k1 * self.k2 * self.k3, 4)
        self.k_parallel = self._calc_k_parallel()
        self.conductor_table = self._build_conductor_table()

    def relink_recommended(self) -> None:
        """Point recommended at the matching row in conductor_table (after rebuild)."""
        rec = self.recommended
        if rec is None or not self.conductor_table:
            return
        code = getattr(rec, 'cable_code', None)
        size = getattr(rec, 'size_mm2', None)
        for row in self.conductor_table:
            if code and row.cable_code == code:
                self.recommended = row
                return
            if size is not None and abs(row.size_mm2 - size) < 0.01:
                self.recommended = row
                return

    def ensure_conductor_table(self) -> bool:
        """
        Build conductor_table when Q1–Q4 are valid but the catalogue list is missing.
        Handles saved sessions that retained recommended/k factors without the table.
        """
        if self.conductor_table:
            self.relink_recommended()
            return True
        if self.k > 0:
            try:
                self.conductor_table = self._build_conductor_table()
                self.relink_recommended()
                if self.conductor_table:
                    return True
            except Exception:
                pass
        ok_sel, _ = self.is_valid_selection()
        if not ok_sel:
            return False
        try:
            self.calculate_derating()
            self.relink_recommended()
        except Exception:
            return False
        return bool(self.conductor_table)

    # ─────────────────────────────────────────────────────────────────────────
    # IEC-COMPLIANT VOLTAGE DROP  (IEC 60364-5-52 Annex G)
    # ─────────────────────────────────────────────────────────────────────────

    def _vdrop(self, row: ConductorRow, Ib: float) -> tuple[float, float, list[str]]:
        """
        IEC 60364-5-52 voltage drop.
        Returns (vdrop_V, vdrop_pct, warnings).

        Rules:
          ≤50mm², non-trefoil  → R only (IEC permits ignoring X)
          >50mm², trefoil      → R·cosφ + X·sinφ  (exact Annex E)
          >50mm², non-trefoil  → R·cosφ + X_trefoil·sinφ  (approx, flagged)
          MC cables            → R·cosφ + X·sinφ  always (X always available)
        """
        warns  = []
        is_1c  = self.core_config == '1C'
        is_trefoil = self.arrangement in ('a','c','e') if is_1c else True
        R      = row.ac90 if self.insulation == 'XLPE' else row.ac70
        PF     = self.PF if self.PF is not None else 0.9
        cosφ   = PF
        sinφ   = math.sqrt(max(0.0, 1.0 - cosφ**2))
        L_km   = self.cable_length / 1000.0
        b      = math.sqrt(3) if self.phases == 3 else 2.0
        if is_1c and not is_trefoil:
            if row.size_mm2 <= 50:
                # IEC 60364-5-52: X negligible for ≤50mm² — no warning
                effective_Z = R * cosφ
            else:
                # Use trefoil X as approximation
                X_approx = row.X_trefoil or 0.0
                effective_Z = R * cosφ + X_approx * sinφ
                arr_name = {
                    'b':'Flat Touched (buried)',  'd':'Flat Touched (duct)',
                    'f':'Flat Touched (air)',     'g':'Flat Spaced (air)'
                }.get(self.arrangement, self.arrangement)
                warns.append(
                    f"X not published for {arr_name} arrangement "
                    f"(trefoil values only in catalogue). "
                    f"Trefoil X = {X_approx:.3f} Ω/km used as approximation "
                    f"for {row.size_mm2}mm² (conservative for flat-touching, "
                    f"slightly optimistic for flat-spaced)."
                )
        else:
            # Trefoil 1C or any MC — use published X
            X = row.X if row.X is not None else 0.0
            effective_Z = R * cosφ + X * sinφ

        vdrop     = b * Ib * L_km * effective_Z
        vdrop_pct = (vdrop / self.voltage) * 100.0
        return round(vdrop, 3), round(vdrop_pct, 3), warns

    # ─────────────────────────────────────────────────────────────────────────
    # DERIVE MISSING P/S/PF
    # ─────────────────────────────────────────────────────────────────────────

    def _derive_power(self) -> None:
        P, S, PF = self.P, self.S, self.PF
        if P is None and S is not None and PF is not None:
            self.P = round(S * PF, 4)
        elif S is None and P is not None and PF is not None:
            self.S = round(P / PF, 4) if PF != 0 else None
        elif PF is None and P is not None and S is not None:
            self.PF = round(P / S, 4) if S != 0 else None

    # ─────────────────────────────────────────────────────────────────────────
    # CALCULATE LOAD
    # ─────────────────────────────────────────────────────────────────────────

    def set_parallel_count(self, n: int) -> None:
        """Set parallel cable sets (1–MAX_PARALLEL_SETS) and refresh k_parallel."""
        self.parallel_cables = max(1, min(int(n), MAX_PARALLEL_SETS))
        self.k_parallel = self._calc_k_parallel()

    def _row_iz(self, row: ConductorRow) -> float:
        n = max(self.parallel_cables, 1)
        k4 = self.k_parallel
        k2 = self._k2_for_size(row.size_mm2)
        k_tot = round(self.k1 * k2 * self.k3 * k4, 4)
        return round(row.In * n * k_tot, 2)

    def _evaluate_row(self, row: ConductorRow, x_warn_issued: bool
                      ) -> tuple[bool, bool, float, float, list[str], bool]:
        """Returns (pass_amp, pass_vd, vd_v, vd_pct, vd_warns, x_warn_issued)."""
        iz = self._row_iz(row)
        n = max(self.parallel_cables, 1)
        ib_per = self.Ib / n
        vd_v, vd_pct, vd_warns = self._vdrop(row, ib_per)
        if vd_warns and not x_warn_issued:
            x_warn_issued = True
        row.Iz = iz
        row.vdrop_v = vd_v
        row.vdrop_pct = vd_pct
        row.passes_amp = iz >= self.Ib
        row.passes_vdrop = vd_pct <= self.max_vdrop_pct
        return row.passes_amp, row.passes_vdrop, vd_v, vd_pct, vd_warns, x_warn_issued

    def calculate_load(self) -> None:
        self.warnings = []
        self._derive_power()

        PF = self.PF if self.PF is not None else 1.0
        S  = self.S
        if S is None and self.P is not None:
            S = self.P / PF if PF != 0 else 0

        if S is None:
            self.warnings.append("Could not determine S (kVA). Check P/S/PF inputs.")
            return

        if self.phases == 3:
            self.Ib = round((S * 1000.0) / (math.sqrt(3) * self.voltage), 3)
        else:
            self.Ib = round((S * 1000.0) / self.voltage, 3)

        if self.manual_sizing:
            if self.recommended:
                x_warn_issued = False
                pass_amp, pass_vd, _, _, vd_warns, x_warn_issued = (
                    self._evaluate_row(self.recommended, x_warn_issued))
                if vd_warns:
                    self.warnings.extend(vd_warns)
                self.passes_ampacity = pass_amp
                self.passes_vdrop = pass_vd
            return

        if not self.conductor_table:
            self.warnings.append("ERROR: No conductor catalogue. Run Cable Selector first.")
            return

        self.recommended = None
        x_warn_issued = False
        saved_n = max(self.parallel_cables, 1)
        found = False
        largest = self.conductor_table[-1]

        self.set_parallel_count(1)
        for row in self.conductor_table:
            pass_amp, pass_vd, _, _, vd_warns, x_warn_issued = (
                self._evaluate_row(row, x_warn_issued))
            if vd_warns:
                self.warnings.extend(vd_warns)
            if pass_amp and pass_vd:
                self.recommended = row
                found = True
                break

        if not found:
            for n in range(2, MAX_PARALLEL_SETS + 1):
                self.set_parallel_count(n)
                pass_amp, pass_vd, _, _, vd_warns, x_warn_issued = (
                    self._evaluate_row(largest, x_warn_issued))
                if vd_warns:
                    self.warnings.extend(vd_warns)
                if pass_amp and pass_vd:
                    self.recommended = largest
                    found = True
                    break

        if found:
            self._evaluate_row(self.recommended, x_warn_issued)
        else:
            # No compliant size — escalate parallel sets on largest catalogue row
            largest = self.conductor_table[-1]
            fallback: tuple[int, ConductorRow] | None = None
            for n in range(1, MAX_PARALLEL_SETS + 1):
                self.set_parallel_count(n)
                pass_amp, pass_vd, _, _, vd_warns, x_warn_issued = (
                    self._evaluate_row(largest, x_warn_issued))
                if vd_warns:
                    self.warnings.extend(vd_warns)
                if pass_amp:
                    fallback = (n, largest)
                    if pass_vd:
                        break
            if fallback is not None:
                n, row = fallback
                self.set_parallel_count(n)
                self._evaluate_row(row, x_warn_issued)
                self.recommended = row
                if not row.passes_vdrop:
                    self.warnings.append(
                        f"ΔU {row.vdrop_pct:.2f}% exceeds limit {self.max_vdrop_pct:.1f}% "
                        f"({n}×{row.size_mm2:.0f}mm² — largest in catalogue).")
            else:
                self.set_parallel_count(saved_n)
                self.warnings.append(
                    f"ERROR: Load {self.Ib:.0f}A exceeds ampacity of "
                    f"{MAX_PARALLEL_SETS}× largest conductor "
                    f"({largest.size_mm2:.0f}mm²) in catalogue.")
                return

        # Enforce project minimum conductor size
        if self.recommended is not None and self.recommended.size_mm2 < self.min_conductor_mm2:
            compliant = [r for r in self.conductor_table
                         if r.size_mm2 >= self.min_conductor_mm2]
            if compliant:
                largest_ok = compliant[-1]
                found = False
                self.set_parallel_count(1)
                for row in compliant:
                    pass_amp, pass_vd, _, _, _, _ = self._evaluate_row(
                        row, x_warn_issued)
                    if pass_amp and pass_vd:
                        self.recommended = row
                        found = True
                        break
                if not found:
                    for try_n in range(2, MAX_PARALLEL_SETS + 1):
                        self.set_parallel_count(try_n)
                        pass_amp, pass_vd, _, _, _, _ = self._evaluate_row(
                            largest_ok, x_warn_issued)
                        if pass_amp and pass_vd:
                            self.recommended = largest_ok
                            found = True
                            break
                if not found:
                    self.recommended = compliant[0]
                    self._evaluate_row(self.recommended, x_warn_issued)

        r = self.recommended
        if r is None:
            return
        self.result_vdrop_v   = r.vdrop_v
        self.result_vdrop_pct = r.vdrop_pct
        self.passes_ampacity  = r.passes_amp
        self.passes_vdrop     = r.passes_vdrop

    # ─────────────────────────────────────────────────────────────────────────
    # IMPEDANCE FOR ISC CHAIN
    # ─────────────────────────────────────────────────────────────────────────

    def get_impedance(self) -> tuple[float, float]:
        """
        Return (R_total, X_total) in Ω for the cable run.
        Used by Switchboard Isc chain.
        R uses ac90/ac70 at rated temp.
        X uses trefoil value (best available).
        """
        if not self.recommended:
            return 0.0, 0.0
        r   = self.recommended
        n   = max(int(getattr(self, 'parallel_cables', 1) or 1), 1)
        R   = (r.ac90 if self.insulation == 'XLPE' else r.ac70) * (self.cable_length / 1000.0) / n
        X_t = r.X_trefoil or r.X or 0.0
        X   = X_t * (self.cable_length / 1000.0) / n
        return round(R, 6), round(X, 6)

    # ─────────────────────────────────────────────────────────────────────────
    # SAVE / LOAD
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    # CONDUCTOR DESCRIPTION
    # ─────────────────────────────────────────────────────────────────────────

    _STD_GROUND_SIZES = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95,
                         120, 150, 185, 240, 300, 400, 500, 630]

    def _ground_size(self, phase_size: float) -> float:
        if phase_size <= 16.0:
            return phase_size
        half = phase_size / 2.0
        avail = sorted(set(r.size_mm2 for r in self.conductor_table)) if self.conductor_table else []
        for s in avail:
            if s >= half:
                return s
        for s in self._STD_GROUND_SIZES:
            if s >= half:
                return s
        return self._STD_GROUND_SIZES[-1]

    def format_conductor_desc(self, phases: Optional[int] = None) -> str:
        if not self.recommended:
            return '—'
        ph    = phases if phases is not None else self.phases
        is1c  = self.core_config == '1C'
        size  = self.recommended.size_mm2
        n_par = max(int(self.parallel_cables or 1), 1)
        ins   = self.insulation       # 'PVC' | 'XLPE'

        def _fs(v: float) -> str:
            return str(int(v)) if v == int(v) else str(v)

        n_act  = {3: 4, 2: 3, 1: 2}.get(ph, 4)
        g_size = self._ground_size(size)
        s_str  = _fs(size)
        g_str  = _fs(g_size)

        # Option C — minimal: Nx SIZE/EARTH INS  |  nC SIZE/EARTH INS
        if is1c:
            core = f'{n_act}×{s_str}/{g_str} {ins}'
            return f'{n_par}×{core}' if n_par > 1 else core
        else:
            core = f'{n_act}C{s_str} + {g_str} {ins}'
            return f'{n_par}S {core}' if n_par > 1 else core

    # ─────────────────────────────────────────────────────────────────────────
    # SAVE / LOAD (overwritten below)
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            'insulation':      self.insulation,
            'core_config':     self.core_config,
            'install_method':  self.install_method,
            'arrangement':     self.arrangement,
            'ambient_temp':    self.ambient_temp,
            'burial_depth':    self.burial_depth,
            'soil_resistivity': self.soil_resistivity,
            'num_circuits':    self.num_circuits,
            'clearance':       self.clearance,
            'tray_type':       self.tray_type,
            'spacing':         self.spacing,
            'num_trays':       self.num_trays,
            'cables_per_tray': self.cables_per_tray,
            'parallel_cables': self.parallel_cables,
            'conductor':       self.conductor,
            'k1': self.k1, 'k2': self.k2, 'k3': self.k3, 'k': self.k,
            'frequency':       self.frequency,
            'phases':          self.phases,
            'voltage':         self.voltage,
            'P': self.P, 'S': self.S, 'PF': self.PF,
            'cable_length':    self.cable_length,
            'max_vdrop_pct':   self.max_vdrop_pct,
            'Ib':              self.Ib,
            'result_vdrop_v':  self.result_vdrop_v,
            'result_vdrop_pct': self.result_vdrop_pct,
            'passes_ampacity': self.passes_ampacity,
            'passes_vdrop':    self.passes_vdrop,
            'warnings':        self.warnings,
            'conductor_table': [r.to_dict() for r in self.conductor_table],
            'recommended':     self.recommended.to_dict() if self.recommended else None,
            'manual_sizing':   self.manual_sizing,
        }

    def save(self, path: str) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(path: str) -> 'C_Cable':
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return C_Cable.from_dict(d)

    @staticmethod
    def from_dict(d: dict) -> 'C_Cable':
        obj = C_Cable()
        for key in ['insulation','core_config','install_method','arrangement',
                    'ambient_temp','burial_depth','soil_resistivity','num_circuits',
                    'clearance','tray_type','spacing','num_trays','cables_per_tray','parallel_cables',
                    'conductor',
                    'k1','k2','k3','k','frequency','phases','voltage','P','S','PF',
                    'cable_length','max_vdrop_pct','Ib','result_vdrop_v',
                    'result_vdrop_pct','passes_ampacity','passes_vdrop','warnings']:
            if key in d:
                setattr(obj, key, d[key])
        obj.conductor_table = [ConductorRow.from_dict(r) for r in d.get('conductor_table', [])]
        obj.recommended     = ConductorRow.from_dict(d['recommended']) if d.get('recommended') else None
        obj.manual_sizing   = bool(d.get('manual_sizing', False))
        return obj

    def __repr__(self) -> str:
        return (f"C_Cable({self.core_config} {self.insulation} | "
                f"{self.install_method} | k={self.k:.3f} | "
                f"Ib={self.Ib:.1f}A | rec={self.recommended.size_mm2 if self.recommended else 'None'}mm²)")
