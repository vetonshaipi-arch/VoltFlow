# vdrop_settings.py — project voltage-drop limits and helpers
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from feeder_class import C_Feeder
    from project_class import C_Project

# Load types that receive a segment ΔU limit (Spare/Space have no cable sizing)
VD_SIZED_LOAD_TYPES = ('Light', 'Motor', 'Socket', 'HVAC', 'Other', 'SubPanel')

VD_CATEGORY_FIELDS = {
    'Light': 'vd_pct_light',
    'Motor': 'vd_pct_motor',
    'Socket': 'vd_pct_socket',
    'HVAC': 'vd_pct_hvac',
    'Other': 'vd_pct_other',
    'SubPanel': 'vd_pct_subpanel',
}

DEFAULT_VDROP_BY_TYPE = {
    'Light': 3.0,
    'Motor': 5.0,
    'Socket': 5.0,
    'HVAC': 5.0,
    'Other': 5.0,
    'SubPanel': 5.0,
    'Spare': 5.0,
    'Space': 5.0,
}


@dataclass
class VdropProjectSettings:
    """Voltage-drop policy stored on C_Project."""
    vd_mode: str = 'per_load'          # per-circuit limits only (global optimizer removed)
    vd_pct_light: float = 3.0
    vd_pct_motor: float = 5.0
    vd_pct_socket: float = 5.0
    vd_pct_hvac: float = 5.0
    vd_pct_other: float = 5.0
    vd_pct_subpanel: float = 5.0
    opt_max_iterations: int = 30
    opt_voltage_passes: int = 3

    def limit_for_load_type(self, load_type: str) -> float:
        key = VD_CATEGORY_FIELDS.get(load_type, 'vd_pct_other')
        return max(0.1, min(100.0, float(getattr(self, key, 5.0))))

    def category_limits_dict(self) -> dict[str, float]:
        return {lt: self.limit_for_load_type(lt) for lt in VD_SIZED_LOAD_TYPES}

    @classmethod
    def from_project(cls, project: 'C_Project') -> 'VdropProjectSettings':
        return cls(
            vd_mode='per_load',
            vd_pct_light=getattr(project, 'vd_pct_light', 3.0),
            vd_pct_motor=getattr(project, 'vd_pct_motor', 5.0),
            vd_pct_socket=getattr(project, 'vd_pct_socket', 5.0),
            vd_pct_hvac=getattr(project, 'vd_pct_hvac', 5.0),
            vd_pct_other=getattr(project, 'vd_pct_other', 5.0),
            vd_pct_subpanel=getattr(project, 'vd_pct_subpanel', 5.0),
            opt_max_iterations=getattr(project, 'opt_max_iterations', 30),
            opt_voltage_passes=getattr(project, 'opt_voltage_passes', 3),
        )

    def apply_to_project(self, project: 'C_Project') -> None:
        project.vd_mode = self.vd_mode
        project.vd_pct_light = self.vd_pct_light
        project.vd_pct_motor = self.vd_pct_motor
        project.vd_pct_socket = self.vd_pct_socket
        project.vd_pct_hvac = self.vd_pct_hvac
        project.vd_pct_other = self.vd_pct_other
        project.vd_pct_subpanel = self.vd_pct_subpanel
        project.opt_max_iterations = self.opt_max_iterations
        project.opt_voltage_passes = self.opt_voltage_passes


def feeder_cable_locked(feeder: 'C_Feeder') -> bool:
    return bool(
        getattr(feeder, '_user_locked_conductor', False)
        or feeder.cable.manual_sizing
    )


def feeder_globally_locked(feeder: 'C_Feeder') -> bool:
    """True when user locked cable type/size — skip global auto-sizing."""
    return feeder_cable_locked(feeder)


def apply_feeder_cable_from_selector(feeder: 'C_Feeder', cable) -> None:
    """Apply Cable Selector output; sync lock flag from Manual/Auto mode."""
    feeder.cable = cable
    feeder._user_locked_conductor = bool(getattr(cable, 'manual_sizing', False))


def feeder_vdrop_user_locked(feeder: 'C_Feeder') -> bool:
    return bool(getattr(feeder, 'vd_user_override', False))


