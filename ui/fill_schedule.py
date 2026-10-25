"""
fill_schedule.py — VoltFlow 3-phase panel schedule export

Windows uses Excel COM through pywin32; other platforms generate the workbook
from the same template with openpyxl.
"""
import os, sys, math

# ── Excel COM integer constants (avoids needing makepy / EnsureDispatch) ──────
_XL_CONTINUOUS       = 1
_XL_NONE             = -4142
_XL_THIN             = 2
_XL_MEDIUM           = -4138
_XL_EDGE_LEFT        = 7
_XL_EDGE_TOP         = 8
_XL_EDGE_BOTTOM      = 9
_XL_EDGE_RIGHT       = 10
_XL_DOWN             = -4121
_XL_PASTE_ALL        = -4104
_XL_HALIGN_CENTER    = -4108
_XL_FILE_FORMAT_XLSX = 51      # xlOpenXMLWorkbook
_XL_CALC_MANUAL      = -4135   # xlCalculationManual
_XL_CALC_AUTO        = -4105   # xlCalculationAutomatic

# ── Layout constants ──────────────────────────────────────────────────────────
INFO_VALUE_ROW        = 2
DATA_START            = 4
TEMPLATE_CIRCUIT_ROWS = 6      # template covers 12 ways (6 rows)

COL_A, COL_B, COL_C, COL_D = 1, 2, 3, 4
COL_E, COL_F               = 5, 6
COL_G, COL_H               = 7, 8
COL_I, COL_J               = 9, 10
COL_K, COL_L, COL_M, COL_N = 11, 12, 13, 14

LEFT_COLS  = (COL_A, COL_B, COL_C, COL_D)
RIGHT_COLS = (COL_K, COL_L, COL_M, COL_N)
KVA_COLS   = (COL_E, COL_F, COL_G, COL_H, COL_I, COL_J)

CYCLE_ACTIVE_LEFT  = {0: COL_E, 1: COL_G, 2: COL_I}
CYCLE_ACTIVE_RIGHT = {0: COL_F, 1: COL_H, 2: COL_J}
CYCLE_MERGES = {
    0: [(COL_G, COL_H), (COL_I, COL_J)],
    1: [(COL_E, COL_F), (COL_I, COL_J)],
    2: [(COL_E, COL_F), (COL_G, COL_H)],
}

SUMMARY_GAP_ROWS = 2
LOAD_TYPE_ORDER = ('Light', 'Motor', 'Socket', 'HVAC', 'Other', 'SubPanel')
LOAD_TYPE_LABELS = {
    'Light':    'Lighting',
    'Motor':    'Motor',
    'Socket':   'Socket',
    'HVAC':     'HVAC',
    'Other':    'Other',
    'SubPanel': 'Sub-panel',
}


# ── Template resolver ─────────────────────────────────────────────────────────
def _resolve_template():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from app_paths import resource_path

    candidates = [
        resource_path('ui', 'panel_schedule_12.xlsx'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'panel_schedule_12.xlsx'),
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                     'ui', 'panel_schedule_12.xlsx'),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        'panel_schedule_12.xlsx not found.\nSearched:\n' +
        '\n'.join(f'  {p}' for p in candidates))


def _template_path() -> str:
    """Resolve Excel template on first use (avoids import-time failure)."""
    return _resolve_template()


# ── Label helpers (pure Python, unchanged) ────────────────────────────────────
def cb_label(f):
    cb    = f.get('cb', {})
    In    = cb.get('In_CB', 0)
    poles = cb.get('poles', 1)
    return f'{int(In)}A-{int(poles)}p' if In else ''


def cable_label(f):
    if f.get('load_type', '') in ('Spare', 'Space'):
        return ''
    return f.get('conductor_desc', '') or ''


# ── Feeder assignment (pure Python, unchanged) ────────────────────────────────
def assign_feeders(feeders, n_circuit_rows):
    normal  = [f for f in feeders if f.get('load_type', '') not in ('Spare', 'Space')]
    spares  = [f for f in feeders if f.get('load_type', '') == 'Spare']
    ordered = normal + spares

    max_idx  = n_circuit_rows - 1
    left_idx = right_idx = 0
    result   = []
    i        = 0

    while i < len(ordered):
        f      = ordered[i]
        poles  = max(1, min(int(f.get('cb', {}).get('poles', 1)), 4))
        n_rows = min(poles, 3)

        if poles > 1:
            paired = False
            if i + 1 < len(ordered):
                f2      = ordered[i + 1]
                poles2  = max(1, min(int(f2.get('cb', {}).get('poles', 1)), 4))
                n_rows2 = min(poles2, 3)
                if n_rows2 == n_rows:
                    r_start = max(left_idx, right_idx)
                    if r_start + n_rows - 1 <= max_idx:
                        if left_idx <= right_idx:
                            result.append((f,  'left',  r_start, n_rows))
                            result.append((f2, 'right', r_start, n_rows))
                        else:
                            result.append((f,  'right', r_start, n_rows))
                            result.append((f2, 'left',  r_start, n_rows))
                        left_idx = right_idx = r_start + n_rows
                        i += 2
                        paired = True
            if not paired:
                if left_idx + n_rows - 1 <= max_idx:
                    result.append((f, 'left', left_idx, n_rows))
                    left_idx += n_rows
                elif right_idx + n_rows - 1 <= max_idx:
                    result.append((f, 'right', right_idx, n_rows))
                    right_idx += n_rows
                i += 1
        else:
            if left_idx <= right_idx and left_idx <= max_idx:
                result.append((f, 'left', left_idx, 1))
                left_idx += 1
            elif right_idx < left_idx and right_idx <= max_idx:
                result.append((f, 'right', right_idx, 1))
                right_idx += 1
            elif left_idx <= max_idx:
                result.append((f, 'left', left_idx, 1))
                left_idx += 1
            elif right_idx <= max_idx:
                result.append((f, 'right', right_idx, 1))
                right_idx += 1
            i += 1

    return result


