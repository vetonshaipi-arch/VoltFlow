# ui/dxf_export.py
# DXF Single Line Diagram export using ezdxf
# Layers: BUSBAR, CABLES, CB, CB_TEXT, LOADS, ANNOTATIONS, TITLEBLOCK
# CB symbol: ACIEC block (assets/blocks/CB_dxf.dxf) when present, else IEC fallback

import os, sys, math
if not getattr(sys, 'frozen', False):
    _HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in [_HERE, os.path.join(_HERE, 'VSEngCableSelector')]:
        if _p not in sys.path:
            sys.path.insert(0, _p)

try:
    import ezdxf
    from ezdxf import colors, bbox
    from ezdxf.enums import TextEntityAlignment
    from ezdxf.math import Matrix44
except ImportError:
    raise ImportError("ezdxf not installed. Run: pip install ezdxf")

from app_paths import resource_path

CB_SYMBOL_NAME = 'CB_SYMBOL'
CB_SYMBOL_HEIGHT_MM = 60.0
CB_BLOCK_FILENAME = 'CB_dxf.dxf'


# ── DXF color indices (ACI) ───────────────────────────────────────────────────
ACI_BLACK    = 7
ACI_BLUE     = 5
ACI_RED      = 1
ACI_MAGENTA  = 6
ACI_CYAN     = 4
ACI_GREY     = 8


def _ph(ph):
    return {'L123':'L1,L2,L3,N,PE','L1':'L1,N,PE',
            'L2':'L2,N,PE','L3':'L3,N,PE'}.get(ph, ph)


