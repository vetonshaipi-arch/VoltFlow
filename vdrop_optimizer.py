# vdrop_optimizer.py — global voltage-drop driven cable optimization
"""
Minimises total copper M ∝ Σ(A_i × L_i) (mm² × parallel sets × length) across
the radial distribution tree, subject to:
  - ΔUc (segment voltage drop) ≤ category limit — sizing constraint (all segments)
  - ΔUtotal from root nominal ≤ category limit — compliance at load points;
    violations upsize upstream distribution, not the load branch
  - ampacity (Iz ≥ Ib)
  - CB protection (when not user-locked)
  - manual / locked conductors (skipped)

Algorithm (utility-style backward–forward sweep + iterative sizing):
  1. Backward pass: bottom-up load/Ib rollup (demand-adjusted per feeder).
  2. Initialise every segment to the minimum catalogue conductor (1 parallel).
  3. Forward pass: propagate bus voltages, evaluate segment ΔUc and Iz.
  4. Upsize one catalogue step only on violating segments; repeat.
     (Single conductors through full catalogue first; parallel sets only
      on the largest row when 1×max still violates.)
  5. Hierarchy floor: incomer / SubPanel feeder ≥ largest branch mm² (ampacity).
  6. One-step downsize on still-feasible segments (IEC ladder only, no parallel shortcuts).
  7. Taper cap (L0→Ln): each switchboard cable ≤ upstream supply (single mm²).
  8. Report ΔUtotal at load points; warn when cumulative limit exceeded.

This targets minimum copper mass, not minimum loss or lifecycle cost.
"""
from __future__ import annotations
import math
import copy
from dataclasses import dataclass
from typing import List, Optional, Tuple, TYPE_CHECKING

from vdrop_settings import (
    VdropProjectSettings,
    feeder_globally_locked,
    apply_vdrop_limit_to_feeder,
    apply_vdrop_limits_tree,
    nominal_voltage_V,
    total_vdrop_pct_from_nominal,
    total_vdrop_passes,
    segment_vdrop_passes,
    is_vdrop_load_point,
)

if TYPE_CHECKING:
    from switchboard_class import C_Switchboard
    from feeder_class import C_Feeder

from VSEngCableSelector.cable_class import MAX_PARALLEL_SETS


@dataclass
class CableSegment:
    """One optimisable cable run (outgoing feeder or board incomer)."""
    board: 'C_Switchboard'
    feeder: 'C_Feeder'
    is_primary: bool = False
    label: str = ''

    def is_locked(self) -> bool:
        return feeder_globally_locked(self.feeder)

    def copper_index(self) -> float:
        f = self.feeder
        rec = f.cable.recommended
        if not rec:
            return 0.0
        n = max(getattr(f.cable, 'parallel_cables', 1), 1)
        return rec.size_mm2 * max(f.cable_length, 0.1) * n


@dataclass
class FeedPathStep:
    """One cable hop in the L0→Load path for manual upsize overrides."""
    step_label: str
    board_id: str
    board_name: str
    is_primary: bool
    circuit_ref: str
    feeder_name: str
    current_mm2: float
    current_parallel: int
    current_display: str
    seg_vdrop_pct: float
    limit_pct: float
    locked: bool
    options: list  # (display str, size_mm2, n_parallel)


@dataclass
class VdropFailureLoad:
    """Load point that failed ΔU after global/per-load sizing."""
    board_id: str
    circuit_ref: str
    name: str
    load_type: str
    seg_pct: float
    total_pct: float
    limit_pct: float
    issues: List[str]
    path: List[FeedPathStep]


def _phase_voltage(board, feeder: 'C_Feeder') -> float:
    av = getattr(board, 'actual_voltage_V', board.voltage) or board.voltage
    if feeder.phase_str in ('L1', 'L2', 'L3'):
        return av / math.sqrt(3)
    return av


def _child_board_source_voltage(root: 'C_Switchboard',
                                board: 'C_Switchboard') -> float:
    """Line voltage at child board incomer terminals (after parent SubPanel cable)."""
    if board.level == 0:
        return nominal_voltage_V(root)
    parent = _find_parent_board(root, board)
    if parent is None:
        return nominal_voltage_V(root)
    v = float(parent.actual_voltage_V or parent.voltage)
    for sf in parent.feeders:
        if (sf.load_type == 'SubPanel'
                and sf.subpanel_id == board.board_id
                and sf.cable.recommended):
            seg = getattr(sf, 'result_vdrop_pct', 0) or 0
            if seg > 0:
                v *= (1.0 - seg / 100.0)
            break
    return v


def _feeder_source_line_v(root: 'C_Switchboard', board,
                          feeder: 'C_Feeder') -> float:
    """Line voltage at the origin of this feeder run."""
    if feeder is board.primary_feeder:
        if board.level == 0:
            return nominal_voltage_V(root)
        return _child_board_source_voltage(root, board)
    return float(board.actual_voltage_V or board.voltage)


def _feeder_taper_mm2(feeder: 'C_Feeder') -> float:
    """Single-conductor mm² for IEC tapering (parallel sets ignored)."""
    rec = feeder.cable.recommended
    if not rec:
        return 0.0
    return rec.size_mm2


def _feeder_cu_mm2(feeder: 'C_Feeder') -> float:
    """Total copper cross-section mm² × parallel sets (copper index metric)."""
    rec = feeder.cable.recommended
    if not rec:
        return 0.0
    return rec.size_mm2 * max(getattr(feeder.cable, 'parallel_cables', 1), 1)


def _max_board_outgoing_taper_mm2(board) -> float:
    mx = 0.0
    for f in board.feeders:
        if f.load_type in ('Space', 'Spare'):
            continue
        mx = max(mx, _feeder_taper_mm2(f))
    return mx


def _max_child_board_taper_mm2(child: 'C_Switchboard') -> float:
    mx = _max_board_outgoing_taper_mm2(child)
    if child.primary_feeder_selected and child.primary_feeder.cable.recommended:
        mx = max(mx, _feeder_taper_mm2(child.primary_feeder))
    return mx


def _feeder_cu_floor(feeder: 'C_Feeder', board, root: 'C_Switchboard') -> float:
    """Minimum single-conductor mm² from tapering (incomer / SubPanel rules)."""
    if feeder is board.primary_feeder:
        return _max_board_outgoing_taper_mm2(board)
    if feeder.load_type == 'SubPanel' and feeder.subpanel_id:
        child = board.find_board(feeder.subpanel_id)
        if child:
            return _max_child_board_taper_mm2(child)
    return 0.0


def _sizing_check_total(feeder: 'C_Feeder', board) -> bool:
    """Sizing uses segment ΔUc only; ΔUtotal checked separately for compliance."""
    return False


def _upstream_segments_for_load(root: 'C_Switchboard',
                                load_seg: CableSegment) -> List[CableSegment]:
    """Distribution segments upstream of a load feeder (root → board)."""
    result: List[CableSegment] = []
    board = load_seg.board
    if (board.primary_feeder_selected
            and board.primary_feeder is not load_seg.feeder
            and board.primary_feeder.cable.conductor_table):
        result.append(CableSegment(
            board, board.primary_feeder, True, f'{board.name}/INC'))
    while board.level > 0:
        parent = _find_parent_board(root, board)
        if parent is None:
            break
        for sf in parent.feeders:
            if (sf.load_type == 'SubPanel' and sf.subpanel_id == board.board_id
                    and sf.cable.conductor_table):
                result.append(CableSegment(
                    parent, sf, False, f'{parent.name}/{sf.circuit_ref}'))
                break
        board = parent
        if (board.primary_feeder_selected
                and board.primary_feeder.cable.conductor_table):
            result.append(CableSegment(
                board, board.primary_feeder, True, f'{board.name}/INC'))
    return result


def _find_parent_board(root: 'C_Switchboard', board: 'C_Switchboard'):
    if board.level == 0 or not board.parent_id:
        return None

    def _search(parent: 'C_Switchboard'):
        for child in parent.child_boards:
            if child.board_id == board.board_id:
                return parent
            found = _search(child)
            if found is not None:
                return found
        return None

    return _search(root)


def _feed_ib_from_power(feeder: 'C_Feeder', board) -> bool:
    """Derive feeder Ib from P/S/PF without cable sizing."""
    if feeder.load_type in ('Space', 'Spare'):
        return False
    feeder._derive_power()
    pf = feeder.PF if feeder.PF is not None else 1.0
    s = feeder.S
    if s is None and feeder.P is not None:
        s = feeder.P / pf if pf else 0
        feeder.S = round(s, 4) if s else None
    if s is None:
        return False
    ph_v = _phase_voltage(board, feeder)
    feeder.voltage = ph_v
    feeder.cable.voltage = ph_v
    if feeder.phases == 3:
        feeder.Ib = round((s * 1000.0) / (math.sqrt(3) * ph_v), 3)
    else:
        feeder.Ib = round((s * 1000.0) / ph_v, 3)
    return True


