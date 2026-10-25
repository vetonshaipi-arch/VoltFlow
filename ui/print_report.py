# ui/print_report.py — VoltFlow print reports
import math, os, sys

# Dev-only path fix: never reorder sys.path inside a PyInstaller bundle —
# that can break frozen imports and kill the process on SLD.
if not getattr(sys, 'frozen', False):
    _HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _CABLE = os.path.join(_HERE, 'VSEngCableSelector')
    if _HERE in sys.path:
        sys.path.remove(_HERE)
    sys.path.insert(0, _HERE)
    if _CABLE not in sys.path:
        sys.path.insert(1, _CABLE)

def _e(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def _ph(ph):
    return {'L123':'L1,L2,L3,N,PE','L1':'L1,N,PE',
            'L2':'L2,N,PE','L3':'L3,N,PE'}.get(ph, ph)

def _rot(text, x, y, angle, size, color, font='Segoe UI,Arial', anchor='middle', bold=False):
    fw = 'bold' if bold else 'normal'
    return (f'<text transform="rotate({angle},{x},{y})" x="{x}" y="{y}" '
            f'text-anchor="{anchor}" font-family="{font}" font-size="{size}" '
            f'font-weight="{fw}" fill="{color}">{_e(text)}</text>')

def _txt(x, y, text, size=11, color='#1a1a1a', anchor='middle',
         font='Segoe UI,Arial', bold=False):
    fw = 'bold' if bold else 'normal'
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
            f'font-family="{font}" font-size="{size}" '
            f'font-weight="{fw}" fill="{color}">{_e(text)}</text>')

def _cb_mcb(cx, y_top, y_bot):
    """IEC MCB symbol: open-contact arc — right-facing semicircular arc."""
    span  = y_bot - y_top
    half  = int(span * 0.10)          # half-gap = arc radius → semicircle
    mid   = y_top + span // 2
    g_top = mid - half
    g_bot = mid + half
    return '\n'.join([
        f'<line x1="{cx}" y1="{y_top}" x2="{cx}" y2="{g_top}" '
        f'stroke="#000" stroke-width="2"/>',
        f'<path d="M {cx} {g_top} A {half} {half} 0 0 1 {cx} {g_bot}" '
        f'fill="none" stroke="#000" stroke-width="2"/>',
        f'<line x1="{cx}" y1="{g_bot}" x2="{cx}" y2="{y_bot}" '
        f'stroke="#000" stroke-width="2"/>',
    ]), g_top


def _cb_mccb(cx, y_top, y_bot):
    """IEC MCCB / ACB symbol: × mark + right-facing arc."""
    span = y_bot - y_top
    xd   = 9                              # half-diagonal of × mark
    x_cy = y_top + int(span * 0.38)      # centre of ×
    r    = int(span * 0.14)              # arc radius
    a_cy = y_top + int(span * 0.70)      # centre of arc
    return '\n'.join([
        # top wire
        f'<line x1="{cx}" y1="{y_top}" x2="{cx}" y2="{x_cy - xd}" '
        f'stroke="#000" stroke-width="2"/>',
        # × — two crossing diagonals
        f'<line x1="{cx-xd}" y1="{x_cy-xd}" x2="{cx+xd}" y2="{x_cy+xd}" '
        f'stroke="#000" stroke-width="1.8"/>',
        f'<line x1="{cx-xd}" y1="{x_cy+xd}" x2="{cx+xd}" y2="{x_cy-xd}" '
        f'stroke="#000" stroke-width="1.8"/>',
        # connecting segment × → arc
        f'<line x1="{cx}" y1="{x_cy + xd}" x2="{cx}" y2="{a_cy - r}" '
        f'stroke="#000" stroke-width="2"/>',
        # right-facing arc: sweeps from top to bottom bulging rightward
        f'<path d="M {cx} {a_cy - r} A {r} {r} 0 0 1 {cx} {a_cy + r}" '
        f'fill="none" stroke="#000" stroke-width="1.8"/>',
        # bottom wire
        f'<line x1="{cx}" y1="{a_cy + r}" x2="{cx}" y2="{y_bot}" '
        f'stroke="#000" stroke-width="2"/>',
    ]), x_cy - xd


