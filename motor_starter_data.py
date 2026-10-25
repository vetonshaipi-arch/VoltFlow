# motor_starter_data.py
# Standard duty ratings for motor starters (IEC 60947-4-1 AC-3 series).
# Generic catalogue refs — replace with manufacturer order codes as needed.

from __future__ import annotations
import math
from typing import Optional

# IEC / market standard AC-3 current steps (A)
STANDARD_STARTER_SIZES_A = [
    6.3, 9, 12.5, 16, 18, 22, 25, 32, 38, 40, 45, 50, 57, 60, 65, 70, 75, 80,
    90, 95, 100, 110, 115, 120, 132, 150, 160, 180, 200, 225, 250, 280, 300,
    315, 335, 400, 450, 500, 560, 630, 710, 800, 900, 1000,
]

# Soft-starter lines use a slightly coarser ladder (typical PSTX / Altistart)
SOFT_STARTER_SIZES_A = [
    18, 22, 30, 37, 45, 55, 72, 85, 105, 130, 160, 210, 260, 330, 420, 530, 650, 820, 1000,
]

# VFD rated current (A) at 400 V, 50 Hz with indicative motor kW
VFD_STD_400V_50HZ = [
    (1.5, 0.55), (2.4, 0.75), (3.9, 1.1), (6.1, 2.2), (8.5, 3.0), (9.5, 4.0),
    (14.0, 5.5), (18.0, 7.5), (23.0, 11), (27.0, 15), (33.0, 18.5), (41.0, 22),
    (52.0, 30), (60.0, 37), (72.0, 45), (85.0, 55), (98.0, 63), (110.0, 75),
    (130.0, 90), (150.0, 110), (177.0, 132), (210.0, 160), (250.0, 200),
    (300.0, 250), (370.0, 315), (420.0, 355), (480.0, 400), (550.0, 450),
    (650.0, 560), (750.0, 630), (850.0, 710), (1000.0, 800),
]

# Star contactor utilisation factor (IEC 60947-4-1 star-delta practice)
Y_DELTA_STAR_FACTOR = 1.0 / math.sqrt(3)   # ≈ 0.577
Y_DELTA_STAR_FACTOR_ROUNDED = 0.58         # catalogue convention


def next_std_size(i_load_a: float, sizes: list[float] | None = None) -> float:
    """Smallest standard rating ≥ load current."""
    if i_load_a <= 0:
        return sizes[0] if sizes else 0.0
    ladder = sizes or STANDARD_STARTER_SIZES_A
    for s in ladder:
        if s >= i_load_a:
            return s
    return ladder[-1]


def _dol_row(in_a: float) -> dict:
    return {
        'start_method': 'DOL',
        'starter_rated_A': in_a,
        'starter_ref': f'DOL starter {in_a:g} A',
        'contactor_line_A': in_a,
        'contactor_star_A': 0.0,
        'contactor_delta_A': in_a,
        'contactor_line_ref': f'AC-3 {in_a:g} A (1×)',
        'contactor_star_ref': '',
        'contactor_delta_ref': '',
        'timer_ref': '',
        'components': [f'1× contactor {in_a:g} A', 'OL relay', 'MPCB/MCCB'],
    }


def _yd_row(line_a: float, star_a: float) -> dict:
    return {
        'start_method': 'Y-Δ',
        'starter_rated_A': line_a,
        'starter_ref': f'Y-Δ starter {line_a:g}/{star_a:g} A',
        'contactor_line_A': line_a,
        'contactor_star_A': star_a,
        'contactor_delta_A': line_a,
        'contactor_line_ref': f'Line (Δ) AC-3 {line_a:g} A',
        'contactor_star_ref': f'Star AC-3 {star_a:g} A',
        'contactor_delta_ref': f'Delta AC-3 {line_a:g} A',
        'timer_ref': 'Y-Δ changeover timer',
        'components': [
            f'1× line contactor {line_a:g} A',
            f'1× star contactor {star_a:g} A',
            f'1× delta contactor {line_a:g} A',
            'Y-Δ timer', 'OL relay', 'MPCB/MCCB',
        ],
    }


def _soft_row(in_a: float) -> dict:
    return {
        'start_method': 'Soft-starter',
        'starter_rated_A': in_a,
        'starter_ref': f'Soft-starter {in_a:g} A',
        'contactor_line_A': 0.0,
        'contactor_star_A': 0.0,
        'contactor_delta_A': 0.0,
        'contactor_line_ref': '— (semiconductor)',
        'contactor_star_ref': '',
        'contactor_delta_ref': '',
        'timer_ref': '',
        'components': [f'Soft-starter unit {in_a:g} A', 'bypass contactor optional'],
    }


def _vfd_row(in_a: float, pn_kw: float) -> dict:
    return {
        'start_method': 'VFD',
        'starter_rated_A': in_a,
        'starter_ref': f'VFD {in_a:g} A ({pn_kw:g} kW @ 400 V)',
        'contactor_line_A': 0.0,
        'contactor_star_A': 0.0,
        'contactor_delta_A': 0.0,
        'contactor_line_ref': '— (inverter)',
        'contactor_star_ref': '',
        'contactor_delta_ref': '',
        'timer_ref': '',
        'components': [f'VFD {in_a:g} A rated', 'input reactor optional'],
    }


def select_starter(
    start_method: str,
    ib_a: float,
    pn_kw: float = 0.0,
    voltage: float = 400.0,
    phases: int = 3,
) -> Optional[dict]:
    """
    Select standard starter rating and generic references for the start method.

    DOL:        one contactor ≥ Ib
    Y-Δ:        line/delta ≥ Ib, star ≥ 58 % Ib
    Soft-starter: unit current ≥ Ib (coarser size ladder)
    VFD:        inverter rated current ≥ Ib (400 V ladder; scale hint if other V)
    """
    if ib_a <= 0 or phases != 3:
        return None

    method = start_method.strip()

    if method == 'DOL':
        in_a = next_std_size(ib_a, STANDARD_STARTER_SIZES_A)
        return _dol_row(in_a)

    if method in ('Y-Δ', 'Y-D'):
        line_a = next_std_size(ib_a, STANDARD_STARTER_SIZES_A)
        star_a = next_std_size(
            ib_a * Y_DELTA_STAR_FACTOR_ROUNDED, STANDARD_STARTER_SIZES_A)
        return _yd_row(line_a, star_a)

    if method == 'Soft-starter':
        in_a = next_std_size(ib_a, SOFT_STARTER_SIZES_A)
        return _soft_row(in_a)

    if method == 'VFD':
        vfd_sizes = [r[0] for r in VFD_STD_400V_50HZ]
        i_need = ib_a
        if voltage > 0 and abs(voltage - 400.0) > 1:
            i_need = ib_a * (400.0 / voltage)
        in_a = next_std_size(i_need, vfd_sizes)
        kw = pn_kw
        if kw <= 0:
            for i_a, pk in VFD_STD_400V_50HZ:
                if i_a == in_a:
                    kw = pk
                    break
        return _vfd_row(in_a, kw or pn_kw)

    return None


def starter_size_list(start_method: str) -> list[float]:
    """Return the applicable standard size ladder for UI combo boxes."""
    if start_method == 'Soft-starter':
        return list(SOFT_STARTER_SIZES_A)
    if start_method == 'VFD':
        return [r[0] for r in VFD_STD_400V_50HZ]
    return list(STANDARD_STARTER_SIZES_A)