def _sync_subpanel_feeder(feeder: 'C_Feeder', board, child: 'C_Switchboard') -> None:
    """Copy child board totals onto parent SubPanel feeder row."""
    feeder.S = child.total_S_kVA
    feeder.PF = child.composite_PF
    feeder.P = round(child.total_S_kVA * child.composite_PF, 2)
    feeder.Ib = child.total_Ib
    feeder.Iz = child.main_cb.Iz if child.main_cb.Iz else child.busbar_A
    feeder.cb.In_CB = child.main_cb.In_CB
    feeder.cb.cb_type = child.main_cb.cb_type
    feeder.cb.poles = child.main_cb.poles
    feeder.cb.passes_protection = child.main_cb.passes_protection
    feeder.cb.passes_Isc = child.main_cb.passes_Isc
    if child.primary_feeder_selected:
        cpf = child.primary_feeder
        feeder.result_vdrop_pct = cpf.result_vdrop_pct
        feeder.result_vdrop_total_pct = getattr(
            cpf, 'result_vdrop_total_pct', cpf.result_vdrop_pct)
    feeder.passes_all = (
        child.main_cb.passes_protection
        and child.busbar_loading <= 100
    )


def _rollup_all_board_totals(root: 'C_Switchboard', df_mode: str,
                             project_df_pct: float) -> None:
    """Bottom-up: feeder Ib and board totals before top-down cable sizing."""
    boards = sorted(root.all_boards(), key=lambda b: -b.level)
    for board in boards:
        if board.level > 0:
            parent = _find_parent_board(root, board)
            if parent is not None:
                board.frequency = parent.frequency
        for feeder in board.feeders:
            if feeder.load_type == 'SubPanel' and feeder.subpanel_id:
                child = board.find_board(feeder.subpanel_id)
                if child:
                    _sync_subpanel_feeder(feeder, board, child)
            elif feeder.load_type not in ('Space', 'Spare'):
                if feeder.load_type == 'Motor' and feeder.motor_configured:
                    ph_v = _phase_voltage(board, feeder)
                    feeder.motor.apply_from_network(
                        ph_v, board.frequency, board.Isc_board_kA)
                    feeder.motor.sync_to_feeder(feeder)
                _feed_ib_from_power(feeder, board)
                feeder.apply_demand_outputs()
        board._calc_totals(df_mode, project_df_pct)


def _prepare_feeder_cable_for_global_sizing(
        feeder: 'C_Feeder', board, min_conductor_mm2: float,
        ph_v: float | None = None) -> bool:
    """
    Sync feeder fields into C_Cable and ensure conductor_table exists.
    Returns False when the feeder cannot be auto-sized (no catalogue).
    """
    if feeder.load_type in ('Space', 'Spare'):
        return False

    c = feeder.cable
    feeder.frequency = board.frequency
    feeder.Isc_board_kA = board.Isc_board_kA
    feeder.min_cb_A = max(getattr(feeder, 'min_cb_A', 0) or 0, min_conductor_mm2)

    if ph_v is not None and ph_v > 0:
        feeder.voltage = ph_v
    elif not feeder.voltage or feeder.voltage <= 0:
        feeder.voltage = _phase_voltage(board, feeder)
    v = feeder.voltage

    feeder._derive_power()
    pf = feeder.PF if feeder.PF is not None else 0.9
    if feeder.S is None and feeder.P is not None and pf:
        feeder.S = round(feeder.P / pf, 4)
    if feeder.P is None and feeder.S is not None:
        feeder.P = round(feeder.S * pf, 4)

    c.frequency = board.frequency
    c.phases = feeder.phases
    c.voltage = v
    c.P = feeder.P
    c.S = feeder.S
    c.PF = pf
    c.cable_length = feeder.cable_length
    c.max_vdrop_pct = feeder.max_vdrop_pct
    c.min_conductor_mm2 = min_conductor_mm2

    if not feeder_globally_locked(feeder):
        c.manual_sizing = False
    elif feeder.cable.manual_sizing:
        feeder._user_locked_conductor = True

    if not c.conductor_table or c.k <= 0:
        c.ensure_conductor_table()
    return bool(c.conductor_table)


def _set_parallel_count(cable, n: int) -> None:
    """Set parallel sets (1–6) and refresh IEC B.52.17 k_parallel."""
    if hasattr(cable, 'set_parallel_count'):
        cable.set_parallel_count(n)
    else:
        cable.parallel_cables = max(1, min(int(n), MAX_PARALLEL_SETS))
        cable.k_parallel = cable._calc_k_parallel()


def _largest_table_row(cable):
    if not cable.conductor_table:
        return None
    return cable.conductor_table[-1]


def _first_table_row_at_least(cable, min_mm2: float):
    if not cable.conductor_table:
        return None
    for row in cable.conductor_table:
        if row.size_mm2 >= min_mm2 - 1e-6:
            return row
    return cable.conductor_table[-1]


def _next_conductor_step(cable, min_mm2: float
                         ) -> Optional[Tuple[int, object]]:
    """
    Next sizing step: walk single conductors through the catalogue, then
    add parallel sets only on the largest row (up to MAX_PARALLEL_SETS).
    """
    if not cable.conductor_table or not cable.recommended:
        return None
    n = max(cable.parallel_cables, 1)
    idx = _row_index(cable, cable.recommended)
    if idx < 0:
        return None
    largest = _largest_table_row(cable)
    largest_idx = len(cable.conductor_table) - 1

    if n == 1:
        if idx < largest_idx:
            return (1, cable.conductor_table[idx + 1])
        if n < MAX_PARALLEL_SETS:
            return (2, largest)
        return None

    if n < MAX_PARALLEL_SETS:
        return (n + 1, largest)
    return None


def _prev_conductor_step(cable, min_mm2: float
                         ) -> Optional[Tuple[int, object]]:
    """Previous step (inverse of _next_conductor_step)."""
    if not cable.conductor_table or not cable.recommended:
        return None
    n = max(cable.parallel_cables, 1)
    idx = _row_index(cable, cable.recommended)
    if idx < 0:
        return None
    largest = _largest_table_row(cable)

    if n > 1:
        return (n - 1, largest) if n > 2 else (1, largest)

    if idx > 0:
        prev = cable.conductor_table[idx - 1]
        if prev.size_mm2 >= min_mm2 - 1e-6:
            return (1, prev)
    return None


def _size_feeder_cb(feeder: 'C_Feeder', board, Ib: float, iz: float) -> None:
    if feeder.user_locked_cb:
        return
    from cb_class import C_CB
    feeder.cb.cb_type = C_CB.auto_type(Ib)
    from cb_class import cb_standard_for_type
    feeder.cb.standard = cb_standard_for_type(feeder.cb.cb_type)
    feeder.cb.poles = C_CB.auto_poles(feeder.phases, feeder.has_neutral)
    feeder.cb.diversity = 1.0
    feeder.cb.size_cb(Ib, iz, board.Isc_board_kA)


def _finalize_feeder_passes(feeder: 'C_Feeder', board,
                            root: 'C_Switchboard' | None = None,
                            settings: VdropProjectSettings | None = None) -> None:
    c = feeder.cable
    feeder.Isc_end_kA = feeder._calc_isc_end(board.Isc_board_kA)
    seg_ok = c.passes_vdrop
    vd_ok = seg_ok
    feeder.passes_all = (
        c.passes_ampacity and vd_ok
        and feeder.cb.passes_protection
        and (feeder.cb.passes_Isc or board.Isc_board_kA == 0)
    )
    feeder.apply_demand_outputs()


def _init_feeder_minimum(feeder: 'C_Feeder', board, root: 'C_Switchboard',
                         settings: VdropProjectSettings,
                         min_conductor_mm2: float, min_cb_A: float,
                         ph_v: float | None,
                         df_mode: str, project_df_pct: float) -> None:
    """Assign minimum catalogue conductor (1 parallel set)."""
    if feeder.load_type in ('Space', 'Spare'):
        return
    apply_vdrop_limit_to_feeder(feeder, settings)
    if feeder_globally_locked(feeder):
        if _prepare_feeder_cable_for_global_sizing(
                feeder, board, min_conductor_mm2, ph_v):
            refresh_feeder_after_isc(
                feeder, board, root, min_conductor_mm2, ph_v,
                df_mode, project_df_pct)
        return
    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return
    Ib = _resolve_sizing_ib(feeder, board, df_mode, project_df_pct)
    if Ib is None:
        return
    c = feeder.cable
    feeder.Ib = Ib
    c.Ib = Ib
    row = _first_table_row_at_least(c, min_conductor_mm2)
    if row is None:
        return
    _set_parallel_count(c, 1)
    _apply_row_to_cable(c, row, Ib, feeder, root, board, feeder.max_vdrop_pct)
    feeder.Iz = c.recommended.Iz
    c.manual_sizing = False
    _size_feeder_cb(feeder, board, Ib, feeder.Iz)
    _finalize_feeder_passes(feeder, board, root, settings)


