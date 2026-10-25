# motor_class.py
# C_Motor — IEC 60947-4-1 Type 2 motor protection (MPCB/MCCB + contactor + OL)
# Cable sizing is excluded; use C_Feeder / Cable Selector separately.

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from motor_coordination_data import MANUFACTURER_TABLES, TYPE2_GENERIC
from motor_starter_data import select_starter, starter_size_list, STANDARD_STARTER_SIZES_A, next_std_size
from cb_class import IEC_MCB_SIZES, IEC_MCCB_SIZES

# ─── ENUMS / LISTS ────────────────────────────────────────────────────────────
START_METHODS = ['DOL', 'Y-Δ', 'Soft-starter', 'VFD']
DUTY_TYPES = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'S9', 'S10']
DEVICE_TOPOLOGIES = [
    'MPCB + OL relay',
    'MCCB thermal-magnetic',
    'aM fuse + OL relay',
]
PD_TYPES = ['MPCB', 'MCCB', 'Fuse']
PD_TO_TOPOLOGY = {
    'MPCB': 'MPCB + OL relay',
    'MCCB': 'MCCB thermal-magnetic',
    'Fuse': 'aM fuse + OL relay',
}
TOPOLOGY_TO_PD = {v: k for k, v in PD_TO_TOPOLOGY.items()}
ISOLATOR_MODES = ['No', 'Yes', 'Lockable', 'Fused']
PROFILE_LABELS = {
    'a': 'Pumps and fans',
    'b': 'Conveyors and compressors',
    'c': 'Heavy / high-inertia loads',
}
PROFILE_LABEL_TO_KEY = {v: k for k, v in PROFILE_LABELS.items()}
MANUFACTURERS = ['Generic', 'ABB', 'Schneider', 'Siemens', 'alfanar']
EARTHING_SYSTEMS = ['TN-S', 'TN-C-S', 'TT', 'IT']
OL_CLASSES = [10, 20, 30]
CODE_BASES = ['KSA', 'KSA + SBC 401']

# Lean-input defaults by application (IEC 60947-4-1 OL relay practice)
APPLICATION_PROFILES = {
    'a': {
        'short': 'Pumps & fans',
        'description': 'Typical LV motor feeders — ts = 3 s, OL Class 10',
        'start_time_s': 3.0,
        'ol_class': 10,
        'thermistor_required': False,
    },
    'b': {
        'short': 'Conveyors & compressors',
        'description': 'ts = 10 s, OL Class 20',
        'start_time_s': 10.0,
        'ol_class': 20,
        'thermistor_required': False,
    },
    'c': {
        'short': 'Heavy / high-inertia',
        'description': 'ts = 20–30 s, OL Class 30',
        'start_time_s': 25.0,
        'ol_class': 30,
        'thermistor_required': True,
    },
}
DEFAULT_APPLICATION_PROFILE = 'a'

# IEC 60364-4-41 Table 41.1 — max disconnection (s) at U0 ≤ 50 V … 400 V
DISCONNECTION_TIMES = {
    'TN-S': 0.4, 'TN-C-S': 0.4, 'TT': 0.2, 'IT': 1.0,
}

# Starting-method multipliers on LRC (Ist nameplate × Ib)
_IST_METHOD_FACTOR = {
    'DOL': 1.0,
    'Y-Δ': 1.0 / 3.0,
    'Soft-starter': 0.4,
    'VFD': 1.0 / 6.5,   # ≈ rated current at start
}

# Magnetic trip Im multiplier on In (breaker frame) vs starting method
_IM_MULT_BY_START = {
    'DOL': 12.0,
    'Y-Δ': 8.0,
    'Soft-starter': 6.0,
    'VFD': 3.0,
}