def _sld_cb_h(cb_type: str, cy, x_left, x_right):
    """IEC CB on a horizontal conductor (arc facing down)."""
    cx = (x_left + x_right) // 2
    half = max(18, (x_right - x_left) // 2)
    fn = _cb_mcb if cb_type == 'MCB' else _cb_mccb
    svg, _ = fn(cx, cy - half, cy + half)
    return (f'<g transform="rotate(270,{cx},{cy})">{svg}</g>',
            cx + half, cx - half)


# ─────────────────────────────────────────────────────────────────────────────
# SLD
# ─────────────────────────────────────────────────────────────────────────────

def build_sld_html(board, root_board=None) -> str:
    feeders = board.feeders
    n = len(feeders)
    if n == 0:
        return '<html><body><p>No feeders.</p></body></html>'

    COL      = 120
    ML       = 90
    TILDE_Y  = 60       # ~ symbol baseline y
    # BUS_Y chosen so incomer span (TILDE_Y → BUS_Y) = outgoing span (BUS_Y → CB_BOT)
    BUS_Y    = TILDE_Y + 94       # = 154 — both spans are 94 px
    CB_TOP   = BUS_Y + 28
    CB_BOT   = CB_TOP + 66
    PHASE_MID= CB_BOT + 50
    CABLE_MID= CB_BOT + 160
    CIR_Y    = CB_BOT + 290
    LBL_Y    = CIR_Y + 26
    SVG_H    = LBL_Y + 120
    SVG_W    = ML + n * COL + 60

    S = []

    # ── Incomer: ~ at top, main CB symbol, line down to busbar ──
    ix = ML - 30
    mcb      = board.main_cb
    mcb_in  = mcb.In_CB  if mcb and mcb.In_CB  else 0
    mcb_typ = mcb.cb_type if mcb and mcb.In_CB  else ''
    S.append(_txt(ix, TILDE_Y, '~', size=42, color='#000', bold=True))
    _inc_fn = _cb_mcb if mcb_typ == 'MCB' else _cb_mccb
    inc_svg, inc_box_y = _inc_fn(ix, TILDE_Y, BUS_Y)
    S.append(inc_svg)
    if mcb_in:
        S.append(_txt(ix + 14, inc_box_y + 10,
                      f'{mcb_in:.0f}A {mcb_typ}',
                      anchor='start', size=7, color='#333'))
    S.append(f'<circle cx="{ix}" cy="{BUS_Y}" r="6" fill="#000"/>')

    # ── Main busbar ──
    bx1 = ML - 44
    bx2 = ML + n * COL + 20
    S.append(f'<line x1="{bx1}" y1="{BUS_Y}" x2="{bx2}" y2="{BUS_Y}" '
             f'stroke="#000" stroke-width="5"/>')

    for i, f in enumerate(feeders):
        cx        = ML + i * COL + COL // 2
        rec       = f.cable.recommended
        is_sp     = f.load_type == 'SubPanel'
        is_spare  = f.load_type == 'Spare'
        is_space  = f.load_type == 'Space'
        c_circ    = '#e67e00' if is_sp else '#1a3a5c'
        f_circ    = '#fff8ee' if is_sp else '#ffffff'
        R         = 18

        # Tap dot ON busbar
        S.append(f'<circle cx="{cx}" cy="{BUS_Y}" r="5" fill="#000"/>')

        if is_space:
            # SPACE: tap dot only — no CB, no conductor, no circle
            S.append(_rot('SPACE', cx-4, CB_TOP+40, -90, 8, '#aaaaaa'))
            continue

        # CB symbol — shape depends on type (resolved after subpanel lookup below)
        _cb_fn = _cb_mcb if f.cb.cb_type == 'MCB' else _cb_mccb
        cb_svg, box_y = _cb_fn(cx, BUS_Y, CB_BOT)
        S.append(cb_svg)

        lx = cx + 15
        S.append(_txt(lx, box_y+15, f.circuit_ref,
                      size=10, color='#c40080', anchor='start', bold=True))
        cb_In  = f.cb.In_CB
        cb_typ = f.cb.cb_type
        if is_sp and not cb_In and root_board:
            child = root_board.find_board(f.subpanel_id) if (
                hasattr(f,'subpanel_id') and f.subpanel_id) else None
            if child and child.main_cb.In_CB:
                cb_In  = child.main_cb.In_CB
                cb_typ = child.main_cb.cb_type
        if cb_In:
            S.append(_txt(lx, box_y+28,
                          f'{cb_In:.0f}A {cb_typ}',
                          size=9, color='#c40080', anchor='start'))

        if is_spare:
            # SPARE: CB shown above, then just name — no conductor, no circle
            S.append(_rot(f.name[:22], cx-4, CB_BOT+40, -90, 9, '#888', anchor='end'))
            continue

        # Normal feeder: phase, conductor, circle, labels
        S.append(_rot(_ph(f.phase_str), cx-12, PHASE_MID, -90, 8, '#444'))

        S.append(f'<line x1="{cx}" y1="{CB_BOT}" x2="{cx}" y2="{CIR_Y-R}" '
                 f'stroke="#555" stroke-width="1.5"/>')

        if rec:
            S.append(_rot(f.cable.format_conductor_desc(f.phases), cx-12, CABLE_MID,
                          -90, 8.5, '#0070c0', font='Courier New,monospace'))
            S.append(_rot(f'L={f.cable_length:.1f}m', cx+14, CABLE_MID,
                          -90, 8.5, '#555'))

        S.append(f'<circle cx="{cx}" cy="{CIR_Y}" r="{R}" '
                 f'fill="{f_circ}" stroke="{c_circ}" stroke-width="2.5"/>')
        S.append(_txt(cx, CIR_Y+5, str(i+1), size=12, color=c_circ, bold=True))

        S.append(_rot(f.name[:22], cx-4, LBL_Y+10, -90, 9, '#1a1a1a', anchor='end'))
        if f.P:
            S.append(_rot(f'P = {f.P:.2f} kW', cx+12, LBL_Y+10,
                          -90, 8.5, '#1a1a1a', anchor='end'))

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'width="{SVG_W}" height="{SVG_H}" style="background:#fff;">'
           + '\n'.join(S) + '</svg>')

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>SLD — {_e(board.name)}</title>
<style>
  body{{margin:0;padding:20px 24px;font-family:'Segoe UI',Arial,sans-serif;background:#fff;}}
  h2{{color:#1a3a5c;margin:0 0 4px 0;font-size:22px;font-weight:bold;}}
  p{{color:#555;font-size:12px;margin:0 0 16px 0;}}
  .w{{overflow:auto;}}
  @media print{{body{{padding:8px;}}.w{{overflow:visible;}}}}
</style></head><body>
<h2>VoltFlow — Single Line Diagram — {_e(board.name)}</h2>
<p>{board.phases}~{board.voltage:.0f}V &nbsp;|&nbsp;
   {board.frequency:.0f}Hz &nbsp;|&nbsp;
   Ik = {board.Isc_board_kA:.2f} kA &nbsp;|&nbsp;
   Busbar: {board.busbar_A:.0f}A</p>
<div class="w">{svg}</div>
</body></html>"""


def _sld_cb_fn(cb_type: str):
    return _cb_mcb if cb_type == 'MCB' else _cb_mccb


def _sld_append_cb_rating(S, lx, box_y, f, root_board, is_sp: bool):
    cb_In = f.cb.In_CB
    cb_typ = f.cb.cb_type
    if is_sp and not cb_In and root_board:
        child = (root_board.find_board(f.subpanel_id)
                 if getattr(f, 'subpanel_id', None) else None)
        if child and child.main_cb.In_CB:
            cb_In = child.main_cb.In_CB
            cb_typ = child.main_cb.cb_type
    if cb_In:
        S.append(_txt(lx, box_y + 28, f'{cb_In:.0f}A {cb_typ}',
                      size=9, color='#c40080', anchor='start'))


def _board_main_cb_text(board) -> str:
    mcb = board.main_cb
    if mcb and mcb.In_CB:
        return f'{mcb.In_CB:.0f}A {mcb.cb_type}'
    return ''


def _sld_draw_cable(S, cx, y_from, y_to, phases, cable_obj, length_m,
                    label_gap=12, label_pad=10, vd_pct=None, incomer=False):
    if cable_obj is None or not cable_obj.recommended:
        return
    y1 = y_from + label_pad
    y2 = y_to - label_pad
    if y2 <= y1:
        y1, y2 = y_from, y_to
    mid_y = (y1 + y2) // 2
    seg = y2 - y1
    stack = min(38, max(20, seg // 4))
    S.append(_rot(cable_obj.format_conductor_desc(phases),
                  cx - label_gap, mid_y, -90, 8.5,
                  '#0070c0', font='Courier New,monospace'))
    if vd_pct is not None:
        vd_lbl = (f'ΔUcable={vd_pct:.2f}%' if incomer
                  else f'ΔUc={vd_pct:.2f}%')
        S.append(_rot(f'L={length_m:.1f}m', cx + label_gap, mid_y - stack, -90, 8.5,
                      '#555', anchor='middle'))
        S.append(_rot(vd_lbl, cx + label_gap, mid_y + stack, -90, 8.5,
                      '#c00000', anchor='middle'))
    else:
        S.append(_rot(f'L={length_m:.1f}m', cx + label_gap, mid_y, -90, 8.5, '#555'))


def _sld_draw_cable_h(S, y, x_from, x_to, phases, cable_obj, length_m,
                      label_gap=14, label_pad=12, vd_pct=None, incomer=False):
    """Horizontal run: cable type above, L and ΔU below."""
    if cable_obj is None or not cable_obj.recommended:
        return
    x1 = x_from + label_pad
    x2 = x_to - label_pad
    if x2 <= x1:
        x1, x2 = x_from, x_to
    mid_x = (x1 + x2) // 2
    S.append(_txt(mid_x, y - label_gap,
                  cable_obj.format_conductor_desc(phases),
                  size=8.5, color='#0070c0', font='Courier New,monospace'))
    if vd_pct is not None:
        vd_lbl = (f'ΔUcable={vd_pct:.2f}%' if incomer
                  else f'ΔUc={vd_pct:.2f}%')
        S.append(_txt(mid_x, y + label_gap, f'L={length_m:.1f}m',
                      size=8.5, color='#555'))
        S.append(_txt(mid_x, y + label_gap + 13, vd_lbl,
                      size=8.5, color='#c00000'))
    else:
        S.append(_txt(mid_x, y + label_gap, f'L={length_m:.1f}m',
                      size=8.5, color='#555'))


def _sld_vd_box(S, cx, cy, vd_pct, prefix='ΔUtotal', anchor='middle'):
    """Tight-bordered ΔU box; anchor 'start' places box to the right of cx."""
    label = f'{prefix}={vd_pct:.2f}%'
    w = int(len(label) * 5.6 + 8)
    h = 16
    x0 = cx if anchor == 'start' else cx - w // 2
    S.append(f'<rect x="{x0}" y="{cy - h}" width="{w}" height="{h}" '
             f'fill="#fff" stroke="#333" stroke-width="1"/>')
    S.append(_txt(x0 + w // 2, cy - 5, label, size=8, color='#000'))
    return x0 + w


def _sld_panel_bus(S, x, y_top, y_bot, width=6):
    S.append(f'<line x1="{x}" y1="{y_top}" x2="{x}" y2="{y_bot}" '
             f'stroke="#000" stroke-width="{width}"/>')


def build_sld_tree_html(root_board) -> str:
    """Left-to-right tree SLD: vertical busbars, horizontal branches, Vdrop labels."""

    MARGIN = 60
    ROW_H = 92
    HEADER_ABOVE = 52
    SIBLING_BOARD_GAP = 36
    FEEDER_LEN = 140
    R_LOAD = 16
    CHILD_AFTER_LOAD_GAP = 80
    SUPPLY_X = MARGIN
    SUPPLY_W = 14
    INCOMER_LEN = FEEDER_LEN
    CB_SPAN = 44
    LABEL_PAD = 12
    BUS_PAD = 16

    def _branch_rows(board):
        rows = []
        for f in board.feeders:
            if f.load_type not in ('SubPanel', 'Spare', 'Space'):
                rows.append(('feeder', f))
        for c in board.child_boards:
            rows.append(('child', c))
        return rows

    def _branch_stack_height(board):
        rows = _branch_rows(board)
        if not rows:
            return ROW_H
        h = 0
        for i, (kind, item) in enumerate(rows):
            if kind == 'child':
                h += _subtree_height(item)
                if i < len(rows) - 1:
                    h += SIBLING_BOARD_GAP
            else:
                h += ROW_H
        return h

    def _subtree_height(board):
        return HEADER_ABOVE + _branch_stack_height(board)

    def _subtree_width(node):
        w = node['bus_x'] + FEEDER_LEN + 115
        for c in node['children']:
            w = max(w, _subtree_width(c))
        return w

    def _layout_board(board, bus_x, y0, parent_actual_V, depth):
        nom_V = float(root_board.voltage or 0.0) or 400.0
        if parent_actual_V is None:
            parent_actual_V = nom_V
        pf = board.primary_feeder
        pf_valid = (board.primary_feeder_selected and
                    pf.cable.recommended is not None and
                    pf.cable.passes_ampacity)
        cable_vd_pct = pf.result_vdrop_pct if pf_valid else 0.0
        board_actual_V = parent_actual_V * (1.0 - cable_vd_pct / 100.0)
        cum_vd = round((nom_V - board_actual_V) / nom_V * 100.0, 3)

        rows = _branch_rows(board)
        branch_h = _branch_stack_height(board)
        total_h = HEADER_ABOVE + branch_h

        y_top = y0 + HEADER_ABOVE
        y_bot = y0 + total_h
        node = {
            'board': board, 'bus_x': bus_x,
            'bus_y_top': y_top, 'bus_y_bot': y_bot,
            'incomer_cy': (y_top + y_bot) // 2,
            'depth': depth, 'pf': pf, 'pf_valid': pf_valid,
            'cable_vd': cable_vd_pct, 'cum_vd': cum_vd,
            'feeders': [], 'children': [],
        }

        y = y0 + HEADER_ABOVE
        for i, (kind, item) in enumerate(rows):
            h = _subtree_height(item) if kind == 'child' else ROW_H
            cy = y + h // 2
            if kind == 'feeder':
                f_vd = item.result_vdrop_pct or 0.0
                f_actual_V = board_actual_V * (1.0 - f_vd / 100.0)
                f_cum_vd = round((nom_V - f_actual_V) / nom_V * 100.0, 3)
                node['feeders'].append({
                    'feeder': item, 'cy': cy, 'cum_vd': f_cum_vd,
                })
            else:
                child_bus_x = bus_x + FEEDER_LEN + R_LOAD + CHILD_AFTER_LOAD_GAP
                cn = _layout_board(item, child_bus_x, y, board_actual_V, depth + 1)
                cn['tap_cy'] = cy
                node['children'].append(cn)
            y += h
            if kind == 'child' and i < len(rows) - 1:
                y += SIBLING_BOARD_GAP
        return node

    root_bus_x = SUPPLY_X + SUPPLY_W + INCOMER_LEN
    root_h = _subtree_height(root_board)
    y0 = MARGIN
    root_node = _layout_board(root_board, root_bus_x, y0, None, 0)
    SVG_W = int(_subtree_width(root_node)) + MARGIN
    SVG_H = int(root_h) + MARGIN * 2
    S = []

    def _draw_panel_header(bx, y_top, b, cum_vd):
        """Stack labels above the busbar top — no overlap with the bus."""
        y = y_top - 10
        if cum_vd > 0:
            _sld_vd_box(S, bx, y, cum_vd)
            y -= 24
        S.append(_txt(bx, y, b.name, size=13, bold=True, color='#003d8f'))
        y -= 15
        cb_lbl = _board_main_cb_text(b)
        info = f'Ik={b.Isc_board_kA:.2f} kA'
        if cb_lbl:
            info += f'  |  {cb_lbl}'
        S.append(_txt(bx, y, info, size=8, color='#666',
                      font='Courier New,monospace'))

    def _draw_h_incomer(x_from, x_to, cy, pf, cable_vd, pf_valid, cb=None):
        x_cb = x_from + 28
        x_line0 = x_from
        if cb and cb.In_CB:
            half = CB_SPAN // 2
            x1, x2 = x_cb - half, x_cb + half
            if x1 > x_from + 4:
                S.append(f'<line x1="{x_from}" y1="{cy}" x2="{x1}" y2="{cy}" '
                         f'stroke="#1a3a5c" stroke-width="2"/>')
            cb_svg, x_line0, _ = _sld_cb_h(cb.cb_type, cy, x1, x2)
            S.append(cb_svg)
            ref = getattr(cb, 'circuit_ref', None) or ''
            if ref:
                S.append(_txt(x_cb, cy - 16, ref, size=7, color='#c40080',
                              bold=True))
            S.append(_txt(x_cb, cy + 16, f'{cb.In_CB:.0f}A {cb.cb_type}',
                          size=7, color='#c40080'))
        else:
            x_line0 = x_from
        S.append(f'<line x1="{x_line0}" y1="{cy}" x2="{x_to}" y2="{cy}" '
                 f'stroke="#1a3a5c" stroke-width="2"/>')
        inc_vd = cable_vd if pf_valid else None
        _sld_draw_cable_h(S, cy, x_line0, x_to, pf.phases, pf.cable,
                          pf.cable_length, vd_pct=inc_vd, incomer=True)

    def _draw_h_feeder(bus_x, cy, f, idx, cum_vd):
        end_x = bus_x + FEEDER_LEN
        is_spare = f.load_type == 'Spare'
        is_space = f.load_type == 'Space'
        c_circ = '#1a3a5c'
        rec = f.cable.recommended

        S.append(f'<circle cx="{bus_x}" cy="{cy}" r="4" fill="#000"/>')
        if is_space:
            S.append(_txt(bus_x + 40, cy, 'SPACE', size=8, color='#aaa',
                          anchor='start'))
            return

        x_cb = bus_x + 20
        x0 = bus_x + 6
        if f.cb.In_CB:
            half = CB_SPAN // 2
            x1, x2 = x_cb - half, x_cb + half
            if x1 > bus_x + 4:
                S.append(f'<line x1="{bus_x}" y1="{cy}" x2="{x1}" y2="{cy}" '
                         f'stroke="#555" stroke-width="1.5"/>')
            cb_svg, x0, _ = _sld_cb_h(f.cb.cb_type, cy, x1, x2)
            S.append(cb_svg)
            if f.circuit_ref:
                S.append(_txt(x_cb, cy - 16, f.circuit_ref,
                              size=8, color='#c40080', bold=True))
            cb_In = f.cb.In_CB
            cb_typ = f.cb.cb_type
            if f.load_type == 'SubPanel' and not cb_In and root_board:
                child = (root_board.find_board(f.subpanel_id)
                         if getattr(f, 'subpanel_id', None) else None)
                if child and child.main_cb.In_CB:
                    cb_In = child.main_cb.In_CB
                    cb_typ = child.main_cb.cb_type
            if cb_In:
                S.append(_txt(x_cb, cy + 16, f'{cb_In:.0f}A {cb_typ}',
                              size=8, color='#c40080'))
        else:
            S.append(_txt(bus_x + 10, cy - 10, f.circuit_ref or '',
                          size=8, color='#c40080', anchor='start'))

        x_circ = end_x
        x_line_end = end_x - R_LOAD
        if is_spare:
            S.append(f'<line x1="{x0}" y1="{cy}" x2="{x_line_end}" y2="{cy}" '
                     f'stroke="#888" stroke-width="1.5" stroke-dasharray="4,3"/>')
            S.append(_txt(x_circ, cy, f.name[:20], size=9, color='#888',
                          anchor='middle'))
            return

        S.append(f'<line x1="{x0}" y1="{cy}" x2="{x_line_end}" y2="{cy}" '
                 f'stroke="#555" stroke-width="1.5"/>')
        if rec:
            vd_c = f.result_vdrop_pct or 0.0
            _sld_draw_cable_h(S, cy, x0, x_line_end, f.phases, f.cable,
                              f.cable_length, vd_pct=vd_c, incomer=False)

        if cum_vd > 0:
            _sld_vd_box(S, x_circ, cy - R_LOAD - 6, cum_vd)
        S.append(f'<circle cx="{x_circ}" cy="{cy}" r="{R_LOAD}" fill="#fff" '
                 f'stroke="{c_circ}" stroke-width="2"/>')
        S.append(_txt(x_circ, cy + 5, str(idx), size=11, color=c_circ, bold=True))
        S.append(_txt(x_circ, cy + R_LOAD + 16, f.name[:18], size=8, color='#333'))
        if f.P:
            S.append(_txt(x_circ, cy + R_LOAD + 28,
                          f'{f.P:.1f} kW', size=8, color='#555'))

    def draw(node, parent_bus_x=None):
        b = node['board']
        bx = node['bus_x']
        yt, yb = node['bus_y_top'], node['bus_y_bot']
        pf = node['pf']
        inc_cy = node.get('tap_cy', node['incomer_cy'])

        if node['depth'] == 0:
            sx = SUPPLY_X
            _sld_panel_bus(S, sx, yt - BUS_PAD, yb + BUS_PAD, width=8)
            S.append(_txt(sx, yt - BUS_PAD - 20, 'Supply', size=12,
                          bold=True, color='#003d8f'))
            S.append(_txt(sx, (yt + yb) // 2, '~', size=22, color='#000', bold=True))
            mcb = b.main_cb
            _draw_h_incomer(sx + SUPPLY_W, bx, inc_cy, pf,
                            node['cable_vd'], node['pf_valid'], cb=mcb)
        elif parent_bus_x is not None:
            S.append(f'<circle cx="{parent_bus_x}" cy="{inc_cy}" r="4" fill="#000"/>')
            _draw_h_incomer(parent_bus_x, bx, inc_cy, pf,
                            node['cable_vd'], node['pf_valid'], cb=pf.cb)

        _sld_panel_bus(S, bx, yt, yb)
        _draw_panel_header(bx, yt, b, node['cum_vd'])

        for i, fd in enumerate(node['feeders']):
            _draw_h_feeder(bx, fd['cy'], fd['feeder'], i + 1, fd['cum_vd'])

        for child in node['children']:
            draw(child, parent_bus_x=bx)

    draw(root_node)

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'width="{SVG_W}" height="{SVG_H}" style="background:#fff;">'
           + '\n'.join(S) + '</svg>')

    b0 = root_board
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>SLD — {_e(b0.name)}</title>
<style>
  body{{margin:0;padding:16px;font-family:'Segoe UI',Arial,sans-serif;background:#fff;}}
  h2{{color:#1a3a5c;margin:0 0 4px 0;font-size:20px;}}
  p{{color:#555;font-size:12px;margin:0 0 12px 0;}}
  .w{{overflow:auto;border:1px solid #d0d0d0;border-radius:4px;}}
  @media print{{.w{{border:none;overflow:visible;}}}}
</style></head><body>
<h2>VoltFlow — Single Line Diagram (with voltage drop)</h2>
<p>{_e(b0.name)} &nbsp;|&nbsp; {b0.phases}~{b0.voltage:.0f}V
   &nbsp;|&nbsp; {b0.frequency:.0f}Hz
   &nbsp;|&nbsp; Ik = {b0.Isc_board_kA:.2f} kA
   &nbsp;|&nbsp; Busbar: {b0.busbar_A:.0f}A
   &nbsp;|&nbsp; Total S = {b0.total_S_kVA:.1f} kVA</p>
<div class="w">{svg}</div>
</body></html>"""


def build_hierarchy_html(root_board) -> str:
    """Deprecated — same as build_sld_tree_html (combined SLD + voltage drop)."""
    return build_sld_tree_html(root_board)