def _upsize_feeder_one_step(feeder: 'C_Feeder', board, root: 'C_Switchboard',
                            settings: VdropProjectSettings,
                            min_conductor_mm2: float,
                            ph_v: float | None,
                            df_mode: str, project_df_pct: float) -> bool:
    """Increase one IEC catalogue step on a violating segment."""
    if feeder_globally_locked(feeder):
        return False
    c = feeder.cable
    if not c.recommended:
        return False
    nxt = _next_conductor_step(c, min_conductor_mm2)
    if nxt is None:
        return False
    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return False
    Ib = _resolve_sizing_ib(feeder, board, df_mode, project_df_pct)
    if Ib is None:
        return False
    feeder.Ib = Ib
    c.Ib = Ib
    n_par, row = nxt
    _set_parallel_count(c, n_par)
    _apply_row_to_cable(c, row, Ib, feeder, root, board, feeder.max_vdrop_pct)
    feeder.Iz = c.recommended.Iz
    _size_feeder_cb(feeder, board, Ib, feeder.Iz)
    _finalize_feeder_passes(feeder, board, root, settings)
    return True


def _downsize_feeder_one_step(feeder: 'C_Feeder', board, root: 'C_Switchboard',
                              settings: VdropProjectSettings,
                              min_conductor_mm2: float,
                              ph_v: float | None,
                              df_mode: str, project_df_pct: float) -> bool:
    """Decrease one IEC catalogue step if still ampacity, CB and vdrop compliant."""
    if feeder_globally_locked(feeder):
        return False
    c = feeder.cable
    rec = c.recommended
    if not rec:
        return False
    prev = _prev_conductor_step(c, min_conductor_mm2)
    if prev is None:
        return False
    n_par, row = prev
    if row.size_mm2 < _feeder_cu_floor(feeder, board, root) - 1e-6:
        return False
    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return False
    Ib = _resolve_sizing_ib(feeder, board, df_mode, project_df_pct)
    if Ib is None:
        return False
    feeder.Ib = Ib
    c.Ib = Ib
    limit = feeder.max_vdrop_pct
    saved_n = max(c.parallel_cables, 1)
    _set_parallel_count(c, n_par)
    _apply_row_to_cable(c, row, Ib, feeder, root, board, limit)
    feeder.Iz = c.recommended.Iz
    _size_feeder_cb(feeder, board, Ib, feeder.Iz)
    seg = CableSegment(board, feeder, feeder is board.primary_feeder, '')
    if not segment_feasible(seg, root):
        _set_parallel_count(c, saved_n)
        c.recommended = rec
        _apply_row_to_cable(c, rec, Ib, feeder, root, board, limit)
        feeder.Iz = rec.Iz
        _size_feeder_cb(feeder, board, Ib, feeder.Iz)
        return False
    _finalize_feeder_passes(feeder, board, root, settings)
    return True


def _feeder_phase_v(root: 'C_Switchboard', board, feeder: 'C_Feeder') -> float:
    if feeder is board.primary_feeder:
        return _feeder_source_line_v(root, board, feeder)
    return _phase_voltage(board, feeder)


def _evaluate_radial_network(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float,
        min_cb_A: float,
        df_mode: str,
        project_df_pct: float,
) -> None:
    """
    Backward load rollup + forward voltage sweep on fixed conductor sizes.
    """
    _rollup_all_board_totals(root, df_mode, project_df_pct)
    boards = sorted(root.all_boards(), key=lambda b: b.level)
    root.actual_voltage_V = root.voltage

    for board in boards:
        if board.level == 0:
            board.actual_voltage_V = root.voltage
        else:
            parent = _find_parent_board(root, board)
            if parent is not None:
                board.frequency = parent.frequency
            board.actual_voltage_V = _child_board_source_voltage(root, board)

        bus_before_incomer = board.actual_voltage_V

        if board.primary_feeder_selected:
            pf = board.primary_feeder
            pf.cable.min_conductor_mm2 = min_conductor_mm2
            pf.min_cb_A = min_cb_A
            if _prepare_feeder_cable_for_global_sizing(
                    pf, board, min_conductor_mm2, bus_before_incomer):
                refresh_feeder_after_isc(
                    pf, board, root, min_conductor_mm2, bus_before_incomer,
                    df_mode, project_df_pct)
            board.main_cb = pf.cb
            if (pf.result_vdrop_pct > 0
                    and not feeder_globally_locked(pf)):
                board.actual_voltage_V = (
                    bus_before_incomer * (1.0 - pf.result_vdrop_pct / 100.0))

        for feeder in board.feeders:
            if feeder.load_type == 'SubPanel' and feeder.subpanel_id:
                child = board.find_board(feeder.subpanel_id)
                if child:
                    _sync_subpanel_feeder(feeder, board, child)
            if feeder.load_type in ('Space', 'Spare'):
                continue
            ph_v = _feeder_phase_v(root, board, feeder)
            feeder.cable.min_conductor_mm2 = min_conductor_mm2
            feeder.min_cb_A = min_cb_A
            apply_vdrop_limit_to_feeder(feeder, settings)
            if _prepare_feeder_cable_for_global_sizing(
                    feeder, board, min_conductor_mm2, ph_v):
                refresh_feeder_after_isc(
                    feeder, board, root, min_conductor_mm2, ph_v,
                    df_mode, project_df_pct)

        board._calc_totals(df_mode, project_df_pct)


def _init_all_segments_minimum(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float,
        min_cb_A: float,
        df_mode: str,
        project_df_pct: float,
) -> None:
    """Set every auto-sized segment to minimum conductor before iteration."""
    _rollup_all_board_totals(root, df_mode, project_df_pct)
    for board in sorted(root.all_boards(), key=lambda b: b.level):
        if board.level == 0:
            board.actual_voltage_V = root.voltage
        else:
            board.actual_voltage_V = _child_board_source_voltage(root, board)

        if board.primary_feeder_selected:
            pf = board.primary_feeder
            pf.cable.min_conductor_mm2 = min_conductor_mm2
            pf.min_cb_A = min_cb_A
            _init_feeder_minimum(
                pf, board, root, settings, min_conductor_mm2, min_cb_A,
                board.actual_voltage_V, df_mode, project_df_pct)

        for feeder in board.feeders:
            if feeder.load_type in ('Space', 'Spare'):
                continue
            if feeder.load_type == 'SubPanel' and feeder.subpanel_id:
                child = board.find_board(feeder.subpanel_id)
                if child:
                    _sync_subpanel_feeder(feeder, board, child)
            if feeder.load_type == 'Motor' and feeder.motor_configured:
                ph_v = _feeder_phase_v(root, board, feeder)
                feeder.motor.apply_from_network(
                    ph_v, board.frequency, board.Isc_board_kA)
                feeder.motor.calculate()
                feeder.motor.sync_to_feeder(feeder)
            feeder.cable.min_conductor_mm2 = min_conductor_mm2
            feeder.min_cb_A = min_cb_A
            _init_feeder_minimum(
                feeder, board, root, settings, min_conductor_mm2, min_cb_A,
                _feeder_phase_v(root, board, feeder), df_mode, project_df_pct)


def _collect_violating_segments(root: 'C_Switchboard') -> List[CableSegment]:
    segs = collect_segments(root)
    violators: List[CableSegment] = []
    seen: set = set()

    def _add(seg: CableSegment) -> None:
        key = (id(seg.board), id(seg.feeder))
        if key not in seen:
            seen.add(key)
            violators.append(seg)

    for s in segs:
        if s.is_locked():
            continue
        if not segment_feasible(s, root):
            _add(s)
            continue
        f = s.feeder
        if not is_vdrop_load_point(f, s.board):
            continue
        total = getattr(f, 'result_vdrop_total_pct', 0.0) or 0.0
        if total <= f.max_vdrop_pct + 1e-6:
            continue
        upstream = [u for u in _upstream_segments_for_load(root, s)
                    if not u.is_locked()]
        if upstream:
            _add(max(upstream,
                     key=lambda u: u.feeder.result_vdrop_pct or 0.0))
        else:
            _add(s)
    return violators


def _iterative_radial_copper_optimize(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float,
        min_cb_A: float,
        df_mode: str,
        project_df_pct: float,
) -> int:
    """
    Minimum-copper sizing: start at minimum conductors, upsize violators
    one step per iteration until converged.
    Returns number of upsize steps applied.
    """
    _init_all_segments_minimum(
        root, settings, min_conductor_mm2, min_cb_A, df_mode, project_df_pct)
    upsizes = 0
    max_iter = max(settings.opt_max_iterations, 1)

    for _ in range(max_iter):
        _evaluate_radial_network(
            root, settings, min_conductor_mm2, min_cb_A,
            df_mode, project_df_pct)
        violators = _collect_violating_segments(root)
        if not violators:
            break
        progressed = False
        for seg in violators:
            f = seg.feeder
            if _upsize_feeder_one_step(
                    f, seg.board, root, settings, min_conductor_mm2,
                    _feeder_phase_v(root, seg.board, f),
                    df_mode, project_df_pct):
                upsizes += 1
                progressed = True
        if not progressed:
            break

    for board in sorted(root.all_boards(), key=lambda b: -b.level):
        _enforce_board_hierarchy(
            board, root, min_conductor_mm2, df_mode, project_df_pct,
            settings)

    for _ in range(max_iter):
        _evaluate_radial_network(
            root, settings, min_conductor_mm2, min_cb_A,
            df_mode, project_df_pct)
        violators = _collect_violating_segments(root)
        if not violators:
            break
        progressed = False
        for seg in violators:
            f = seg.feeder
            if _upsize_feeder_one_step(
                    f, seg.board, root, settings, min_conductor_mm2,
                    _feeder_phase_v(root, seg.board, f),
                    df_mode, project_df_pct):
                upsizes += 1
                progressed = True
        if not progressed:
            break

    _greedy_copper_downsize_pass(
        root, settings, min_conductor_mm2, min_cb_A,
        df_mode, project_df_pct)

    _enforce_switchboard_taper_chain(
        root, settings, min_conductor_mm2, df_mode, project_df_pct)
    _evaluate_radial_network(
        root, settings, min_conductor_mm2, min_cb_A,
        df_mode, project_df_pct)

    _refresh_compliance_passes(root, settings)
    return upsizes


