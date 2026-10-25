# conduit_class.py
# IEC electrical conduit — metal or uPVC
# Internal diameters per IEC 61386 / EN 50086 series (mm)
#
# Fill rules — BS 7671:2018 Appendix 5, Table 5A (cable factors):
#   1 cable  → max 53% of conduit bore CSA  (rounded to 54% in practice)
#   2 cables → max 31% of conduit bore CSA
#   ≥3 cables → max 40% of conduit bore CSA
#
# Fill area is based on cable OUTER DIAMETER from manufacturer catalogue
# (π × (OD/2)²), NOT bare conductor cross-section.

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List

CONDUIT_SIZES_MM = [16, 20, 25, 32, 40, 50, 63, 75, 80, 100, 125, 150, 200]
CONDUIT_TYPES    = ['metal', 'uPVC']

_FILL_PCT         = {1: 54.0, 2: 31.0}
_FILL_PCT_DEFAULT = 40.0   # 3 or more cables


def _fill_limit(n: int) -> float:
    return _FILL_PCT.get(n, _FILL_PCT_DEFAULT)


def _nom_area(id_mm: float) -> float:
    """Internal cross-sectional area of conduit bore (mm²) = π × (ID/2)²."""
    return math.pi * (id_mm / 2.0) ** 2


def cable_od_area(od_mm: float) -> float:
    """Cross-sectional area occupied by one cable of outer diameter od_mm (mm²)."""
    return math.pi * (od_mm / 2.0) ** 2


@dataclass
class C_Conduit:
    """One conduit run carrying one or more cables."""

    size_mm:      int  = 20       # internal diameter (mm) — must be in CONDUIT_SIZES_MM
    conduit_type: str  = 'uPVC'   # 'metal' | 'uPVC'
    cables:       list = field(default_factory=list)  # list[float] — cable OD in mm

    # ── GEOMETRIC PROPERTIES ─────────────────────────────────────────────────

    @property
    def nom_area(self) -> float:
        """Nominal internal bore area (mm²) = π × (ID/2)²."""
        return _nom_area(self.size_mm)

    @property
    def filled_area(self) -> float:
        """Total area occupied by all cables (mm²) = Σ π × (OD/2)²."""
        return sum(cable_od_area(od) for od in self.cables)

    @property
    def free_area(self) -> float:
        """Remaining unused area (mm²)."""
        return self.nom_area - self.filled_area

    # ── FILL RULES ────────────────────────────────────────────────────────────

    @property
    def max_fill_pct(self) -> float:
        """Allowed fill % for the current number of cables."""
        return _fill_limit(len(self.cables))

    @property
    def fill_pct(self) -> float:
        """Current fill as a percentage of nom_area."""
        return (self.filled_area / self.nom_area * 100.0) if self.nom_area > 0 else 0.0

    @property
    def is_overfilled(self) -> bool:
        return self.fill_pct > self.max_fill_pct

    @property
    def passes(self) -> bool:
        return not self.is_overfilled and self.size_mm in CONDUIT_SIZES_MM

    # ── CABLE MANAGEMENT ─────────────────────────────────────────────────────

    def add_cable(self, od_mm: float) -> None:
        """Add a cable by its outer diameter (mm)."""
        self.cables.append(float(od_mm))

    def remove_cable(self, od_mm: float) -> bool:
        """Remove the first cable matching od_mm. Returns True if found."""
        for i, d in enumerate(self.cables):
            if abs(d - od_mm) < 0.05:
                self.cables.pop(i)
                return True
        return False

    def clear_cables(self) -> None:
        self.cables.clear()

    # ── AUTO-SIZING ───────────────────────────────────────────────────────────

    def suggest_size(self) -> int:
        """Smallest standard conduit ID (mm) that fits current cables."""
        return C_Conduit.min_size_for(self.cables)

    @staticmethod
    def min_size_for(cable_ods: List[float]) -> int:
        """Smallest standard conduit ID (mm) that fits cables with given ODs."""
        n = len(cable_ods)
        if n == 0:
            return CONDUIT_SIZES_MM[0]
        limit    = _fill_limit(n)
        total    = sum(cable_od_area(od) for od in cable_ods)
        required = total / (limit / 100.0)
        for size in CONDUIT_SIZES_MM:
            if _nom_area(size) >= required:
                return size
        return CONDUIT_SIZES_MM[-1]

    # ── SERIALISATION ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            'size_mm':      self.size_mm,
            'conduit_type': self.conduit_type,
            'cables':       list(self.cables),
        }

    @staticmethod
    def from_dict(d: dict) -> 'C_Conduit':
        obj = C_Conduit()
        obj.size_mm      = int(d.get('size_mm', 20))
        obj.conduit_type = str(d.get('conduit_type', 'uPVC'))
        obj.cables       = [float(x) for x in d.get('cables', [])]
        return obj

    def __repr__(self) -> str:
        return (f"C_Conduit({self.conduit_type} Ø{self.size_mm}mm | "
                f"{len(self.cables)} cables | "
                f"fill={self.fill_pct:.1f}% / {self.max_fill_pct:.0f}% max | "
                f"{'OVER' if self.is_overfilled else 'OK'})")
