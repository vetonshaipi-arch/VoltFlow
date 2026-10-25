# cb_class.py
# C_CB — LV circuit breaker: MCB / MCCB / ACB (VoltFlow KSA edition)

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

# ─── STANDARD CB SIZES (KSA / 60 Hz catalogue) ───────────────────────────────
MCB_SIZES   = [6, 10, 13, 16, 20, 25, 32, 40, 50, 63]
MCCB_SIZES  = [16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200,
               250, 320, 400, 500, 630, 800, 1000, 1250, 1600, 2000]
ACB_SIZES   = [630, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6300]
ICU_KA      = [6, 10, 16, 25, 36, 50, 63, 85, 100, 150, 200]
# Legacy import names
IEC_MCB_SIZES, IEC_MCCB_SIZES, IEC_ACB_SIZES, IEC_ICU_KA = (
    MCB_SIZES, MCCB_SIZES, ACB_SIZES, ICU_KA)

MCB_ICU   = [3, 6, 10]
MCCB_ICU  = [16, 25, 36, 50, 65, 85, 100, 120, 150]
ACB_ICU   = [42, 65, 85, 100, 130, 150]

CB_TYPES      = ['MCB', 'MCCB', 'ACB']
CB_STANDARDS  = ['MCB', 'MCCB']


def cb_standard_for_type(cb_type: str) -> str:
    return 'MCB' if cb_type == 'MCB' else 'MCCB'


def normalize_cb_standard(value: str | None) -> str:
    if not value:
        return 'MCCB'
    v = value.strip()
    if v in ('IEC 60898', 'MCB'):
        return 'MCB'
    if v in ('IEC 60947-2', 'MCCB', 'ACB'):
        return 'MCCB'
    return v
TRIP_CURVES   = ['B', 'C', 'D']
CB_FAMILIES   = ['auto', 'MCB', 'MCCB', 'ACB']   # user constraint
DIVERSITY_STEPS = [0.0] + [round(x * 0.1, 1) for x in range(10, 0, -1)]

# Motor/HVAC load types that get Type-D defaults
MOTOR_LOAD_TYPES = {'Motor', 'HVAC'}