def _refresh_compliance_passes(root: 'C_Switchboard',
                               settings: VdropProjectSettings) -> None:
    """Recompute passes_all using segment ΔUc + ΔUtotal at load points."""
    for board in root.all_boards():
        targets = list(board.feeders)
        if board.primary_feeder_selected:
            targets.append(board.primary_feeder)
        for f in targets:
            if f.load_type in ('Space', 'Spare') or not f.cable.recommended:
                continue
            _finalize_feeder_passes(f, board, root, settings)


def _fallback_largest_parallel(cable, Ib: float, root, board,
                               limit_pct: float, feeder: 'C_Feeder',
                               length: float,
                               check_total: bool = False
                               ) -> Optional[Tuple[int, object]]:
    """
    When no catalogue combo is fully compliant, use the largest row and
    increase parallel sets (up to MAX_PARALLEL_SETS) before failing.
    Prefers the fewest sets that pass ampacity; stops early on full compliance.
    """
    largest = _largest_table_row(cable)
    if largest is None:
        return None
    saved_n = max(getattr(cable, 'parallel_cables', 1), 1)
    best: Optional[Tuple[int, object]] = None
    for n_par in range(1, MAX_PARALLEL_SETS + 1):
        _set_parallel_count(cable, n_par)
        if not _row_meets_ampacity(cable, largest, Ib):
            continue
        best = (n_par, largest)
        ib_per = Ib / n_par
        _, seg_pct, _ = cable._vdrop(largest, ib_per)
        if check_total:
            v_src = _feeder_source_line_v(root, board, feeder)
            if total_vdrop_passes(
                    root, board, seg_pct, limit_pct, feeder, v_src):
                break
        elif seg_pct <= limit_pct + 1e-6:
            break
    _set_parallel_count(cable, saved_n)
    return best


def _row_meets_vdrop(cable, row, Ib: float, root, board,
                     limit_pct: float, feeder: 'C_Feeder',
                     check_total: bool) -> bool:
    n = max(cable.parallel_cables, 1)
    ib_per = Ib / n
    _, seg_pct, _ = cable._vdrop(row, ib_per)
    if check_total:
        v_src = _feeder_source_line_v(root, board, feeder)
        return total_vdrop_passes(
            root, board, seg_pct, limit_pct, feeder, v_src)
    return seg_pct <= limit_pct + 1e-6


def _apply_row_to_cable(cable, row, Ib: float, feeder: 'C_Feeder',
                        root: 'C_Switchboard', board,
                        limit_pct: float) -> None:
    """Apply conductor row; track segment ΔUc and cumulative ΔUtotal."""
    n = max(getattr(cable, 'parallel_cables', 1), 1)
    k4 = getattr(cable, 'k_parallel', 1.0)
    k2 = cable._k2_for_size(row.size_mm2)
    k_tot = round(cable.k1 * k2 * cable.k3 * k4, 4)
    iz = round(row.In * n * k_tot, 2)
    ib_per = Ib / n if n else Ib
    vd_v, seg_pct, vd_warns = cable._vdrop(row, ib_per)
    cable.warnings.extend(vd_warns)
    v_src = _feeder_source_line_v(root, board, feeder)
    total_pct = total_vdrop_pct_from_nominal(
        root, board, seg_pct, feeder, v_src)
    ok_seg = segment_vdrop_passes(seg_pct, limit_pct)
    ok_total = total_vdrop_passes(
        root, board, seg_pct, limit_pct, feeder, v_src)
    row.Iz = iz
    row.vdrop_v = vd_v
    row.vdrop_pct = seg_pct
    row.passes_amp = iz >= Ib
    row.passes_vdrop = ok_seg
    cable.recommended = row
    cable.passes_ampacity = row.passes_amp
    cable.passes_vdrop = ok_seg
    cable.result_vdrop_v = vd_v
    cable.result_vdrop_pct = seg_pct
    feeder.result_vdrop_v = vd_v
    feeder.result_vdrop_pct = seg_pct
    feeder.result_vdrop_total_pct = total_pct
    feeder.passes_vdrop_total = ok_total


def _row_meets_limits(cable, row, Ib: float, root, board,
                      limit_pct: float, feeder: 'C_Feeder',
                      check_total: bool | None = None) -> bool:
    if check_total is None:
        check_total = _sizing_check_total(feeder, board)
    n = max(cable.parallel_cables, 1)
    k4 = getattr(cable, 'k_parallel', 1.0)
    k2 = cable._k2_for_size(row.size_mm2)
    k_tot = round(cable.k1 * k2 * cable.k3 * k4, 4)
    iz = round(row.In * n * k_tot, 2)
    if iz < Ib:
        return False
    return _row_meets_vdrop(
        cable, row, Ib, root, board, limit_pct, feeder, check_total)


def _option_copper(size_mm2: float, n_par: int, length: float) -> float:
    """Copper index for one candidate: Σ mm² × parallel sets × length."""
    return size_mm2 * max(n_par, 1) * max(length, 0.1)


def _option_cu_mm2(size_mm2: float, n_par: int) -> float:
    """Total conductor cross-section (mm² × parallel sets) — selection metric."""
    return size_mm2 * max(n_par, 1)


def _row_meets_ampacity(cable, row, Ib: float) -> bool:
    n = max(cable.parallel_cables, 1)
    k4 = getattr(cable, 'k_parallel', 1.0)
    k2 = cable._k2_for_size(row.size_mm2)
    k_tot = round(cable.k1 * k2 * cable.k3 * k4, 4)
    return round(row.In * n * k_tot, 2) >= Ib


def _pick_compliant_conductor(cable, Ib: float, root, board, limit_pct: float,
                              feeder: 'C_Feeder',
                              min_cu_mm2: float = 0.0,
                              min_single_mm2: float = 0.0,
                              ampacity_only: bool = False,
                              check_total: bool = False
                              ) -> Optional[Tuple[int, object]]:
    """
    Smallest single conductor through full catalogue; parallel sets only
    on the largest row when no single cable passes.
    """
    saved_n = max(getattr(cable, 'parallel_cables', 1), 1)
    largest = _largest_table_row(cable)
    if largest is None:
        return None
    min_single = max(min_single_mm2, min_cu_mm2)

    _set_parallel_count(cable, 1)
    for row in cable.conductor_table:
        if row.size_mm2 < min_single - 1e-6:
            continue
        if ampacity_only:
            ok = _row_meets_ampacity(cable, row, Ib)
        else:
            ok = _row_meets_limits(
                cable, row, Ib, root, board, limit_pct, feeder,
                check_total)
        if ok:
            _set_parallel_count(cable, saved_n)
            return (1, row)

    if largest.size_mm2 < min_single - 1e-6:
        _set_parallel_count(cable, saved_n)
        return None

    for n_par in range(2, MAX_PARALLEL_SETS + 1):
        _set_parallel_count(cable, n_par)
        if ampacity_only:
            ok = _row_meets_ampacity(cable, largest, Ib)
        else:
            ok = _row_meets_limits(
                cable, largest, Ib, root, board, limit_pct, feeder,
                check_total)
        if ok:
            _set_parallel_count(cable, saved_n)
            return (n_par, largest)

    _set_parallel_count(cable, saved_n)
    return None


def _resolve_sizing_ib(feeder: 'C_Feeder', board,
                       df_mode: str = 'per_load',
                       project_df_pct: float = 100.0) -> Optional[float]:
    """Design current (A) for cable/CB sizing — demand-adjusted when applicable."""
    if feeder is board.primary_feeder:
        return board.total_Ib if board.total_Ib > 0 else None
    if feeder.load_type == 'SubPanel' and feeder.Ib and feeder.Ib > 0:
        return feeder.Ib

    if df_mode == 'per_load':
        ib = board._feeder_demand_ib(feeder)
        if ib > 0:
            return ib
    elif (board.level == 0 and df_mode == 'project'
          and project_df_pct < 100.0 and feeder.Ib):
        factor = max(0.0, min(100.0, project_df_pct)) / 100.0
        return round(feeder.Ib * factor, 3)

    if feeder.Ib and feeder.Ib > 0:
        return feeder.Ib

    pf = feeder.PF if feeder.PF is not None else 1.0
    s = feeder.S
    if s is None and feeder.P is not None:
        s = feeder.P / pf if pf else 0
    if s is None:
        return None
    ph_v = feeder.voltage or _phase_voltage(board, feeder)
    if ph_v <= 0:
        return None
    if feeder.phases == 3:
        return round((s * 1000.0) / (math.sqrt(3) * ph_v), 3)
    return round((s * 1000.0) / ph_v, 3)