# ── COM range / border helpers ────────────────────────────────────────────────
def _r(ws, r1, c1, r2=None, c2=None):
    """Return a COM Range for a single cell or a block."""
    return ws.Range(ws.Cells(r1, c1),
                    ws.Cells(r1 if r2 is None else r2,
                             c1 if c2 is None else c2))


def _edge(rng, edge, weight):
    """Set a solid border edge with the given weight (xlThin / xlMedium)."""
    b           = rng.Borders(edge)
    b.LineStyle = _XL_CONTINUOUS
    b.Weight    = weight


def _no_edge(rng, edge):
    """Remove a border edge."""
    rng.Borders(edge).LineStyle = _XL_NONE


def _box(rng, weight):
    """Set all four outer edges of a range to a solid border."""
    for e in (_XL_EDGE_TOP, _XL_EDGE_BOTTOM, _XL_EDGE_LEFT, _XL_EDGE_RIGHT):
        _edge(rng, e, weight)


def _xl_set(obj, name: str, value) -> None:
    """Set an Excel COM property; skip if this Excel build rejects it."""
    try:
        setattr(obj, name, value)
    except Exception:
        pass


def _open_excel_app():
    """Start a dedicated Excel instance (avoids attaching to a locked running Excel)."""
    import win32com.client as win32
    try:
        xl = win32.DispatchEx('Excel.Application')
    except Exception:
        xl = win32.Dispatch('Excel.Application')
    _xl_set(xl, 'Visible', False)
    _xl_set(xl, 'DisplayAlerts', False)
    return xl


def _excel_fast_mode(xl, on: bool) -> None:
    """Toggle Excel settings that slow bulk COM updates (best-effort)."""
    if on:
        _xl_set(xl, 'ScreenUpdating', False)
        _xl_set(xl, 'DisplayAlerts', False)
        _xl_set(xl, 'EnableEvents', False)
        _xl_set(xl, 'Calculation', _XL_CALC_MANUAL)
    else:
        _xl_set(xl, 'Calculation', _XL_CALC_AUTO)
        _xl_set(xl, 'EnableEvents', True)
        _xl_set(xl, 'DisplayAlerts', True)
        _xl_set(xl, 'ScreenUpdating', True)


# ── Sheet expansion ───────────────────────────────────────────────────────────
def prepare_sheet(ws, xl, n_circuit_rows_needed):
    """
    Extend beyond the 12-way template by inserting groups of 3 rows and
    copying format (fill, merges, row height) from the 3 rows immediately above.
    Excel handles the row insertion natively — no merge-range bookkeeping needed.
    """
    if n_circuit_rows_needed <= TEMPLATE_CIRCUIT_ROWS:
        return

    extra_groups = (n_circuit_rows_needed - TEMPLATE_CIRCUIT_ROWS) // 3

    for g in range(extra_groups):
        ins_row   = DATA_START + TEMPLATE_CIRCUIT_ROWS + g * 3
        src_start = ins_row - 3

        # Insert 3 blank rows; Excel shifts everything below down correctly
        ws.Rows(f'{ins_row}:{ins_row + 2}').Insert(Shift=_XL_DOWN)

        # Paste all formatting (fills, merges, number formats) from source rows
        _r(ws, src_start, COL_A, src_start + 2, COL_N).Copy()
        _r(ws, ins_row,   COL_A, ins_row   + 2, COL_N).PasteSpecial(
            Paste=_XL_PASTE_ALL)
        xl.CutCopyMode = False

        # Clear any values that came with the paste; keep formatting
        _r(ws, ins_row, COL_A, ins_row + 2, COL_N).ClearContents()

        # Row heights are not transferred by cell-range paste — copy explicitly
        for k in range(3):
            ws.Rows(ins_row + k).RowHeight = ws.Rows(src_start + k).RowHeight


# ── Board info header ─────────────────────────────────────────────────────────
def write_board_info(ws, board_info):
    _r(ws, INFO_VALUE_ROW, COL_A, INFO_VALUE_ROW, COL_D).Value = (
        board_info.get('name', ''),
        board_info.get('ip_rating', ''),
        board_info.get('main_cb_type', ''),
        board_info.get('main_cb_size', ''),
    )
    ws.Cells(INFO_VALUE_ROW, COL_F).Value = board_info.get('main_cable', '')
    ws.Cells(INFO_VALUE_ROW, COL_N).Value = board_info.get('source', '')