def apply_vdrop_limit_to_feeder(feeder: 'C_Feeder', settings: VdropProjectSettings,
                              force: bool = False) -> None:
    """Set max_vdrop_pct from project category unless user overrode (per-load mode)."""
    if feeder.load_type in ('Space', 'Spare'):
        return
    if feeder_vdrop_user_locked(feeder) and not force:
        return
    feeder.max_vdrop_pct = settings.limit_for_load_type(feeder.load_type)


def nominal_voltage_V(root) -> float:
    """Root nominal line voltage (V) — same reference as SLD ΔUtotal."""
    return float(getattr(root, 'voltage', 400.0) or 400.0)


def _phase_neutral_feeder(feeder: Optional['C_Feeder']) -> bool:
    return bool(
        feeder is not None and feeder.phase_str in ('L1', 'L2', 'L3'))


def line_voltage_after_segment(v_src_line: float, segment_vdrop_pct: float,
                               feeder: Optional['C_Feeder'] = None) -> float:
    """
    Line voltage at load after one cable segment.
    Single-phase (L1/L2/L3) segment % is relative to phase voltage.
    """
    if v_src_line <= 0:
        return 0.0
    if _phase_neutral_feeder(feeder):
        v_phase = v_src_line / math.sqrt(3)
        v_end_phase = v_phase * (1.0 - segment_vdrop_pct / 100.0)
        return v_end_phase * math.sqrt(3)
    return v_src_line * (1.0 - segment_vdrop_pct / 100.0)


def voltage_after_segment(board, segment_vdrop_pct: float,
                          feeder: Optional['C_Feeder'] = None,
                          v_src_line: float | None = None) -> float:
    """Line voltage at load after this cable segment."""
    if v_src_line is None:
        v_src_line = float(
            getattr(board, 'actual_voltage_V', None) or board.voltage)
    return line_voltage_after_segment(v_src_line, segment_vdrop_pct, feeder)


def total_vdrop_pct_from_nominal(root, board, segment_vdrop_pct: float,
                                 feeder: Optional['C_Feeder'] = None,
                                 v_src_line: float | None = None) -> float:
    """
    Cumulative ΔU from root nominal to end of segment — matches SLD:
      ΔUtotal = (Vnom − Vload) / Vnom × 100
    """
    nom = nominal_voltage_V(root)
    if nom <= 0:
        return 0.0
    v_end = voltage_after_segment(
        board, segment_vdrop_pct, feeder, v_src_line)
    return round(max(0.0, (nom - v_end) / nom * 100.0), 3)


def segment_vdrop_passes(segment_pct: float, limit_pct: float) -> bool:
    """True when this cable segment's ΔUc ≤ limit."""
    return segment_pct <= limit_pct + 1e-6


def is_vdrop_load_point(feeder: 'C_Feeder', board) -> bool:
    """
    End-of-circuit load where cumulative ΔUtotal from root is checked (SLD).
    Excludes board incomers and SubPanel distribution feeders.
    """
    if feeder.load_type in ('Space', 'Spare'):
        return False
    if feeder is board.primary_feeder:
        return False
    if feeder.load_type == 'SubPanel':
        return False
    return True


def feeder_vdrop_sizing_uses_segment(feeder: 'C_Feeder', board) -> bool:
    """True when sizing uses segment ΔUc (distribution); False at load points (ΔUtotal)."""
    if feeder.load_type in ('Space', 'Spare'):
        return False
    return not is_vdrop_load_point(feeder, board)


def total_vdrop_passes(root, board, segment_vdrop_pct: float,
                       limit_pct: float,
                       feeder: Optional['C_Feeder'] = None,
                       v_src_line: float | None = None) -> bool:
    return total_vdrop_pct_from_nominal(
        root, board, segment_vdrop_pct, feeder, v_src_line
    ) <= limit_pct + 1e-6


def apply_vdrop_limits_tree(root, settings: VdropProjectSettings,
                            force: bool = False) -> None:
    """Apply category limits to all feeders in the tree (respecting user overrides)."""
    for board in root.all_boards():
        for f in board.feeders:
            apply_vdrop_limit_to_feeder(f, settings, force=force)
        if board.primary_feeder_selected:
            pf = board.primary_feeder
            if not feeder_vdrop_user_locked(pf):
                pf.max_vdrop_pct = settings.limit_for_load_type('Other')