def _row_index(cable, row) -> int:
    if not cable.conductor_table or row is None:
        return -1
    for i, r in enumerate(cable.conductor_table):
        if r.cable_code == row.cable_code and abs(r.size_mm2 - row.size_mm2) < 0.01:
            return i
    return -1


def refresh_feeder_after_isc(feeder: 'C_Feeder', board, root: 'C_Switchboard',
                             min_conductor_mm2: float = 1.5,
                             ph_v: float | None = None,
                             df_mode: str = 'per_load',
                             project_df_pct: float = 100.0) -> None:
    """
    Re-evaluate Iz, ΔU, CB and Isc via C_Cable.calculate_load() (VSEngCableSelector).
    Preserves manual/locked conductors; auto-selects only when not locked.
    """
    del df_mode, project_df_pct  # sizing Ib comes from feeder.calculate / calculate_load
    if feeder.load_type in ('Space', 'Spare'):
        return
    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return
    feeder.calculate(board.Isc_board_kA)


def select_smallest_compliant_conductor(feeder: 'C_Feeder', board,
                                        root: 'C_Switchboard',
                                        min_conductor_mm2: float = 1.5,
                                        ph_v: float | None = None,
                                        df_mode: str = 'per_load',
                                        project_df_pct: float = 100.0) -> bool:
    """
    Pick smallest table row passing Iz and segment ΔUc; upsize for CB if needed.
    Returns True if a conductor was selected.
    """
    if feeder.load_type in ('Space', 'Spare'):
        return False
    if feeder_globally_locked(feeder):
        refresh_feeder_after_isc(
            feeder, board, root, min_conductor_mm2, ph_v,
            df_mode, project_df_pct)
        return bool(feeder.cable.recommended)

    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return False
    c = feeder.cable
    Ib = _resolve_sizing_ib(feeder, board, df_mode, project_df_pct)
    if Ib is None:
        return False

    feeder.Ib = Ib
    c.Ib = Ib
    limit = feeder.max_vdrop_pct
    length = max(feeder.cable_length, 0.1)

    check_total = _sizing_check_total(feeder, board)
    picked = _pick_compliant_conductor(
        c, Ib, root, board, limit, feeder, min_cu_mm2=0.0,
        ampacity_only=False, check_total=check_total)
    if picked is None:
        picked = _fallback_largest_parallel(
            c, Ib, root, board, limit, feeder, length,
            check_total=check_total)

    if picked is None:
        largest = _largest_table_row(c)
        sz = f'{largest.size_mm2:.0f}mm²' if largest else 'catalogue'
        feeder.warnings.append(
            f'Load {Ib:.0f}A exceeds ampacity of '
            f'{MAX_PARALLEL_SETS}× largest conductor ({sz}).')
        return False

    n_par, chosen = picked
    _set_parallel_count(c, n_par)
    _apply_row_to_cable(c, chosen, Ib, feeder, root, board, limit)
    feeder.Iz = c.recommended.Iz
    c.manual_sizing = False

    if not feeder.user_locked_cb:
        from cb_class import C_CB
        feeder.cb.cb_type = C_CB.auto_type(Ib)
        from cb_class import cb_standard_for_type
        feeder.cb.standard = cb_standard_for_type(feeder.cb.cb_type)
        feeder.cb.poles = C_CB.auto_poles(feeder.phases, feeder.has_neutral)
        feeder.cb.diversity = 1.0
        feeder.cb.size_cb(Ib, feeder.Iz, board.Isc_board_kA)

        if not feeder.cb.passes_protection:
            saved_n = max(c.parallel_cables, 1)
            saved_rec = c.recommended
            while not feeder.cb.passes_protection:
                nxt = _next_conductor_step(c, min_conductor_mm2)
                if nxt is None:
                    break
                n_try, row = nxt
                _set_parallel_count(c, n_try)
                _apply_row_to_cable(c, row, Ib, feeder, root, board, limit)
                feeder.Iz = c.recommended.Iz
                feeder.cb.size_cb(Ib, feeder.Iz, board.Isc_board_kA)
            if not feeder.cb.passes_protection:
                _set_parallel_count(c, saved_n)
                c.recommended = saved_rec
                if saved_rec:
                    _apply_row_to_cable(
                        c, saved_rec, Ib, feeder, root, board, limit)
                    feeder.Iz = c.recommended.Iz
    else:
        feeder.cb.coordinate_icu(board.Isc_board_kA)

    _finalize_feeder_passes(feeder, board, root, VdropProjectSettings())
    if not c.passes_vdrop:
        seg = feeder.result_vdrop_pct
        n = max(c.parallel_cables, 1)
        sz = c.recommended.size_mm2 if c.recommended else 0
        feeder.warnings.append(
            f'Segment ΔUc {seg:.2f}% exceeds limit {limit:.1f}% '
            f'({n}×{sz:.0f}mm²).')
    if (is_vdrop_load_point(feeder, board)
            and not feeder.passes_vdrop_total):
        t = feeder.result_vdrop_total_pct
        feeder.warnings.append(
            f'ΔUtotal {t:.2f}% exceeds limit {limit:.1f}% at load '
            f'({feeder.name}).')
    if not c.passes_ampacity:
        n = max(c.parallel_cables, 1)
        sz = c.recommended.size_mm2 if c.recommended else 0
        feeder.warnings.append(
            f'Load {Ib:.0f}A exceeds Iz '
            f'({n}×{sz:.0f}mm² — largest parallel set in catalogue).')
    return True


def _enforce_feeder_cu_floor(feeder: 'C_Feeder', board, root,
                             min_taper_mm2: float, min_conductor_mm2: float,
                             ph_v: float | None,
                             df_mode: str, project_df_pct: float) -> None:
    """Upsize to minimum single conductor mm² ≥ largest downstream (tapering)."""
    if feeder_globally_locked(feeder) or min_taper_mm2 <= 0:
        return
    if _feeder_taper_mm2(feeder) >= min_taper_mm2 - 1e-6:
        return
    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return
    Ib = _resolve_sizing_ib(feeder, board, df_mode, project_df_pct)
    if Ib is None:
        return
    c = feeder.cable
    floor = max(min_taper_mm2, min_conductor_mm2)
    picked = _pick_compliant_conductor(
        c, Ib, root, board, feeder.max_vdrop_pct, feeder,
        min_single_mm2=floor, ampacity_only=True)
    if picked is None:
        picked = _pick_compliant_conductor(
            c, Ib, root, board, feeder.max_vdrop_pct, feeder,
            min_single_mm2=floor, ampacity_only=False)
    if picked is None:
        length = max(feeder.cable_length, 0.1)
        picked = _fallback_largest_parallel(
            c, Ib, root, board, feeder.max_vdrop_pct, feeder, length,
            check_total=False)
    if picked is None:
        return
    n_par, chosen = picked
    _set_parallel_count(c, n_par)
    _apply_row_to_cable(
        c, chosen, Ib, feeder, root, board, feeder.max_vdrop_pct)
    feeder.Iz = c.recommended.Iz
    if not feeder.user_locked_cb:
        from cb_class import C_CB
        feeder.cb.size_cb(Ib, feeder.Iz, board.Isc_board_kA)
    feeder.apply_demand_outputs()


def _enforce_board_hierarchy(board, root: 'C_Switchboard',
                             min_conductor_mm2: float,
                             df_mode: str, project_df_pct: float,
                             settings: VdropProjectSettings) -> None:
    """
    Tapering: incomer and SubPanel feeders — single conductor mm² ≥
    largest downstream branch (parallel sets not matched).
    """
    if board.primary_feeder_selected and not feeder_globally_locked(
            board.primary_feeder):
        floor = _max_board_outgoing_taper_mm2(board)
        if floor > 0:
            pf = board.primary_feeder
            ph_v = _feeder_source_line_v(root, board, pf)
            _enforce_feeder_cu_floor(
                pf, board, root, floor, min_conductor_mm2, ph_v,
                df_mode, project_df_pct)

    for f in board.feeders:
        if f.load_type != 'SubPanel' or not f.subpanel_id:
            continue
        child = board.find_board(f.subpanel_id)
        if not child:
            continue
        floor = _max_child_board_taper_mm2(child)
        if floor > 0:
            _enforce_feeder_cu_floor(
                f, board, root, floor, min_conductor_mm2,
                board.actual_voltage_V, df_mode, project_df_pct)