# ── Border application (range-based — far fewer COM calls) ───────────────────
def apply_all_borders(ws, assignments, n_circuit_rows):
    """Medium boxes per feeder block / SPACE row; light kVA column dividers."""
    last_idx = n_circuit_rows - 1
    left_used  = set()
    right_used = set()

    for _, side, start_idx, n_rows in assignments:
        r1 = DATA_START + start_idx
        r2 = DATA_START + start_idx + n_rows - 1
        if side == 'left':
            _box(_r(ws, r1, COL_A, r2, COL_D), _XL_MEDIUM)
            left_used.update(range(start_idx, start_idx + n_rows))
        else:
            _box(_r(ws, r1, COL_K, r2, COL_N), _XL_MEDIUM)
            right_used.update(range(start_idx, start_idx + n_rows))

    for idx in range(n_circuit_rows):
        r = DATA_START + idx
        if idx not in left_used:
            _box(_r(ws, r, COL_A, r, COL_D), _XL_MEDIUM)
        if idx not in right_used:
            _box(_r(ws, r, COL_K, r, COL_N), _XL_MEDIUM)

    # kVA zone outer frame + per-row phase-pair divider
    _edge(_r(ws, DATA_START, COL_E, DATA_START + last_idx, COL_E),
          _XL_EDGE_LEFT, _XL_MEDIUM)
    _edge(_r(ws, DATA_START, COL_E, DATA_START, COL_J),
          _XL_EDGE_TOP, _XL_MEDIUM)
    _edge(_r(ws, DATA_START + last_idx, COL_E, DATA_START + last_idx, COL_J),
          _XL_EDGE_BOTTOM, _XL_MEDIUM)
    for idx in range(n_circuit_rows):
        r     = DATA_START + idx
        cycle = idx % 3
        act_l = CYCLE_ACTIVE_LEFT[cycle]
        act_r = CYCLE_ACTIVE_RIGHT[cycle]
        _edge(_r(ws, r, act_l), _XL_EDGE_RIGHT, _XL_THIN)
        _edge(_r(ws, r, act_r), _XL_EDGE_LEFT,  _XL_THIN)


def apply_totals_borders(ws, totals_start):
    """
    Totals rows r0 (Power/phase), r1 (Amps/phase), r2 (Total kVA).
    r2: merge E:J with thick outer box; C:D label cell gets thick outer box.
    """
    r0, r1, r2 = totals_start, totals_start + 1, totals_start + 2

    for ri, r in enumerate((r0, r1)):
        rng = _r(ws, r, COL_C, r, COL_J)
        _edge(rng, _XL_EDGE_TOP,    _XL_MEDIUM if ri == 0 else _XL_THIN)
        _edge(rng, _XL_EDGE_BOTTOM, _XL_THIN)
        _edge(rng, _XL_EDGE_LEFT,   _XL_MEDIUM)
        _edge(rng, _XL_EDGE_RIGHT,  _XL_MEDIUM)
        # K-left closes the right side of the kVA zone for these rows
        _edge(_r(ws, r, COL_K), _XL_EDGE_LEFT, _XL_MEDIUM)

    # r2 — re-merge E:J (template only has E:H), thick box all around
    for c1, c2 in [(COL_E, COL_H), (COL_I, COL_J), (COL_E, COL_J)]:
        try: _r(ws, r2, c1, r2, c2).UnMerge()
        except Exception: pass
    _r(ws, r2, COL_E, r2, COL_J).Merge()
    _box(_r(ws, r2, COL_E, r2, COL_J), _XL_MEDIUM)

    # C:D label — unmerge, set border, remerge
    try: _r(ws, r2, COL_C, r2, COL_D).UnMerge()
    except Exception: pass
    _r(ws, r2, COL_C, r2, COL_D).Merge()
    rcd = _r(ws, r2, COL_C, r2, COL_D)
    _edge(rcd, _XL_EDGE_TOP,    _XL_THIN)
    _edge(rcd, _XL_EDGE_BOTTOM, _XL_MEDIUM)
    _edge(rcd, _XL_EDGE_LEFT,   _XL_MEDIUM)
    _edge(rcd, _XL_EDGE_RIGHT,  _XL_THIN)


def _feeder_demand_kva(f: dict) -> float:
    """Demand kVA for one feeder (S × DF — matches board total_S_kVA)."""
    sd = f.get('S_demand')
    if sd is not None:
        return float(sd)
    s = float(f.get('S') or 0.0)
    df = float(f.get('demand_factor_pct', 100.0)) / 100.0
    return round(s * df, 3)