@dataclass
class C_Motor:
    """Motor nameplate, network, protection preferences, and Type 2 results."""

    # ── 1. MOTOR NAMEPLATE / PROCESS ─────────────────────────────────────────
    tag:              str   = ''
    Pn_kW:            float = 15.0
    Un_v:             float = 400.0
    phases:           int   = 3
    frequency_hz:     float = 60.0
    efficiency:       float = 0.90
    cos_phi:          float = 0.85
    ist_ratio:        float = 6.5      # Ist / In (LRA ratio); default 6–7 DOL
    start_method:     str   = 'DOL'
    application_profile: str = 'a'   # a | b | c — see APPLICATION_PROFILES
    start_time_s:     float = 3.0    # default profile a (pumps / fans)
    starts_per_hour:  int   = 6
    duty_type:        str   = 'S1'
    service_factor:   float = 1.0
    thermistor_required: bool = False

    # ── 2. SOURCE / NETWORK (at MCC busbar) ──────────────────────────────────
    earthing:         str   = 'TN-S'
    Isc_3ph_kA:       float = 25.0
    Isc_earth_kA:     float = 0.0    # 0 = not specified

    # ── 3. PROTECTIVE DEVICE PREFERENCES ─────────────────────────────────────
    coordination_std: str   = 'Type 2 coordination'
    device_topology:  str   = 'MPCB + OL relay'
    pd_type:          str   = 'MPCB'    # MPCB | MCCB | Fuse
    manufacturer:     str   = 'Generic'
    Icu_required_kA:  float = 0.0    # 0 = use Isc_3ph_kA
    Ics_required_kA:  float = 0.0
    ol_class:         int   = 10     # 10 / 20 / 30 — set by application profile
    isolator_mode:    str   = 'Yes'     # No | Yes | Lockable | Fused
    isolator_required: bool = True
    isolator_lockable: bool = False
    isolator_fused:   bool  = False
    isolator_size_A:  float = 0.0

    # ── 4. PROJECT RULES ─────────────────────────────────────────────────────
    code_basis:       str   = 'KSA'
    max_disconnection_s: float = 0.4

    # ── 5. DERIVED (calculated — not user-entered) ───────────────────────────
    Ib_A:             float = 0.0
    In_motor_A:       float = 0.0    # rated motor current (= Ib)
    Ist_nameplate_A:  float = 0.0    # ist_ratio × Ib
    Ist_effective_A:  float = 0.0    # after starting method
    Im_mult:          float = 12.0
    Im_A:             float = 0.0
    Ir_A:             float = 0.0
    contactor_ac3_A:  float = 0.0
    ol_class_used:    int   = 10

    # ── 6. TYPE 2 SELECTION OUTPUT ───────────────────────────────────────────
    kit_found:        bool  = False
    In_device_A:      float = 0.0
    Icu_kA:           float = 0.0
    mpcb_ref:         str   = ''
    mccb_ref:         str   = ''
    fuse_ref:         str   = ''
    contactor_ref:    str   = ''
    ol_relay_ref:     str   = ''
    isolator_ref:     str   = ''
    passes_all:       bool  = False
    warnings:         list  = field(default_factory=list)

    # ── 7. STARTER (standard sizes — DOL / Y-Δ / soft-starter / VFD) ─────────
    starter_rated_A:    float = 0.0
    starter_ref:        str   = ''
    contactor_line_A:   float = 0.0
    contactor_star_A:   float = 0.0
    contactor_delta_A:  float = 0.0
    contactor_line_ref: str   = ''
    contactor_star_ref: str   = ''
    contactor_delta_ref: str   = ''
    starter_timer_ref:  str   = ''
    starter_components: list  = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────────
    # VALIDATION
    # ─────────────────────────────────────────────────────────────────────────

    def is_valid(self) -> tuple[bool, list[str]]:
        errs = []
        if self.Pn_kW <= 0:
            errs.append('Rated power Pn must be > 0 kW.')
        if self.Un_v <= 0:
            errs.append('Rated voltage Un must be > 0 V.')
        if self.phases not in (1, 3):
            errs.append('Phases must be 1 or 3.')
        if not 0 < self.efficiency <= 1:
            errs.append('Efficiency η must be between 0 and 1.')
        if not 0 < self.cos_phi <= 1:
            errs.append('Power factor cos φ must be between 0 and 1.')
        if self.ist_ratio <= 0:
            errs.append('Ist/In ratio must be > 0.')
        if self.start_method not in START_METHODS:
            errs.append(f'Start method must be one of: {", ".join(START_METHODS)}')
        if self.device_topology not in DEVICE_TOPOLOGIES:
            errs.append(f'Device topology must be one of: {", ".join(DEVICE_TOPOLOGIES)}')
        if self.pd_type not in PD_TYPES:
            errs.append(f'PD type must be one of: {", ".join(PD_TYPES)}')
        if self.isolator_mode not in ISOLATOR_MODES:
            errs.append(f'Isolator mode must be one of: {", ".join(ISOLATOR_MODES)}')
        return len(errs) == 0, errs

    # ─────────────────────────────────────────────────────────────────────────
    # DERIVED CALCULATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def calc_ib(self) -> float:
        """Full-load current Ib = Pn / (η · cos φ · voltage factor)."""
        pn_w = self.Pn_kW * 1000.0 * self.service_factor
        denom = self.efficiency * self.cos_phi
        if denom <= 0:
            return 0.0
        if self.phases == 3:
            return pn_w / (math.sqrt(3) * self.Un_v * denom)
        return pn_w / (self.Un_v * denom)

    def calc_ist_nameplate(self, ib: float) -> float:
        """Locked-rotor current from nameplate ratio Ist/In × Ib."""
        return self.ist_ratio * ib

    def calc_ist_effective(self, ist_nameplate: float) -> float:
        """Starting current seen by protection, adjusted for starting method."""
        factor = _IST_METHOD_FACTOR.get(self.start_method, 1.0)
        if self.start_method == 'VFD':
            return self.calc_ib()   # ≈ Ib at start
        return ist_nameplate * factor

    def calc_im_mult(self) -> float:
        """Magnetic trip setting multiplier on breaker frame current In."""
        return _IM_MULT_BY_START.get(self.start_method, 12.0)

    def apply_pd_type(self, pd_type: str) -> None:
        if pd_type in PD_TO_TOPOLOGY:
            self.pd_type = pd_type
            self.device_topology = PD_TO_TOPOLOGY[pd_type]

    def apply_isolator_mode(self, mode: str) -> None:
        if mode not in ISOLATOR_MODES:
            return
        self.isolator_mode = mode
        self.isolator_required = mode != 'No'
        self.isolator_lockable = mode == 'Lockable'
        self.isolator_fused = mode == 'Fused'

    def calc_isolator_size_a(self) -> float:
        """Minimum isolator rating = next IEC frame ≥ 1.25 × Ib."""
        ib = self.Ib_A or self.calc_ib()
        if ib <= 0 or not self.isolator_required:
            return 0.0
        ladder = sorted(set(IEC_MCB_SIZES + IEC_MCCB_SIZES))
        return next_std_size(ib * 1.25, ladder)

    def apply_application_profile(self, profile: str) -> None:
        """Apply recommended ts / OL class / thermistor for profile a, b, or c."""
        spec = APPLICATION_PROFILES.get(profile)
        if not spec:
            return
        self.application_profile = profile
        self.start_time_s = float(spec['start_time_s'])
        self.ol_class = int(spec['ol_class'])
        self.thermistor_required = bool(spec['thermistor_required'])

    def ensure_default_profile(self) -> None:
        """Use lean-input profile (a) when no valid profile is stored."""
        if self.application_profile not in APPLICATION_PROFILES:
            self.apply_application_profile(DEFAULT_APPLICATION_PROFILE)

    def select_ol_class(self) -> int:
        """Overload relay class — explicit ol_class or derived from start time."""
        if self.ol_class in OL_CLASSES:
            return self.ol_class
        ts = self.start_time_s
        if ts <= 10:
            return 10
        if ts <= 20:
            return 20
        return 30

    def standard_in_for_pd(self) -> float:
        """Next IEC frame In ≥ Ib for the selected PD type (MCB / MCCB / Fuse)."""
        ib = self.Ib_A or self.calc_ib()
        if self.pd_type == 'MCB':
            ladder = IEC_MCB_SIZES
        elif self.pd_type == 'MCCB':
            ladder = IEC_MCCB_SIZES
        else:
            ladder = sorted(set(IEC_MCB_SIZES + IEC_MCCB_SIZES))
        return next_std_size(ib, ladder)

    def _format_ol_relay_ref(self, _ref: str) -> str:
        """Display text for overload relay — standard class only, no catalogue."""
        return f'OL Class {self.ol_class_used}'

    def select_starter_kit(self) -> Optional[dict]:
        """Standard starter size + refs for DOL / Y-Δ / soft-starter / VFD."""
        return select_starter(
            self.start_method,
            self.Ib_A or self.calc_ib(),
            self.Pn_kW,
            self.Un_v,
            self.phases,
        )

    @staticmethod
    def standard_starter_sizes(start_method: str) -> list:
        return starter_size_list(start_method)

    def select_type2_kit(self, ib: float, icu_required_kA: float) -> Optional[dict]:
        """
        Pick the smallest Type 2 coordination row with ib_max_A ≥ Ib and Icu ≥ required.
        Returns table row dict or None.
        """
        table = MANUFACTURER_TABLES.get(self.manufacturer, TYPE2_GENERIC)
        if self.manufacturer not in MANUFACTURER_TABLES:
            table = MANUFACTURER_TABLES['Generic']

        candidates = [
            row for row in table
            if row.get('topology') == self.device_topology
            and row.get('ib_max_A', 0) >= ib
            and row.get('Icu_kA', 0) >= icu_required_kA
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda r: r['ib_max_A'])

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN CALCULATE
    # ─────────────────────────────────────────────────────────────────────────

    def calculate(self) -> None:
        """Run full motor-protection calculation (Type 2 coordination path)."""
        self.warnings = []
        ok, errs = self.is_valid()
        if not ok:
            self.warnings.extend(errs)
            self.passes_all = False
            return

        if self.max_disconnection_s <= 0:
            self.max_disconnection_s = DISCONNECTION_TIMES.get(
                self.earthing, 0.4)

        if self.pd_type in PD_TO_TOPOLOGY:
            self.device_topology = PD_TO_TOPOLOGY[self.pd_type]
        elif self.device_topology in TOPOLOGY_TO_PD:
            self.pd_type = TOPOLOGY_TO_PD[self.device_topology]
        self.apply_isolator_mode(self.isolator_mode)

        # Derived currents
        self.Ib_A = round(self.calc_ib(), 2)
        self.In_motor_A = self.Ib_A
        self.Ist_nameplate_A = round(self.calc_ist_nameplate(self.Ib_A), 1)
        self.Ist_effective_A = round(self.calc_ist_effective(self.Ist_nameplate_A), 1)
        self.ol_class_used = self.select_ol_class()
        self.Im_mult = self.calc_im_mult()

        # Standard starter selection (method-specific size ladder)
        sk = self.select_starter_kit()
        if sk is None:
            self.warnings.append(
                f'No standard starter size for {self.start_method} at Ib={self.Ib_A:.1f} A.')
        else:
            self.starter_rated_A    = float(sk['starter_rated_A'])
            self.starter_ref         = sk.get('starter_ref', '')
            self.contactor_line_A    = float(sk.get('contactor_line_A', 0))
            self.contactor_star_A    = float(sk.get('contactor_star_A', 0))
            self.contactor_delta_A   = float(sk.get('contactor_delta_A', 0))
            self.contactor_line_ref  = sk.get('contactor_line_ref', '')
            self.contactor_star_ref  = sk.get('contactor_star_ref', '')
            self.contactor_delta_ref = sk.get('contactor_delta_ref', '')
            self.starter_timer_ref   = sk.get('timer_ref', '')
            self.starter_components  = list(sk.get('components', []))

        icu_req = self.Icu_required_kA or self.Isc_3ph_kA
        if icu_req <= 0:
            self.warnings.append('Isc at MCC busbar not set — cannot verify breaking capacity.')

        # CB frame — always next standard IEC size ≥ Ib (independent of starter)
        std_in = self.standard_in_for_pd()
        self.In_device_A = std_in
        self.mpcb_ref = ''
        self.mccb_ref = ''
        self.fuse_ref = ''

        # Type 2 kit (MPCB/MCCB + contactor + OL) — DOL and Y-Δ; soft/VFD use starter only
        needs_type2 = self.start_method in ('DOL', 'Y-Δ')
        kit = None
        if needs_type2:
            kit = self.select_type2_kit(self.Ib_A, icu_req)
            if kit is None:
                self.warnings.append(
                    f'No Type 2 coordination kit for {self.manufacturer} / '
                    f'{self.device_topology} at Ib={self.Ib_A:.1f} A, '
                    f'Icu≥{icu_req:.1f} kA.')
                self.kit_found = False
            else:
                self.kit_found = True
                if kit.get('ib_max_A', 0) < self.Ib_A:
                    self.warnings.append(
                        f'Coordination table supports Ib≤{kit["ib_max_A"]} A; '
                        f'motor Ib={self.Ib_A:.1f} A.')
                self.Icu_kA = float(kit.get('Icu_kA', 0))
                self.contactor_ref = kit.get('contactor', '')
                self.ol_relay_ref = self._format_ol_relay_ref(
                    kit.get('ol_relay', ''))
                if self.thermistor_required and self.ol_relay_ref:
                    if 'thermistor' not in self.ol_relay_ref.lower():
                        self.ol_relay_ref += ' + PTC thermistor'
                if self.isolator_required:
                    self.isolator_size_A = self.calc_isolator_size_a()
                    self.isolator_ref = ''
                else:
                    self.isolator_size_A = 0.0
                    self.isolator_ref = ''
        else:
            self.kit_found = bool(sk)
            self.contactor_ref = ''
            self.contactor_ac3_A = self.starter_rated_A or self.Ib_A
            self.ol_relay_ref = ''
            if icu_req > 0:
                self.Icu_kA = icu_req
            if self.isolator_required:
                self.isolator_size_A = self.calc_isolator_size_a()
                self.isolator_ref = ''

        self.Ir_A = round(self.Ib_A, 1)
        if needs_type2 and kit:
            self.Im_A = round(self.Im_mult * self.In_device_A, 0)
            self.contactor_ac3_A = self.contactor_line_A or self.Ib_A
        else:
            self.Im_A = round(self.Im_mult * (self.In_device_A or self.starter_rated_A), 0)
            self.contactor_ac3_A = self.starter_rated_A or self.Ib_A

        if needs_type2 and kit and self.Icu_kA < icu_req:
            self.warnings.append(
                f'Selected kit Icu={self.Icu_kA} kA < required {icu_req} kA.')
            self.passes_all = False
            return

        if not sk and not (needs_type2 and kit):
            self.passes_all = False
            return

        if self.Ist_effective_A > self.Im_A and self.Im_A > 0:
            self.warnings.append(
                f'Starting current {self.Ist_effective_A:.0f} A may exceed '
                f'magnetic trip Im≈{self.Im_A:.0f} A — verify coordination.')

        if self.thermistor_required:
            self.warnings.append(
                'PTC thermistor in motor windings recommended for this application profile.')

        self.passes_all = True

    # ─────────────────────────────────────────────────────────────────────────
    # FEEDER / BOARD INTEGRATION
    # ─────────────────────────────────────────────────────────────────────────

    def apply_from_network(self, voltage: float, frequency: float,
                           Isc_kA: float, earthing: str = '',
                           set_un: bool = True) -> None:
        """Pull busbar data from switchboard / feeder context."""
        if set_un and voltage > 0:
            self.Un_v = round(voltage, 0)
        if frequency > 0:
            self.frequency_hz = frequency
        if Isc_kA > 0:
            self.Isc_3ph_kA = Isc_kA
        if earthing:
            self.earthing = earthing

    def sync_to_feeder(self, feeder) -> None:
        """Push motor results into feeder P / PF / Ib for cable & CB path."""
        feeder.P = round(self.Pn_kW * self.service_factor, 3)
        feeder.PF = self.cos_phi
        feeder.phases = self.phases
        feeder.voltage = self.Un_v
        feeder.frequency = self.frequency_hz
        if self.Ib_A > 0:
            feeder.Ib = self.Ib_A
            if self.phases == 3:
                feeder.S = round(
                    self.Ib_A * math.sqrt(3) * self.Un_v / 1000, 2)
            else:
                feeder.S = round(self.Ib_A * self.Un_v / 1000, 2)

    def summary(self) -> dict:
        out = {
            'Start': self.start_method,
            'Ib': f'{self.Ib_A:.1f} A',
            'Ist': f'{self.Ist_effective_A:.0f} A',
            'Ir': f'{self.Ir_A:.0f} A',
            'Im': f'{self.Im_A:.0f} A',
            'OL class': str(self.ol_class_used),
            'Profile': APPLICATION_PROFILES.get(
                self.application_profile, {}).get('short', 'Custom'),
            'Starter': self.starter_ref or '—',
            'Starter In': f'{self.starter_rated_A:g} A' if self.starter_rated_A else '—',
            'Contactor': self.contactor_ref or '—',
            'Kit': self.mpcb_ref or self.mccb_ref or self.fuse_ref or '—',
            'passes': self.passes_all,
        }
        if self.start_method == 'Y-Δ' and self.contactor_star_A:
            out['Star contactor'] = f'{self.contactor_star_A:g} A'
            out['Line/Delta'] = f'{self.contactor_line_A:g} A'
        return out

    # ─────────────────────────────────────────────────────────────────────────
    # SERIALISE
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        keys = [
            'tag', 'Pn_kW', 'Un_v', 'phases', 'frequency_hz',
            'efficiency', 'cos_phi', 'ist_ratio', 'start_method',
            'application_profile', 'start_time_s', 'starts_per_hour',
            'duty_type', 'service_factor', 'thermistor_required',
            'earthing', 'Isc_3ph_kA', 'Isc_earth_kA',
            'coordination_std', 'device_topology', 'pd_type', 'manufacturer',
            'isolator_mode', 'isolator_size_A',
            'Icu_required_kA', 'Ics_required_kA', 'ol_class',
            'isolator_required', 'isolator_lockable', 'isolator_fused',
            'code_basis', 'max_disconnection_s',
            'Ib_A', 'In_motor_A', 'Ist_nameplate_A', 'Ist_effective_A',
            'Im_mult', 'Im_A', 'Ir_A', 'contactor_ac3_A', 'ol_class_used',
            'kit_found', 'In_device_A', 'Icu_kA',
            'mpcb_ref', 'mccb_ref', 'fuse_ref', 'contactor_ref', 'ol_relay_ref',
            'isolator_ref', 'passes_all', 'warnings',
            'starter_rated_A', 'starter_ref',
            'contactor_line_A', 'contactor_star_A', 'contactor_delta_A',
            'contactor_line_ref', 'contactor_star_ref', 'contactor_delta_ref',
            'starter_timer_ref', 'starter_components',
        ]
        return {k: getattr(self, k) for k in keys}

    @staticmethod
    def from_dict(d: dict) -> 'C_Motor':
        obj = C_Motor()
        for k, v in d.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        return obj