def _parent_supply_taper_mm2(root: 'C_Switchboard',
                             board: 'C_Switchboard') -> Optional[float]:
    """Single-conductor mm² of the parent SubPanel feeder supplying this board."""
    if board.level == 0:
        return None
    parent = _find_parent_board(root, board)
    if parent is None:
        return None
    for sf in parent.feeders:
        if sf.load_type == 'SubPanel' and sf.subpanel_id == board.board_id:
            return _feeder_taper_mm2(sf) or None
    return None


def _pick_largest_compliant_under_cap(
        cable, Ib: float, root, board, limit_pct: float, feeder: 'C_Feeder',
        max_single_mm2: float, min_conductor_mm2: float = 1.5,
        ampacity_only: bool = False,
        check_total: bool = False) -> Optional[Tuple[int, object]]:
    """Largest single conductor ≤ cap that still passes ampacity / vdrop."""
    if max_single_mm2 <= 0 or not cable.conductor_table:
        return None
    saved_n = max(getattr(cable, 'parallel_cables', 1), 1)
    largest = _largest_table_row(cable)
    cap = max_single_mm2
    min_sz = max(min_conductor_mm2, 0.0)

    _set_parallel_count(cable, 1)
    for row in reversed(cable.conductor_table):
        if row.size_mm2 > cap + 1e-6 or row.size_mm2 < min_sz - 1e-6:
            continue
        if ampacity_only:
            ok = _row_meets_ampacity(cable, row, Ib)
        else:
            ok = _row_meets_limits(
                cable, row, Ib, root, board, limit_pct, feeder, check_total)
        if ok:
            _set_parallel_count(cable, saved_n)
            return (1, row)

    if (largest is not None and largest.size_mm2 <= cap + 1e-6
            and largest.size_mm2 >= min_sz - 1e-6):
        for n_par in range(2, MAX_PARALLEL_SETS + 1):
            _set_parallel_count(cable, n_par)
            if ampacity_only:
                ok = _row_meets_ampacity(cable, largest, Ib)
            else:
                ok = _row_meets_limits(
                    cable, largest, Ib, root, board, limit_pct, feeder,
                    check_total)
            if ok:
                _set_parallel_count(cable, saved_n)
                return (n_par, largest)

    _set_parallel_count(cable, saved_n)
    return None


def _cap_feeder_taper_to_max(
        feeder: 'C_Feeder', board, root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float, max_taper_mm2: float,
        ph_v: float | None,
        df_mode: str, project_df_pct: float) -> bool:
    """Reduce feeder to largest compliant single size ≤ upstream cap."""
    if feeder_globally_locked(feeder) or max_taper_mm2 <= 0:
        return False
    if _feeder_taper_mm2(feeder) <= max_taper_mm2 + 1e-6:
        return False
    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return False
    Ib = _resolve_sizing_ib(feeder, board, df_mode, project_df_pct)
    if Ib is None:
        return False
    c = feeder.cable
    feeder.Ib = Ib
    c.Ib = Ib
    limit = feeder.max_vdrop_pct
    picked = _pick_largest_compliant_under_cap(
        c, Ib, root, board, limit, feeder, max_taper_mm2,
        min_conductor_mm2, ampacity_only=False)
    if picked is None:
        picked = _pick_largest_compliant_under_cap(
            c, Ib, root, board, limit, feeder, max_taper_mm2,
            min_conductor_mm2, ampacity_only=True)
    if picked is None:
        for row in reversed(c.conductor_table):
            if (row.size_mm2 <= max_taper_mm2 + 1e-6
                    and row.size_mm2 >= min_conductor_mm2 - 1e-6):
                _set_parallel_count(c, 1)
                _apply_row_to_cable(c, row, Ib, feeder, root, board, limit)
                feeder.Iz = c.recommended.Iz
                feeder.warnings.append(
                    f'Capped to {row.size_mm2:.0f}mm² (≤ upstream '
                    f'{max_taper_mm2:.0f}mm²); check ampacity / ΔU.')
                break
        else:
            return False
    else:
        n_par, chosen = picked
        _set_parallel_count(c, n_par)
        _apply_row_to_cable(c, chosen, Ib, feeder, root, board, limit)
        feeder.Iz = c.recommended.Iz
    if not feeder.user_locked_cb:
        from cb_class import C_CB
        feeder.cb.size_cb(Ib, feeder.Iz, board.Isc_board_kA)
    _finalize_feeder_passes(feeder, board, root, settings)
    return True


def _board_taper_snapshot(board) -> tuple:
    snap = []
    if board.primary_feeder_selected and board.primary_feeder.cable.recommended:
        pf = board.primary_feeder
        snap.append((
            'INC',
            _feeder_taper_mm2(pf),
            max(getattr(pf.cable, 'parallel_cables', 1), 1),
        ))
    for f in board.feeders:
        if f.cable.recommended:
            snap.append((
                f.circuit_ref or f.name,
                _feeder_taper_mm2(f),
                max(getattr(f.cable, 'parallel_cables', 1), 1),
            ))
    return tuple(snap)


def _enforce_board_taper_cap_down(
        board, root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float,
        df_mode: str, project_df_pct: float) -> None:
    """
    From L0 outward: each switchboard cable ≤ the upstream supply that feeds it.
    Board incomer ≤ parent SubPanel feeder; outgoing ≤ board incomer.
    """
    parent_cap = _parent_supply_taper_mm2(root, board)

    if (board.primary_feeder_selected and parent_cap is not None
            and not feeder_globally_locked(board.primary_feeder)):
        ph_v = _feeder_source_line_v(root, board, board.primary_feeder)
        _cap_feeder_taper_to_max(
            board.primary_feeder, board, root, settings,
            min_conductor_mm2, parent_cap, ph_v, df_mode, project_df_pct)

    if board.primary_feeder_selected and board.primary_feeder.cable.recommended:
        bus_cap = _feeder_taper_mm2(board.primary_feeder)
    elif parent_cap is not None:
        bus_cap = parent_cap
    else:
        return

    if bus_cap <= 0:
        return

    for f in board.feeders:
        if f.load_type in ('Space', 'Spare') or feeder_globally_locked(f):
            continue
        ph_v = _feeder_phase_v(root, board, f)
        _cap_feeder_taper_to_max(
            f, board, root, settings, min_conductor_mm2, bus_cap,
            ph_v, df_mode, project_df_pct)


def _enforce_switchboard_taper_chain(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float,
        df_mode: str, project_df_pct: float) -> None:
    """Apply L0→Ln taper caps; repeat until stable (child caps may cascade)."""
    max_pass = max(len(root.all_boards()), 1)
    for _ in range(max_pass):
        changed = False
        for board in sorted(root.all_boards(), key=lambda b: b.level):
            before = _board_taper_snapshot(board)
            _enforce_board_taper_cap_down(
                board, root, settings, min_conductor_mm2,
                df_mode, project_df_pct)
            if _board_taper_snapshot(board) != before:
                changed = True
        if not changed:
            break


def _size_board_primary_incomer(board, settings: VdropProjectSettings,
                                min_conductor_mm2: float, min_cb_A: float,
                                df_mode: str, project_df_pct: float,
                                root: 'C_Switchboard') -> None:
    """Size board incomer before outgoing feeders (correct bus V for ΔUtotal)."""
    board._calc_totals(df_mode, project_df_pct)
    if not board.primary_feeder_selected:
        board._size_main_cb()
        return
    pf = board.primary_feeder
    pf.cable.min_conductor_mm2 = min_conductor_mm2
    pf.min_cb_A = min_cb_A
    if not board.primary_feeder_selected:
        board._size_main_cb()
        return
    if not _prepare_feeder_cable_for_global_sizing(
            pf, board, min_conductor_mm2, board.actual_voltage_V):
        board._size_main_cb()
        return

    if not feeder_globally_locked(pf):
        apply_vdrop_limit_to_feeder(pf, settings)
        pf.voltage = board.actual_voltage_V
        pf.cable.voltage = board.actual_voltage_V
        pf.cable.max_vdrop_pct = pf.max_vdrop_pct
        pf.phases = board.phases
        pf.Ib = board.total_Ib
        if board.phases == 3:
            pf.S = round(
                board.total_Ib * math.sqrt(3) * board.actual_voltage_V / 1000, 2)
        else:
            pf.S = round(board.total_Ib * board.actual_voltage_V / 1000, 2)
        pf.PF = board.composite_PF
        pf.P = round(pf.S * pf.PF, 2) if pf.S else None
        pf.frequency = board.frequency
        pf.cable.frequency = board.frequency
        select_smallest_compliant_conductor(
            pf, board, root, min_conductor_mm2, board.actual_voltage_V,
            df_mode, project_df_pct)
        board.main_cb = pf.cb
    else:
        refresh_feeder_after_isc(
            pf, board, root, min_conductor_mm2, board.actual_voltage_V,
            df_mode, project_df_pct)
        board.main_cb = pf.cb