def _cb_dxf_path() -> str | None:
    """Resolve ACIEC CB block DXF (bundled asset, then legacy install path)."""
    candidates = [
        resource_path('assets', 'blocks', CB_BLOCK_FILENAME),
        r'c:\ACIEC\BLOCKS\CB_dxf.dxf',
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _define_cb_block(doc) -> bool:
    """
    Define CB_SYMBOL block. Uses ACIEC CB_dxf.dxf when available.
    Returns True when block includes FRAME/TRIP attribute definitions.
    """
    ext = _cb_dxf_path()
    if ext:
        try:
            return _import_cb_block_from_dxf(doc, ext)
        except Exception:
            pass
    _define_cb_block_fallback(doc)
    return False


def _import_cb_block_from_dxf(doc, filepath: str) -> bool:
    """Import model-space geometry from ACIEC CB DXF into CB_SYMBOL."""
    src = ezdxf.readfile(filepath)
    msp = src.modelspace()
    geom = list(msp.query('LINE ARC CIRCLE LWPOLYLINE POLYLINE SPLINE'))
    attdefs = list(msp.query('ATTDEF'))
    if not geom:
        raise ValueError('CB DXF has no drawable geometry')

    box = bbox.extents(geom)
    cx = (box.extmin.x + box.extmax.x) / 2.0
    top = box.extmax.y
    height = box.size.y
    if height <= 0:
        raise ValueError('CB DXF has zero height')
    scale = CB_SYMBOL_HEIGHT_MM / height
    transform = Matrix44.translate(-cx, -top, 0.0) @ Matrix44.scale(scale)

    blk = doc.blocks.new(name=CB_SYMBOL_NAME)
    for entity in geom:
        copy = entity.copy()
        copy.transform(transform)
        copy.dxf.layer = 'CB'
        blk.add_entity(copy)
    for entity in attdefs:
        copy = entity.copy()
        copy.transform(transform)
        copy.dxf.layer = 'CB_TEXT'
        blk.add_entity(copy)
    return bool(attdefs)


def _define_cb_block_fallback(doc):
    """Programmatic IEC CB when ACIEC block file is unavailable."""
    blk = doc.blocks.new(name=CB_SYMBOL_NAME)
    w, h = 20, 40
    bx   = -w/2

    blk.add_line((0, 0), (0, -10),
                 dxfattribs={'layer': 'CB', 'lineweight': 35})
    blk.add_lwpolyline(
        [(bx, -10), (bx+w, -10), (bx+w, -10-h), (bx, -10-h), (bx, -10)],
        dxfattribs={'layer': 'CB', 'lineweight': 35, 'closed': True})
    blk.add_line((bx+3, -10-h+4), (bx+w-3, -10+4-4),
                 dxfattribs={'layer': 'CB', 'lineweight': 35})
    blk.add_line((0, -10-h), (0, -CB_SYMBOL_HEIGHT_MM),
                 dxfattribs={'layer': 'CB', 'lineweight': 35})


def export_sld_dxf(board, root_board, filepath: str) -> None:
    """
    Export Single Line Diagram as DXF.

    Units: mm (1 unit = 1mm)
    Scale: 1:1 (layout in mm, intended for A1/A0 plot at 1:50 or 1:100)
    """
    doc  = ezdxf.new(dxfversion='R2010')
    doc.units = 4   # mm
    msp  = doc.modelspace()

    # ── Layers ───────────────────────────────────────────────────────────────
    layer_defs = [
        ('BUSBAR',      ACI_BLACK,   100),   # lw in 1/100 mm → 1.0mm
        ('CABLES',      ACI_BLACK,    50),   # 0.50mm
        ('CB',          ACI_BLACK,    35),   # 0.35mm
        ('CB_TEXT',     ACI_MAGENTA,  18),   # 0.18mm
        ('PHASE_TEXT',  ACI_BLACK,    18),
        ('CABLE_TEXT',  ACI_BLUE,     18),
        ('LOAD_CIRCLE', ACI_BLACK,    35),
        ('LOAD_TEXT',   ACI_BLACK,    18),
        ('ANNOTATIONS', ACI_GREY,     18),
        ('TITLEBLOCK',  ACI_BLACK,    50),
    ]
    for name, color, lw in layer_defs:
        layer = doc.layers.new(name)
        layer.color = color
        layer.lineweight = lw

    # ── CB block ─────────────────────────────────────────────────────────────
    cb_has_attribs = _define_cb_block(doc)

    feeders = board.feeders
    n       = len(feeders)
    if n == 0:
        doc.saveas(filepath)
        return

    # ── Layout constants (mm) ─────────────────────────────────────────────────
    COL       = 60       # column spacing
    ML        = 80       # left margin
    BUS_Y     = 0        # busbar y (DXF Y increases upward)
    INCOMER_H = 40       # supply symbol height above incomer CB top
    INCOMER_CB_TOP = BUS_Y + CB_SYMBOL_HEIGHT_MM
    CB_TOP    = BUS_Y - 10   # CB symbol top (bus → down)
    PHASE_Y   = CB_TOP - 75
    CABLE_Y   = CB_TOP - 160
    CIRCLE_Y  = CB_TOP - 290
    LABEL_Y   = CIRCLE_Y - 35

    TH_SMALL  = 2.5      # text height small
    TH_MED    = 3.0      # text height medium
    TH_LARGE  = 4.0      # text height large
    R         = 12       # circle radius

    # ── Title / system info ───────────────────────────────────────────────────
    sys_txt = (f'{board.phases}~{board.voltage:.0f}V  '
               f'{board.frequency:.0f}Hz  '
               f'Ik={board.Isc_board_kA:.2f}kA')
    msp.add_text(sys_txt,
                 dxfattribs={'layer':'ANNOTATIONS','height':TH_MED,
                             'insert':(ML-40, INCOMER_CB_TOP+INCOMER_H+20)})
    msp.add_text('From supply',
                 dxfattribs={'layer':'ANNOTATIONS','height':TH_SMALL,
                             'insert':(ML-40, INCOMER_CB_TOP+INCOMER_H+14)})

    # ── Incomer ───────────────────────────────────────────────────────────────
    ix = ML - 20
    # ~ symbol
    msp.add_text('~',
                 dxfattribs={'layer':'ANNOTATIONS','height':TH_LARGE,
                             'insert':(ix-2, INCOMER_CB_TOP+INCOMER_H+4),
                             'style':'Standard'})
    # Supply line down to incomer CB top
    msp.add_line((ix, INCOMER_CB_TOP+INCOMER_H), (ix, INCOMER_CB_TOP),
                 dxfattribs={'layer':'CABLES','lineweight':50})

    inc_cb = board.main_cb if board.main_cb.In_CB else None
    if board.primary_feeder_selected and board.primary_feeder.cb.In_CB:
        inc_cb = board.primary_feeder.cb
    if inc_cb and inc_cb.In_CB:
        inc_ins = msp.add_blockref(CB_SYMBOL_NAME, (ix, INCOMER_CB_TOP),
                                   dxfattribs={'layer': 'CB'})
        if cb_has_attribs:
            inc_ins.add_auto_attribs({
                'FRAME': 'INC',
                'TRIP': f'{inc_cb.In_CB:.0f}A {inc_cb.cb_type}',
            })
        else:
            msp.add_text('INC',
                         dxfattribs={'layer': 'CB_TEXT', 'height': TH_MED,
                                     'insert': (ix + 12, INCOMER_CB_TOP - 14)})
            msp.add_text(f'{inc_cb.In_CB:.0f}A {inc_cb.cb_type}',
                         dxfattribs={'layer': 'CB_TEXT', 'height': TH_SMALL,
                                     'insert': (ix + 12, INCOMER_CB_TOP - 22)})
    else:
        msp.add_line((ix, INCOMER_CB_TOP), (ix, BUS_Y),
                     dxfattribs={'layer':'CABLES','lineweight':50})

    # Dot on busbar
    msp.add_circle((ix, BUS_Y), 2.0,
                   dxfattribs={'layer':'BUSBAR'})
    msp.add_solid([(ix-2,BUS_Y-2),(ix+2,BUS_Y-2),(ix-2,BUS_Y+2),(ix+2,BUS_Y+2)],
                  dxfattribs={'layer':'BUSBAR'})

    # ── Main busbar ───────────────────────────────────────────────────────────
    bx1 = ML - 30
    bx2 = ML + n * COL + 20
    msp.add_line((bx1, BUS_Y), (bx2, BUS_Y),
                 dxfattribs={'layer':'BUSBAR','lineweight':100})

    # ── Per-feeder ────────────────────────────────────────────────────────────
    for i, f in enumerate(feeders):
        cx     = ML + i * COL
        rec    = f.cable.recommended
        is_sp  = f.load_type == 'SubPanel'

        # Tap dot on busbar
        msp.add_circle((cx, BUS_Y), 2.5,
                       dxfattribs={'layer':'BUSBAR'})

        # ── CB block reference ────────────────────────────────────────────────
        insert = msp.add_blockref(CB_SYMBOL_NAME, (cx, CB_TOP),
                                  dxfattribs={'layer': 'CB'})

        cb_In  = f.cb.In_CB
        cb_typ = f.cb.cb_type
        if is_sp and not cb_In and root_board:
            child = root_board.find_board(f.subpanel_id) if (
                hasattr(f, 'subpanel_id') and f.subpanel_id) else None
            if child and child.main_cb.In_CB:
                cb_In = child.main_cb.In_CB
                cb_typ = child.main_cb.cb_type

        if cb_has_attribs:
            trip = f'{cb_In:.0f}A {cb_typ}' if cb_In else ''
            insert.add_auto_attribs({
                'FRAME': f.circuit_ref or f.name,
                'TRIP': trip,
            })
        else:
            lx = cx + 12
            cb_top_abs = CB_TOP
            msp.add_text(f.circuit_ref,
                         dxfattribs={'layer': 'CB_TEXT', 'height': TH_MED,
                                     'insert': (lx, cb_top_abs - 14)})
            if cb_In:
                msp.add_text(f'{cb_In:.0f}A {cb_typ}',
                             dxfattribs={'layer': 'CB_TEXT', 'height': TH_SMALL,
                                         'insert': (lx, cb_top_abs - 22)})

        # ── Phase label (vertical, left of cable line) ────────────────────────
        ph_txt = _ph(f.phase_str)
        ph_y   = (CB_TOP + CABLE_Y) // 2
        msp.add_text(ph_txt,
                     dxfattribs={'layer':'PHASE_TEXT','height':TH_SMALL,
                                 'insert':(cx - 8, ph_y),
                                 'rotation': 90})

        # ── Vertical cable drop line ──────────────────────────────────────────
        # From CB bottom to top of circle
        cb_bot_y = CB_TOP - CB_SYMBOL_HEIGHT_MM
        circle_top = CIRCLE_Y + R
        msp.add_line((cx, cb_bot_y), (cx, circle_top),
                     dxfattribs={'layer':'CABLES','lineweight':35})

        # ── Cable text (rotated, alongside line) ─────────────────────────────
        if rec:
            cable_mid = (cb_bot_y + circle_top) / 2
            # Code — left of line (negative x offset, rotated 90°)
            msp.add_text(rec.cable_code[:24],
                         dxfattribs={'layer':'CABLE_TEXT','height':TH_SMALL,
                                     'insert':(cx - 6, cable_mid),
                                     'rotation': 90})
            # Length — right of line
            msp.add_text(f'L={f.cable_length:.1f}m',
                         dxfattribs={'layer':'CABLE_TEXT','height':TH_SMALL,
                                     'insert':(cx + 6, cable_mid),
                                     'rotation': 90})

        # ── Load circle ───────────────────────────────────────────────────────
        circ_color = 6 if is_sp else 5  # magenta for subpanel, blue for feeder
        msp.add_circle((cx, CIRCLE_Y), R,
                       dxfattribs={'layer':'LOAD_CIRCLE',
                                   'color': circ_color,
                                   'lineweight': 50})
        msp.add_text(str(i+1),
                     dxfattribs={'layer':'LOAD_CIRCLE','height':TH_MED,
                                 'insert':(cx - TH_MED*0.3, CIRCLE_Y - TH_MED*0.4),
                                 'color': circ_color})

        # ── Load labels (rotated below circle) ───────────────────────────────
        msp.add_text(f.name[:22],
                     dxfattribs={'layer':'LOAD_TEXT','height':TH_SMALL,
                                 'insert':(cx - 2, LABEL_Y),
                                 'rotation': 270})   # -90° = 270°
        if f.P:
            msp.add_text(f'P = {f.P:.2f} kW',
                         dxfattribs={'layer':'LOAD_TEXT','height':TH_SMALL,
                                     'insert':(cx + 6, LABEL_Y),
                                     'rotation': 270})

    # ── Title block ───────────────────────────────────────────────────────────
    tb_x = ML - 50
    tb_y = LABEL_Y - 60
    tb_w = n * COL + 80
    tb_h = 40

    # Border rectangle
    msp.add_lwpolyline(
        [(tb_x, tb_y), (tb_x+tb_w, tb_y),
         (tb_x+tb_w, tb_y-tb_h), (tb_x, tb_y-tb_h), (tb_x, tb_y)],
        dxfattribs={'layer':'TITLEBLOCK','lineweight':50,'closed':True})

    # Dividing lines
    col1 = tb_x + tb_w * 0.35
    col2 = tb_x + tb_w * 0.65
    for xd in [col1, col2]:
        msp.add_line((xd, tb_y), (xd, tb_y-tb_h),
                     dxfattribs={'layer':'TITLEBLOCK'})
    mid_h = tb_y - tb_h/2
    msp.add_line((tb_x, mid_h), (tb_x+tb_w, mid_h),
                 dxfattribs={'layer':'TITLEBLOCK'})

    # Title block text
    tb_texts = [
        (tb_x+4,     tb_y-6,    TH_SMALL, 'Project:'),
        (tb_x+4,     tb_y-14,   TH_MED,   board.project or board.name),
        (col1+4,     tb_y-6,    TH_SMALL, 'Drawing:'),
        (col1+4,     tb_y-14,   TH_MED,   board.drawing_ref or 'SLD'),
        (col2+4,     tb_y-6,    TH_SMALL, 'Engineer:'),
        (col2+4,     tb_y-14,   TH_MED,   board.engineer or ''),
        (tb_x+4,     mid_h-6,   TH_SMALL, 'Board:'),
        (tb_x+4,     mid_h-14,  TH_MED,   board.name),
        (col1+4,     mid_h-6,   TH_SMALL, 'System:'),
        (col1+4,     mid_h-14,  TH_MED,
         f'{board.phases}~{board.voltage:.0f}V  {board.frequency:.0f}Hz'),
        (col2+4,     mid_h-6,   TH_SMALL, 'Ik (kA):'),
        (col2+4,     mid_h-14,  TH_MED,   f'{board.Isc_board_kA:.2f}'),
        (tb_x+tb_w-52, tb_y-tb_h+4, TH_SMALL, 'VoltFlow'),
    ]
    for x, y, h, txt in tb_texts:
        msp.add_text(str(txt),
                     dxfattribs={'layer':'TITLEBLOCK','height':h,
                                 'insert':(x, y)})

    # ── Save ─────────────────────────────────────────────────────────────────
    doc.saveas(filepath)