@dataclass
class C_CB:
    # ── IDENTITY ──────────────────────────────────────────────────────────────
    standard:    str   = 'MCCB'
    cb_type:     str   = 'MCCB'         # 'MCB' | 'MCCB' | 'ACB'
    cb_family:   str   = 'auto'         # user constraint: 'auto'|'MCB'|'MCCB'|'ACB'
    poles:       int   = 3
    Icu_kA:      float = 25.0
    diversity:   float = 1.0

    # ── MCB SETTINGS ──────────────────────────────────────────────────────────
    trip_curve:  str   = 'C'            # 'B'|'C'|'D'
    # Im = instantaneous trip threshold (× In_CB)
    # B: 3-5×, C: 5-10×, D: 10-20×
    Im_mult:     float = 10.0           # user-settable Im multiplier

    # ── MCCB/ACB LONG-TIME PROTECTION (LTP) ──────────────────────────────────
    Ir_mult:     float = 1.0            # thermal setting Ir = Ir_mult × In_CB (0.4–1.0)
    tr_s:        float = 0.0            # LTP time delay (s), 0 = inverse time

    # ── MCCB/ACB SHORT-TIME PROTECTION (STP) ─────────────────────────────────
    Isd_mult:    float = 8.0            # STP threshold Isd = Isd_mult × Ir (1.5–10)
    tsd_s:       float = 0.1            # STP time delay (s) 0.05–0.5

    # ── MCCB/ACB INSTANTANEOUS ────────────────────────────────────────────────
    Ii_mult:     float = 12.0           # Instantaneous trip Ii = Ii_mult × In_CB
    Ii_enabled:  bool  = True           # False = Ii disabled (STP only)

    # ── GROUND FAULT (optional, MCCB/ACB) ────────────────────────────────────
    Ig_enabled:  bool  = False
    Ig_mult:     float = 0.3            # Ig = Ig_mult × In_CB
    tg_s:        float = 0.1

    # ── OVERLOAD RELAY (for motors) ────────────────────────────────────────────
    overload_relay:  bool  = False
    relay_setting:   float = 1.0        # relay setting × Ib

    # ── ACB EXTRAS ─────────────────────────────────────────────────────────────
    ZSI_enabled:     bool  = False      # zone selective interlocking
    communication:   str   = 'None'     # 'None'|'Modbus'|'Profibus'|'PROFINET'

    # ── SIZING OUTPUTS ────────────────────────────────────────────────────────
    Ib:          float = 0.0
    Ib_design:   float = 0.0
    In_CB:       float = 0.0
    Iz:          float = 0.0

    # ── DERIVED SETTINGS (calculated from multipliers × In_CB) ───────────────
    Ir_A:        float = 0.0    # Ir in Amps
    Isd_A:       float = 0.0    # Isd in Amps
    Ii_A:        float = 0.0    # Ii in Amps
    Im_A:        float = 0.0    # Im in Amps (MCB)
    Ig_A:        float = 0.0    # Ig in Amps

    # ── CHECKS ────────────────────────────────────────────────────────────────
    passes_protection:    bool  = False
    passes_Isc:           bool  = False
    passes_coordination:  bool  = True   # vs upstream CB
    Isc_at_board:         float = 0.0
    warnings:             list  = field(default_factory=list)
    coordination_notes:   list  = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────────
    # DEFAULTS BY LOAD TYPE
    # ─────────────────────────────────────────────────────────────────────────

    def apply_load_type_defaults(self, load_type: str) -> None:
        """Apply IEC 60947-2 recommended defaults based on load type."""
        if load_type in MOTOR_LOAD_TYPES:
            # Motors/HVAC: Type D, high magnetic trip to ride through starting
            self.trip_curve  = 'D'
            self.Im_mult     = 12.0   # covers 6-8× FLC starting current
            self.Isd_mult    = 10.0
            self.Ii_mult     = 15.0
            self.overload_relay = True
            self.relay_setting  = 1.0
        else:
            # General loads: Type C
            self.trip_curve  = 'C'
            self.Im_mult     = 10.0
            self.Isd_mult    = 8.0
            self.Ii_mult     = 12.0
            self.overload_relay = False

    # ─────────────────────────────────────────────────────────────────────────
    # SIZE CB
    # ─────────────────────────────────────────────────────────────────────────

    def size_cb(self, Ib: float, Iz: float, Isc_kA: float = 0.0) -> None:
        """
        Size CB per IEC 60947-2 / IEC 60364-4-43: Ib ≤ In_CB ≤ Iz
        Respects cb_family constraint.
        Auto-escalates MCB→MCCB→ACB if needed.
        After sizing, calculates all derived trip settings.
        """
        self.warnings = []
        self.Ib        = round(Ib, 2)
        self.Ib_design = round(Ib * self.diversity, 2)
        self.Iz        = round(Iz, 2)
        self.Isc_at_board = Isc_kA

        size_map = {'MCB': MCB_SIZES, 'MCCB': MCCB_SIZES, 'ACB': ACB_SIZES}

        # Determine which CB types to try
        if self.cb_family != 'auto':
            # User constrained to specific type
            type_order = [self.cb_family]
        else:
            # Auto-escalate from current type
            all_types  = ['MCB', 'MCCB', 'ACB']
            start_idx  = all_types.index(self.cb_type) if self.cb_type in all_types else 0
            type_order = all_types[start_idx:]

        self.passes_protection = False
        self.In_CB = 0

        for cb_t in type_order:
            ideal = [s for s in size_map[cb_t] if self.Ib_design <= s <= self.Iz]
            if ideal:
                self.In_CB    = ideal[0]
                self.cb_type  = cb_t
                self.standard = cb_standard_for_type(cb_t)
                self.passes_protection = True
                break

        if not self.passes_protection:
            all_sizes = MCB_SIZES + MCCB_SIZES + ACB_SIZES
            if self.cb_family != 'auto':
                all_sizes = size_map.get(self.cb_family, all_sizes)
            above_ib = [s for s in all_sizes if s >= self.Ib_design]
            if above_ib:
                self.In_CB = above_ib[0]
                if self.In_CB in MCB_SIZES:
                    self.cb_type = 'MCB'; self.standard = 'MCB'
                elif self.In_CB in MCCB_SIZES:
                    self.cb_type = 'MCCB'; self.standard = 'MCCB'
                else:
                    self.cb_type = 'ACB'; self.standard = 'MCCB'
            else:
                self.In_CB   = ACB_SIZES[-1]
                self.cb_type = 'ACB'
                self.warnings.append(
                    f"No CB size ≥ Ib={self.Ib_design:.1f}A. Use parallel circuits.")
            if self.Ib_design > self.Iz:
                self.warnings.append(
                    f"Ib={self.Ib:.1f}A > Iz={self.Iz:.1f}A — conductor undersized.")
            else:
                self.warnings.append(
                    f"No standard CB fits {self.Ib_design:.1f}A ≤ In_CB ≤ "
                    f"{self.Iz:.1f}A. Using {self.In_CB}A {self.cb_type} "
                    "— consider upsizing conductor.")

        # Auto-coordinate breaking capacity (next standard Icu ≥ prospective Isc)
        self.coordinate_icu(Isc_kA)

        # Calculate derived trip settings
        self._calc_trip_settings()

    def coordinate_icu(self, Isc_kA: float = 0.0) -> None:
        """Set Icu_kA to the next standard rating ≥ calculated fault level."""
        self.Isc_at_board = Isc_kA
        if Isc_kA <= 0:
            if self.Icu_kA <= 0:
                self.Icu_kA = 25.0
            self.passes_Isc = True
            return
        required = self.auto_icu(Isc_kA, self.cb_type)
        self.Icu_kA = required
        self.passes_Isc = self.Icu_kA >= Isc_kA - 1e-6
        if not self.passes_Isc:
            self.warnings.append(
                f"Icu={self.Icu_kA}kA < Isc={Isc_kA:.2f}kA "
                f"— no standard Icu ≥ fault level.")

    def _calc_trip_settings(self) -> None:
        """Calculate absolute trip values from multipliers × In_CB."""
        if self.In_CB <= 0:
            return
        In = self.In_CB
        if self.cb_type == 'MCB':
            self.Im_A  = round(self.Im_mult * In, 1)
            self.Ir_A  = In   # MCB: Ir = In (fixed)
            self.Isd_A = 0.0
            self.Ii_A  = 0.0
        else:  # MCCB / ACB
            self.Ir_A  = round(self.Ir_mult  * In, 1)
            self.Isd_A = round(self.Isd_mult * self.Ir_A, 1)
            self.Ii_A  = round(self.Ii_mult  * In, 1) if self.Ii_enabled else 0.0
            self.Im_A  = 0.0
        if self.Ig_enabled:
            self.Ig_A = round(self.Ig_mult * In, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # COORDINATION CHECK
    # ─────────────────────────────────────────────────────────────────────────

    def check_coordination(self, upstream: 'C_CB',
                           Isc_kA: float = 0.0) -> dict:
        """
        Check selectivity/discrimination between this CB (downstream)
        and upstream CB per IEC 60947-2.

        Returns dict with:
          - selective: bool — full selectivity achieved
          - partial: bool — partial selectivity up to Is (A)
          - Is_A: float — selectivity current limit
          - cascade: bool — cascade protection only
          - notes: list[str]
        """
        self.coordination_notes = []
        result = {
            'selective': False,
            'partial':   False,
            'Is_A':      0.0,
            'cascade':   False,
            'notes':     [],
        }

        if upstream.In_CB <= 0 or self.In_CB <= 0:
            result['notes'].append("Incomplete CB data — cannot check coordination.")
            self.passes_coordination = True
            return result

        Isc = Isc_kA * 1000  # convert to A

        # ── Rule 1: Size ratio ────────────────────────────────────────────────
        # For good selectivity: upstream In_CB ≥ 1.6 × downstream In_CB
        ratio = upstream.In_CB / self.In_CB if self.In_CB > 0 else 0
        if ratio < 1.6:
            result['notes'].append(
                f"Size ratio {ratio:.1f} < 1.6 — selectivity not guaranteed.")

        # ── Rule 2: Short-time discrimination ─────────────────────────────────
        # Downstream must trip before upstream at all fault levels
        # Check instantaneous/magnetic levels

        dn_inst  = self.Ii_A   if self.cb_type != 'MCB' else self.Im_A
        up_stp   = upstream.Isd_A if upstream.cb_type != 'MCB' else (upstream.Im_A)

        if dn_inst > 0 and up_stp > 0:
            if dn_inst < up_stp:
                # Downstream instantaneous < upstream STP threshold → selective up to up_stp
                result['partial'] = True
                result['Is_A']    = up_stp
                result['notes'].append(
                    f"Partial selectivity up to Is={up_stp:.0f}A "
                    f"(downstream Ii={dn_inst:.0f}A < upstream Isd={up_stp:.0f}A).")
            else:
                result['notes'].append(
                    f"Downstream Ii={dn_inst:.0f}A ≥ upstream Isd={up_stp:.0f}A "
                    "— possible loss of selectivity at high fault currents.")

        # ── Rule 3: Time discrimination ───────────────────────────────────────
        if self.cb_type != 'MCB' and upstream.cb_type != 'MCB':
            dt = upstream.tsd_s - self.tsd_s
            if dt >= 0.1:
                result['selective'] = True
                result['notes'].append(
                    f"Time discrimination: Δt={dt:.2f}s ≥ 0.1s — fully selective.")
            elif dt > 0:
                result['partial'] = True
                result['notes'].append(
                    f"Δt={dt:.3f}s < 0.1s — marginal time discrimination.")
            else:
                result['notes'].append(
                    "Same or inverted STP times — no time discrimination.")

        # ── Rule 4: ZSI ───────────────────────────────────────────────────────
        if self.ZSI_enabled and upstream.ZSI_enabled:
            result['selective'] = True
            result['notes'].append("ZSI active — full selectivity regardless of time settings.")

        # ── Rule 5: Cascade ───────────────────────────────────────────────────
        if not result['selective'] and not result['partial']:
            result['cascade'] = True
            # Cascade limit: upstream CB limits let-through energy
            # Simplified: Is = min(upstream Ii, Isc_prospective)
            Is_cascade = min(upstream.Ii_A or upstream.Im_A or upstream.In_CB * 10,
                             Isc * 1000 if Isc > 0 else upstream.In_CB * 10)
            result['Is_A'] = Is_cascade
            result['notes'].append(
                f"Cascade protection only — let-through limited to ~{Is_cascade:.0f}A.")

        # ── Rule 6: Icu vs prospective Isc ───────────────────────────────────
        if Isc > 0:
            if self.Icu_kA * 1000 < Isc:
                result['notes'].append(
                    f"⚠ Downstream Icu={self.Icu_kA}kA < Isc={Isc_kA:.2f}kA!")
            if upstream.Icu_kA * 1000 < Isc:
                result['notes'].append(
                    f"⚠ Upstream Icu={upstream.Icu_kA}kA < Isc={Isc_kA:.2f}kA!")

        self.passes_coordination = result['selective'] or result['partial']
        self.coordination_notes  = result['notes']
        result['notes'] = result['notes']
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_sizes(self) -> list:
        if self.cb_type == 'MCB':   return MCB_SIZES
        if self.cb_type == 'ACB':   return ACB_SIZES
        return MCCB_SIZES

    @staticmethod
    def auto_icu(isc_kA: float, cb_type: str | None = None) -> float:
        """Return smallest standard Icu ≥ Isc; uses type catalogue then IEC ladder."""
        if isc_kA <= 0:
            return 25.0
        type_tables = {
            'MCB': MCB_ICU,
            'MCCB': MCCB_ICU,
            'ACB': ACB_ICU,
        }
        if cb_type in type_tables:
            for icu in type_tables[cb_type]:
                if icu >= isc_kA - 1e-6:
                    return float(icu)
        for icu in ICU_KA:
            if icu >= isc_kA - 1e-6:
                return float(icu)
        return float(ICU_KA[-1])

    @staticmethod
    def auto_type(Ib: float) -> str:
        if Ib <= 63:    return 'MCB'
        if Ib <= 2000:  return 'MCCB'
        return 'ACB'

    @staticmethod
    def auto_poles(phases: int, has_neutral: bool = False) -> int:
        if phases == 1: return 1
        if phases == 2: return 2
        return 4 if has_neutral else 3

    def summary(self) -> str:
        """One-line summary for display."""
        base = f"{self.In_CB:.0f}A {self.cb_type} {self.poles}P"
        if self.cb_type == 'MCB':
            return f"{base} Type-{self.trip_curve} Icu={self.Icu_kA}kA"
        elif self.cb_type == 'MCCB':
            return (f"{base} Ir={self.Ir_A:.0f}A Isd={self.Isd_A:.0f}A "
                    f"tsd={self.tsd_s:.2f}s Icu={self.Icu_kA}kA")
        else:
            return (f"{base} Ir={self.Ir_A:.0f}A Isd={self.Isd_A:.0f}A "
                    f"tsd={self.tsd_s:.2f}s "
                    f"{'ZSI ' if self.ZSI_enabled else ''}Icu={self.Icu_kA}kA")

    # ─────────────────────────────────────────────────────────────────────────
    # SERIALISE
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            'standard': self.standard, 'cb_type': self.cb_type,
            'cb_family': self.cb_family, 'poles': self.poles,
            'Icu_kA': self.Icu_kA, 'diversity': self.diversity,
            'trip_curve': self.trip_curve, 'Im_mult': self.Im_mult,
            'Ir_mult': self.Ir_mult, 'tr_s': self.tr_s,
            'Isd_mult': self.Isd_mult, 'tsd_s': self.tsd_s,
            'Ii_mult': self.Ii_mult, 'Ii_enabled': self.Ii_enabled,
            'Ig_enabled': self.Ig_enabled, 'Ig_mult': self.Ig_mult, 'tg_s': self.tg_s,
            'overload_relay': self.overload_relay, 'relay_setting': self.relay_setting,
            'ZSI_enabled': self.ZSI_enabled, 'communication': self.communication,
            'Ib': self.Ib, 'Ib_design': self.Ib_design,
            'In_CB': self.In_CB, 'Iz': self.Iz,
            'Ir_A': self.Ir_A, 'Isd_A': self.Isd_A,
            'Ii_A': self.Ii_A, 'Im_A': self.Im_A, 'Ig_A': self.Ig_A,
            'passes_protection': self.passes_protection,
            'passes_Isc': self.passes_Isc,
            'passes_coordination': self.passes_coordination,
            'Isc_at_board': self.Isc_at_board,
            'warnings': self.warnings,
            'coordination_notes': self.coordination_notes,
        }

    @staticmethod
    def from_dict(d: dict) -> 'C_CB':
        obj = C_CB()
        for k, v in d.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        obj.standard = normalize_cb_standard(obj.standard)
        return obj

    def __repr__(self) -> str:
        return (f"C_CB({self.cb_type} {self.poles}P {self.In_CB:.0f}A "
                f"Icu={self.Icu_kA}kA | "
                f"{'✔' if self.passes_protection else '✘'} prot "
                f"{'✔' if self.passes_Isc else '✘'} Isc "
                f"{'✔' if self.passes_coordination else '~'} coord)")