def normalize_schedule_demands(feeders, board_info: dict) -> dict:
    """
    Demand kVA per feeder for panel schedule + summary (one map, one total).
    Keys: id(feeder dict) → demand kVA after L0 project DF scaling if applicable.
    """
    panel_demand = float(board_info.get('total_S_kVA') or 0.0)
    df_mode = board_info.get('df_mode', 'per_load')
    project_df = float(board_info.get('project_df_pct', 100.0))

    sized = [f for f in feeders
             if f.get('load_type', '') not in ('Space', 'Spare')]
    out = {id(f): round(_feeder_demand_kva(f), 3) for f in sized}
    if not out:
        return out

    sum_demand = round(sum(out.values()), 3)
    if (df_mode == 'project' and project_df < 100.0
            and panel_demand > 0 and sum_demand > 0
            and abs(sum_demand - panel_demand) > 0.05):
        scale = panel_demand / sum_demand
        for fid in out:
            out[fid] = round(out[fid] * scale, 2)

    return out


def schedule_cumulative_demand(demand_map: dict, board_info: dict) -> float:
    """Panel demand total — must match phase kVA total on the sheet."""
    panel_demand = float(board_info.get('total_S_kVA') or 0.0)
    if panel_demand > 0:
        return round(panel_demand, 2)
    return round(sum(demand_map.values()), 2)


def build_individual_load_schedule(feeders, board_info: dict,
                                 demand_map: dict = None) -> tuple:
    """
    Individual feeder lines grouped by load type.
    kVA column = demand load (connected × DF).
    """
    if demand_map is None:
        demand_map = normalize_schedule_demands(feeders, board_info)
    cumulative = schedule_cumulative_demand(demand_map, board_info)

    sized = [f for f in feeders
             if f.get('load_type', '') not in ('Space', 'Spare')]
    display = []

    for lt in LOAD_TYPE_ORDER:
        group = [f for f in sized if f.get('load_type') == lt]
        if not group:
            continue
        display.append({'kind': 'header', 'label': LOAD_TYPE_LABELS.get(lt, lt)})
        for f in sorted(group, key=lambda x: (x.get('name') or '').lower()):
            demand = round(demand_map.get(id(f), _feeder_demand_kva(f)), 2)
            conn = round(float(f.get('S') or 0.0), 2)
            df = round(float(f.get('demand_factor_pct', 100.0)), 1)
            if conn > 0 and abs(df - demand / conn * 100.0) > 0.15:
                df = round(demand / conn * 100.0, 1)
            display.append({
                'kind': 'feeder',
                'name': f.get('name', '') or '—',
                'conn_kva': conn,
                'df_pct': df,
                'd_load': demand,
            })

    return display, cumulative


def _insert_summary_rows(ws, xl, insert_at: int, count: int) -> None:
    if count <= 0:
        return
    ws.Rows(f'{insert_at}:{insert_at + count - 1}').Insert(Shift=_XL_DOWN)
    _r(ws, insert_at, COL_A, insert_at + count - 1, COL_N).ClearContents()
    _r(ws, insert_at, COL_A, insert_at + count - 1, COL_N).Borders.LineStyle = _XL_NONE


def apply_summary_borders(ws, start_row: int, n_rows: int) -> None:
    """Medium box around load-type summary block (cols A–D)."""
    if n_rows < 1:
        return
    _box(_r(ws, start_row, COL_A, start_row + n_rows - 1, COL_D), _XL_MEDIUM)


# Excel Font.Color — BGR (red = 255)
_EXCEL_RED = 255


def _cell_font(cell, bold=False, italic=False, red=False) -> None:
    f = cell.Font
    f.Bold = bold
    f.Italic = italic
    if red:
        f.Color = _EXCEL_RED


def write_load_type_summary(ws, xl, feeders, board_info: dict,
                            totals_start: int) -> None:
    """
    Two rows below phase totals: loads by type with kVA, DF %, D.Load;
    cumulative demand in D.Load column (matches panel total).
    """
    demand_map = normalize_schedule_demands(feeders, board_info)
    display, cumulative_demand = build_individual_load_schedule(
        feeders, board_info, demand_map)
    if not display:
        return

    block_start = totals_start + 3 + SUMMARY_GAP_ROWS
    n_block = 1 + len(display) + 1
    _insert_summary_rows(ws, xl, block_start, n_block)

    r = block_start
    c_load = ws.Cells(r, COL_A)
    c_kva = ws.Cells(r, COL_B)
    c_df = ws.Cells(r, COL_C)
    c_dl = ws.Cells(r, COL_D)
    c_load.Value = 'Load'
    c_kva.Value = 'kVA (S × DF)'
    c_df.Value = 'DF %'
    c_dl.Value = 'D.Load'
    _cell_font(c_load, bold=True)
    _cell_font(c_kva, bold=True, italic=True)
    _cell_font(c_df, bold=True, italic=True)
    _cell_font(c_dl, bold=True, red=True)
    r += 1

    for row in display:
        if row['kind'] == 'header':
            c0 = ws.Cells(r, COL_A)
            c0.Value = row['label']
            _cell_font(c0, bold=True)
            ws.Cells(r, COL_B).Value = ''
            ws.Cells(r, COL_C).Value = ''
            ws.Cells(r, COL_D).Value = ''
        else:
            ws.Cells(r, COL_A).Value = row['name']
            ws.Cells(r, COL_B).Value = row['conn_kva']
            ws.Cells(r, COL_C).Value = row['df_pct']
            ws.Cells(r, COL_D).Value = row['d_load']
        r += 1

    c_lbl = ws.Cells(r, COL_A)
    c_lbl.Value = 'Cumulative Demand Load'
    _cell_font(c_lbl, bold=True)
    ws.Cells(r, COL_B).Value = ''
    ws.Cells(r, COL_C).Value = ''
    c_tot = ws.Cells(r, COL_D)
    c_tot.Value = cumulative_demand
    _cell_font(c_tot, bold=True, red=True)

    apply_summary_borders(ws, block_start, n_block)