def _size_board_outgoing_feeders(board, settings: VdropProjectSettings,
                                 min_conductor_mm2: float, min_cb_A: float,
                                 root: 'C_Switchboard',
                                 df_mode: str = 'per_load',
                                 project_df_pct: float = 100.0) -> None:
    """Size outgoing feeders at the post-incomer bus voltage."""
    for feeder in board.feeders:
        if feeder.load_type == 'SubPanel' and feeder.subpanel_id:
            child = board.find_board(feeder.subpanel_id)
            if child:
                _sync_subpanel_feeder(feeder, board, child)
            ph_v = board.actual_voltage_V
            feeder.voltage = ph_v
            feeder.cable.voltage = ph_v
            feeder.cable.min_conductor_mm2 = min_conductor_mm2
            feeder.min_cb_A = min_cb_A
            apply_vdrop_limit_to_feeder(feeder, settings)
            feeder.cable.max_vdrop_pct = feeder.max_vdrop_pct
            if _prepare_feeder_cable_for_global_sizing(
                    feeder, board, min_conductor_mm2, ph_v):
                feeder.calculate(board.Isc_board_kA)
            continue

        if feeder.load_type in ('Space', 'Spare'):
            continue

        apply_vdrop_limit_to_feeder(feeder, settings)
        ph_v = _phase_voltage(board, feeder)
        feeder.voltage = ph_v
        feeder.cable.voltage = ph_v
        feeder.cable.min_conductor_mm2 = min_conductor_mm2
        feeder.min_cb_A = min_cb_A
        feeder.cable.max_vdrop_pct = feeder.max_vdrop_pct

        if _prepare_feeder_cable_for_global_sizing(
                feeder, board, min_conductor_mm2, ph_v):
            feeder.calculate(board.Isc_board_kA)


def _calc_board_feeders(board, settings: VdropProjectSettings,
                        min_conductor_mm2: float, min_cb_A: float,
                        df_mode: str, project_df_pct: float,
                        root: 'C_Switchboard') -> None:
    """Legacy entry — outgoing feeders only (used by downgrade recheck paths)."""
    _size_board_outgoing_feeders(
        board, settings, min_conductor_mm2, min_cb_A, root,
        df_mode, project_df_pct)


def recalculate_network_voltages(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float,
        min_cb_A: float,
        df_mode: str,
        project_df_pct: float,
) -> None:
    """
    Forward/backward evaluation on current conductor sizes, hierarchy check,
    then Isc refresh (sizes preserved).
    """
    _evaluate_radial_network(
        root, settings, min_conductor_mm2, min_cb_A,
        df_mode, project_df_pct)
    for board in sorted(root.all_boards(), key=lambda b: -b.level):
        _enforce_board_hierarchy(
            board, root, min_conductor_mm2, df_mode, project_df_pct,
            settings)
    _evaluate_radial_network(
        root, settings, min_conductor_mm2, min_cb_A,
        df_mode, project_df_pct)
    _enforce_switchboard_taper_chain(
        root, settings, min_conductor_mm2, df_mode, project_df_pct)
    _evaluate_radial_network(
        root, settings, min_conductor_mm2, min_cb_A,
        df_mode, project_df_pct)
    root._propagate_isc(
        0.0, root.transformer.Un_LV, min_conductor_mm2, min_cb_A,
        preserve_cables=True, vd_root=root)


def collect_segments(root: 'C_Switchboard') -> List[CableSegment]:
    segs: List[CableSegment] = []
    for board in root.all_boards():
        for f in board.feeders:
            if f.load_type in ('Space', 'Spare'):
                continue
            if f.cable.conductor_table:
                segs.append(CableSegment(
                    board, f, False,
                    f'{board.name}/{f.circuit_ref}'))
        if (board.primary_feeder_selected
                and board.primary_feeder.cable.conductor_table):
            segs.append(CableSegment(
                board, board.primary_feeder, True,
                f'{board.name}/INC'))
    return segs


def segment_feasible(seg: CableSegment, root: 'C_Switchboard') -> bool:
    """Sizing feasibility: segment ΔUc, ampacity, CB (ΔUtotal checked separately)."""
    f = seg.feeder
    c = f.cable
    if not c.recommended:
        return False
    if not c.passes_ampacity:
        return False
    seg_pct = f.result_vdrop_pct
    if not segment_vdrop_passes(seg_pct, f.max_vdrop_pct):
        return False
    if f.Ib > 0 and not f.user_locked_cb:
        if not f.cb.passes_protection:
            return False
    return True


def all_auto_segments_feasible(segments: List[CableSegment],
                               root: 'C_Switchboard') -> bool:
    for seg in segments:
        if seg.is_locked():
            continue
        if not segment_feasible(seg, root):
            return False
    return True


def total_copper(segments: List[CableSegment]) -> float:
    return sum(s.copper_index() for s in segments if not s.is_locked())


def try_downsize_segment(seg: CableSegment, root: 'C_Switchboard',
                         settings: VdropProjectSettings,
                         min_conductor_mm2: float,
                         df_mode: str, project_df_pct: float) -> bool:
    """One IEC step down on a segment (mirror of upsize)."""
    f = seg.feeder
    return _downsize_feeder_one_step(
        f, seg.board, root, settings, min_conductor_mm2,
        _feeder_phase_v(root, seg.board, f), df_mode, project_df_pct)


def _greedy_copper_downsize_pass(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        min_conductor_mm2: float,
        min_cb_A: float,
        df_mode: str,
        project_df_pct: float,
) -> int:
    """One IEC step down per iteration on oversized segments (highest copper first)."""
    downsizes = 0
    max_iter = max(settings.opt_max_iterations, 1)
    for _ in range(max_iter):
        _evaluate_radial_network(
            root, settings, min_conductor_mm2, min_cb_A,
            df_mode, project_df_pct)
        segs = [s for s in collect_segments(root) if not s.is_locked()]
        if not segs:
            break
        segs.sort(key=lambda s: s.copper_index(), reverse=True)
        progressed = False
        for seg in segs:
            if try_downsize_segment(
                    seg, root, settings, min_conductor_mm2,
                    df_mode, project_df_pct):
                downsizes += 1
                progressed = True
        if not progressed:
            break
    return downsizes


def collect_vdrop_violations(root: 'C_Switchboard') -> List[str]:
    """Segment ΔUc and cumulative ΔUtotal violations."""
    msgs: List[str] = []
    for board in root.all_boards():
        targets = list(board.feeders)
        if board.primary_feeder_selected:
            targets.append(board.primary_feeder)
        for f in targets:
            if f.load_type in ('Space', 'Spare'):
                continue
            if not f.cable.recommended:
                continue
            tag = getattr(f, 'circuit_ref', '') or f.name
            who = board.name
            if f is board.primary_feeder:
                tag = 'INC'
            seg = f.result_vdrop_pct
            if not segment_vdrop_passes(seg, f.max_vdrop_pct):
                msgs.append(
                    f'[{who}/{tag}] segment ΔUc {seg:.2f}% > '
                    f'{f.max_vdrop_pct:.1f}% limit ({f.load_type}).')
            if not is_vdrop_load_point(f, board):
                continue
            t = getattr(f, 'result_vdrop_total_pct', 0.0)
            if t <= 0 and seg:
                v_src = _feeder_source_line_v(root, board, f)
                t = total_vdrop_pct_from_nominal(
                    root, board, seg, f, v_src)
                f.result_vdrop_total_pct = t
            if t > f.max_vdrop_pct + 1e-6:
                msgs.append(
                    f'[{who}/{tag}] ΔUtotal {t:.2f}% > '
                    f'{f.max_vdrop_pct:.1f}% limit ({f.load_type}).')
    return msgs


def _find_feeder_in_root(root: 'C_Switchboard', board_id: str,
                         is_primary: bool, circuit_ref: str):
    board = root.find_board(board_id)
    if board is None:
        return None, None
    if is_primary and board.primary_feeder_selected:
        return board, board.primary_feeder
    for f in board.feeders:
        ref = getattr(f, 'circuit_ref', '') or f.name
        if ref == circuit_ref or f.name == circuit_ref:
            return board, f
    return board, None


def conductor_upsize_options(feeder: 'C_Feeder',
                             min_conductor_mm2: float = 1.5,
                             max_choices: int = 10) -> List[Tuple[str, float, int]]:
    """Dropdown choices: current size and the next practical upsize steps."""
    c = feeder.cable
    if not c.conductor_table or not c.recommended:
        return []
    cur_sz = c.recommended.size_mm2
    cur_n = max(getattr(c, 'parallel_cables', 1), 1)
    cur_cu = cur_sz * cur_n
    min_sz = max(min_conductor_mm2, cur_sz)
    seen: set[tuple] = set()
    opts: List[Tuple[str, float, int]] = []

    def add(display: str, sz: float, n: int) -> bool:
        key = (round(sz, 4), n)
        if key in seen:
            return False
        seen.add(key)
        opts.append((display, sz, n))
        return len(opts) >= max_choices

    add(f'{cur_n}×{cur_sz:g} mm² (current)' if cur_n > 1
        else f'{cur_sz:g} mm² (current)', cur_sz, cur_n)
    for row in c.conductor_table:
        if row.size_mm2 < min_sz - 1e-6:
            continue
        if row.size_mm2 <= cur_sz + 1e-6 and cur_n <= 1:
            continue
        label = f'{row.size_mm2:g} mm²'
        if add(label, row.size_mm2, 1):
            return opts
    largest = c.conductor_table[-1]
    for n_par in range(2, MAX_PARALLEL_SETS + 1):
        cu = largest.size_mm2 * n_par
        if cu <= cur_cu + 1e-6 and n_par <= cur_n:
            continue
        label = f'{n_par}×{largest.size_mm2:g} mm²'
        if add(label, largest.size_mm2, n_par):
            return opts
    return opts


def _path_step_label(hop_index: int, *, is_load: bool = False,
                     is_incomer: bool = False) -> str:
    if is_incomer:
        return 'Incomer'
    if is_load:
        return 'Load'
    return f'Level {hop_index}'


def feed_path_root_to_primary(root: 'C_Switchboard',
                              board) -> List[CableSegment]:
    """Cable segments from L0 toward a board incomer (root → INC order)."""
    pf = board.primary_feeder
    inc_seg = CableSegment(board, pf, True, f'{board.name}/INC')
    upstream = _upstream_segments_for_load(root, inc_seg)
    upstream.reverse()
    path = list(upstream)
    path.append(inc_seg)
    return path


def feed_path_root_to_load(root: 'C_Switchboard', load_board,
                           load_feeder: 'C_Feeder') -> List[CableSegment]:
    """Cable segments from L0 toward the load (root → load order)."""
    load_seg = CableSegment(
        load_board, load_feeder, False,
        f'{load_board.name}/{load_feeder.circuit_ref or load_feeder.name}')
    upstream = _upstream_segments_for_load(root, load_seg)
    upstream.reverse()
    path = list(upstream)
    path.append(load_seg)
    return path


def build_feed_path_steps(root: 'C_Switchboard', target_board,
                          target_feeder: 'C_Feeder',
                          min_conductor_mm2: float = 1.5,
                          *, is_primary: bool = False) -> List[FeedPathStep]:
    steps: List[FeedPathStep] = []
    if is_primary:
        path = feed_path_root_to_primary(root, target_board)
        end_feeder = target_board.primary_feeder
    else:
        path = feed_path_root_to_load(root, target_board, target_feeder)
        end_feeder = target_feeder
    hop = 0
    for seg in path:
        f = seg.feeder
        if f.load_type in ('Space', 'Spare') or not f.cable.recommended:
            continue
        is_end = (seg.board is target_board and f is end_feeder
                  and seg.is_primary == is_primary)
        rec = f.cable.recommended
        n_par = max(getattr(f.cable, 'parallel_cables', 1), 1)
        sz = rec.size_mm2
        steps.append(FeedPathStep(
            step_label=_path_step_label(
                hop, is_load=is_end and not is_primary,
                is_incomer=is_end and is_primary),
            board_id=seg.board.board_id,
            board_name=seg.board.name,
            is_primary=seg.is_primary,
            circuit_ref=(
                'INC' if seg.is_primary
                else (getattr(f, 'circuit_ref', '') or f.name)),
            feeder_name=f.name,
            current_mm2=sz,
            current_parallel=n_par,
            current_display=f'{n_par}×{sz:.0f} mm²',
            seg_vdrop_pct=f.result_vdrop_pct or 0.0,
            limit_pct=f.max_vdrop_pct,
            locked=feeder_globally_locked(f),
            options=conductor_upsize_options(f, min_conductor_mm2),
        ))
        if not is_end:
            hop += 1
    return steps


def _append_vdrop_failure(
        failures: List[VdropFailureLoad], seen: set[str],
        board, f: 'C_Feeder', *, is_primary: bool,
        root: 'C_Switchboard', min_conductor_mm2: float) -> None:
    if not f.cable.recommended:
        return
    circuit = 'INC' if is_primary else (f.circuit_ref or f.name)
    key = f'{board.board_id}:{circuit}'
    if key in seen:
        return
    issues: List[str] = []
    seg = f.result_vdrop_pct or 0.0
    if not segment_vdrop_passes(seg, f.max_vdrop_pct):
        issues.append(
            f'Segment ΔUc {seg:.2f}% > {f.max_vdrop_pct:.1f}%')
    total = getattr(f, 'result_vdrop_total_pct', 0.0) or 0.0
    if not is_primary and not is_vdrop_load_point(f, board):
        total = 0.0
    if not is_primary and is_vdrop_load_point(f, board):
        if total <= 0 and seg:
            v_src = _feeder_source_line_v(root, board, f)
            total = total_vdrop_pct_from_nominal(
                root, board, seg, f, v_src)
            f.result_vdrop_total_pct = total
        if total > f.max_vdrop_pct + 1e-6:
            issues.append(
                f'ΔUtotal {total:.2f}% > {f.max_vdrop_pct:.1f}%')
    if not issues:
        return
    seen.add(key)
    name = f'{board.name} incomer' if is_primary else f.name
    failures.append(VdropFailureLoad(
        board_id=board.board_id,
        circuit_ref=circuit,
        name=name,
        load_type=f.load_type if not is_primary else 'Other',
        seg_pct=seg,
        total_pct=total if total else seg,
        limit_pct=f.max_vdrop_pct,
        issues=issues,
        path=build_feed_path_steps(
            root, board, f, min_conductor_mm2, is_primary=is_primary),
    ))


def collect_vdrop_failure_loads(
        root: 'C_Switchboard',
        min_conductor_mm2: float = 1.5) -> List[VdropFailureLoad]:
    """Feeders with ΔU violations — terminal loads and board incomers."""
    failures: List[VdropFailureLoad] = []
    seen: set[str] = set()
    for board in root.all_boards():
        if board.primary_feeder_selected:
            pf = board.primary_feeder
            _append_vdrop_failure(
                failures, seen, board, pf, is_primary=True,
                root=root, min_conductor_mm2=min_conductor_mm2)
        for f in board.feeders:
            if not is_vdrop_load_point(f, board):
                continue
            _append_vdrop_failure(
                failures, seen, board, f, is_primary=False,
                root=root, min_conductor_mm2=min_conductor_mm2)
    return failures


def apply_feeder_conductor_override(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        board_id: str,
        is_primary: bool,
        circuit_ref: str,
        size_mm2: float,
        n_parallel: int,
        min_conductor_mm2: float,
        min_cb_A: float,
        df_mode: str,
        project_df_pct: float) -> bool:
    """Lock feeder to chosen conductor size (≥ current) and refresh passes."""
    board, feeder = _find_feeder_in_root(root, board_id, is_primary, circuit_ref)
    if board is None or feeder is None:
        return False
    if feeder.load_type in ('Space', 'Spare'):
        return False
    feeder._user_locked_conductor = True
    feeder.cable.manual_sizing = True
    ph_v = _feeder_phase_v(root, board, feeder)
    if not _prepare_feeder_cable_for_global_sizing(
            feeder, board, min_conductor_mm2, ph_v):
        return False
    row = None
    for r in feeder.cable.conductor_table:
        if abs(r.size_mm2 - size_mm2) < 1e-6:
            row = r
            break
    if row is None:
        return False
    Ib = _resolve_sizing_ib(feeder, board, df_mode, project_df_pct)
    if Ib is None:
        return False
    feeder.Ib = Ib
    feeder.cable.Ib = Ib
    _set_parallel_count(feeder.cable, max(1, int(n_parallel)))
    _apply_row_to_cable(
        feeder.cable, row, Ib, feeder, root, board, feeder.max_vdrop_pct)
    feeder.Iz = feeder.cable.recommended.Iz
    _size_feeder_cb(feeder, board, Ib, feeder.Iz)
    _finalize_feeder_passes(feeder, board, root, settings)
    return True


def apply_vdrop_train_overrides(
        root: 'C_Switchboard',
        settings: VdropProjectSettings,
        overrides: List[dict],
        min_conductor_mm2: float,
        min_cb_A: float,
        df_mode: str,
        project_df_pct: float) -> int:
    """
    Apply manual conductor sizes along a load path; re-evaluate network.
    Each override dict: board_id, is_primary, circuit_ref, size_mm2, n_parallel.
    Returns count applied.
    """
    applied = 0
    for ov in overrides:
        if apply_feeder_conductor_override(
                root, settings,
                ov['board_id'], ov['is_primary'], ov['circuit_ref'],
                ov['size_mm2'], ov['n_parallel'],
                min_conductor_mm2, min_cb_A, df_mode, project_df_pct):
            applied += 1
    if applied <= 0:
        return 0
    recalculate_network_voltages(
        root, settings, min_conductor_mm2, min_cb_A,
        df_mode, project_df_pct)
    root._propagate_isc(
        0.0, root.transformer.Un_LV, min_conductor_mm2, min_cb_A,
        preserve_cables=True, vd_root=root)
    _refresh_compliance_passes(root, settings)
    return applied


# optimize_cables_globally removed — per-circuit sizing via calculate_all only.