# ── Main sheet filler ─────────────────────────────────────────────────────────
def fill_board_sheet(ws, xl, board_info, feeders, voltage=400.0, panel_size=12):
    n_circuit_rows = panel_size // 2
    totals_start   = DATA_START + n_circuit_rows
    last_data_row  = totals_start - 1

    # 1. Expand beyond 12 ways if needed
    prepare_sheet(ws, xl, n_circuit_rows)

    # 2. Write header
    write_board_info(ws, board_info)

    # 3. Clear circuit area in one COM call
    _r(ws, DATA_START, COL_A, DATA_START + n_circuit_rows - 1, COL_N).ClearContents()
    _r(ws, DATA_START, COL_A, DATA_START + n_circuit_rows - 1, COL_N).Borders.LineStyle = _XL_NONE

    # 4. Build grid in Python, write once (14 cols × n_circuit_rows)
    # kVA cells = demand load (connected × DF), same basis as board total_S_kVA
    demand_map = normalize_schedule_demands(feeders, board_info)
    non_space   = [f for f in feeders if f.get('load_type', '') != 'Space']
    assignments = assign_feeders(non_space, n_circuit_rows)
    grid = [[None] * COL_N for _ in range(n_circuit_rows)]

    for f, side, start_idx, n_rows in assignments:
        is_spare = f.get('load_type', '') == 'Spare'
        demand_kva = float(demand_map.get(id(f), 0.0) or 0.0)
        mid_idx  = start_idx + (n_rows - 1) // 2

        for i in range(n_rows):
            idx  = start_idx + i
            pole = str(2 * idx + (1 if side == 'left' else 2)).zfill(2)
            if side == 'left':
                grid[idx][COL_D - 1] = pole
            else:
                grid[idx][COL_K - 1] = pole

        row = grid[mid_idx]
        if side == 'left':
            row[COL_A - 1] = f.get('name', '')
            row[COL_B - 1] = cable_label(f)
            row[COL_C - 1] = cb_label(f)
        else:
            row[COL_N - 1] = f.get('name', '')
            row[COL_M - 1] = cable_label(f)
            row[COL_L - 1] = cb_label(f)

        if not is_spare and demand_kva:
            kva_per_row = round(demand_kva / n_rows, 2)
            for i in range(n_rows):
                idx   = start_idx + i
                cycle = idx % 3
                col   = (CYCLE_ACTIVE_LEFT[cycle] if side == 'left'
                         else CYCLE_ACTIVE_RIGHT[cycle])
                grid[idx][col - 1] = kva_per_row

    left_used  = {a[2] + i for a in assignments if a[1] == 'left'  for i in range(a[3])}
    right_used = {a[2] + i for a in assignments if a[1] == 'right' for i in range(a[3])}
    for idx in range(n_circuit_rows):
        if idx not in left_used:
            grid[idx][COL_A - 1] = 'SPACE'
            grid[idx][COL_D - 1] = str(2 * idx + 1).zfill(2)
        if idx not in right_used:
            grid[idx][COL_N - 1] = 'SPACE'
            grid[idx][COL_K - 1] = str(2 * idx + 2).zfill(2)

    _r(ws, DATA_START, COL_A, DATA_START + n_circuit_rows - 1, COL_N).Value = tuple(
        tuple(row) for row in grid
    )

    # 5. Apply all borders from scratch
    apply_all_borders(ws, assignments, n_circuit_rows)
    apply_totals_borders(ws, totals_start)

    # 7. Totals formulas (one row write)
    vln = round(voltage / math.sqrt(3), 1)
    r0, r1, r2 = totals_start, totals_start + 1, totals_start + 2
    _r(ws, r0, COL_E, r0, COL_I).Value = (
        f'=SUM(E{DATA_START}:F{last_data_row})',
        None,
        f'=SUM(G{DATA_START}:H{last_data_row})',
        None,
        f'=SUM(I{DATA_START}:J{last_data_row})',
    )
    _r(ws, r1, COL_E, r1, COL_I).Value = (
        f'=IFERROR(E{r0}*1000/{vln},"")',
        None,
        f'=IFERROR(G{r0}*1000/{vln},"")',
        None,
        f'=IFERROR(I{r0}*1000/{vln},"")',
    )
    ws.Cells(r2, COL_E).Value = f'=E{r0}+G{r0}+I{r0}'

    # 8. Individual load demand list (2 rows below phase totals)
    write_load_type_summary(ws, xl, feeders, board_info, totals_start)


def _build_workbook_openpyxl(boards, voltage, out_path):
    """Build the schedule from the same template without requiring Excel/COM."""
    from copy import copy

    from openpyxl import load_workbook
    from openpyxl.cell.cell import MergedCell
    from openpyxl.styles import Border, Side

    if not boards or not out_path:
        return None, []

    wb = load_workbook(_template_path())
    warnings = []
    template_sheet = wb.worksheets[0]

    for board_index, board in enumerate(boards, 1):
        ws = wb.copy_worksheet(template_sheet)
        safe_name = board['name'].translate(str.maketrans('/\\?*:[]', '-------'))
        ws.title = safe_name[:31] or f'Board {board_index}'

        n_circuit_rows = max(TEMPLATE_CIRCUIT_ROWS, int(board.get('panel_size', 12) or 12) // 2)
        original_totals_start = DATA_START + TEMPLATE_CIRCUIT_ROWS
        totals_start = DATA_START + n_circuit_rows
        extra_rows = n_circuit_rows - TEMPLATE_CIRCUIT_ROWS
        total_styles = None

        if extra_rows:
            total_styles = [
                [copy(ws.cell(original_totals_start + row, col)._style) for col in range(1, COL_N + 1)]
                for row in range(3)
            ]
            total_heights = [
                ws.row_dimensions[original_totals_start + row].height
                for row in range(3)
            ]
            for merged_range in list(ws.merged_cells.ranges):
                if merged_range.min_row >= original_totals_start:
                    ws.unmerge_cells(str(merged_range))
            ws.insert_rows(original_totals_start, extra_rows)

            for offset in range(extra_rows):
                source_row = DATA_START + TEMPLATE_CIRCUIT_ROWS - 3 + offset % 3
                target_row = original_totals_start + offset
                for col in range(1, COL_N + 1):
                    ws.cell(target_row, col)._style = copy(ws.cell(source_row, col)._style)
                ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
                for col1, col2 in CYCLE_MERGES[offset % 3]:
                    ws.merge_cells(start_row=target_row, start_column=col1,
                                   end_row=target_row, end_column=col2)

            for row_offset, styles in enumerate(total_styles):
                row = totals_start + row_offset
                for col, style in enumerate(styles, 1):
                    ws.cell(row, col)._style = style
                ws.row_dimensions[row].height = total_heights[row_offset]

        board_info = {key: board.get(key, '') for key in (
            'name', 'ip_rating', 'main_cb_type', 'main_cb_size',
            'main_cable', 'source', 'total_S_kVA', 'total_S_connected',
            'df_mode', 'project_df_pct',
        )}
        for col, key in enumerate(('name', 'ip_rating', 'main_cb_type', 'main_cb_size'), 1):
            ws.cell(INFO_VALUE_ROW, col).value = board_info[key]
        ws.cell(INFO_VALUE_ROW, COL_F).value = board_info['main_cable']
        ws.cell(INFO_VALUE_ROW, COL_N).value = board_info['source']

        feeders = board.get('feeders', [])
        demand_map = normalize_schedule_demands(feeders, board_info)
        assignments = assign_feeders(
            [feeder for feeder in feeders if feeder.get('load_type', '') != 'Space'],
            n_circuit_rows,
        )
        grid = [[None] * COL_N for _ in range(n_circuit_rows)]

        for feeder, side, start_idx, n_rows in assignments:
            is_spare = feeder.get('load_type', '') == 'Spare'
            demand_kva = float(demand_map.get(id(feeder), 0.0) or 0.0)
            mid_idx = start_idx + (n_rows - 1) // 2
            for idx in range(start_idx, start_idx + n_rows):
                if side == 'left':
                    grid[idx][COL_D - 1] = str(2 * idx + 1).zfill(2)
                else:
                    grid[idx][COL_K - 1] = str(2 * idx + 2).zfill(2)

            row = grid[mid_idx]
            if side == 'left':
                row[COL_A - 1] = feeder.get('name', '')
                row[COL_B - 1] = cable_label(feeder)
                row[COL_C - 1] = cb_label(feeder)
            else:
                row[COL_N - 1] = feeder.get('name', '')
                row[COL_M - 1] = cable_label(feeder)
                row[COL_L - 1] = cb_label(feeder)

            if not is_spare and demand_kva:
                kva_per_row = round(demand_kva / n_rows, 2)
                for idx in range(start_idx, start_idx + n_rows):
                    phase = idx % 3
                    col = CYCLE_ACTIVE_LEFT[phase] if side == 'left' else CYCLE_ACTIVE_RIGHT[phase]
                    grid[idx][col - 1] = kva_per_row

        left_used = {assignment[2] + i for assignment in assignments
                     if assignment[1] == 'left' for i in range(assignment[3])}
        right_used = {assignment[2] + i for assignment in assignments
                      if assignment[1] == 'right' for i in range(assignment[3])}
        for idx in range(n_circuit_rows):
            if idx not in left_used:
                grid[idx][COL_A - 1] = 'SPACE'
                grid[idx][COL_D - 1] = str(2 * idx + 1).zfill(2)
            if idx not in right_used:
                grid[idx][COL_N - 1] = 'SPACE'
                grid[idx][COL_K - 1] = str(2 * idx + 2).zfill(2)

        for row_offset, values in enumerate(grid):
            row = DATA_START + row_offset
            for col, value in enumerate(values, 1):
                cell = ws.cell(row, col)
                if not isinstance(cell, MergedCell):
                    cell.value = value

        thin = Side(style='thin')
        medium = Side(style='medium')

        def outline(min_row, min_col, max_row, max_col, side):
            for col in range(min_col, max_col + 1):
                cell = ws.cell(min_row, col)
                cell.border = Border(left=cell.border.left, right=cell.border.right,
                                     top=side, bottom=cell.border.bottom)
                cell = ws.cell(max_row, col)
                cell.border = Border(left=cell.border.left, right=cell.border.right,
                                     top=cell.border.top, bottom=side)
            for row in range(min_row, max_row + 1):
                cell = ws.cell(row, min_col)
                cell.border = Border(left=side, right=cell.border.right,
                                     top=cell.border.top, bottom=cell.border.bottom)
                cell = ws.cell(row, max_col)
                cell.border = Border(left=cell.border.left, right=side,
                                     top=cell.border.top, bottom=cell.border.bottom)

        for _, side, start_idx, n_rows in assignments:
            start_row = DATA_START + start_idx
            end_row = start_row + n_rows - 1
            outline(start_row, COL_A if side == 'left' else COL_K,
                    end_row, COL_D if side == 'left' else COL_N, medium)
        for idx in range(n_circuit_rows):
            row = DATA_START + idx
            if idx not in left_used:
                outline(row, COL_A, row, COL_D, medium)
            if idx not in right_used:
                outline(row, COL_K, row, COL_N, medium)

        outline(DATA_START, COL_E, DATA_START + n_circuit_rows - 1, COL_J, medium)
        for idx in range(n_circuit_rows):
            row = DATA_START + idx
            phase = idx % 3
            for col, edge in ((CYCLE_ACTIVE_LEFT[phase], 'right'),
                              (CYCLE_ACTIVE_RIGHT[phase], 'left')):
                cell = ws.cell(row, col)
                border = copy(cell.border)
                setattr(border, edge, thin)
                cell.border = border

        vln = round(voltage / math.sqrt(3), 1)
        phase_totals = totals_start
        for col, formula in zip(
            (COL_E, COL_G, COL_I),
            (f'=SUM(E{DATA_START}:F{totals_start - 1})',
             f'=SUM(G{DATA_START}:H{totals_start - 1})',
             f'=SUM(I{DATA_START}:J{totals_start - 1})'),
        ):
            ws.cell(phase_totals, col).value = formula
        for col, source_col in zip((COL_E, COL_G, COL_I), ('E', 'G', 'I')):
            ws.cell(phase_totals + 1, col).value = (
                f'=IFERROR({source_col}{phase_totals}*1000/{vln},"")')
        ws.cell(phase_totals + 2, COL_E).value = (
            f'=E{phase_totals}+G{phase_totals}+I{phase_totals}')

        for merged_range in list(ws.merged_cells.ranges):
            if merged_range.min_row >= phase_totals:
                ws.unmerge_cells(str(merged_range))
        for row in (phase_totals, phase_totals + 1):
            ws.merge_cells(start_row=row, start_column=COL_C, end_row=row, end_column=COL_D)
            for col in (COL_E, COL_G, COL_I):
                ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
        ws.merge_cells(start_row=phase_totals + 2, start_column=COL_C,
                       end_row=phase_totals + 2, end_column=COL_D)
        ws.merge_cells(start_row=phase_totals + 2, start_column=COL_E,
                       end_row=phase_totals + 2, end_column=COL_J)
        outline(phase_totals, COL_C, phase_totals + 1, COL_J, medium)
        outline(phase_totals + 2, COL_C, phase_totals + 2, COL_J, medium)

        display, cumulative = build_individual_load_schedule(feeders, board_info, demand_map)
        if display:
            summary_start = phase_totals + 3 + SUMMARY_GAP_ROWS
            summary_count = len(display) + 2
            ws.insert_rows(summary_start, summary_count)
            source_row = DATA_START
            for offset in range(summary_count):
                row = summary_start + offset
                for col in range(1, COL_N + 1):
                    ws.cell(row, col)._style = copy(ws.cell(source_row, col)._style)
                ws.row_dimensions[row].height = ws.row_dimensions[source_row].height

            headers = ('Load', 'kVA (S × DF)', 'DF %', 'D.Load')
            for col, value in enumerate(headers, 1):
                cell = ws.cell(summary_start, col)
                cell.value = value
                font = copy(cell.font)
                font.bold = True
                font.italic = col in (2, 3)
                if col == 4:
                    font.color = 'FF0000'
                cell.font = font

            for offset, item in enumerate(display, 1):
                row = summary_start + offset
                if item['kind'] == 'header':
                    cell = ws.cell(row, 1)
                    cell.value = item['label']
                    font = copy(cell.font)
                    font.bold = True
                    cell.font = font
                else:
                    ws.cell(row, 1).value = item['name']
                    ws.cell(row, 2).value = item['conn_kva']
                    ws.cell(row, 3).value = item['df_pct']
                    ws.cell(row, 4).value = item['d_load']

            total_row = summary_start + summary_count - 1
            ws.cell(total_row, 1).value = 'Cumulative Demand Load'
            font = copy(ws.cell(total_row, 1).font)
            font.bold = True
            ws.cell(total_row, 1).font = font
            ws.cell(total_row, 4).value = cumulative
            font = copy(ws.cell(total_row, 4).font)
            font.bold = True
            font.color = 'FF0000'
            ws.cell(total_row, 4).font = font
            outline(summary_start, COL_A, total_row, COL_D, medium)

    wb.remove(template_sheet)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.save(out_path)
    return None, warnings


def _workbook_path(wb) -> str:
    try:
        return os.path.normcase(os.path.abspath(wb.FullName))
    except Exception:
        return os.path.normcase(wb.Name)


def _close_stray_workbooks(xl, keep_wb) -> None:
    """Close extra workbooks (e.g. from Sheet.Copy) without saving."""
    keep_path = _workbook_path(keep_wb)
    try:
        for i in range(xl.Workbooks.Count, 0, -1):
            other = xl.Workbooks(i)
            if _workbook_path(other) != keep_path:
                try:
                    other.Close(SaveChanges=False)
                except Exception:
                    pass
    except Exception:
        pass


def _add_board_sheet(wb, ws_tmpl, xl) -> None:
    """Add one worksheet to wb by pasting the template (never Sheet.Copy — spawns new files)."""
    new_ws = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
    ws_tmpl.Cells.Copy()
    new_ws.Cells(1, 1).PasteSpecial(Paste=_XL_PASTE_ALL)
    new_ws.Cells(1, 1).PasteSpecial(Paste=8)   # xlPasteColumnWidths
    xl.CutCopyMode = False
    _close_stray_workbooks(xl, wb)


# ── Multi-sheet workbook ──────────────────────────────────────────────────────
def build_workbook(boards, voltage=400.0, out_path=None):
    """
    Export a panel schedule workbook, using Excel COM on Windows and
    openpyxl elsewhere.
    Returns (None, warnings_list).
    """
    if not boards or not out_path:
        return None, []

    if sys.platform != 'win32':
        return _build_workbook_openpyxl(boards, voltage, out_path)

    import shutil

    # ── Step 1: physical file copy — template → destination ──────────────────
    # This means we never touch the original template and never need to delete
    # any sheet from within Excel.
    abs_out = os.path.abspath(out_path)
    shutil.copy(os.path.abspath(_template_path()), abs_out)

    warnings = []
    xl = None
    wb = None
    _owned = False
    try:
        xl     = _open_excel_app()
        _owned = True   # dedicated instance — Quit on failure

        # Open the already-copied output file (not the original template)
        wb      = xl.Workbooks.Open(abs_out)
        _excel_fast_mode(xl, True)   # after open — Calculation may fail earlier on some Excel builds
        ws_tmpl = wb.Worksheets(1)   # the one blank template sheet

        # ── Step 2: one sheet per board (reliable clone into this workbook) ─────
        while wb.Worksheets.Count < len(boards):
            _add_board_sheet(wb, ws_tmpl, xl)
        _close_stray_workbooks(xl, wb)

        # ── Step 3: fill each sheet ───────────────────────────────────────────
        n_sheets = wb.Worksheets.Count
        for idx, board in enumerate(boards):
            if idx + 1 > n_sheets:
                raise RuntimeError(
                    f'Excel workbook has {n_sheets} sheet(s) but '
                    f'{len(boards)} board(s) were requested.')

            ws    = wb.Worksheets(idx + 1)   # 1-based
            _xl_set(ws, 'Visible', -1)       # xlSheetVisible
            _safe = board['name'].translate(
                        str.maketrans('/\\?*:[],', '--------'))
            try:
                ws.Name = _safe[:31]
            except Exception:
                pass

            board_info = {k: board.get(k, '') for k in
                          ('name', 'ip_rating', 'main_cb_type',
                           'main_cb_size', 'main_cable', 'source',
                           'total_S_kVA', 'total_S_connected',
                           'df_mode', 'project_df_pct')}
            panel_size = max(12, int(board.get('panel_size', 12) or 12))
            fill_board_sheet(ws, xl, board_info, board.get('feeders', []),
                             voltage, panel_size)

        wb.Worksheets(1).Activate()
        _close_stray_workbooks(xl, wb)

        # Save in place (file was already copied to abs_out)
        wb.Save()
        _close_stray_workbooks(xl, wb)

        # Hand off to the user — reveal Excel with the finished workbook
        _excel_fast_mode(xl, False)
        _xl_set(xl, 'Visible', True)
        try:
            wb.Activate()
        except Exception:
            pass

    except Exception:
        if xl is not None:
            try:
                _excel_fast_mode(xl, False)
            except Exception:
                pass
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if xl is not None and _owned:
            try:
                xl.Quit()
            except Exception:
                pass
        raise

    return None, warnings
