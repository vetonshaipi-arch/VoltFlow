# ui/switchboard_window.py  — Professional 3-pane switchboard designer
import sys, os, math, copy, time
if not getattr(sys, 'frozen', False):
    _HERE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _CABLE = os.path.join(_HERE, 'VSEngCableSelector')
    if _HERE in sys.path:
        sys.path.remove(_HERE)
    sys.path.insert(0, _HERE)
    if _CABLE not in sys.path:
        sys.path.insert(1, _CABLE)

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QMessageBox, QFileDialog, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QInputDialog,
    QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QMenu, QApplication,
    QStyledItemDelegate, QSizePolicy, QAbstractItemDelegate,
)
from PySide6.QtCore import Qt, QTimer, QThread, QEvent, Signal as _Signal, Signal, QPoint, QUrl
from PySide6.QtGui import QColor, QBrush, QFont, QKeySequence, QDesktopServices
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtGui import QTextDocument

from switchboard_class import (C_Switchboard, C_Transformer,
                                FRAME_TYPES, IP_RATINGS, MOUNTING, BUSBAR_STD_A,
                                PANEL_SIZES)
from feeder_class import C_Feeder
from project_class import PROJECT_STANDARD, KSA_FREQUENCY_HZ
from version import APP_VERSION
from vdrop_settings import (
    VdropProjectSettings, apply_vdrop_limit_to_feeder,
    apply_feeder_cable_from_selector,
    feeder_vdrop_user_locked, DEFAULT_VDROP_BY_TYPE,
)
from .status_messages import (
    collect_messages, format_status_line, status_tooltip, status_stylesheet,
)
from VSEngCableSelector.cable_class import C_Cable
from cb_class import (C_CB, CB_TYPES, DIVERSITY_STEPS, CB_FAMILIES,
                       IEC_MCB_SIZES, IEC_MCCB_SIZES, IEC_ACB_SIZES,
                       MOTOR_LOAD_TYPES)

LOAD_TYPES = ['Motor','Light','Socket','HVAC','SubPanel','Other']
# Load types editable from the grid Type column (dropdown)
GRID_LOAD_TYPES = ['Motor', 'Light', 'Socket', 'HVAC', 'Other']
PHASES     = ['L123','L1','L2','L3','L12','L13','L23']
LOAD_COLORS = {
    'Motor':'#c00000','Light':'#0070c0','Socket':'#0070c0',
    'HVAC':'#7030a0','SubPanel':'#e67e00','Other':'#404040',
}
LOAD_ICONS = {'Motor':'M','Light':'L','Socket':'S','HVAC':'H','SubPanel':'⚡','Other':'O'}

_GRID_CTX_MENU_STYLE = """
QMenu#feederGridMenu {
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #b0b0b0;
    padding: 4px 0;
}
QMenu#feederGridMenu::item {
    padding: 6px 32px 6px 24px;
    background-color: #ffffff;
    color: #1a1a1a;
}
QMenu#feederGridMenu::item:selected {
    background-color: #cce4ff;
    color: #003d8f;
}
QMenu#feederGridMenu::item:disabled {
    color: #999999;
    background-color: #f5f5f5;
}
QMenu#feederGridMenu::separator {
    height: 1px;
    background: #d0d0d0;
    margin: 4px 10px;
}
"""

COLS = [
    ('No',       36,False),('Load Name',160,True), ('Type', 58,False),
    ('Ph',       42,True), ('P kW',     62,True),  ('S kVA',62,False),
    ('cosφ',     50,True), ('DF %',     44,True),  ('L m',  52,True),
    ('ΔU%',      50,True), ('Ib A',     54,False), ('CB',   84,False),
    ('mm²',      46,False),('Conductor',290,True), ('Vd%',  50,False),
    ('✔',        32,False),
]
COL_DF = 7
COL_VDROP = 9

# Fonts created after QApplication exists (see SwitchboardWindow.__init__)
MONO  = None
SANS  = None
SANSB = None
SANS9 = None

def _init_fonts():
    global MONO, SANS, SANSB, SANS9
    if MONO is None:
        from .qt_helpers import app_font
        MONO  = app_font('Courier New', 10)
        SANS  = app_font('Segoe UI', 11)
        SANSB = app_font('Segoe UI', 11, bold=True)
        SANS9 = app_font('Segoe UI', 9)

from app_paths import resource_path as _resource_path
LIGHT_QSS = _resource_path('theme', 'light.qss')

def _load_qss():
    if os.path.exists(LIGHT_QSS):
        with open(LIGHT_QSS) as f: return f.read()
    return ''


class FeederGridTable(QTableWidget):
    """Feeder grid — right-click always opens row Cut/Copy/Paste menu."""

    menu_requested = Signal(QPoint)  # position in viewport coordinates

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.viewport().installEventFilter(self)

    def contextMenuEvent(self, event):
        vp_pos = self.viewport().mapFrom(self, event.pos())
        self.menu_requested.emit(vp_pos)
        event.accept()

    def eventFilter(self, obj, event):
        if obj is self.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    self.menu_requested.emit(event.pos())
                    return True
            elif event.type() == QEvent.Type.ContextMenu:
                self.menu_requested.emit(event.pos())
                return True
        return super().eventFilter(obj, event)


class LoadTypeDelegate(QStyledItemDelegate):
    """Dropdown in grid column Type for Motor / Light / Other / …"""

    def __init__(self, on_changed, parent=None):
        super().__init__(parent)
        self._on_changed = on_changed

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(GRID_LOAD_TYPES)
        return cb

    def setEditorData(self, editor, index):
        text = (index.data(Qt.DisplayRole) or '').strip()
        i = editor.findText(text)
        editor.setCurrentIndex(i if i >= 0 else 0)

    def setModelData(self, editor, model, index):
        new_type = editor.currentText()
        row = index.row()
        model.setData(index, new_type, Qt.EditRole)
        # Defer side effects until after Qt closes the combo editor.
        QTimer.singleShot(0, lambda r=row, t=new_type: self._on_changed(r, t))

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class _XlsThread(QThread):
    """Background worker that calls build_workbook so the GUI stays live."""
    done   = _Signal(list)   # emitted with warnings list on success
    failed = _Signal(str)    # emitted with formatted traceback on error

    def __init__(self, boards, voltage, path):
        super().__init__()
        self._boards  = boards
        self._voltage = voltage
        self._path    = path

    def run(self):
        pythoncom = None
        if sys.platform == 'win32':
            import pythoncom as win32_pythoncom
            pythoncom = win32_pythoncom
            pythoncom.CoInitialize()
        try:
            from .fill_schedule import build_workbook
            _, warnings = build_workbook(self._boards, self._voltage, self._path)
            self.done.emit(warnings or [])
        except Exception as e:
            import traceback
            self.failed.emit(
                f'{type(e).__name__}: {e}\n\n'
                + traceback.format_exc()[-1200:])
        finally:
            if pythoncom is not None:
                pythoncom.CoUninitialize()


class SwitchboardWindow(QWidget):
    """Main network designer — tree, feeder grid, properties, status bar."""

    app_status = Signal(str, str, bool, bool)  # text, tooltip, has_errors, has_warnings

    def __init__(self, switchboard=None, min_conductor_mm2: float = 1.5,
                 min_cb_A: float = 6.0, df_mode: str = 'per_load',
                 project_df_pct: float = 100.0,
                 vd_settings: VdropProjectSettings = None,
                 parent=None):
        super().__init__(parent)
        _init_fonts()  # ensure fonts exist after QApplication
        import uuid
        self._root = switchboard or C_Switchboard()
        if not self._root.board_id:
            self._root.board_id = uuid.uuid4().hex[:8]
        self._board           = self._root
        self._file            = None
        self._min_conductor_mm2 = min_conductor_mm2
        self._min_cb_A          = min_cb_A
        self._df_mode           = df_mode
        self._project_df_pct    = project_df_pct
        self._vd_settings       = vd_settings or VdropProjectSettings()
        self._busy            = False
        self._sel_win         = None
        self._props_mode      = 'primary'  # 'primary' | 'feeder' | 'motor'
        self._feeder_clipboard: list = []   # list[C_Feeder] — copy/cut buffer
        self._tree_drag_bid: str = ''       # board_id being dragged in tree
        self._timer   = QTimer(singleShot=True, interval=350)
        self._timer.timeout.connect(self._calc_row)
        # Full recalc timer — fires after load/phase changes that affect
        # total_Ib, actual_voltage_V, or primary feeder sizing.
        self._full_timer = QTimer(singleShot=True, interval=400)
        self._full_timer.timeout.connect(self._calc_full)
        self.setWindowTitle('VoltFlow')
        self.setMinimumSize(1300, 780)
        self._build()
        self._reload_tree()
        self._load_board(self._root)
        self._update_vd_ui()

    # ── BUILD ─────────────────────────────────────────────────────────────────
    def _build(self):
        vl = QVBoxLayout(self); vl.setContentsMargins(0,0,0,0); vl.setSpacing(0)
        # _hdr / _hdr_r were in the old standalone header bar.
        # They are hidden stubs here — _update_header still writes to them
        # so the ribbon can read their text if needed, but they are not shown.
        self._hdr   = QLabel(); self._hdr.hide()
        self._hdr_r = QLabel(); self._hdr_r.hide()
        # Header and toolbar live in the ribbon — not repeated here
        # Top: horizontal splitter — tree (left) | grid+totals (right)
        hs = QSplitter(Qt.Horizontal); hs.setHandleWidth(3)
        hs.addWidget(self._mk_tree())
        hs.addWidget(self._mk_grid())
        hs.setSizes([230, 1070])

        # Outer vertical splitter — top (tree+grid) | bottom (props full width)
        vs = QSplitter(Qt.Vertical); vs.setHandleWidth(4)
        vs.addWidget(hs)
        self._props_wrap = self._mk_props()
        vs.addWidget(self._props_wrap)
        vs.setSizes([520, 158])
        self._props_splitter = vs
        vl.addWidget(vs, 1)
        vl.addWidget(self._mk_statusbar())

    # ── HEADER ────────────────────────────────────────────────────────────────
    def _mk_header(self):
        w = QWidget(); w.setFixedHeight(42)
        w.setStyleSheet('background:qlineargradient(x1:0,y1:0,x2:0,y2:1,'
                        'stop:0 #1a3a5c,stop:1 #0d2137);border-bottom:2px solid #f0a500;')
        hl = QHBoxLayout(w); hl.setContentsMargins(10,0,10,0)
        logo = QLabel('VoltFlow')
        logo.setStyleSheet('background:#f0a500;color:#000;font-size:14px;'
                           'font-weight:bold;padding:3px 12px;letter-spacing:2px;')
        self._hdr = QLabel('Switchboard Designer')
        self._hdr.setStyleSheet('color:#fff;font-size:13px;font-weight:bold;padding-left:14px;')
        self._hdr_r = QLabel()
        self._hdr_r.setStyleSheet('color:#8ab4d4;font-size:11px;')
        hl.addWidget(logo); hl.addWidget(self._hdr, 1); hl.addWidget(self._hdr_r)
        return w

    # ── TOOLBAR ───────────────────────────────────────────────────────────────
    def _mk_toolbar(self):
        w = QWidget()
        w.setStyleSheet('background:#f0f0f0;border-bottom:1px solid #d0d0d0;')
        hl = QHBoxLayout(w); hl.setContentsMargins(6,3,6,3); hl.setSpacing(3)

        def b(txt, slot, style='', tip=''):
            btn = QPushButton(txt)
            btn.setFixedHeight(26); btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip); btn.clicked.connect(slot)
            if style: btn.setStyleSheet(style)
            hl.addWidget(btn); return btn

        GRN = ('QPushButton{background:#107c10;color:#fff;border:none;'
               'font-weight:bold;padding:3px 10px;}'
               'QPushButton:hover{background:#0a5e0a;}')
        ORG = ('QPushButton{background:#e67e00;color:#fff;border:none;'
               'font-weight:bold;padding:3px 10px;}'
               'QPushButton:hover{background:#c06800;}')
        RED = ('QPushButton{background:#c42b1c;color:#fff;border:none;'
               'padding:3px 10px;}'
               'QPushButton:hover{background:#a02015;}')
        PRP = ('QPushButton{background:#5c2d91;color:#fff;border:none;'
               'font-weight:bold;padding:3px 10px;}'
               'QPushButton:hover{background:#4a2474;}')
        STD = ('QPushButton{background:#e8e8e8;border:1px solid #b0b0b0;'
               'padding:3px 10px;}'
               'QPushButton:hover{background:#d0e4f8;border-color:#0078d4;color:#0078d4;}')

        b('➕  Feeder',     self._add_feeder,    GRN, 'Add feeder row')
        b('⚡  Sub-Panel',  self._add_subpanel,  ORG, 'Add child distribution board')
        b('✕  Remove',      self._del_row,        RED, 'Remove selected row')
        self._vsep(hl)
        b('⚙  Board',       self._board_settings, STD, 'Board settings')
        b('⚡  Calc All',      self._calc_all,      PRP, 'Calculate all feeders')
        b('⚖  Balance',       self._balance_phases,
          'QPushButton{background:#1a6b8a;color:#fff;border:none;'
          'font-weight:bold;padding:3px 10px;}'
          'QPushButton:hover{background:#145570;}',
          'LDM Phase Balancing — reorder and assign phases for minimum imbalance')
        b('⚡  Calc Selected', self._calc_selected,
          'QPushButton{background:#2d6e2d;color:#fff;border:none;'
          'font-weight:bold;padding:3px 10px;}'
          'QPushButton:hover{background:#1a4f1a;}',
          'Calculate selected rows only')
        b('🔲 Spare/Space', self._gen_spare_space,
          'QPushButton{background:#607d8b;color:#fff;border:none;'
          'font-weight:bold;padding:3px 10px;}'
          'QPushButton:hover{background:#455a64;}',
          'Generate Spare (20%) and Space (10%) for ALL boards')
        hl.addStretch()
        b('💾', self._save,    STD, 'Save')
        b('📂', self._load,    STD, 'Load')
        b('Save As', self._save_as, STD)
        b('🖨 Schedule',  self._print,          STD, 'Print feeder schedule (PDF/printer)')
        b('📊 XLS',       self._export_xls,     STD, 'Export panel schedule as Excel workbook')
        b('🖨 SLD',       self._print_sld,       STD,
          'Print single line diagram (with voltage drop)')
        b('⬇ DXF',       self._export_dxf,      STD, 'Export SLD as DXF (AutoCAD)')
        return w

    def _vsep(self, hl):
        f = QFrame(); f.setFrameShape(QFrame.VLine)
        f.setStyleSheet('color:#c0c0c0;'); f.setFixedWidth(1)
        hl.addSpacing(3); hl.addWidget(f); hl.addSpacing(3)

    # ── TREE ──────────────────────────────────────────────────────────────────
    def _mk_tree(self):
        w = QWidget(); w.setFixedWidth(228)
        vl = QVBoxLayout(w); vl.setContentsMargins(0,0,0,0); vl.setSpacing(0)
        hdr = QLabel('  Electrical Distribution')
        hdr.setFixedHeight(28)
        hdr.setStyleSheet('background:#1a3a5c;color:#fff;font-weight:bold;'
                          'font-size:11px;border-bottom:1px solid #f0a500;')
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True); self._tree.setIndentation(14)
        self._tree.setAnimated(True)
        self._tree.setStyleSheet(
            'QTreeWidget{background:#fff;border:none;border-right:1px solid #d8d8d8;}'
            'QTreeWidget::item{height:26px;padding:0 2px;}'
            'QTreeWidget::item:selected{background:#cce4ff;color:#003d8f;}'
            'QTreeWidget::item:hover:!selected{background:#e8f4ff;}')
        self._tree.currentItemChanged.connect(self._on_tree_sel)
        # itemClicked fires even when the item is already current (currentItemChanged wouldn't)
        self._tree.itemClicked.connect(lambda item, _col: self._on_tree_sel(item, None))
        # Drag-drop for board re-parenting — let QTreeWidget handle the visual
        # move itself, then sync the data model via rowsMoved signal.
        self._tree.setDragEnabled(True)
        self._tree.setAcceptDrops(True)
        self._tree.setDropIndicatorShown(True)
        self._tree.setDragDropMode(QAbstractItemView.InternalMove)
        self._tree.model().rowsMoved.connect(self._on_tree_rows_moved)
        vl.addWidget(hdr); vl.addWidget(self._tree, 1)
        return w

    def _reload_tree(self):
        self._tree.blockSignals(True); self._tree.clear()
        ri = self._tree_item(self._root)
        self._tree.addTopLevelItem(ri)
        self._add_children(ri, self._root)
        self._tree.expandAll()
        self._tree.blockSignals(False)

    def _tree_item(self, board):
        ico = '🔌' if board.level == 0 else '⚡'
        item = QTreeWidgetItem([f'{ico}  {board.name}'])
        item.setData(0, Qt.UserRole, board.board_id)
        from .qt_helpers import app_font
        f = app_font('Segoe UI', 11, bold=(board.level <= 1))
        item.setFont(0, f)
        cols = ['#1a3a5c','#003d8f','#e67e00','#e67e00','#e67e00',
                '#888','#888','#888','#888','#888','#888']
        item.setForeground(0, QBrush(QColor(cols[min(board.level, 10)])))
        return item

    def _add_children(self, pi, board):
        for ch in board.child_boards:
            ci = self._tree_item(ch)
            pi.addChild(ci); self._add_children(ci, ch)

    def _find_ti(self, bid, parent=None):
        if parent is None: parent = self._tree.invisibleRootItem()
        for i in range(parent.childCount()):
            item = parent.child(i)
            if item.data(0, Qt.UserRole) == bid: return item
            found = self._find_ti(bid, item)
            if found: return found
        return None

    def _on_tree_sel(self, cur, _):
        if cur is None: return
        board = self._root.find_board(cur.data(0, Qt.UserRole))
        if not board: return
        self._load_board(board)
        # Always show board-level (incomer) properties on any tree click —
        # even when the same board is re-clicked while a feeder row is selected.
        self._tbl.blockSignals(True)
        self._tbl.clearSelection()
        self._tbl.selectionModel().clearCurrentIndex()
        self._tbl.blockSignals(False)
        self._sync_primary_props()

    # ── GRID ──────────────────────────────────────────────────────────────────
    def _mk_grid(self):
        w = QWidget()
        vl = QVBoxLayout(w); vl.setContentsMargins(0,0,0,0); vl.setSpacing(0)

        # ── Board info bar — AAA-style cells above the table ─────────────────
        _bb = QWidget(); _bb.setFixedHeight(68)
        _bb.setStyleSheet('background:#e8f0f8;border-bottom:2px solid #b8cce4;')
        _bbl = QHBoxLayout(_bb)
        _bbl.setContentsMargins(6, 2, 6, 2); _bbl.setSpacing(6)

        def _bbc(parent, lbl_txt, val_color='#003d8f', min_w=60):
            """One label-over-value cell, same structure as AAA totals bar."""
            vl2 = QVBoxLayout(); vl2.setSpacing(1); vl2.setContentsMargins(0, 0, 0, 0)
            k = QLabel(lbl_txt); k.setStyleSheet('font-size:8pt;color:#888;')
            v = QLabel('—'); v.setMinimumWidth(min_w)
            v.setStyleSheet(
                f'font-size:9pt;font-weight:bold;color:{val_color};'
                f'font-family:Courier New;')
            vl2.addWidget(k); vl2.addWidget(v)
            parent.addLayout(vl2)
            return v

        def _bbs(parent, text, color):
            """Section header at top, stretch below — same as AAA."""
            vl2 = QVBoxLayout(); vl2.setSpacing(1); vl2.setContentsMargins(0, 0, 4, 0)
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f'font-size:8pt;font-weight:bold;color:{color};'
                f'letter-spacing:1px;padding-right:4px;')
            vl2.addWidget(lbl); vl2.addStretch()
            parent.addLayout(vl2)

        # ── Group 1: BOARD (blue) ────────────────────────────────────────────
        _g1 = QFrame()
        _g1.setStyleSheet(
            'QFrame{background:#eef4fb;border:1px solid #c8daea;border-radius:3px;}')
        _gl1 = QHBoxLayout(_g1)
        _gl1.setContentsMargins(8, 2, 8, 2); _gl1.setSpacing(10)
        _bbs(_gl1, 'BOARD', '#003d8f')
        self._bb_name  = _bbc(_gl1, 'Name',   min_w=90)
        self._bb_lvl   = _bbc(_gl1, 'Level',  min_w=36)
        self._bb_sys   = _bbc(_gl1, 'System', min_w=72)
        _bbl.addWidget(_g1)

        # ── Group 2: BUSBAR (green) ──────────────────────────────────────────
        _g2 = QFrame()
        _g2.setStyleSheet(
            'QFrame{background:#edf8ed;border:1px solid #b8ddb8;border-radius:3px;}')
        _gl2 = QHBoxLayout(_g2)
        _gl2.setContentsMargins(8, 2, 8, 2); _gl2.setSpacing(10)
        _bbs(_gl2, 'BUSBAR', '#107c10')
        self._bb_bus  = _bbc(_gl2, 'Rating A',  '#107c10', min_w=58)
        self._bb_load = _bbc(_gl2, 'Loading %', '#107c10', min_w=52)
        _bbl.addWidget(_g2)

        # ── Group 3: FAULT / ENCLOSURE (purple) ─────────────────────────────
        _g3 = QFrame()
        _g3.setStyleSheet(
            'QFrame{background:#f4f0ff;border:1px solid #d0c8e8;border-radius:3px;}')
        _gl3 = QHBoxLayout(_g3)
        _gl3.setContentsMargins(8, 2, 8, 2); _gl3.setSpacing(10)
        _bbs(_gl3, 'FAULT / ENCLOSURE', '#5c2d91')
        self._bb_isc   = _bbc(_gl3, 'Isc kA',  '#5c2d91', min_w=52)
        self._bb_frame = _bbc(_gl3, 'Frame',   '#5c2d91', min_w=70)
        self._bb_ip    = _bbc(_gl3, 'IP',      '#5c2d91', min_w=40)
        _bbl.addWidget(_g3, 1)

        self._board_bar = _bb   # keep ref for show/hide if needed
        vl.addWidget(_bb)

        self._tbl = FeederGridTable()
        self._tbl.setColumnCount(len(COLS))
        self._tbl.setHorizontalHeaderLabels([c[0] for c in COLS])
        self._tbl.setAlternatingRowColors(False)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tbl.setDragDropMode(QAbstractItemView.InternalMove)
        self._tbl.setDragEnabled(True)
        self._tbl.setAcceptDrops(True)
        self._tbl.setDropIndicatorShown(True)
        self._tbl.model().rowsMoved.connect(self._on_rows_moved)
        # Allow editItem / F2 / typing; non-editable cells use ItemIsEditable flag.
        self._tbl.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.verticalHeader().setDefaultSectionSize(24)
        self._tbl.setShowGrid(True)
        self._tbl.setStyleSheet(
            'QTableWidget{background:#fff;gridline-color:#e8e8e8;border:none;}'
            'QTableWidget::item{padding:1px 4px;}'
            'QTableWidget::item:selected{background:#cce4ff;color:#003d8f;}'
            'QHeaderView::section{background:#f0f2f4;color:#444;border:none;'
            'border-bottom:2px solid #c8d8e8;border-right:1px solid #dde;'
            'padding:3px 5px;font-weight:bold;font-size:10px;}')

        hdr = self._tbl.horizontalHeader()
        for i, (_, w2, _) in enumerate(COLS):
            hdr.resizeSection(i, w2)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setStretchLastSection(False)

        self._tbl.itemSelectionChanged.connect(self._on_row_sel)
        self._tbl.cellChanged.connect(self._on_cell)
        self._tbl.cellDoubleClicked.connect(self._on_dbl)
        self._tbl.cellClicked.connect(self._on_cell_click)
        self._tbl.keyPressEvent = self._grid_key_press
        self._grid_viewport = self._tbl.viewport()
        self._tbl.menu_requested.connect(self._on_grid_ctx_menu)
        self._load_type_delegate = LoadTypeDelegate(
            self._apply_load_type_from_grid, self._tbl)
        self._tbl.setItemDelegateForColumn(2, self._load_type_delegate)
        self._df_banner = QLabel('')
        self._df_banner.setWordWrap(True)
        self._df_banner.setStyleSheet(
            'color:#5c2d91;font-size:9pt;font-weight:bold;padding:2px 8px;')
        self._df_banner.hide()
        vl.addWidget(self._df_banner)
        self._vd_banner = QLabel('')
        self._vd_banner.setWordWrap(True)
        self._vd_banner.setStyleSheet(
            'color:#5c2d91;font-size:8pt;font-style:italic;padding:2px 6px;')
        self._vd_banner.hide()
        vl.addWidget(self._vd_banner)
        vl.addWidget(self._tbl, 1)
        vl.addWidget(self._mk_totals())
        return w

    def _mk_totals(self):
        w = QWidget(); w.setFixedHeight(68)
        w.setStyleSheet('background:#e8f0f8;border-top:2px solid #b8cce4;')
        hl = QHBoxLayout(w); hl.setContentsMargins(6,2,6,2); hl.setSpacing(0)

        # ── Helper: one label/value pair ────────────────────────────────────
        def cell(parent_layout, lbl, val_color='#003d8f', bold=True, mono=True,
                 min_w=60):
            vl = QVBoxLayout(); vl.setSpacing(1); vl.setContentsMargins(0,0,0,0)
            k = QLabel(lbl); k.setStyleSheet('font-size:8pt;color:#888;')
            v = QLabel('—')
            v.setMinimumWidth(min_w)
            style = (f'font-size:9pt;color:{val_color};'
                     f'{"font-weight:bold;" if bold else ""}'
                     f'{"font-family:Courier New;" if mono else ""}')
            v.setStyleSheet(style)
            vl.addWidget(k); vl.addWidget(v)
            parent_layout.addLayout(vl)
            return v

        def sep(parent):
            s = QFrame(); s.setFrameShape(QFrame.VLine)
            s.setStyleSheet('color:#b8cce4;'); s.setFixedWidth(1)
            s.setContentsMargins(0,4,0,4)
            parent.addSpacing(8); parent.addWidget(s); parent.addSpacing(8)

        def section_label(parent, text, color='#003d8f'):
            # Label at TOP (same row as field labels), stretch fills value row below
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f'font-size:8pt;font-weight:bold;color:{color};'
                f'letter-spacing:1px;padding-right:4px;')
            vl = QVBoxLayout(); vl.setSpacing(1); vl.setContentsMargins(0,0,4,0)
            vl.addWidget(lbl); vl.addStretch()
            parent.addLayout(vl)

        # ══ Section 1: LOAD ═════════════════════════════════════════════════
        grp_load = QFrame()
        grp_load.setStyleSheet(
            'QFrame{background:#eef4fb;border:1px solid #c8daea;border-radius:3px;}')
        gl = QHBoxLayout(grp_load); gl.setContentsMargins(8,2,8,2); gl.setSpacing(10)
        section_label(gl, 'LOAD')
        self._tP   = cell(gl, 'P kW',     min_w=65)
        self._tS   = cell(gl, 'S kVA',    min_w=65)
        self._tIb  = cell(gl, 'Ib A',     min_w=60)
        self._tBus = cell(gl, 'Busbar %', min_w=55, val_color='#003d8f')
        sep(gl)
        self._tS1  = cell(gl, 'L1 kVA',  min_w=65, val_color='#5c2d91')
        self._tS2  = cell(gl, 'L2 kVA',  min_w=65, val_color='#5c2d91')
        self._tS3  = cell(gl, 'L3 kVA',  min_w=65, val_color='#5c2d91')
        hl.addWidget(grp_load)

        hl.addSpacing(6)

        # ══ Section 2: MAIN CB ══════════════════════════════════════════════
        grp_cb = QFrame()
        grp_cb.setStyleSheet(
            'QFrame{background:#edf8ed;border:1px solid #b8ddb8;border-radius:3px;}')
        gc = QHBoxLayout(grp_cb); gc.setContentsMargins(8,2,8,2); gc.setSpacing(10)
        section_label(gc, 'MAIN CB', color='#107c10')
        self._tIsc = cell(gc, 'Isc kA',  min_w=52)
        self._pfIb = cell(gc, 'Ib A',    min_w=60, val_color='#107c10')
        self._pfCB = cell(gc, 'Main CB', min_w=110, val_color='#107c10')
        # Hidden reference — _upd_totals still writes to _tCB without crashing
        self._tCB = QLabel(); self._tCB.hide()
        hl.addWidget(grp_cb)

        hl.addSpacing(6)

        # ══ Section 3: CABLE ════════════════════════════════════════════════
        grp_cab = QFrame()
        grp_cab.setStyleSheet(
            'QFrame{background:#f4f0ff;border:1px solid #d0c8e8;border-radius:3px;}')
        gca = QHBoxLayout(grp_cab); gca.setContentsMargins(8,2,8,2); gca.setSpacing(10)
        section_label(gca, 'CABLE', color='#5c2d91')
        self._pfMm2  = cell(gca, 'mm²',        min_w=55,  val_color='#5c2d91')
        self._pfCode = cell(gca, 'Cable Code',  min_w=180, val_color='#5c2d91')
        self._pfVd   = cell(gca, 'Vd%',         min_w=52,  val_color='#5c2d91')
        hl.addWidget(grp_cab, 1)

        return w

    # ── PROPERTIES PANEL ──────────────────────────────────────────────────────
    def _mk_props(self):
        outer = QWidget()
        outer.setStyleSheet('background:#f5f5f5;')
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        w = QWidget()
        w.setStyleSheet('background:#f5f5f5;border-top:2px solid #0078d4;')
        w.setMinimumHeight(125)
        hl = QHBoxLayout(w); hl.setContentsMargins(6,4,6,4); hl.setSpacing(4)

        # ── Section builder: fixed-height header strip pinned to top ────────
        def mk_section(title, txt_color, line_color, border_col, bg_col):
            frm = QFrame()
            frm.setStyleSheet(
                f'QFrame{{border:1px solid {border_col};'
                f'border-radius:3px;background:{bg_col};}}')
            outer = QVBoxLayout(frm)
            outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
            # Header strip — fixed 20px, flush to top
            hdr_strip = QWidget()
            hdr_strip.setFixedHeight(20)
            hdr_strip.setStyleSheet(
                f'background:transparent;border:none;'
                f'border-bottom:2px solid {line_color};')
            hs_l = QHBoxLayout(hdr_strip)
            hs_l.setContentsMargins(8,1,8,1); hs_l.setSpacing(0)
            lbl = QLabel(title)
            lbl.setStyleSheet(
                f'font-size:9pt;font-weight:bold;color:{txt_color};'
                f'letter-spacing:2px;border:none;background:transparent;')
            hs_l.addWidget(lbl); hs_l.addStretch()
            outer.addWidget(hdr_strip)
            # Content area
            content_w = QWidget()
            content_w.setStyleSheet('background:transparent;border:none;')
            cl = QVBoxLayout(content_w)
            cl.setContentsMargins(8,5,8,4); cl.setSpacing(4)
            outer.addWidget(content_w, 1)
            return frm, cl

        # ══ SECTION 1: LOAD ═══════════════════════════════════════════════════
        p_load, ll = mk_section('LOAD', '#003d8f', '#0078d4', '#c8daea', '#eef4fb')

        # Grid layout — even columns = labels (right-aligned, same width per column)
        #               odd  columns = inputs (aligned vertically across all rows)
        # Cols: 0=lbl  1=input  2=lbl  3=input  4=lbl  5=input  6=lbl  7=input  8=lbl  9=input
        _g = QGridLayout()
        _g.setHorizontalSpacing(5); _g.setVerticalSpacing(4)
        _g.setContentsMargins(0, 0, 0, 0)
        _g.setColumnStretch(1, 1)   # Name field stretches; all spinbox cols stay fixed

        def _gl(text):
            """Right-aligned grid label — lets QGridLayout enforce column widths."""
            lbl = QLabel(text)
            lbl.setStyleSheet('font-size:9pt;color:#555;')
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lbl

        # ── Row 0: Name | Ref | Type ─────────────────────────────────────────
        _g.addWidget(_gl('Name'),  0, 0)
        self._pName = self._le()
        _g.addWidget(self._pName,  0, 1)
        _g.addWidget(_gl('Ref'),   0, 2)
        self._pRef = self._le(); self._pRef.setFixedWidth(44)
        _g.addWidget(self._pRef,   0, 3)
        _g.addWidget(_gl('Type'),  0, 4)
        self._pType = self._cb(LOAD_TYPES)
        _g.addWidget(self._pType,  0, 5)

        # ── Row 1: P[kW] | S[kVA] | P.F. ────────────────────────────────────
        _g.addWidget(_gl('P[kW]'),  1, 0)
        self._pP = self._sp(0, 100000, 0, 0.1); self._pP.setFixedWidth(72)
        _g.addWidget(self._pP,      1, 1)
        _g.addWidget(_gl('S[kVA]'), 1, 2)
        self._pS = self._sp(0, 100000, 0, 0.1); self._pS.setFixedWidth(72)
        _g.addWidget(self._pS,      1, 3)
        _g.addWidget(_gl('P.F.'),   1, 4)
        self._pPF = self._sp(0.01, 1, 0.9, 0.01); self._pPF.setFixedWidth(62)
        _g.addWidget(self._pPF,     1, 5)

        # ── Row 2: L[m] | ΔU% | Phase | D.F. | Iscc[kA] ─────────────────────
        _g.addWidget(_gl('L[m]'),     2, 0)
        self._pL = self._sp(1, 100000, 10, 1); self._pL.setFixedWidth(72)
        _g.addWidget(self._pL,        2, 1)
        _g.addWidget(_gl('ΔU%'),      2, 2)
        self._pVD = self._sp(0.1, 20, 3, 0.5); self._pVD.setFixedWidth(60)
        _g.addWidget(self._pVD,       2, 3)
        _g.addWidget(_gl('Phase'),    2, 4)
        self._pPh = self._cb(PHASES)
        _g.addWidget(self._pPh,       2, 5)
        _g.addWidget(_gl('D.F. %'),   2, 6)
        self._pDF = self._sp(0, 100, 100, 1)
        self._pDF.setFixedWidth(56)
        self._pDF.setToolTip('Demand factor (%). 80 → Pdf = 0.8 × P for board totals;\n'
                             'feeder cable/CB sized at 100 % connected load.')
        _g.addWidget(self._pDF,       2, 7)

        ll.addLayout(_g)
        ll.addStretch()

        # Signals
        self._pP.valueChanged.connect(lambda v: self._psf_changed('P', v))
        self._pS.valueChanged.connect(lambda v: self._psf_changed('S', v))
        self._pPF.valueChanged.connect(lambda v: self._psf_changed('PF', v))
        self._pName.textChanged.connect(lambda t: self._pset('name', t))
        self._pRef.textChanged.connect(lambda t: self._pset('circuit_ref', t))
        self._pPh.currentTextChanged.connect(lambda t: self._pset('phase_str', t))
        self._pType.currentTextChanged.connect(self._type_changed)
        self._pL.valueChanged.connect(lambda v: self._pset('cable_length', v))
        self._pVD.valueChanged.connect(lambda v: self._pset('max_vdrop_pct', v))
        self._pDF.valueChanged.connect(
            lambda v: self._pset('demand_factor_pct', float(v)))
        hl.addWidget(p_load, 5)
        self._sect_load = p_load

        # ══ SECTION 2: CIRCUIT BREAKER ════════════════════════════════════════
        p_cb, cl = mk_section('CIRCUIT BREAKER', '#107c10', '#107c10', '#b8ddb8', '#edf8ed')

        # CB summary label — monospace, one line
        self._pCBLbl = QLabel('CB: —')
        self._pCBLbl.setStyleSheet(
            'color:#107c10;font-weight:bold;font-size:9pt;'
            'font-family:"Courier New";border:none;background:transparent;')
        cl.addWidget(self._pCBLbl)

        # Row A: Auto/Manual toggle | size picker | Family | Curve | 4P
        cb_ov = QHBoxLayout(); cb_ov.setSpacing(5)
        cb_ov.addWidget(self._fl('CB:'))
        _tog_style = (
            'QPushButton{background:#edf8ed;border:1px solid #b8ddb8;'
            'color:#107c10;font-size:8pt;padding:2px 8px;font-weight:bold;}'
            'QPushButton:checked{background:#107c10;color:#ffffff;border:1px solid #107c10;}'
            'QPushButton:hover:!checked{background:#d4edda;}')
        self._pCBBtnAuto   = QPushButton('⚡ Auto')
        self._pCBBtnManual = QPushButton('🔒 Manual')
        for _b in (self._pCBBtnAuto, self._pCBBtnManual):
            _b.setCheckable(True); _b.setFixedHeight(22)
            _b.setStyleSheet(_tog_style)
        self._pCBBtnAuto.setChecked(True)
        self._pCBBtnAuto.clicked.connect(lambda: self._cb_set_mode(False))
        self._pCBBtnManual.clicked.connect(lambda: self._cb_set_mode(True))
        cb_ov.addWidget(self._pCBBtnAuto)
        cb_ov.addWidget(self._pCBBtnManual)
        self._pCBOverride = QComboBox()
        self._pCBOverride.setStyleSheet(
            'QComboBox{background:#ffffff;border:1px solid #b8ddb8;border-radius:2px;'
            'padding:2px 6px;font-size:9pt;font-family:"Courier New";color:#1a1a1a;}'
            'QComboBox:focus{border-color:#107c10;}'
            'QComboBox::drop-down{border-left:1px solid #b8ddb8;width:18px;background:#edf8ed;}'
            'QComboBox QAbstractItemView{background:#fff;border:1px solid #107c10;'
            'selection-background-color:#d4edda;color:#1a1a1a;}')
        self._pCBOverride.setMinimumWidth(90)
        self._pCBOverride.setVisible(False)   # hidden until Manual selected
        self._pCBOverride.currentIndexChanged.connect(self._cb_override_changed)
        cb_ov.addWidget(self._pCBOverride)
        # Family — shown for MCCB / ACB only
        self._cb_family_lbl = self._fl('Family:')
        self._pCBFamily = self._cb(CB_FAMILIES)
        self._pCBFamily.setFixedWidth(86)
        self._pCBFamily.currentTextChanged.connect(
            lambda t: self._cb_attr_changed('cb_family', t))
        cb_ov.addWidget(self._cb_family_lbl)
        cb_ov.addWidget(self._pCBFamily)
        # Curve B/C/D — shown for MCB only
        self._cb_curve_lbl = self._fl('Curve:')
        self._pTripCurve = self._cb(['B', 'C', 'D'])
        self._pTripCurve.setFixedWidth(48)
        self._pTripCurve.currentTextChanged.connect(
            lambda t: self._cb_attr_changed('trip_curve', t))
        cb_ov.addWidget(self._cb_curve_lbl)
        cb_ov.addWidget(self._pTripCurve)
        # 4P — visible only for 3-phase circuits
        self._p4P = QCheckBox('4P')
        self._p4P.setToolTip('Force 4-pole CB (e.g. generator circuits) — 3-phase only')
        self._p4P.stateChanged.connect(self._4p_changed)
        cb_ov.addWidget(self._p4P)
        # Icu — breaking capacity
        cb_ov.addSpacing(8)
        self._pIcuLbl = self._fl('Icu:')
        cb_ov.addWidget(self._pIcuLbl)
        self._pIcuCB = QComboBox()
        _icu_style = (
            'QComboBox{background:#ffffff;border:1px solid #b8ddb8;border-radius:2px;'
            'padding:2px 5px;font-size:9pt;font-family:"Courier New";color:#1a1a1a;}'
            'QComboBox:focus{border-color:#107c10;}'
            'QComboBox::drop-down{border-left:1px solid #b8ddb8;width:16px;background:#edf8ed;}'
            'QComboBox QAbstractItemView{background:#fff;border:1px solid #107c10;'
            'selection-background-color:#d4edda;color:#1a1a1a;}')
        self._pIcuCB.setStyleSheet(_icu_style)
        self._pIcuCB.setFixedWidth(80)
        for _kA in (6, 10, 16, 25, 36, 50, 63, 85, 100, 150, 200):
            self._pIcuCB.addItem(f'{_kA} kA', _kA)
        self._pIcuCB.setCurrentIndex(3)   # default 25 kA
        self._pIcuCB.setToolTip('CB rated breaking capacity (Icu)')
        self._pIcuCB.currentIndexChanged.connect(self._icu_cb_changed)
        cb_ov.addWidget(self._pIcuCB)
        cb_ov.addStretch()
        cl.addLayout(cb_ov)

        # Row B: Ir× | Isd× | tsd | Relay (MCCB/ACB only — hidden for MCB)
        self._cb_row_b = QWidget()
        self._cb_row_b.setStyleSheet('background:transparent;border:none;')
        tr_row = QHBoxLayout(self._cb_row_b)
        tr_row.setContentsMargins(0, 0, 0, 0); tr_row.setSpacing(5)
        tr_row.addWidget(self._fl('Ir×:'))
        self._pIr = self._sp(0.4, 1.0, 1.0, 0.05)
        self._pIr.setFixedWidth(52)
        self._pIr.valueChanged.connect(lambda v: self._cb_attr_changed('Ir_mult', v))
        tr_row.addWidget(self._pIr)
        tr_row.addWidget(self._fl('Isd×:'))
        self._pIsd = self._sp(1.5, 10.0, 8.0, 0.5)
        self._pIsd.setFixedWidth(52)
        self._pIsd.valueChanged.connect(lambda v: self._cb_attr_changed('Isd_mult', v))
        tr_row.addWidget(self._pIsd)
        tr_row.addWidget(self._fl('tsd s:'))
        self._pTsd = self._sp(0.0, 0.5, 0.1, 0.05)
        self._pTsd.setFixedWidth(48)
        self._pTsd.valueChanged.connect(lambda v: self._cb_attr_changed('tsd_s', v))
        tr_row.addWidget(self._pTsd)
        # Overload relay — MCCB only (not ACB, which has built-in motor protection)
        tr_row.addSpacing(8)
        self._pOverloadRelay = QCheckBox('Relay')
        self._pOverloadRelay.setStyleSheet('font-size:9pt;')
        self._pOverloadRelay.stateChanged.connect(self._relay_changed)
        tr_row.addWidget(self._pOverloadRelay)
        self._pRelaySetting = self._sp(0.7, 1.25, 1.0, 0.05)
        self._pRelaySetting.setFixedWidth(48)
        self._pRelaySetting.valueChanged.connect(
            lambda v: self._cb_attr_changed('relay_setting', v))
        tr_row.addWidget(self._pRelaySetting)
        tr_row.addStretch()
        cl.addWidget(self._cb_row_b)

        # Coordination note — smaller, italic
        self._pCoordLbl = QLabel('')
        self._pCoordLbl.setStyleSheet(
            'font-size:8pt;color:#555;font-style:italic;border:none;background:transparent;')
        self._pCoordLbl.setWordWrap(True)
        self._pCoordLbl.setToolTip('Coordination check result')
        cl.addWidget(self._pCoordLbl)
        cl.addStretch()
        hl.addWidget(p_cb, 4)
        self._sect_cb = p_cb

        # Motor MOTOR + CB (same row as CABLE; replaces LOAD + CB for Motor rows)
        from .motor_circuit_sizing import MotorCircuitSizingPanel
        self._motor_sizing = MotorCircuitSizingPanel(self)
        self._motor_sizing.motor_applied.connect(self._on_motor_applied)
        self._motor_sizing.feeder_fields_changed.connect(
            self._on_motor_feeder_fields_changed)
        self._motor_sizing.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._motor_sizing.setStyleSheet(
            'background:#f5f5f5;border:none;')
        self._motor_sizing.setVisible(False)
        hl.addWidget(self._motor_sizing, 9)

        # ══ SECTION 3: CABLE ══════════════════════════════════════════════════
        p_cab, cal = mk_section('CABLE', '#5c2d91', '#5c2d91', '#d0c8e8', '#f4f0ff')

        _res_ss = ('background:#f0f0f0;color:#5c2d91;font-weight:bold;'
                   'border:1px solid #d0d0d0;padding:2px 4px;'
                   'font-family:"Courier New";font-size:9pt;')

        # Row 1: SIZE | Iz A | Vd%  — all result fields in one compact row
        r_sz = QHBoxLayout(); r_sz.setSpacing(5)
        r_sz.addWidget(self._fl('SIZE'))
        self._pSize = QLineEdit('—'); self._pSize.setReadOnly(True)
        self._pSize.setFixedWidth(72); self._pSize.setStyleSheet(_res_ss)
        r_sz.addWidget(self._pSize)
        r_sz.addWidget(self._fl('Iz A'))
        self._pIz = QLineEdit('—'); self._pIz.setReadOnly(True)
        self._pIz.setFixedWidth(58); self._pIz.setStyleSheet(_res_ss)
        r_sz.addWidget(self._pIz)
        r_sz.addWidget(self._fl('Vd%'))
        self._pVdrop = QLineEdit('—'); self._pVdrop.setReadOnly(True)
        self._pVdrop.setFixedWidth(58); self._pVdrop.setStyleSheet(_res_ss)
        r_sz.addWidget(self._pVdrop)
        r_sz.addStretch()
        cal.addLayout(r_sz)

        # Row 2: Code dropdown + Select Cable button
        cc = QHBoxLayout(); cc.setSpacing(4)
        cc.addWidget(self._fl('Code'))
        self._pCode = QComboBox(); self._pCode.setEditable(True)
        self._pCode.setInsertPolicy(QComboBox.NoInsert)
        from .qt_helpers import app_font
        self._pCode.setFont(app_font('Courier New', 9))
        self._pCode.setMinimumWidth(120)
        self._pCode.currentTextChanged.connect(self._code_changed)
        cc.addWidget(self._pCode, 1)
        self._pSelBtn = QPushButton('Select Cable')
        self._pSelBtn.setStyleSheet(
            'QPushButton{background:#0078d4;color:#fff;border:none;'
            'font-weight:bold;padding:4px 10px;font-size:9pt;}'
            'QPushButton:hover{background:#005fa3;}')
        self._pSelBtn.setToolTip(
            'Open Cable Selector — choose type/installation/k-factors,\n'
            'press Proceed, then calculation runs automatically')
        self._pSelBtn.clicked.connect(self._open_selector)
        cc.addWidget(self._pSelBtn)
        cal.addLayout(cc)

        # Status — smaller italic note
        self._pStat = QLabel('Click a row to edit  |  Double-click for full editor')
        self._pStat.setStyleSheet(
            'color:#888;font-size:8pt;font-style:italic;'
            'border:none;background:transparent;')
        self._pStat.setWordWrap(True)
        cal.addWidget(self._pStat)
        cal.addStretch()

        # Unused but referenced elsewhere — keep hidden
        self._props_context = QLabel('')
        self._props_context.hide()
        hl.addWidget(p_cab, 3)
        self._sect_cable = p_cab

        self._props_standard = w
        ol.addWidget(self._props_standard)
        return outer

    def _set_motor_props_mode(self, motor: bool) -> None:
        """Motor row: MOTOR + motor CB in the top bar; generic LOAD/CB hidden."""
        if hasattr(self, '_sect_load'):
            self._sect_load.setVisible(not motor)
        if hasattr(self, '_sect_cb'):
            self._sect_cb.setVisible(not motor)
        if hasattr(self, '_motor_sizing'):
            self._motor_sizing.setVisible(motor)

    def show_motor_circuit_tab(self):
        """Ribbon MOTOR tab — focus motor sizing for current Motor feeder."""
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            QMessageBox.information(
                self, 'Motor Circuit Sizing',
                'Select a Motor feeder row in the board grid first.')
            return
        f = self._board.feeders[row]
        if f.load_type != 'Motor':
            QMessageBox.information(
                self, 'Motor Circuit Sizing',
                'The selected row is not a Motor load. Change Type to Motor first.')
            return
        self._show_motor_circuit_sizing(f, row)

    def _show_motor_circuit_sizing(self, f, row: int):
        """Motor protection strip (Start/CB) — standard props bar stays for cable."""
        self._props_mode = 'feeder'
        self._sync_props(f)
        if row >= 0:
            self._motor_sizing.bind_feeder(f, row, self._board)
        self._set_motor_props_mode(True)

    def _show_standard_props_panel(self, motor: bool = False):
        self._set_motor_props_mode(motor)

    def _on_motor_feeder_fields_changed(self, feeder: C_Feeder):
        """Motor panel edited — refresh grid row and keep S/PF in sync."""
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            for i, f in enumerate(self._board.feeders):
                if f is feeder:
                    row = i
                    break
        if row < 0 or row >= len(self._board.feeders):
            return
        self._derive_psf(feeder, 'P')
        self._refresh_row(row)
        self._full_timer.start()

    def _on_motor_applied(self, feeder: C_Feeder):
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            for i, f in enumerate(self._board.feeders):
                if f is feeder:
                    row = i
                    break
        if row < 0 or row >= len(self._board.feeders):
            return
        self._board.feeders[row] = feeder
        self._derive_psf(feeder, 'P')
        self._do_calc(feeder)
        self._refresh_row(row)
        self._upd_totals()
        if (feeder.load_type == 'Motor'
                and hasattr(self, '_motor_sizing')
                and self._motor_sizing.isVisible()):
            self._motor_sizing.bind_feeder(feeder, row, self._board)
        else:
            self._sync_props(feeder)
        self._full_timer.start()

    def _sync_motor_feeder_power(self, f: C_Feeder) -> None:
        """Keep standard LOAD fields aligned with motor nameplate when configured."""
        if f.load_type != 'Motor':
            return
        m = f.motor
        if getattr(f, 'motor_configured', False) and m.Ib_A > 0:
            m.sync_to_feeder(f)
        elif m.Pn_kW > 0:
            sf = max(m.service_factor or 1.0, 0.01)
            f.P = round(m.Pn_kW * sf, 3)
            if m.cos_phi:
                f.PF = m.cos_phi
                f.S = round(f.P / m.cos_phi, 3) if m.cos_phi else f.S

    # ── STATUS BAR ────────────────────────────────────────────────────────────
    def _mk_statusbar(self):
        w = QWidget(); w.setFixedHeight(24)
        w.setStyleSheet('background:#e0e8f0;border-top:1px solid #b8cce4;')
        hl = QHBoxLayout(w); hl.setContentsMargins(8,0,8,0)
        self._status = QLabel('Ready')
        self._status.setStyleSheet(
            'font-size:10px;color:#444;background:transparent;')
        self._status.setWordWrap(False)
        hl.addWidget(self._status, 1)
        ver = QLabel(f'VoltFlow v{APP_VERSION}  |  KSA · 60 Hz LV distribution')
        ver.setStyleSheet('font-size:10px;color:#888;')
        hl.addWidget(ver)
        return w

    def _refresh_status_messages(self, info: str = '') -> None:
        """Show calc info plus all project warnings/errors on the bottom bar."""
        errors, warnings = collect_messages(self._root)
        text = format_status_line(info, errors, warnings)
        tip = status_tooltip(errors, warnings)
        has_err = bool(errors)
        has_warn = bool(warnings)
        self._status.setText(text)
        self._status.setToolTip(tip)
        self._status.setStyleSheet(status_stylesheet(has_err, has_warn))

    # ── BOARD LOADING ─────────────────────────────────────────────────────────
    def _load_board(self, board):
        self._board = board
        self._update_header()
        self._update_df_ui()
        self._fill_grid()
        item = self._find_ti(board.board_id)
        if item:
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(item)
            self._tree.blockSignals(False)
        # Auto-select first non-SubPanel feeder row
        first_editable = next(
            (i for i, f in enumerate(self._board.feeders)
             if f.load_type not in ('SubPanel', 'Space')), None)
        if first_editable is not None:
            self._tbl.blockSignals(True)
            self._tbl.selectRow(first_editable)
            self._tbl.blockSignals(False)
            self._sync_props(self._board.feeders[first_editable])
        else:
            self._tbl.clearSelection()
            self._sync_primary_props()
        self._refresh_status_messages(
            f'Board: {board.name}  |  Level {board.level}  |  '
            f'{len(board.feeders)} feeders  |  '
            f'{len(board.child_boards)} sub-panels')

    def _update_header(self):
        b = self._board
        lnames = ['', 'MDB', 'SDB', 'DB', 'CP', 'Panel', '', '', '', '', '']
        ln = lnames[min(b.level, 10)]
        # Hidden ribbon labels (still written so ribbon can read them)
        self._hdr.setText(
            f'{ln}  {b.name}  ·  {b.phases}~{b.voltage:.0f}V  ·  '
            f'Busbar {b.busbar_A:.0f}A  ·  {b.frame}  ·  {b.IP}')
        self._hdr_r.setText(f'{b.project}   {b.drawing_ref}')

        # ── Board bar cells ───────────────────────────────────────────────────
        _v = 'font-size:9pt;font-weight:bold;font-family:Courier New;color:'
        self._bb_name.setText(b.name)
        self._bb_lvl.setText(ln or f'L{b.level}')
        self._bb_sys.setText(f'{b.phases}~{b.voltage:.0f}V')
        self._bb_bus.setText(f'{b.busbar_A:.0f} A')
        # Busbar loading — red when overloaded
        load_clr = '#c42b1c' if b.busbar_loading > 90 else '#107c10'
        self._bb_load.setText(f'{b.busbar_loading:.1f} %')
        self._bb_load.setStyleSheet(_v + load_clr + ';')
        self._bb_isc.setText(f'{b.Isc_board_kA:.2f} kA')
        self._bb_frame.setText(b.frame or '—')
        self._bb_ip.setText(b.IP or '—')

    def _editor_under_table(self, editor) -> bool:
        """True if widget belongs to this table's in-cell editor."""
        if editor is None or editor is self._tbl:
            return False
        w = editor
        while w is not None:
            if w is self._tbl or w is self._tbl.viewport():
                return True
            w = w.parentWidget()
        return False

    def _end_grid_edit(self, submit: bool = True) -> None:
        """Close the active in-cell editor without cross-view commit errors."""
        if self._tbl.state() != QAbstractItemView.State.EditingState:
            return
        idx = self._tbl.currentIndex()
        if not idx.isValid():
            return
        editor = self._tbl.indexWidget(idx)
        if editor is None:
            fw = self._tbl.focusWidget()
            if self._editor_under_table(fw):
                editor = fw
        if editor is None or not self._editor_under_table(editor):
            # Focus moved to props panel / another widget — drop stale edit state
            item = self._tbl.item(idx.row(), idx.column())
            if item is not None:
                try:
                    self._tbl.closePersistentEditor(item)
                except Exception:
                    pass
            self._tbl.setState(QAbstractItemView.State.NoState)
            return
        delegate = (self._load_type_delegate if idx.column() == 2
                    else self._tbl.itemDelegate(idx))
        hint = (QAbstractItemDelegate.EndEditHint.SubmitModelCache if submit
                else QAbstractItemDelegate.EndEditHint.RevertModelCache)
        delegate.commitData.emit(editor)
        delegate.closeEditor.emit(editor, hint)

    # ── GRID FILL ─────────────────────────────────────────────────────────────
    def _fill_grid(self):
        self._end_grid_edit()
        self._busy = True
        b = self._board
        self._tbl.setRowCount(len(b.feeders))
        for ri, f in enumerate(b.feeders):
            self._fill_row(ri, f)
        self._busy = False
        self._upd_totals()

    def _fill_row(self, ri, f):
        rec   = f.cable.recommended
        is_sp = f.load_type == 'SubPanel'
        is_stub_row = is_sp and f.is_stub
        clr   = QColor(LOAD_COLORS.get(f.load_type, '#404040'))
        is_spare = f.load_type == 'Spare'
        is_space = f.load_type == 'Space'
        bg    = (QColor('#ffe0b2') if is_stub_row else
                 QColor('#fff3e0') if is_sp else
                 QColor('#e8f5e9') if is_spare else
                 QColor('#eceff1') if is_space else
                 QColor('#ffffff') if ri % 2 == 0 else QColor('#f8f9fa'))

        S_val = f.S or ((f.P / f.PF) if f.P and f.PF else 0)
        # For SubPanel rows, get CB/conductor from child board if available
        if f.load_type == 'SubPanel' and f.subpanel_id:
            child_b = self._root.find_board(f.subpanel_id)
            if child_b:
                # Always sync CB from child board main CB
                if child_b.main_cb.In_CB:
                    f.cb.In_CB   = child_b.main_cb.In_CB
                    f.cb.cb_type = child_b.main_cb.cb_type
                    f.cb.poles   = child_b.main_cb.poles
                    f.cb.Icu_kA  = child_b.main_cb.Icu_kA
                    f.cb.passes_protection = child_b.main_cb.passes_protection
                    f.cb.passes_Isc       = child_b.main_cb.passes_Isc
                # Always sync load from child board totals
                if child_b.total_Ib:
                    f.Ib = child_b.total_Ib
                    f.S  = child_b.total_S_kVA
                    f.P  = round(child_b.total_S_kVA * 0.9, 2)
                # Get primary feeder cable data from child board
                child_pf = child_b.primary_feeder
                if child_b.primary_feeder_selected and child_pf.cable.recommended:
                    import copy
                    cc = child_pf.cable
                    f.cable.conductor_table = copy.deepcopy(cc.conductor_table)
                    f.cable.recommended     = cc.recommended
                    f.cable.k1 = cc.k1
                    f.cable.k2 = cc.k2
                    f.cable.k3 = cc.k3
                    f.cable.k = cc.k
                    f.cable.k_parallel = getattr(cc, 'k_parallel', 1.0)
                    f.cable.parallel_cables = getattr(cc, 'parallel_cables', 1)
                    f.cable.manual_sizing = getattr(cc, 'manual_sizing', False)
                    f.cable.relink_recommended()
                    f.result_vdrop_pct      = child_pf.result_vdrop_pct
                    f.result_vdrop_v        = child_pf.result_vdrop_v
                    f.cable.passes_ampacity = child_pf.cable.passes_ampacity
                    f.cable.passes_vdrop    = child_pf.cable.passes_vdrop
                    f.Iz                    = child_pf.Iz
                elif not child_b.primary_feeder_selected:
                    # Primary feeder not configured — clear stale data
                    f.cable.recommended = None
                    f.result_vdrop_pct  = 0.0
                    f.Iz                = 0.0
                # Check protection rule: In_CB <= Iz
                # If fails, try next larger conductor from primary feeder table
                if (child_b.main_cb.In_CB and child_pf.cable.conductor_table
                        and f.Iz < child_b.main_cb.In_CB):
                    for row in child_pf.cable.conductor_table:
                        k2 = child_pf.cable._k2_for_size(row.size_mm2)
                        k  = round(child_pf.cable.k1 * k2 * child_pf.cable.k3, 4)
                        iz = round(row.In * k, 2)
                        if iz >= child_b.main_cb.In_CB:
                            f.cable.recommended     = row
                            f.Iz                    = iz
                            vd_v, vd_pct, _         = child_pf.cable._vdrop(row, f.Ib)
                            f.result_vdrop_v        = vd_v
                            f.result_vdrop_pct      = vd_pct
                            f.cable.passes_ampacity = iz >= f.Ib
                            f.cable.passes_vdrop    = (vd_pct <=
                                                        child_pf.max_vdrop_pct)
                            break

                cb_ok = (f.Ib <= child_b.main_cb.In_CB <= f.Iz
                         if f.Iz > 0 else False)
                f.cb.passes_protection = cb_ok
                f.passes_all = (cb_ok and
                                f.cable.passes_ampacity
                                if child_b.main_cb.In_CB else False)
        cb_s  = f'{f.cb.In_CB:.0f}A {f.cb.cb_type}' if f.cb.In_CB else '—'
        n_par = getattr(f.cable, 'parallel_cables', 1)
        mm2_s = (f'{int(rec.size_mm2) if rec.size_mm2==int(rec.size_mm2) else rec.size_mm2}'
                 if rec else '—')
        cod_s = f.cable.format_conductor_desc(f.phases) if rec else '—'
        vd_s = f'{f.result_vdrop_pct:.2f}' if f.result_vdrop_pct else '—'
        ib_s  = f'{f.Ib:.1f}' if f.Ib else '—'
        if is_stub_row:
            st_s, st_c = '📦', QColor('#e67e00')
        elif f.passes_all and f.Ib > 0:
            st_s, st_c = '✔', QColor('#107c10')
        elif not f.passes_all and f.Ib > 0:
            st_s, st_c = '✘', QColor('#c42b1c')
        else:
            st_s, st_c = '—', QColor('#aaaaaa')

        if is_space:
            vals = [str(ri+1), f.name, '—', '—',
                    '—','—','—','—','—','—','—','—','—','—','—','—']
        else:
            if is_stub_row:
                type_s = '📦'
            elif f.load_type in GRID_LOAD_TYPES:
                type_s = f.load_type
            else:
                type_s = f.load_type
            df_s = '—'
            if self._df_mode == 'per_load' and not is_sp:
                df_s = f'{f.demand_factor_pct:.0f}'
            elif (self._board.level == 0 and self._df_mode == 'project'
                  and not is_sp):
                df_s = '—'
            p_show = f'{f.P:.2f}' if f.P else '0.00'
            if (self._df_mode == 'per_load' and f.P_demand is not None
                    and f.demand_factor_pct < 100 and not is_sp):
                p_show = f'{f.P:.2f} ({f.P_demand:.1f})'
            vals = [
                str(ri+1), f.name,
                type_s, f.phase_str,
                p_show,
                f'{S_val:.2f}' if S_val else '—',
                f'{f.PF:.2f}' if f.PF else '0.90',
                df_s,
                f'{f.cable_length:.1f}', f'{f.max_vdrop_pct:.1f}',
                ib_s, cb_s, mm2_s, cod_s, vd_s, st_s,
            ]
        # non-editable col indices — P/S/cosφ (4,5,6) locked for SubPanel rows
        # because those values are computed from the child board's totals.
        no_edit = {0, 10, 11, 12, 14, 15}
        if is_sp or is_space or is_spare or is_stub_row:
            no_edit.add(2)
        if is_sp:
            no_edit |= {4, 5, 6, COL_DF}

        for ci, v in enumerate(vals):
            item = self._tbl.item(ri, ci)
            if item is None:
                item = QTableWidgetItem(); self._tbl.setItem(ri, ci, item)
            item.setText(v)
            item.setBackground(QBrush(bg))
            item.setTextAlignment(Qt.AlignCenter)

            if ci == 0:
                item.setForeground(QBrush(QColor('#888'))); item.setFont(SANS9)
            elif ci == 1:
                item.setForeground(QBrush(clr))
                item.setFont(SANSB if is_sp else SANS)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            elif ci == 2:
                item.setForeground(QBrush(clr)); item.setFont(SANSB)
            elif ci == 14:
                item.setForeground(QBrush(st_c)); item.setFont(SANSB)
            elif ci in (9, 10, 11, 13):
                item.setForeground(QBrush(QColor('#0078d4'))); item.setFont(MONO)
            elif ci == 12:
                item.setForeground(QBrush(QColor('#5c2d91'))); item.setFont(MONO)
            elif ci == 5:  # S kVA — editable, same style as P kW
                item.setForeground(QBrush(QColor('#1a1a1a'))); item.setFont(SANS)
            else:
                item.setForeground(QBrush(QColor('#1a1a1a'))); item.setFont(SANS)

            flags = item.flags()
            if ci in no_edit:
                item.setFlags(flags & ~Qt.ItemIsEditable)
            else:
                item.setFlags(flags | Qt.ItemIsEditable)

        self._tbl.setRowHeight(ri, 24)

    def _refresh_row(self, ri):
        if 0 <= ri < len(self._board.feeders):
            self._busy = True
            self._fill_row(ri, self._board.feeders[ri])
            self._busy = False

    # ── CELL EVENTS ───────────────────────────────────────────────────────────
    def _on_cell(self, row, col):
        if self._busy or row >= len(self._board.feeders): return
        if col == 2:
            return  # Type column — handled by LoadTypeDelegate.setModelData
        f = self._board.feeders[row]
        item = self._tbl.item(row, col)
        if not item: return
        v = item.text().strip()
        try:
            if col == 1:
                f.name = v
                if f.load_type == 'SubPanel' and f.subpanel_id:
                    child = self._root.find_board(f.subpanel_id)
                    if child:
                        child.name = v
                        item = self._find_ti(child.board_id)
                        if item:
                            ico = '🔌' if child.level == 0 else '⚡'
                            item.setText(0, f'{ico}  {v}')
            elif col == 3:  f.phase_str      = v if v in PHASES else 'L123'
            elif col == 4:
                f.P = float(v) if v else 0
                self._derive_psf(f, 'P')
            elif col == 5:
                f.S = float(v) if v else 0
                self._derive_psf(f, 'S')
            elif col == 6:
                f.PF = max(0.01, min(1, float(v))) if v else 0.9
                self._derive_psf(f, 'PF')
            elif col == COL_DF:
                f.demand_factor_pct = max(0.0, min(100.0, float(v) if v else 100))
            elif col == 8:
                f.cable_length = float(v) if v else 10
                f.cable.cable_length = f.cable_length
            elif col == COL_VDROP:
                f.max_vdrop_pct = float(v) if v else 3.0
                f.vd_user_override = True
                f.cable.max_vdrop_pct = f.max_vdrop_pct
            elif col == 13: self._apply_code(f, v)
            else: return
        except ValueError: return
        self._sync_props(f)
        # Load-affecting edits (P, S, PF, phase, DF) change total_Ib and therefore
        # require a full recalc so the primary feeder cable is re-sized.
        # In global mode, length / vdrop limit changes need full network optimize.
        if col in (3, 4, 5, 6, COL_DF, 8, COL_VDROP):
            self._full_timer.start()
        else:
            self._timer.start()

    def _commit_grid_editor(self):
        """Commit and close the active grid cell editor."""
        self._end_grid_edit(submit=True)

    def _on_cell_click(self, row, col):
        """Single click on editable cell → enter edit mode immediately."""
        item = self._tbl.item(row, col)
        if not item or not (item.flags() & Qt.ItemIsEditable):
            return
        idx = self._tbl.model().index(row, col)
        if not self._tbl.edit(idx):
            return
        if col == 2:
            w = self._tbl.indexWidget(idx)
            if isinstance(w, QComboBox):
                w.showPopup()

    def _on_dbl(self, row, col):
        if row >= len(self._board.feeders): return
        f = self._board.feeders[row]
        if f.load_type == 'SubPanel' and f.subpanel_id:
            board = self._root.find_board(f.subpanel_id)
            if board: self._load_board(board)
        elif f.load_type not in ('Space',):
            self._open_feeder_window(f, row)

    def _selected_grid_rows(self) -> list[int]:
        """Selected feeder row indices (reliable with SelectRows mode)."""
        return sorted(
            idx.row() for idx in self._tbl.selectionModel().selectedRows()
        )

    def _grid_key_press(self, event):
        """Excel-like keyboard behaviour for the feeder grid."""
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QApplication, QTableWidget
        from PySide6.QtCore import Qt as _Qt

        key  = event.key()
        mods = event.modifiers()
        row  = self._tbl.currentRow()
        col  = self._tbl.currentColumn()
        n_rows = self._tbl.rowCount()
        n_cols = self._tbl.columnCount()

        # ── Ctrl+C / Ctrl+X — copy / cut full feeder row(s) ───────────────
        if event.matches(QKeySequence.Copy):
            rows = self._selected_grid_rows()
            if rows:
                self._copy_feeders(rows, cut=False)
                event.accept()
                return
            event.accept()
            return

        if event.matches(QKeySequence.Cut):
            rows = self._selected_grid_rows()
            if rows:
                self._copy_feeders(rows, cut=True)
                event.accept()
                return
            event.accept()
            return

        # ── Ctrl+V — paste copied feeder row(s) below selection ──────────
        if event.matches(QKeySequence.Paste):
            if self._feeder_clipboard:
                self._paste_feeders(self._selected_grid_rows())
                event.accept()
                return
            # Fallback: paste tab-separated cell text from Excel
            text = QApplication.clipboard().text()
            if not text:
                event.accept()
                return
            start_row = row
            start_col = col
            if start_row < 0:
                event.accept()
                return
            self._busy = True
            for ri, line in enumerate(text.split('\n')):
                target_row = start_row + ri
                if target_row >= len(self._board.feeders):
                    break
                for ci, val in enumerate(line.split('\t')):
                    target_col = start_col + ci
                    if target_col >= n_cols:
                        break
                    item = self._tbl.item(target_row, target_col)
                    if item and (item.flags() & _Qt.ItemIsEditable):
                        item.setText(val.strip())
            self._busy = False
            for ri in range(len(self._board.feeders)):
                self._on_cell(ri, col)
            event.accept()
            return

        # ── Delete / Backspace — clear editable cell ──────────────────────
        if key in (_Qt.Key_Delete, _Qt.Key_Backspace):
            item = self._tbl.item(row, col)
            if item and (item.flags() & _Qt.ItemIsEditable):
                self._tbl.editItem(item)
                editor = self._tbl.focusWidget()
                if editor: editor.setProperty('text', '')
            event.accept(); return

        # ── Enter — confirm + move down ───────────────────────────────────
        if key in (_Qt.Key_Return, _Qt.Key_Enter):
            # Commit current edit and move down
            if self._tbl.state() == QAbstractItemView.State.EditingState:
                self._tbl.currentIndex()  # force commit via focus change
                self._tbl.setCurrentCell(min(row + 1, n_rows - 1), col)
            else:
                self._tbl.setCurrentCell(min(row + 1, n_rows - 1), col)
            event.accept(); return

        # ── Tab — confirm + move right (wrap to next row) ─────────────────
        if key == _Qt.Key_Tab:
            next_col = col + 1
            next_row = row
            # Skip non-editable columns
            while next_col < n_cols:
                item = self._tbl.item(next_row, next_col)
                if item and (item.flags() & _Qt.ItemIsEditable): break
                next_col += 1
            if next_col >= n_cols:
                next_col = 1  # wrap to Load Name col
                next_row = min(row + 1, n_rows - 1)
            self._tbl.setCurrentCell(next_row, next_col)
            event.accept(); return

        # ── Escape — cancel edit ──────────────────────────────────────────
        if key == _Qt.Key_Escape:
            self._end_grid_edit(submit=False)
            event.accept(); return

        # ── Arrow keys — commit edit if editing, then navigate ───────────────
        if key in (_Qt.Key_Up, _Qt.Key_Down, _Qt.Key_Left, _Qt.Key_Right):
            if self._tbl.state() == QAbstractItemView.State.EditingState:
                self._commit_grid_editor()
            if key == _Qt.Key_Up:
                self._tbl.setCurrentCell(max(row-1, 0), col)
            elif key == _Qt.Key_Down:
                self._tbl.setCurrentCell(min(row+1, n_rows-1), col)
            elif key == _Qt.Key_Left:
                self._tbl.setCurrentCell(row, max(col-1, 0))
            elif key == _Qt.Key_Right:
                self._tbl.setCurrentCell(row, min(col+1, n_cols-1))
            event.accept(); return

        # ── F2 — enter edit mode at end of text ───────────────────────────
        if key == _Qt.Key_F2:
            item = self._tbl.item(row, col)
            if item and (item.flags() & _Qt.ItemIsEditable):
                self._tbl.editItem(item)
            event.accept(); return

        # ── Printable character — start typing immediately (replaces) ─────
        if (not mods or mods == _Qt.ShiftModifier) and event.text() and event.text().isprintable():
            item = self._tbl.item(row, col)
            if item and (item.flags() & _Qt.ItemIsEditable):
                self._tbl.editItem(item)
                # Send the key to the new editor so first char appears
                editor = self._tbl.focusWidget()
                if editor:
                    from PySide6.QtWidgets import QLineEdit, QAbstractSpinBox
                    if isinstance(editor, QLineEdit):
                        editor.clear()
                        editor.insert(event.text())
                    elif isinstance(editor, QAbstractSpinBox):
                        editor.lineEdit().clear()
                        editor.lineEdit().insert(event.text())
                event.accept(); return

        QTableWidget.keyPressEvent(self._tbl, event)

    # ── TREE DRAG-DROP (board re-parenting) ───────────────────────────────────
    def _on_tree_rows_moved(self, src_parent, src_start, _src_end,
                            dst_parent, dst_row):
        """Called by rowsMoved after QTreeWidget has already moved the item."""
        # Identify the destination parent item
        dst_item = (self._tree.itemFromIndex(dst_parent)
                    if dst_parent.isValid()
                    else self._tree.invisibleRootItem())
        if not dst_item:
            self._reload_tree(); return

        # The moved item sits at dst_row (may be clamped if past end)
        actual_row = min(dst_row, dst_item.childCount() - 1)
        if actual_row < 0:
            self._reload_tree(); return
        moved_item = dst_item.child(actual_row)
        if not moved_item:
            self._reload_tree(); return

        moved_bid      = moved_item.data(0, Qt.UserRole)
        new_parent_bid = dst_item.data(0, Qt.UserRole) if dst_parent.isValid() else None

        if not moved_bid or not new_parent_bid:
            # Dropped at the invisible root — not allowed; restore
            self._reload_tree(); return

        old_parent = self._root.find_parent(moved_bid)
        if not old_parent:
            self._reload_tree(); return

        if old_parent.board_id == new_parent_bid:
            # Sibling reorder — tree already looks right, just rebuild to
            # keep icons/colours consistent with model level info.
            self._reload_tree(); return

        self._reparent_board(moved_bid, new_parent_bid)

    def _reparent_board(self, bid: str, new_parent_bid: str):
        board      = self._root.find_board(bid)
        new_parent = self._root.find_board(new_parent_bid)
        if not board or not new_parent:
            self._reload_tree(); return
        # Prevent circular: new_parent must not be a descendant of board
        if new_parent.find_board(bid):
            self._reload_tree(); return
        old_parent = self._root.find_parent(bid)
        if not old_parent or old_parent.board_id == new_parent_bid:
            self._reload_tree(); return
        # Move the SubPanel feeder to new parent (preserving CB/cable settings)
        sp = next((f for f in old_parent.feeders if f.subpanel_id == bid), None)
        if sp:
            old_parent.feeders.remove(sp)
            new_parent.feeders.append(sp)
        else:
            sp = C_Feeder(name=board.name, load_type='SubPanel', subpanel_id=bid,
                          phases=new_parent.phases, voltage=new_parent.voltage)
            new_parent.feeders.append(sp)
        old_parent.child_boards.remove(board)
        new_parent.child_boards.append(board)
        board.parent_id = new_parent.board_id
        self._update_board_levels(board, new_parent.level + 1)
        self._reload_tree()
        # Refresh grid if the current view was one of the affected boards
        if self._board in (old_parent, new_parent, board):
            self._load_board(self._board)

    def _update_board_levels(self, board, level: int):
        board.level = level
        for child in board.child_boards:
            self._update_board_levels(child, level + 1)

    # ── GRID CONTEXT MENU (cut / copy / paste + row ops) ─────────────────────
    def _on_grid_ctx_menu(self, pos: QPoint):
        idx = self._tbl.indexAt(pos)
        row_at = idx.row() if idx.isValid() else -1
        if row_at >= 0 and row_at not in self._selected_grid_rows():
            self._tbl.clearSelection()
            self._tbl.selectRow(row_at)

        sel_rows = list(self._selected_grid_rows())
        has_sel = bool(sel_rows)
        has_clip = bool(self._feeder_clipboard)
        is_single = len(sel_rows) == 1

        menu = QMenu(self._tbl)
        menu.setObjectName('feederGridMenu')
        menu.setStyleSheet(_GRID_CTX_MENU_STYLE)

        act_cut = menu.addAction('Cut')
        act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        act_copy = menu.addAction('Copy')
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        n_clip = len(self._feeder_clipboard)
        act_paste = menu.addAction(
            'Paste' + (f'  ({n_clip})' if n_clip else ''))
        act_paste.setShortcut(QKeySequence.StandardKey.Paste)

        menu.addSeparator()
        act_up = menu.addAction('Move Up')
        act_dn = menu.addAction('Move Down')
        menu.addSeparator()
        act_del = menu.addAction('Delete')

        act_cut.setEnabled(has_sel)
        act_copy.setEnabled(has_sel)
        act_paste.setEnabled(has_clip)
        act_up.setEnabled(is_single and sel_rows[0] > 0)
        act_dn.setEnabled(
            is_single and sel_rows[0] < len(self._board.feeders) - 1)
        act_del.setEnabled(has_sel)

        def _do_copy():
            self._copy_feeders(sel_rows, cut=False)

        def _do_cut():
            self._copy_feeders(sel_rows, cut=True)

        def _do_paste():
            self._paste_feeders(sel_rows)

        act_copy.triggered.connect(_do_copy)
        act_cut.triggered.connect(_do_cut)
        act_paste.triggered.connect(_do_paste)
        act_up.triggered.connect(lambda: self._move(-1))
        act_dn.triggered.connect(lambda: self._move(1))
        act_del.triggered.connect(self._del_row)

        global_pos = self._grid_viewport.mapToGlobal(pos)
        menu.popup(global_pos)

    def _copy_feeders(self, rows: list, cut: bool):
        feeders = self._board.feeders
        to_copy = [feeders[r] for r in rows
                   if r < len(feeders) and feeders[r].load_type != 'SubPanel']
        if not to_copy:
            return
        self._feeder_clipboard = [copy.deepcopy(f) for f in to_copy]
        if cut:
            # Remove in reverse order to keep indices valid
            for r in sorted(rows, reverse=True):
                if r < len(feeders) and feeders[r].load_type != 'SubPanel':
                    feeders.pop(r)
            self._fill_grid()
            self._upd_totals()

    def _paste_feeders(self, sel_rows: list):
        if not self._feeder_clipboard:
            return
        b = self._board
        if sel_rows:
            insert_after = sel_rows[-1]
        elif b.feeders:
            insert_after = len(b.feeders) - 1
        else:
            insert_after = -1
        insert_pos = insert_after + 1
        for i, src in enumerate(self._feeder_clipboard):
            new_f = copy.deepcopy(src)
            # Make name unique by appending a suffix
            existing_names = {f.name for f in b.feeders}
            base = new_f.name
            candidate = base
            n = 1
            while candidate in existing_names:
                n += 1
                candidate = f'{base} ({n})'
            new_f.name = candidate
            new_f.voltage   = b.voltage
            new_f.phases    = b.phases
            new_f.frequency = b.frequency
            b.feeders.insert(insert_pos + i, new_f)
            existing_names.add(candidate)
        self._fill_grid()
        self._upd_totals()
        self._full_timer.start()
        # Select the pasted rows
        self._tbl.clearSelection()
        for i in range(len(self._feeder_clipboard)):
            self._tbl.selectRow(insert_pos + i)

    def _on_rows_moved(self, parent, start, end, dest_parent, dest_row):
        """Sync feeder list order after drag-drop row reorder."""
        # Rebuild feeder list order from current table visual order
        b = self._board
        new_order = []
        for ri in range(self._tbl.rowCount()):
            item = self._tbl.item(ri, 1)  # Load Name col
            if item:
                name = item.text()
                for f in b.feeders:
                    if f.name == name and f not in new_order:
                        new_order.append(f); break
        if len(new_order) == len(b.feeders):
            b.feeders = new_order
        self._fill_grid()

    def _on_row_sel(self):
        self._end_grid_edit()
        rows = self._tbl.selectionModel().selectedRows()
        if not rows:
            self._sync_primary_props()
            return
        row = rows[0].row()
        if row < 0 or row >= len(self._board.feeders):
            self._sync_primary_props()
            return
        self._sync_props(self._board.feeders[row])

    # ── P/S/PF AUTO-DERIVE ────────────────────────────────────────────────────
    def _derive_psf(self, f, changed: str):
        """Derive the third of P/S/PF from whichever two are set."""
        P, S, PF = f.P, f.S, f.PF
        try:
            if changed == 'P':
                if PF and PF > 0: f.S = round(P / PF, 3)
                elif S and S > 0: f.PF = round(P / S, 3)
            elif changed == 'S':
                if PF and PF > 0: f.P = round(S * PF, 3)
                elif P and P > 0: f.PF = round(P / S, 3)
            elif changed == 'PF':
                if P and P > 0: f.S = round(P / PF, 3)
                elif S and S > 0: f.P = round(S * PF, 3)
        except (ZeroDivisionError, TypeError):
            pass

    # ── PROPERTIES SYNC ───────────────────────────────────────────────────────
    def _update_cb_visibility(self, cb_type: str, load_type: str = 'Other'):
        """Show/hide CB property controls based on CB type."""
        is_mcb  = cb_type == 'MCB'
        is_mccb = cb_type == 'MCCB'
        # Family (MCCB / ACB only — MCB has no adjustable trip unit family)
        self._cb_family_lbl.setVisible(not is_mcb)
        self._pCBFamily.setVisible(not is_mcb)
        # Curve B/C/D (MCB only)
        self._cb_curve_lbl.setVisible(is_mcb)
        self._pTripCurve.setVisible(is_mcb)
        # Row B: Ir / Isd / tsd / Relay — hidden entirely for MCB
        self._cb_row_b.setVisible(not is_mcb)
        if not is_mcb:
            # Overload relay only relevant for MCCB (ACB has built-in motor protection)
            self._pOverloadRelay.setVisible(is_mccb)
            self._pRelaySetting.setVisible(is_mccb)

    def _sync_primary_props(self):
        """Show primary feeder data in properties panel when no row selected."""
        self._end_grid_edit()
        self._set_motor_props_mode(False)
        self._props_mode = 'primary'
        b  = self._board
        pf = b.primary_feeder
        self._busy = True
        # Board P/S are derived from assigned loads — PF editable on incomer
        for w in (self._pP, self._pS):
            w.setEnabled(False)
        self._pPF.setEnabled(True)
        # Load properties — board totals (single source of truth)
        self._pName.setText(b.name)
        self._pRef.setText('INC')
        self._pS.setValue(round(b.total_S_kVA, 2))
        self._pPF.setValue(b.composite_PF)
        self._pP.setValue(
            round(b.total_S_kVA * b.composite_PF, 2) if b.total_S_kVA else 0)
        self._pL.setValue(pf.cable_length)
        self._pVD.setValue(pf.max_vdrop_pct)
        if pf.vd_user_override:
            self._pVD.setToolTip('User voltage-drop limit for this incomer.')
        else:
            self._pVD.setToolTip(
                'Max voltage drop % for this incomer — category default applies '
                'until edited.')
        self._update_vd_ui()
        self._pPh.setCurrentText('L123')
        self._pType.setCurrentText('Other')
        self._busy = True
        for _i in range(self._pIcuCB.count()):
            if self._pIcuCB.itemData(_i) == int(pf.cb.Icu_kA):
                self._pIcuCB.setCurrentIndex(_i); break
        self._busy = False
        self._fill_code_cb(pf)
        rec = pf.cable.recommended
        np_pf = getattr(pf.cable, 'parallel_cables', 1)
        self._pSize.setText(
            (f'{np_pf}×{rec.size_mm2}mm²' if np_pf > 1
             else f'{rec.size_mm2}mm²') if rec else '—')
        self._pIz.setText(f'{pf.Iz:.1f}' if pf.Iz else '—')
        self._pVdrop.setText(f'{pf.result_vdrop_pct:.3f}%' if pf.result_vdrop_pct else '—')
        self._style_vd_field(
            self._pVdrop, pf.result_vdrop_pct,
            pf.cable.passes_vdrop if rec else True)
        self._pCBLbl.setText(
            f'CB:  {pf.cb.In_CB:.0f}A  {pf.cb.cb_type}  {pf.cb.poles}P  Icu={pf.cb.Icu_kA}kA'
            if pf.cb.In_CB else 'CB: —')
        # ── CB sizing mode toggle (primary feeder) ──
        _pf_manual = bool(pf.user_locked_cb)
        for _btn in (self._pCBBtnAuto, self._pCBBtnManual):
            _btn.blockSignals(True)
        self._pCBBtnAuto.setChecked(not _pf_manual)
        self._pCBBtnManual.setChecked(_pf_manual)
        for _btn in (self._pCBBtnAuto, self._pCBBtnManual):
            _btn.blockSignals(False)
        self._pCBOverride.setVisible(_pf_manual)
        self._pIcuLbl.setVisible(_pf_manual)
        self._pIcuCB.setVisible(_pf_manual)

        # ── CB detail fields — must be populated so widgets write to the right CB ──
        self._pTripCurve.setCurrentText(pf.cb.trip_curve)
        self._pIr.setValue(pf.cb.Ir_mult)
        self._pIsd.setValue(pf.cb.Isd_mult)
        self._pTsd.setValue(pf.cb.tsd_s)
        self._pOverloadRelay.setChecked(pf.cb.overload_relay)
        self._pRelaySetting.setValue(pf.cb.relay_setting)
        idx_fam = CB_FAMILIES.index(pf.cb.cb_family) if pf.cb.cb_family in CB_FAMILIES else 0
        self._pCBFamily.setCurrentIndex(idx_fam)
        self._p4P.setVisible(pf.phases == 3)
        self._p4P.setChecked(pf.cb.poles == 4)
        # Coordination note
        coord_txt = ''
        if pf.cb.In_CB > 0 and pf.cb.cb_type != 'MCB':
            coord_txt = (f'Ir={pf.cb.Ir_A:.0f}A  Isd={pf.cb.Isd_A:.0f}A  '
                         f'tsd={pf.cb.tsd_s:.2f}s  Ii={pf.cb.Ii_A:.0f}A')
        self._pCoordLbl.setText(coord_txt)
        self._update_cb_visibility(pf.cb.cb_type)
        if pf.Ib > 0:
            ok = pf.passes_all
            self._pStat.setText(
                f'Primary: Ib={pf.Ib:.1f}A  |  '
                f'{"✔  OK" if ok else "⚠  " + (pf.warnings[0][:60] if pf.warnings else "Check")}')
            self._pStat.setStyleSheet(
                f'color:{"#107c10" if ok else "#c42b1c"};font-weight:bold;font-size:8pt;')
        else:
            self._pStat.setText(
                f'Board load: Ib={b.total_Ib:.1f}A  |  Select cable then press Select & Calculate')
            self._pStat.setStyleSheet('color:#0078d4;font-size:8pt;font-style:italic;')

        # Primary feeder — Select Cable always available
        self._show_standard_props_panel()
        self._pSelBtn.setText('Select Cable')
        self._pSelBtn.setEnabled(True)
        self._pSelBtn.setToolTip(
            'Select primary incomer cable for this board')
        self._busy = False

    def _sync_props(self, f):
        self._end_grid_edit()
        is_sp = f.load_type == 'SubPanel'
        is_space = f.load_type == 'Space'
        if not is_sp and not is_space:
            self._sync_motor_feeder_power(f)
        self._props_mode = 'feeder'
        is_motor = f.load_type == 'Motor' and not is_sp and not is_space
        self._set_motor_props_mode(is_motor)
        # SubPanel P/S/PF come from the child board's computed totals — read-only
        for w in (self._pP, self._pS, self._pPF):
            w.setEnabled(not is_sp and not is_motor)
        self._pSelBtn.setText('Select Cable')
        self._pSelBtn.setEnabled(not is_sp and not is_space)
        self._pSelBtn.setToolTip(
            'Cable configured inside the child board — double-click to navigate'
            if is_sp else
            'Space circuit — no cable required'
            if is_space else
            'Open Cable Selector — choose type/installation/k-factors,\n'
            'press Proceed, then calculation runs automatically')
        self._busy = True
        if not is_motor:
            self._pName.setText(f.name)
            self._pRef.setText(f.circuit_ref)
            self._pP.setValue(f.P or 0)
            S_val = f.S or ((f.P / f.PF) if f.P and f.PF else 0)
            self._pS.setValue(round(S_val, 3))
            self._pPF.setValue(f.PF or 0.9)
            self._pL.setValue(f.cable_length)
            self._pVD.setValue(f.max_vdrop_pct)
            if f.vd_user_override:
                self._pVD.setToolTip('User voltage-drop limit for this circuit.')
            else:
                lim = self._vd_limit_for_feeder(f)
                self._pVD.setToolTip(
                    f'Category default {lim:g}% ({f.load_type}) — edit to override.')
            self._update_vd_ui()
            idx = PHASES.index(f.phase_str) if f.phase_str in PHASES else 0
            self._pPh.setCurrentIndex(idx)
            idx2 = LOAD_TYPES.index(f.load_type) if f.load_type in LOAD_TYPES else 0
            self._pType.setCurrentIndex(idx2)
            self._pDF.setValue(int(round(f.demand_factor_pct)))
            self._pDF.setEnabled(
                self._df_mode == 'per_load'
                and f.load_type not in ('SubPanel', 'Space', 'Spare'))
            for _i in range(self._pIcuCB.count()):
                if self._pIcuCB.itemData(_i) == int(f.cb.Icu_kA):
                    self._pIcuCB.setCurrentIndex(_i); break
        self._busy = False
        self._fill_code_cb(f)
        rec = f.cable.recommended
        n_par = getattr(f.cable, 'parallel_cables', 1)
        self._pSize.setText(
            (f'{n_par}×{rec.size_mm2}mm²' if n_par > 1
             else f'{rec.size_mm2}mm²') if rec else '—')
        # Results
        self._pIz.setText(f'{f.Iz:.1f}' if f.Iz else '—')
        self._pVdrop.setText(f'{f.result_vdrop_pct:.3f}%' if f.result_vdrop_pct else '—')
        self._style_vd_field(
            self._pVdrop, f.result_vdrop_pct,
            f.cable.passes_vdrop if rec else True)
        if not is_motor:
            self._busy = True
            self._pTripCurve.setCurrentText(f.cb.trip_curve)
            self._pIr.setValue(f.cb.Ir_mult)
            self._pIsd.setValue(f.cb.Isd_mult)
            self._pTsd.setValue(f.cb.tsd_s)
            self._pOverloadRelay.setChecked(f.cb.overload_relay)
            self._pRelaySetting.setValue(f.cb.relay_setting)
            idx_fam = (CB_FAMILIES.index(f.cb.cb_family)
                       if f.cb.cb_family in CB_FAMILIES else 0)
            self._pCBFamily.setCurrentIndex(idx_fam)
            self._p4P.setVisible(f.phases == 3)
            self._p4P.setChecked(f.cb.poles == 4)
            self._update_cb_visibility(f.cb.cb_type, f.load_type)
            coord_txt = ''
            if f.cb.In_CB > 0:
                if f.cb.cb_type == 'MCB':
                    coord_txt = f'Im = {f.cb.Im_A:.0f} A  (×{f.cb.Im_mult:.0f})'
                else:
                    coord_txt = (f'Ir={f.cb.Ir_A:.0f}A  Isd={f.cb.Isd_A:.0f}A  '
                                 f'tsd={f.cb.tsd_s:.2f}s  Ii={f.cb.Ii_A:.0f}A')
                if f.cb.overload_relay and f.cb.cb_type == 'MCCB':
                    coord_txt += f'  | Relay={f.cb.relay_setting:.2f}×Ib'
                if f.cb.coordination_notes:
                    coord_txt += '  |  '.join(f.cb.coordination_notes[:2])
            self._pCoordLbl.setText(coord_txt)
            self._pCoordLbl.setToolTip('; '.join(f.cb.coordination_notes))
            self._busy = False

        k_par = getattr(f.cable, 'k_parallel', 1.0)
        par_txt = (f'  |  ({n_par}) sets  k_par={k_par:.2f}'
                   if n_par > 1 else '')
        self._pCode.setToolTip(
            f'({n_par}) sets of {rec.size_mm2}mm²  {rec.cable_code}{par_txt}'
            if rec and n_par > 1 else '')
        if not is_motor:
            self._pCBLbl.setText(
                f'CB:  {f.cb.In_CB:.0f}A  {f.cb.cb_type}  {f.cb.poles}P  Icu={f.cb.Icu_kA}kA'
                f'{par_txt}'
                if f.cb.In_CB else 'CB: —')
        if f.Ib > 0:
            ok = f.passes_all
            warns = f.warnings + f.cable.warnings + f.cb.warnings
            warns = list(dict.fromkeys(w for w in warns if w))
            if ok:
                self._pStat.setText(f'Ib = {f.Ib:.1f} A  |  ✔  All checks passed')
                self._pStat.setStyleSheet(
                    'color:#107c10;font-weight:bold;font-size:8pt;')
            elif warns:
                self._pStat.setText(f'⚠  {warns[0]}')
                self._pStat.setStyleSheet(
                    'color:#c42b1c;font-size:8pt;font-weight:bold;')
                self._pStat.setWordWrap(True)
            else:
                self._pStat.setText(f'Ib = {f.Ib:.1f} A  |  ✘  Check failed')
                self._pStat.setStyleSheet(
                    'color:#c42b1c;font-weight:bold;font-size:8pt;')
        else:
            self._pStat.setText('Select cable, enter P/cosφ, then press Select & Calculate')
            self._pStat.setStyleSheet('color:#888;font-size:8pt;font-style:italic;')
        self._busy = False
        if is_motor:
            row = self._tbl.currentRow()
            if row < 0 or row >= len(self._board.feeders):
                for i, bf in enumerate(self._board.feeders):
                    if bf is f:
                        row = i
                        break
            if row >= 0:
                self._motor_sizing.bind_feeder(f, row, self._board)

    def _style_vd_field(self, field, pct: float, passes: bool) -> None:
        ok_ss = ('background:#f0f0f0;color:#5c2d91;font-weight:bold;'
                 'border:1px solid #d0d0d0;padding:2px 4px;'
                 'font-family:"Courier New";font-size:9pt;')
        fail_ss = ('background:#ffe0e0;color:#8b0000;font-weight:bold;'
                   'border:1px solid #e09090;padding:2px 4px;'
                   'font-family:"Courier New";font-size:9pt;')
        field.setStyleSheet(
            fail_ss if pct and not passes else ok_ss)

    def _fill_code_cb(self, f):
        self._pCode.blockSignals(True)
        self._pCode.clear()
        if f.cable.conductor_table:
            for row in f.cable.conductor_table:
                self._pCode.addItem(row.cable_code, userData=row.cable_code)
            rec = f.cable.recommended
            if rec:
                matched = False
                for i in range(self._pCode.count()):
                    if self._pCode.itemData(i) == rec.cable_code:
                        self._pCode.setCurrentIndex(i)
                        matched = True
                        break
                if not matched:
                    # Fallback: select by size when cable_code is stale
                    for i, row in enumerate(f.cable.conductor_table):
                        if row.size_mm2 == rec.size_mm2:
                            self._pCode.setCurrentIndex(i)
                            break
        else:
            self._pCode.addItem('— press "Select & Calculate" —')
        self._pCode.blockSignals(False)

        # CB sizing mode toggle + size/Icu pickers
        # blockSignals prevents setChecked from firing _cb_set_mode via clicked
        is_manual = bool(f.user_locked_cb)
        for _btn in (self._pCBBtnAuto, self._pCBBtnManual):
            _btn.blockSignals(True)
        self._pCBBtnAuto.setChecked(not is_manual)
        self._pCBBtnManual.setChecked(is_manual)
        for _btn in (self._pCBBtnAuto, self._pCBBtnManual):
            _btn.blockSignals(False)
        self._pCBOverride.setVisible(is_manual)
        self._pIcuLbl.setVisible(is_manual)
        self._pIcuCB.setVisible(is_manual)
        self._pCBOverride.blockSignals(True)
        self._pCBOverride.clear()
        from cb_class import IEC_MCB_SIZES, IEC_MCCB_SIZES, IEC_ACB_SIZES
        for sz in IEC_MCB_SIZES + IEC_MCCB_SIZES + IEC_ACB_SIZES:
            self._pCBOverride.addItem(f'{int(sz)} A', userData=sz)
        if f.cb.In_CB > 0:
            for i in range(self._pCBOverride.count()):
                if self._pCBOverride.itemData(i) == f.cb.In_CB:
                    self._pCBOverride.setCurrentIndex(i); break
        self._pCBOverride.blockSignals(False)

    # ── PROPERTY CHANGE HANDLERS ──────────────────────────────────────────────
    def _psf_changed(self, which, val):
        """Handle P, S, or PF change in properties panel — derive third."""
        if self._busy:
            return
        if self._props_mode == 'primary':
            b = self._board
            if which == 'PF':
                b.composite_pf_override = val
                self._busy = True
                self._pP.setValue(
                    round(b.total_S_kVA * val, 2) if b.total_S_kVA else 0)
                self._busy = False
                self._full_timer.start()
            return
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders): return
        f = self._board.feeders[row]

        if which == 'P':  f.P  = val
        elif which == 'S': f.S  = val
        elif which == 'PF': f.PF = val

        self._derive_psf(f, which)

        # Update the derived field display without triggering recursion
        self._busy = True
        if which == 'P' or which == 'PF':
            S_val = f.S or 0
            self._pS.setValue(round(S_val, 3))
        if which == 'S' or which == 'PF':
            self._pP.setValue(f.P or 0)
        if which == 'P' or which == 'S':
            self._pPF.setValue(f.PF or 0.9)
        self._busy = False

        self._refresh_row(row)
        # P/S/PF change → total_Ib changes → primary feeder + actual_voltage_V
        # must be recalculated. Use full recalc timer.
        self._full_timer.start()

    def _pset(self, attr, val):
        if self._busy: return
        row = self._tbl.currentRow()
        # Primary feeder mode when no row selected
        if row < 0 or row >= len(self._board.feeders):
            pf = self._board.primary_feeder
            if attr == 'name':
                self._board.name = val
                self._update_header()
                item = self._find_ti(self._board.board_id)
                if item:
                    ico = '🔌' if self._board.level == 0 else '⚡'
                    item.setText(0, f'{ico}  {val}')
                # Keep parent feeder name in sync
                if self._board.parent_id:
                    parent = self._root.find_board(self._board.parent_id)
                    if parent:
                        for f in parent.feeders:
                            if f.subpanel_id == self._board.board_id:
                                f.name = val
                                break
            elif attr == 'cable_length':
                pf.cable_length = val
                pf.cable.cable_length = val
            elif attr == 'max_vdrop_pct':
                pf.max_vdrop_pct = val
                pf.vd_user_override = True
                pf.cable.max_vdrop_pct = val
            else:
                return  # other attrs not applicable to primary feeder
            if attr != 'name':
                # Primary feeder change shifts actual_voltage_V for all downstream
                # feeders → needs full recalc from root.
                self._full_timer.start()
            return
        f = self._board.feeders[row]
        setattr(f, attr, val)
        if attr == 'cable_length':
            f.cable.cable_length = val
        if attr == 'max_vdrop_pct':
            f.vd_user_override = True
            f.cable.max_vdrop_pct = val
        # Cascade name change to child board and tree
        if attr == 'name' and f.load_type == 'SubPanel' and f.subpanel_id:
            child = self._root.find_board(f.subpanel_id)
            if child:
                child.name = val
                self._reload_tree()
                # Re-select current board in tree
                item = self._find_ti(self._board.board_id)
                if item:
                    self._tree.blockSignals(True)
                    self._tree.setCurrentItem(item)
                    self._tree.blockSignals(False)
        self._refresh_row(row)
        # phase_str changes Ib formula → full recalc
        if attr == 'phase_str':
            self._full_timer.start()
        elif attr in ('cable_length', 'max_vdrop_pct'):
            self._full_timer.start()
        else:
            self._timer.start()

    def _pset_cb(self, attr, val):
        if self._busy: return
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            # Primary feeder — only Icu_kA is meaningful here (not diversity)
            if attr == 'Icu_kA':
                self._board.primary_feeder.cb.Icu_kA = val
            return
        setattr(self._board.feeders[row].cb, attr, val)
        self._timer.start()

    def _apply_load_type_from_grid(self, row: int, new_type: str):
        """Grid Type column — Motor / Light / Other / …"""
        self._end_grid_edit()
        if self._busy:
            return
        if row < 0 or row >= len(self._board.feeders):
            return
        f = self._board.feeders[row]
        if f.load_type in ('SubPanel', 'Space', 'Spare'):
            return
        if new_type not in GRID_LOAD_TYPES:
            return
        if f.load_type == new_type:
            return
        self._busy = True
        f.load_type = new_type
        f.cb.apply_load_type_defaults(new_type)
        if not feeder_vdrop_user_locked(f):
            apply_vdrop_limit_to_feeder(f, self._vd_settings, force=True)
        if new_type == 'Motor':
            f.motor.ensure_default_profile()
        elif new_type != 'Motor':
            f.motor_configured = False
        self._busy = False
        self._refresh_row(row)
        self._sync_props(f)
        self._full_timer.start()

    def _type_changed(self, t):
        if self._busy: return
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders): return
        self._apply_load_type_from_grid(row, t)

    def _relay_changed(self, state):
        """Toggle overload relay and show/hide relay setting."""
        if self._busy: return
        enabled = bool(state)
        self._pRelaySetting.setEnabled(enabled)
        self._cb_attr_changed('overload_relay', enabled)

    def _icu_cb_changed(self, _idx):
        """User selected a new Icu value from the CB section dropdown."""
        if self._busy: return
        val = self._pIcuCB.currentData()
        if val is None: return
        self._cb_attr_changed('Icu_kA', float(val))

    def _4p_changed(self, state):
        """Toggle 4P override for 3-phase CBs (e.g. generator circuits)."""
        if self._busy: return
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            pf = self._board.primary_feeder
            if pf.phases == 3:
                pf.cb.poles = 4 if bool(state) else 3
                pf.has_neutral = bool(state)
                self._sync_primary_props()
            return
        f = self._board.feeders[row]
        if f.phases == 3:
            f.cb.poles = 4 if bool(state) else 3
            f.has_neutral = bool(state)
            self._refresh_row(row)
            self._pCBLbl.setText(
                f'CB:  {f.cb.In_CB:.0f}A  {f.cb.cb_type}  {f.cb.poles}P  Icu={f.cb.Icu_kA}kA'
                if f.cb.In_CB else 'CB: —')

    def _cb_attr_changed(self, attr, val):
        """Handle CB settings change from properties panel."""
        if self._busy: return
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            # Primary feeder — apply directly to pf.cb
            pf = self._board.primary_feeder
            setattr(pf.cb, attr, val)
            if pf.cb.In_CB > 0:
                pf.cb._calc_trip_settings()
            self._sync_primary_props()
            return
        f = self._board.feeders[row]
        setattr(f.cb, attr, val)

        # If CB family changed — recalculate conductor to satisfy new CB constraint
        if attr == 'cb_family' and f.cable.conductor_table:
            f._user_locked_conductor = False
            self._do_calc(f)
            self._refresh_row(row)
            self._sync_props(f)
            self._upd_totals()
            return

        # Recalculate derived trip settings
        if f.cb.In_CB > 0:
            f.cb._calc_trip_settings()
        self._refresh_row(row)
        self._sync_props(f)

    def _cb_set_mode(self, manual: bool):
        """Toggle Auto / Manual CB sizing for the selected feeder."""
        if self._busy: return
        self._pCBBtnAuto.setChecked(not manual)
        self._pCBBtnManual.setChecked(manual)
        self._pCBOverride.setVisible(manual)
        self._pIcuLbl.setVisible(manual)
        self._pIcuCB.setVisible(manual)
        if not manual:
            # Switching back to Auto — unlock and recalculate
            row = self._tbl.currentRow()
            if row < 0 or row >= len(self._board.feeders):
                self._board.primary_feeder.user_locked_cb = False
                self._full_timer.start()
            else:
                f = self._board.feeders[row]
                f.user_locked_cb = False
                if f.cable.conductor_table:
                    self._do_calc(f)
                self._refresh_row(row)
                self._sync_props(f)
                self._upd_totals()

    def _cb_override_changed(self, _idx):
        """User selected a CB size in Manual mode."""
        if self._busy: return
        if not self._pCBBtnManual.isChecked(): return
        row = self._tbl.currentRow()
        sz  = self._pCBOverride.currentData()
        if not sz: return
        if row < 0 or row >= len(self._board.feeders):
            pf = self._board.primary_feeder
            pf.cb.In_CB      = float(sz)
            pf.user_locked_cb = True
            self._full_timer.start()
            return
        f = self._board.feeders[row]
        f.cb.In_CB       = float(sz)
        f.user_locked_cb = True
        f._user_locked_conductor = False
        if f.cable.conductor_table:
            self._do_calc(f)
        self._refresh_row(row)
        self._sync_props(f)
        self._upd_totals()

    def _code_changed(self, text):
        if self._busy: return
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders): return
        f = self._board.feeders[row]
        code = self._pCode.currentData() or (text.split()[-1] if text.split() else '')
        self._apply_code(f, code)
        f.cable.manual_sizing = True
        f._user_locked_conductor = True
        self._refresh_row(row)
        self._sync_props(f)
        self._upd_totals()

    def _apply_code(self, f, code):
        """Apply conductor by code and recalculate Iz, Vdrop, CB with new conductor."""
        for r in f.cable.conductor_table:
            if r.cable_code == code or code in r.cable_code:
                f.cable.recommended = r
                # Recalculate Iz, Vdrop, CB with this specific conductor
                if f.Ib > 0:
                    import math
                    c = f.cable
                    k2_row = c._k2_for_size(r.size_mm2)
                    k_row  = round(c.k1 * k2_row * c.k3, 4)
                    f.Iz   = round(r.In * k_row, 2)
                    # Vdrop
                    vd_v, vd_pct, _ = c._vdrop(r, f.Ib)
                    r.Iz        = f.Iz
                    r.vdrop_v   = vd_v
                    r.vdrop_pct = vd_pct
                    r.passes_amp   = f.Iz >= f.Ib
                    r.passes_vdrop = vd_pct <= f.max_vdrop_pct
                    f.result_vdrop_v   = vd_v
                    f.result_vdrop_pct = vd_pct
                    f.cable.passes_ampacity = r.passes_amp
                    f.cable.passes_vdrop    = r.passes_vdrop
                    # Resize CB with new Iz
                    f.cb.size_cb(f.Ib, f.Iz, f.Isc_board_kA)
                    f.passes_all = (r.passes_amp and r.passes_vdrop and
                                    f.cb.passes_protection and f.cb.passes_Isc)
                break

    # ── AUTO CALC ─────────────────────────────────────────────────────────────
    def _calc_row(self):
        """Tier-1: recalculate only the currently selected feeder row."""
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders): return
        f = self._board.feeders[row]
        self._do_calc(f)
        self._refresh_row(row)
        self._sync_props(f)
        self._upd_totals()
        self._sync_sp_up()
        self._refresh_status_messages(
            f'Row {row + 1} recalculated — {f.name or f.circuit_ref}')

    def _calc_full(self, toolbar=False):
        """Tier-2: full recursive recalc from root board downward.
        Triggered when a change affects total_Ib, actual_voltage_V,
        or the primary feeder (load, phase, primary feeder cable props).
        Also called by the Calc All toolbar button.
        """
        import time
        t0 = time.perf_counter()
        self._root.calculate_all(
            self._min_conductor_mm2, self._min_cb_A,
            self._df_mode, self._project_df_pct,
            self._vd_settings)
        elapsed = (time.perf_counter() - t0) * 1000
        self._update_vd_ui()
        # Refresh current board view
        self._fill_grid()
        self._upd_totals()
        self._update_header()
        # Re-sync props panel — use _props_mode, not currentRow(), because
        # clearCurrentIndex() leaves currentRow() == -1 even in primary mode.
        row = self._tbl.currentRow()
        if self._props_mode == 'primary':
            self._sync_primary_props()
        elif row >= 0 and row < len(self._board.feeders):
            self._sync_props(self._board.feeders[row])
        else:
            self._sync_primary_props()
        n_boards  = len(self._root.all_boards())
        n_feeders = sum(len(b.feeders) for b in self._root.all_boards())
        src = "Calc All" if toolbar else "auto"
        self._refresh_status_messages(
            f'[{src}] Full recalc: {n_boards} boards, {n_feeders} feeders '
            f'— {elapsed:.0f}ms  |  '
            f'Isc={self._board.Isc_board_kA:.2f}kA  '
            f'Ib={self._board.total_Ib:.1f}A')

    def _do_calc(self, f):
        if f.load_type == 'Space': return  # Space rows have no CB/cable
        if not f.P and not f.S: return
        if not f.S and f.P and f.PF:
            f.S = round(f.P / f.PF, 3)
        _ph_count = {'L123': 3, 'L12': 2, 'L13': 2, 'L23': 2,
                     'L1': 1, 'L2': 1, 'L3': 1}
        f.cable.phases        = _ph_count.get(f.phase_str, 3)
        f.cable.frequency     = self._board.frequency
        f.frequency           = self._board.frequency
        # Use actual busbar voltage (reduced by upstream drops) as Vdrop base.
        # L1/L2/L3 are phase-to-neutral circuits — use phase voltage (Vline/√3).
        # L12/L13/L23 are line-to-line and L123 is 3-phase — use line voltage.
        actual_V = getattr(self._board, 'actual_voltage_V', self._board.voltage)
        import math as _math
        phase_V = (actual_V / _math.sqrt(3)
                   if f.phase_str in ('L1', 'L2', 'L3') else actual_V)
        f.cable.voltage       = phase_V
        f.cable.cable_length  = f.cable_length
        f.cable.max_vdrop_pct = f.max_vdrop_pct
        f.cable.PF            = f.PF          # keep PF in sync for _vdrop
        f.phases  = f.cable.phases
        f.voltage = phase_V
        locked = getattr(f, '_user_locked_conductor', False)
        # Preserve parallel_cables through recalc
        n_par_saved = getattr(f.cable, 'parallel_cables', 1)
        if not f.cable.ensure_conductor_table():
            return
        if locked and f.cable.recommended:
            # User chose conductor manually — only recalc Iz/CB/Vdrop, skip selection
            rec = f.cable.recommended
            c = f.cable
            # Always recalculate Ib — P/S/voltage may have changed since last run
            if f.phases == 3:
                f.Ib = round((f.S*1000)/(_math.sqrt(3)*f.voltage), 3)
            else:
                f.Ib = round((f.S*1000)/f.voltage, 3)
            k2_row = c._k2_for_size(rec.size_mm2)
            k_row  = round(c.k1 * k2_row * c.k3, 4)
            f.Iz   = round(rec.In * k_row * n_par_saved, 2)
            vd_v, vd_pct, _ = c._vdrop(rec, f.Ib)
            rec.Iz = f.Iz; rec.vdrop_v = vd_v; rec.vdrop_pct = vd_pct
            rec.passes_amp = f.Iz >= f.Ib
            rec.passes_vdrop = vd_pct <= f.max_vdrop_pct
            f.result_vdrop_v = vd_v; f.result_vdrop_pct = vd_pct
            f.passes_vdrop_total = rec.passes_vdrop
            c.passes_ampacity = rec.passes_amp; c.passes_vdrop = rec.passes_vdrop
            f.cb.size_cb(f.Ib, f.Iz, self._board.Isc_board_kA)
            f.passes_all = (
                rec.passes_amp and rec.passes_vdrop and f.cb.passes_protection)
        else:
            # Ensure parallel_cables is set before calculate
            f.cable.parallel_cables = n_par_saved
            f.calculate(self._board.Isc_board_kA)

        # Run coordination check vs board main CB (upstream)
        main_cb = self._board.main_cb
        if main_cb and main_cb.In_CB > 0:
            f.cb.check_coordination(main_cb, self._board.Isc_board_kA)

    def _balance_phases(self):
        """
        LDM (Largest Differencing Method) Phase Balancing.
        Reorders feeders and assigns phases to minimise L1/L2/L3 imbalance.
        Algorithm:
          1. Sort all feeders by kVA descending
          2. For each feeder, assign to phase combination that minimises total imbalance
          3. 3-phase → always L123 (adds kVA/3 to each phase)
          4. 2-phase → assign to the two least-loaded phases
          5. 1-phase → assign to least-loaded single phase
        """
        from PySide6.QtWidgets import QMessageBox
        b = self._board
        feeders = [f for f in b.feeders if f.load_type != 'SubPanel']
        subpanels = [f for f in b.feeders if f.load_type == 'SubPanel']

        if not feeders:
            QMessageBox.information(self, 'Balance', 'No feeders to balance.')
            return

        # Sort by kVA descending
        feeders.sort(key=lambda f: (f.S or (f.P/f.PF if f.P and f.PF else 0)),
                     reverse=True)

        # Phase load tracker
        phase_load = {'L1': 0.0, 'L2': 0.0, 'L3': 0.0}

        def add_load(phase_str, kva):
            ph_map = {'L123': ['L1','L2','L3'],
                      'L12':  ['L1','L2'], 'L13': ['L1','L3'], 'L23': ['L2','L3'],
                      'L1':   ['L1'],      'L2':  ['L2'],       'L3':  ['L3']}
            phases = ph_map.get(phase_str, ['L1'])
            per_ph = kva / len(phases)
            for p in phases:
                phase_load[p] += per_ph

        def assign_phase(n_phases, kva):
            """Return best phase string for n_phases load."""
            if n_phases == 3:
                return 'L123'
            # Try all combinations for n_phases
            if n_phases == 2:
                combos = [('L12',['L1','L2']), ('L13',['L1','L3']), ('L23',['L2','L3'])]
            else:
                combos = [('L1',['L1']), ('L2',['L2']), ('L3',['L3'])]
            # Pick combo that minimises max-min after assignment
            best_ph = None; best_imbal = float('inf')
            for ph_str, phases in combos:
                per_ph = kva / len(phases)
                tmp = dict(phase_load)
                for p in phases: tmp[p] += per_ph
                imbal = max(tmp.values()) - min(tmp.values())
                if imbal < best_imbal:
                    best_imbal = imbal
                    best_ph = ph_str
            return best_ph

        # Assign phases
        for f in feeders:
            kva = f.S or (f.P/f.PF if f.P and f.PF else 0)
            orig_ph = f.phase_str
            ph_n = {'L123':3,'L12':2,'L13':2,'L23':2,'L1':1,'L2':1,'L3':1}.get(orig_ph,1)
            new_ph = assign_phase(ph_n, kva)
            f.phase_str = new_ph
            add_load(new_ph, kva)

        # Rebuild feeder list: 3-phase first, then 2-phase, then 1-phase, then subpanels
        def ph_order(f):
            n = {'L123':0,'L12':1,'L13':1,'L23':1,'L1':2,'L2':2,'L3':2}.get(f.phase_str,3)
            return (n, -(f.S or 0))
        feeders.sort(key=ph_order)
        b.feeders = feeders + subpanels

        # Show result
        l1 = phase_load['L1']; l2 = phase_load['L2']; l3 = phase_load['L3']
        imbal = max(l1,l2,l3) - min(l1,l2,l3)
        imbal_pct = imbal / max(l1,l2,l3) * 100 if max(l1,l2,l3) > 0 else 0

        self._fill_grid()
        self._upd_totals()
        self._refresh_status_messages(
            f'Phase balanced — L1={l1:.1f}kVA  L2={l2:.1f}kVA  L3={l3:.1f}kVA  '
            f'Imbalance={imbal_pct:.1f}%')

    def _calc_host(self):
        """Ribbon (or other host) that owns the CALCULATE results page."""
        p = self.parent()
        if p is not None and hasattr(p, '_begin_calc_run'):
            return p
        return None

    def _calc_all(self):
        """Toolbar Calc All — always triggers full root recalc."""
        host = self._calc_host()
        if host:
            host._begin_calc_run()
        self._calc_full(toolbar=True)
        if host:
            host._finish_calc_run()

    def _calc_selected(self):
        """Calculate only currently selected feeder rows."""
        sel_rows = sorted(set(i.row() for i in self._tbl.selectedItems()))
        if not sel_rows:
            QMessageBox.information(self, 'No Selection',
                'Please select one or more feeder rows first.')
            return
        host = self._calc_host()
        if host:
            host._begin_calc_run()
        b = self._board
        # Isc is propagated by calculate_all; use cached value from last full calc

        for ri in sel_rows:
            if ri >= len(b.feeders): continue
            f = b.feeders[ri]
            if f.load_type == 'SubPanel': continue
            f.warnings = []
            f.cable.warnings = []
            f.cb.warnings = []
            if getattr(f, 'motor_configured', False):
                f.motor.warnings = []
            self._do_calc(f)
            self._refresh_row(ri)
        self._upd_totals()
        cur = self._tbl.currentRow()
        if cur >= 0 and cur < len(b.feeders):
            self._sync_props(b.feeders[cur])
        self._refresh_status_messages(
            f'Calculated {len(sel_rows)} selected feeder(s)')
        if host:
            host._finish_calc_run()

    def _gen_spare_space(self):
        """
        Generate Spare (20%) and Space (10%) feeders for ALL boards.
        Runs on every board in the hierarchy. Existing Spare/Space
        are replaced (clean slate). User can delete individual ones after.
        """
        all_boards = self._root.all_boards()
        summary = []
        for b in all_boards:
            n_circuits = len([f for f in b.feeders
                              if f.load_type not in ('Spare', 'Space')])
            b.generate_spare_space()
            n_spare = max(1, round(n_circuits * 0.20))
            n_space = max(1, round(n_circuits * 0.10))
            summary.append(
                f'{b.name}: {n_circuits} circuits → {n_spare} spare + {n_space} space')
        # Refresh current board view
        self._fill_grid()
        self._upd_totals()
        self._refresh_status_messages(
            'Spare/Space generated for all boards. '
            'Delete individual rows in the grid if not needed.')
        # Show summary
        QMessageBox.information(
            self, 'Spare/Space Generated',
            'Generated for all boards:\n\n' + '\n'.join(summary) +
            '\n\nDelete individual Spare/Space rows in the grid if not needed.')

    def apply_vdrop_train_overrides(self, overrides: list) -> int:
        """Apply manual path upsizes from CALCULATE tab; refresh board view."""
        from vdrop_optimizer import apply_vdrop_train_overrides
        n = apply_vdrop_train_overrides(
            self._root, self._vd_settings, overrides,
            self._min_conductor_mm2, self._min_cb_A,
            self._df_mode, self._project_df_pct)
        if n <= 0:
            return 0
        self._fill_grid()
        self._upd_totals()
        self._update_header()
        self._refresh_status_messages(
            f'Applied {n} manual cable override(s) — network recalculated')
        return n

    def _sync_sp_up(self):
        b = self._board
        if not b.parent_id: return
        parent = self._root.find_board(b.parent_id)
        if not parent: return
        for f in parent.feeders:
            if f.subpanel_id == b.board_id:
                f.S  = b.total_S_kVA
                f.PF = b.composite_PF
                f.P  = round(b.total_S_kVA * b.composite_PF, 2)
                f.Ib = b.total_Ib; break

    def set_df_settings(self, df_mode: str, project_df_pct: float):
        self._df_mode = df_mode or 'per_load'
        self._project_df_pct = max(0.0, min(100.0, float(project_df_pct)))
        self._update_df_ui()
        self._full_timer.start()

    def set_vd_settings(self, vd_settings: VdropProjectSettings):
        self._vd_settings = vd_settings or VdropProjectSettings()
        self._update_vd_ui()
        self._full_timer.start()

    def _vd_limit_for_feeder(self, f: C_Feeder) -> float:
        return self._vd_settings.limit_for_load_type(f.load_type)

    def _update_vd_ui(self):
        self._pVD.setEnabled(self._props_mode in ('feeder', 'primary'))
        self._vd_banner.hide()
        row = self._tbl.currentRow()
        if 0 <= row < len(self._board.feeders):
            f = self._board.feeders[row]
            if not feeder_vdrop_user_locked(f):
                apply_vdrop_limit_to_feeder(f, self._vd_settings)

    def _update_df_ui(self):
        per = self._df_mode == 'per_load'
        self._tbl.setColumnHidden(COL_DF, not per)
        self._pDF.setEnabled(per and self._props_mode == 'feeder')
        if hasattr(self, '_motor_sizing'):
            self._motor_sizing.set_df_enabled(
                per and self._motor_sizing.isVisible())
        if (self._board.level == 0 and self._df_mode == 'project'
                and self._project_df_pct < 100):
            self._df_banner.setText(
                f'Project demand factor {self._project_df_pct:.0f}% — '
                f'L0 bus and incomer sized on diversified load '
                f'(feeders still at 100% connected load).')
            self._df_banner.show()
        else:
            self._df_banner.hide()

    def _upd_totals(self):
        b = self._board
        tIb = b.total_Ib
        tS  = b.total_S_kVA
        tP  = round(tS * b.composite_PF, 1) if tS else 0.0
        if b.busbar_A > 0:
            b.busbar_loading = round(tIb / b.busbar_A * 100, 1)

        def s(lbl, txt, warn=False):
            lbl.setText(txt)
            lbl.setStyleSheet(
                f'font-size:9pt;font-weight:bold;'
                f'color:{"#c42b1c" if warn else "#003d8f"};'
                f'font-family:"Courier New";')

        s(self._tP,   f'{tP:.1f}')
        s(self._tS,   f'{tS:.1f}')
        ib_txt = f'{tIb:.1f}'
        if b.project_df_applied and b.total_Ib_connected > tIb:
            ib_txt = f'{tIb:.1f}  ({b.total_Ib_connected:.0f} conn.)'
        s(self._tIb, ib_txt)
        # Busbar % — red if overloaded
        self._tBus.setText(f'{b.busbar_loading:.1f}%')
        self._tBus.setStyleSheet(
            f'font-size:9pt;font-weight:bold;font-family:Courier New;'
            f'color:{"#c42b1c" if b.busbar_loading > 90 else "#003d8f"};')
        s(self._tIsc, f'{b.Isc_board_kA:.2f}')
        self._tCB.setText(f'{b.main_cb.In_CB:.0f}A' if b.main_cb.In_CB else '—')

        # Phase loading
        ph_map = {'L123':['L1','L2','L3'],'L12':['L1','L2'],'L13':['L1','L3'],
                  'L23':['L2','L3'],'L1':['L1'],'L2':['L2'],'L3':['L3']}
        s1 = s2 = s3 = 0.0
        proj_scale = 1.0
        if (b.level == 0 and self._df_mode == 'project'
                and b.project_df_applied):
            proj_scale = b.project_df_pct / 100.0
        for f in b.feeders:
            if self._df_mode == 'per_load' and f.S_demand is not None:
                kva = f.S_demand
            elif self._df_mode == 'per_load':
                kva = (f.S or 0) * f.demand_factor()
            else:
                kva = f.S or ((f.P/f.PF) if f.P and f.PF else 0)
            kva *= proj_scale
            phs = ph_map.get(f.phase_str, ['L1'])
            per = kva / len(phs)
            if 'L1' in phs: s1 += per
            if 'L2' in phs: s2 += per
            if 'L3' in phs: s3 += per
        s(self._tS1, f'{s1:.1f}')
        s(self._tS2, f'{s2:.1f}')
        s(self._tS3, f'{s3:.1f}')

        self._update_header()
        self._upd_primary_feeder()

    def _upd_primary_feeder(self):
        """Refresh primary feeder summary strip in totals bar."""
        b   = self._board
        pf  = b.primary_feeder
        rec = pf.cable.recommended if b.primary_feeder_selected else None

        def sp(lbl, txt, ok=None):
            lbl.setText(txt)
            color = ('#107c10' if ok is True else
                     '#c42b1c' if ok is False else '#107c10')
            lbl.setStyleSheet(
                f'font-size:9pt;font-weight:bold;color:{color};'
                f'font-family:"Courier New";')

        if not b.primary_feeder_selected or b.total_Ib == 0:
            for lbl in [self._pfIb, self._pfCB, self._pfMm2,
                        self._pfCode, self._pfVd]:
                sp(lbl, '—')
            return

        # Use total_Ib (always current) so the Ib cell updates immediately
        # when load changes, without waiting for the primary feeder recalc.
        pf_ib = f'{b.total_Ib:.1f}'
        if b.project_df_applied:
            pf_ib += f'  (DF {b.project_df_pct:.0f}%)'
        sp(self._pfIb, pf_ib)
        sp(self._pfCB,
           f'{pf.cb.In_CB:.0f}A {pf.cb.cb_type}' if pf.cb.In_CB else '—',
           ok=pf.cb.passes_protection and pf.cb.passes_Isc)
        sp(self._pfMm2,
           f'{rec.size_mm2}' if rec else '—',
           ok=pf.cable.passes_ampacity if rec else None)
        sp(self._pfCode,
           rec.cable_code if rec else '—')
        sp(self._pfVd,
           f'{pf.result_vdrop_pct:.2f}%' if pf.result_vdrop_pct else '—',
           ok=pf.cable.passes_vdrop if rec else None)

    # ── CABLE SELECTOR ────────────────────────────────────────────────────────
    def _open_feeder_window(self, f, row):
        """Open feeder detail window for full editing (double-click)."""
        from .feeder_window import FeederWindow
        dlg = FeederWindow(
            f, self._board.Isc_board_kA,
            min_conductor_mm2=self._min_conductor_mm2,
            parent=self)
        def on_saved(updated_f):
            self._board.feeders[row] = updated_f
            self._refresh_row(row)
            self._sync_props(updated_f)
            self._upd_totals()
            self._refresh_status_messages(
                f'Feeder saved — {updated_f.name or updated_f.circuit_ref}')
        dlg.feeder_saved.connect(on_saved)
        dlg.show()

    def _open_selector(self):
        """Open Cable Selector — handles both feeder rows and primary feeder."""
        # Use props_mode flag — reliable regardless of selection state
        if self._props_mode == 'primary':
            self._open_primary_selector()
            return

        # Get all selected rows
        sel_rows = sorted(set(i.row() for i in self._tbl.selectedItems()))
        if not sel_rows:
            # Fallback: still no selection → primary
            self._open_primary_selector()
            return

        # Filter out SubPanel rows
        target_rows = [r for r in sel_rows
                       if r < len(self._board.feeders) and
                       self._board.feeders[r].load_type != 'SubPanel']
        if not target_rows:
            return

        if self._sel_win is not None:
            try:
                self._sel_win.show(); self._sel_win.raise_()
                self._sel_win.activateWindow(); return
            except RuntimeError:
                self._sel_win = None

        from VSEngCableSelector.ui.main_window import MainWindow

        # Use first selected feeder's cable as template; set frequency before opening
        first_f = self._board.feeders[target_rows[0]]
        first_f.cable.frequency = self._board.frequency
        multi = len(target_rows) > 1

        def on_proceed(cable):
            self._sel_win = None
            # Apply cable to ALL selected feeders, calculate each
            for ri in target_rows:
                if ri >= len(self._board.feeders): continue
                f = self._board.feeders[ri]
                import copy
                f_cable = copy.deepcopy(cable)
                f_cable.cable_length  = f.cable_length
                f_cable.max_vdrop_pct = f.max_vdrop_pct
                apply_feeder_cable_from_selector(f, f_cable)
                self._do_calc(f)
            self._fill_grid()
            self._upd_totals()
            # Sync props for current row
            cur = self._tbl.currentRow()
            if cur >= 0 and cur < len(self._board.feeders):
                self._sync_props(self._board.feeders[cur])
            if multi:
                info = f'Cable applied and calculated for {len(target_rows)} feeders'
            else:
                f0 = self._board.feeders[target_rows[0]]
                info = f'Cable applied — {f0.name or f0.circuit_ref}'
            self._refresh_status_messages(info)

        def on_close():
            self._sel_win = None

        try:
            self._sel_win = MainWindow(
                cable=first_f.cable, on_proceed=on_proceed, parent=self)
        except Exception as _e:
            import traceback
            QMessageBox.critical(self, 'Cable Selector Error',
                                 f'{type(_e).__name__}: {_e}\n\n'
                                 + traceback.format_exc()[-800:])
            self._sel_win = None
            return
        self._sel_win.destroyed.connect(on_close)
        if multi:
            self._sel_win.setWindowTitle(
                f'Cable Selector  [{len(target_rows)} feeders selected — '
                f'cable will be applied to all]')
        qss = _load_qss()
        if qss: self._sel_win.setStyleSheet(qss)
        self._sel_win.show()

    # ── PRIMARY CABLE ─────────────────────────────────────────────────────────
    def _open_primary_selector(self):
        """Open Cable Selector for the primary feeder. Load = board total."""
        if self._sel_win is not None:
            try:
                self._sel_win.show(); self._sel_win.raise_()
                self._sel_win.activateWindow(); return
            except RuntimeError:
                self._sel_win = None

        from VSEngCableSelector.ui.main_window import MainWindow
        from VSEngCableSelector.cable_class import C_Cable
        b  = self._board
        pf = b.primary_feeder

        # Set primary feeder load from board totals
        pf.Ib     = b.total_Ib
        pf.S      = b.total_S_kVA
        pf.PF     = b.composite_PF
        pf.P      = round(b.total_S_kVA * b.composite_PF, 2)
        pf.phases = b.phases
        pf.voltage= b.voltage
        pf.cable_length  = self._pL.value()
        pf.max_vdrop_pct = self._pVD.value()

        # Always propagate board frequency (60 Hz KSA)
        pf.frequency       = b.frequency
        pf.cable.frequency = b.frequency

        # Initialize cable with proper defaults if not yet configured
        if not pf.cable.conductor_table:
            pf.cable.insulation    = 'XLPE'
            pf.cable.core_config   = '1C'
            pf.cable.install_method= 'air'
            pf.cable.arrangement   = 'e'   # trefoil
            pf.cable.ambient_temp  = 40
            pf.cable.phases        = b.phases
            pf.cable.voltage       = b.voltage
            pf.cable.cable_length  = pf.cable_length
            pf.cable.max_vdrop_pct = pf.max_vdrop_pct
            pf.cable.S             = pf.S
            pf.cable.PF            = pf.PF
            pf.cable.calculate_derating()

        def on_proceed(cable):
            import copy
            cable.cable_length  = pf.cable_length
            cable.max_vdrop_pct = pf.max_vdrop_pct
            apply_feeder_cable_from_selector(pf, cable)
            b.primary_feeder_selected = True
            self._sel_win = None
            # Calculate primary feeder
            b._calc_primary_feeder()
            self._sync_primary_props()
            self._upd_totals()

        def on_close():
            self._sel_win = None

        try:
            self._sel_win = MainWindow(cable=pf.cable, on_proceed=on_proceed, parent=self)
        except Exception as _e:
            import traceback
            QMessageBox.critical(self, 'Cable Selector Error',
                                 f'{type(_e).__name__}: {_e}\n\n'
                                 + traceback.format_exc()[-800:])
            self._sel_win = None
            return
        self._sel_win.destroyed.connect(on_close)
        self._sel_win.setWindowTitle(
            f'Cable Selector — Primary Feeder  |  '
            f'Board load: Ib={b.total_Ib:.1f}A  S={b.total_S_kVA:.1f}kVA')
        qss = _load_qss()
        if qss: self._sel_win.setStyleSheet(qss)
        self._sel_win.show()

    # ── BOARD SETTINGS ────────────────────────────────────────────────────────
    def _board_settings(self):
        dlg = BoardSettingsDialog(self._board, self)
        if dlg.exec():
            self._reload_tree()
            self._load_board(self._board)

    # ── ADD / REMOVE / MOVE ───────────────────────────────────────────────────
    def _add_feeder(self):
        b = self._board
        f = b.add_feeder(); f.voltage = b.voltage; f.phases = b.phases
        f.frequency = b.frequency
        apply_vdrop_limit_to_feeder(f, self._vd_settings, force=False)
        self._fill_grid()
        last = self._tbl.rowCount() - 1
        self._tbl.setCurrentCell(last, 1)
        self._tbl.editItem(self._tbl.item(last, 1))

    def _add_subpanel(self):
        b = self._board
        if b.level >= 10:
            QMessageBox.warning(self, 'Max Depth', 'Maximum 10 levels reached.')
            return
        name, ok = QInputDialog.getText(self, 'New Sub-Panel', 'Sub-panel name:',
                                        text=f'SDB-{len(b.child_boards)+1}')
        if not ok or not name.strip(): return
        child = b.add_child_board(name.strip())
        if child:
            self._reload_tree(); self._fill_grid()
            for ri, f in enumerate(b.feeders):
                if f.subpanel_id == child.board_id:
                    self._tbl.setCurrentCell(ri, 1); break

    def _del_row(self):
        # Check if a sub-board is selected in tree (not a feeder row)
        tree_item = self._tree.currentItem()
        if tree_item:
            bid = tree_item.data(0, Qt.UserRole)
            board = self._root.find_board(bid) if bid else None
            if board and board is not self._board and board is not self._root:
                # User selected a sub-board node in tree — delete that board
                parent = self._root.find_board(board.parent_id) if board.parent_id else None
                if parent:
                    if QMessageBox.question(
                            self, 'Remove Board',
                            f'Remove board "{board.name}" and all its feeders?',
                            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                        return
                    parent.remove_child_board(board.board_id)
                    self._reload_tree()
                    self._load_board(parent)
                    return

        # Otherwise delete selected feeder row(s)
        sel_rows = sorted(set(i.row() for i in self._tbl.selectedItems()), reverse=True)
        if not sel_rows: return
        names = [self._board.feeders[r].name for r in sel_rows
                 if r < len(self._board.feeders)]
        if not names: return
        msg = (f'Remove {len(names)} feeders?' if len(names) > 1
               else f'Remove "{names[0]}"?')
        if QMessageBox.question(self, 'Remove', msg,
           QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        for row in sel_rows:
            if row >= len(self._board.feeders): continue
            f = self._board.feeders[row]
            if f.load_type == 'SubPanel' and f.subpanel_id:
                self._board.remove_child_board(f.subpanel_id)
                self._reload_tree()
            else:
                self._board.feeders.pop(row)
        self._fill_grid(); self._upd_totals()

    def _move(self, d):
        row = self._tbl.currentRow()
        nr  = row + d; b = self._board
        if nr < 0 or nr >= len(b.feeders): return
        b.feeders[row], b.feeders[nr] = b.feeders[nr], b.feeders[row]
        self._fill_grid()
        self._tbl.setCurrentCell(nr, self._tbl.currentColumn())

    # ── FILE OPS ──────────────────────────────────────────────────────────────
    def _save(self):
        if not self._file: self._save_as(); return
        self._root.save(self._file)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save', '',
                                              'Switchboard (*.swb);;All (*)')
        if path:
            if not path.endswith('.swb'): path += '.swb'
            self._file = path; self._root.save(path)
            self.setWindowTitle(f'VoltFlow — {path}')

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load', '',
                                              'Switchboard (*.swb);;All (*)')
        if not path: return
        try:
            self._root = C_Switchboard.load(path)
            self._file = path; self._board = self._root
            self._reload_tree(); self._load_board(self._root)
            self.setWindowTitle(f'VoltFlow — {path}')
        except Exception as e:
            QMessageBox.critical(self, 'Load Error', str(e))

    def _print(self):
        """Print feeder schedule table."""
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QPrintDialog.Accepted:
            doc = QTextDocument()
            doc.setHtml(self._print_html(self._board))
            doc.print_(printer)

    def _boards_data_for_xls(self) -> list:
        """Serialize all boards for fill_schedule.build_workbook."""
        all_boards = self._root.all_boards()
        id_to_name = {b.board_id: b.name for b in all_boards}
        boards_data = []
        for b in all_boards:
            feeders_data = []
            for f in b.feeders:
                rec = f.cable.recommended
                feeders_data.append({
                    'name':            f.name,
                    'load_type':       f.load_type,
                    'phase_str':       f.phase_str,
                    'phases':          f.phases,
                    'S':               f.S or 0.0,
                    'S_demand':        f.S_demand,
                    'demand_factor_pct': f.demand_factor_pct,
                    'P':               f.P or 0.0,
                    'PF':              f.PF or 0.9,
                    'cable_length':    f.cable_length,
                    'parallel_cables': getattr(f.cable, 'parallel_cables', 1),
                    'cb': {
                        'In_CB':   f.cb.In_CB or 0,
                        'poles':   f.cb.poles or 1,
                        'cb_type': f.cb.cb_type or 'MCB',
                    },
                    'cable': {'size_mm2': rec.size_mm2 if rec else None},
                    'conductor_desc': (
                        f.cable.format_conductor_desc(f.phases) if rec else ''),
                })

            mcb = b.main_cb
            main_cb_size = (f'{int(mcb.In_CB)}A-{int(mcb.poles)}p'
                            if mcb and mcb.In_CB else '')
            main_cb_type = (mcb.cb_type or '') if mcb else ''

            pf = b.primary_feeder
            if b.primary_feeder_selected and pf.cable.recommended:
                main_cable = pf.cable.format_conductor_desc(b.phases)
            else:
                main_cable = ''

            if b.level == 0:
                t = b.transformer
                source = (f'{int(t.Sn_kVA)} kVA / '
                          f'{int(t.Un_HV / 1000)} kV Transformer')
            else:
                source = id_to_name.get(b.parent_id, '')

            boards_data.append({
                'name':         b.name,
                'panel_size':   b.effective_panel_size,
                'feeders':      feeders_data,
                'total_S_kVA':  b.total_S_kVA,
                'total_S_connected': round(sum(
                    (f.S or 0.0) for f in b.feeders
                    if f.load_type not in ('Space', 'Spare')), 2),
                'df_mode':      self._df_mode,
                'project_df_pct': self._project_df_pct,
                'ip_rating':    b.IP,
                'main_cb_type': main_cb_type,
                'main_cb_size': main_cb_size,
                'main_cable':   main_cable,
                'source':       source,
            })
        return boards_data

    def _export_xls(self):
        """Export panel schedule for all boards as Excel (.xlsx) workbook."""
        if sys.platform == 'win32':
            try:
                import win32com.client  # noqa: F401
            except ImportError:
                QMessageBox.critical(
                    self, 'Missing dependency',
                    'pywin32 is not installed.\n\n'
                    'Run:  pip install pywin32\n\n'
                    'Then restart the application.')
                return

        path, _ = QFileDialog.getSaveFileName(
            self, 'Export XLS Schedule', '',
            'Excel Workbook (*.xlsx)')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'

        from .fill_schedule import build_workbook

        boards_data = self._boards_data_for_xls()
        self._status.setText('Generating XLS schedule — please wait…')
        self._status.setStyleSheet('font-size:10px;color:#444;')
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

        try:
            # Excel COM must run on the main UI thread (STA) — background threads fail.
            build_workbook(boards_data, voltage=self._root.voltage, out_path=path)
            self._refresh_status_messages(f'XLS Schedule saved: {path}')
            if sys.platform != 'win32' and not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                QMessageBox.warning(
                    self, 'Schedule saved',
                    f'The workbook was saved, but no spreadsheet app could open it:\n{path}')
        except Exception as e:
            import traceback
            self._refresh_status_messages('XLS export failed.')
            QMessageBox.critical(
                self, 'XLS Export Error',
                f'{type(e).__name__}: {e}\n\n'
                + traceback.format_exc()[-1200:])
        finally:
            QApplication.restoreOverrideCursor()

    def _print_sld(self):
        """Print hierarchical SLD with voltage-drop annotations."""
        try:
            from .print_report import build_sld_tree_html, build_sld_html
            if self._root:
                html = build_sld_tree_html(self._root)
            else:
                html = build_sld_html(self._board, self._root)
            self._show_print_preview(html, 'Single Line Diagram')
        except Exception as e:
            import traceback
            err = f'{e}\n\n{traceback.format_exc()[-1500:]}'
            try:
                log = os.path.join(os.environ.get('TEMP', '.'), 'voltflow_sld_error.txt')
                with open(log, 'w', encoding='utf-8') as f:
                    f.write(err)
            except Exception:
                log = None
            msg = f'Could not generate Single Line Diagram:\n\n{e}'
            if log:
                msg += f'\n\nDetails written to:\n{log}'
            QMessageBox.critical(self, 'SLD Error', msg)

    def _export_dxf(self):
        """Export current board as DXF Single Line Diagram."""
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export DXF', f'{self._board.name}_SLD',
            'DXF Drawing (*.dxf);;All Files (*)')
        if not path:
            return
        if not path.endswith('.dxf'):
            path += '.dxf'
        try:
            from .dxf_export import export_sld_dxf
            export_sld_dxf(self._board, self._root, path)
            self._refresh_status_messages(f'DXF exported: {path}')
            if sys.platform == 'win32':
                os.startfile(path)
        except ImportError:
            QMessageBox.warning(self, 'Missing Package',
                'ezdxf not installed.\n\nRun:\n  pip install ezdxf')
        except Exception as e:
            QMessageBox.critical(self, 'DXF Export Error', str(e))

    def _show_print_preview(self, html: str, title: str):
        """Write HTML report and open it with the OS default browser/viewer.

        Avoids Python's webbrowser module (unreliable / crash-prone in
        PyInstaller one-file builds). Uses Qt + os.startfile instead.
        """
        import tempfile
        safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in title)
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', delete=False,
            encoding='utf-8', prefix=f'VoltFlow_{safe}_')
        try:
            tmp.write(html)
        finally:
            tmp.close()
        path = tmp.name

        opened = False
        try:
            opened = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        except Exception:
            opened = False
        if not opened and sys.platform == 'win32':
            try:
                os.startfile(path)
                opened = True
            except OSError:
                opened = False

        if opened:
            self._refresh_status_messages(
                f'{title} opened — use browser Print (Ctrl+P)')
        else:
            QMessageBox.information(
                self, title,
                f'Report saved but could not open automatically:\n\n{path}\n\n'
                'Open that file in a browser to view / print.')
    def _print_html(self, b):
        """Generate Panel Schedule matching reference format exactly."""
        feeders = [f for f in b.feeders if f.load_type != 'SubPanel']

        # ── Assign circuits ─────────────────────────────────────────────────
        # Left: odd  1,3,5,...,41  (21 slots)
        # Right: even 2,4,6,...,42 (21 slots)
        # Each feeder occupies N consecutive slots on one side:
        #   L123 = 3 slots, L12/L13/L23 = 2 slots, L1/L2/L3 = 1 slot
        # Alternate assignment: first feeder left, second right, etc.

        def n_slots(f):
            return {'L123':3,'L12':2,'L13':2,'L23':2,
                    'L1':1,'L2':1,'L3':1}.get(f.phase_str, 1)

        def phase_cols(f):
            """Return which of A/B/C carry load."""
            return {'L123':['A','B','C'],'L12':['A','B'],'L13':['A','C'],
                    'L23':['B','C'],'L1':['A'],'L2':['B'],'L3':['C']
                    }.get(f.phase_str, ['A','B','C'])

        # Build left and right slot lists (each slot = circuit number)
        left_slots  = list(range(1, 42, 2))   # 1,3,5,...,41
        right_slots = list(range(2, 43, 2))   # 2,4,6,...,42

        # Assign feeders to slots
        # slot_data[circuit_no] = {'feeder':f, 'role':'name'|'load'|'empty',
        #                          'va_A':v, 'va_B':v, 'va_C':v}
        slot_data = {}
        for c in left_slots + right_slots:
            slot_data[c] = {'feeder':None,'role':'empty',
                            'va_A':'','va_B':'','va_C':'','name':''}

        left_ptr  = 0   # index into left_slots
        right_ptr = 0   # index into right_slots
        use_left  = True

        for f in feeders:
            ns     = n_slots(f)
            phases = phase_cols(f)
            nphs   = len(phases)
            va_ea  = round(f.S * 1000 / nphs, 0) if f.S else 0
            va_str = f'{va_ea/1000:.2f}' if va_ea >= 1000 else f'{va_ea:.0f}'

            # Pick side
            if use_left:
                if left_ptr + ns <= len(left_slots):
                    cirs = left_slots[left_ptr:left_ptr+ns]
                    left_ptr += ns
                else:
                    use_left = False  # overflow to right

            if not use_left:
                if right_ptr + ns <= len(right_slots):
                    cirs = right_slots[right_ptr:right_ptr+ns]
                    right_ptr += ns
                else:
                    break  # no more space

            # Middle circuit gets the name
            mid_idx = len(cirs) // 2

            for i, c in enumerate(cirs):
                d = slot_data[c]
                d['feeder'] = f
                d['role']   = 'name' if i == mid_idx else 'load'
                d['name']   = f.name if i == mid_idx else ''
                for ph in phases:
                    d[f'va_{ph}'] = va_str

            use_left = not use_left   # alternate sides

        # ── Build table rows ────────────────────────────────────────────────
        def cell(c):
            d   = slot_data[c]
            f   = d['feeder']
            clr = LOAD_COLORS.get(f.load_type,'#1a1a1a') if f else '#1a1a1a'
            name_cell = (f'<td style="text-align:left;color:{clr};'
                         f'font-weight:bold">{d["name"]}</td>'
                         if d["name"] else '<td></td>')
            cb_a = ''
            pol  = ''
            if f and d['role'] == 'name':
                cb_a = f'{f.cb.In_CB:.0f}' if f.cb.In_CB else ''
                pol  = str(f.cb.poles) if f.cb.In_CB else ''
            va_a = d['va_A'] or ''
            va_b = d['va_B'] or ''
            va_c = d['va_C'] or ''
            ph   = f.phase_str if f and d['role']=='name' else ''
            rec_pr = f.cable.recommended if f else None
            n_par_pr = getattr(f.cable, 'parallel_cables', 1) if f else 1
            mm2_pr = (f'({n_par_pr}) {rec_pr.size_mm2}mm²' if rec_pr and n_par_pr > 1
                      else f'{rec_pr.size_mm2}mm²' if rec_pr else '')
            return (f'<td>{c}</td>{name_cell}'
                    f'<td>{pol}</td><td>{cb_a}</td>'
                    f'<td>{va_a}</td><td>{va_b}</td><td>{va_c}</td>'
                    f'<td>{ph}</td><td>{mm2_pr}</td>')

        rows_html = ''
        for i in range(21):
            lc  = left_slots[i]
            rc  = right_slots[i]
            bg  = '#f5f7fa' if i % 2 == 0 else '#ffffff'
            rows_html += (f'<tr style="background:{bg}">'
                          + cell(lc)
                          + '<td style="background:#c8d8e8;width:3px;padding:0"></td>'
                          + cell(rc)
                          + '</tr>')

        # ── Phase totals ────────────────────────────────────────────────────
        def phase_tot(ph):
            col = f'va_{ph}'
            tot = 0
            for d in slot_data.values():
                v = d.get(col,'')
                if v:
                    try:
                        tot += float(v)
                    except (TypeError, ValueError):
                        pass
            return tot

        tA = phase_tot('A'); tB = phase_tot('B'); tC = phase_tot('C')
        tT = tA + tB + tC

        # Load type totals
        type_map = {'Light':'LIGHTING','Socket':'RECEPTS',
                    'Motor':'EQUIP','HVAC':'EQUIP','Other':'EQUIP'}
        type_tots = {'LIGHTING':{'A':0,'B':0,'C':0},
                     'RECEPTS': {'A':0,'B':0,'C':0},
                     'EQUIP':   {'A':0,'B':0,'C':0}}
        for f in feeders:
            tp  = type_map.get(f.load_type,'EQUIP')
            phs = phase_cols(f)
            va  = (f.S*1000/len(phs)) if f.S else 0
            for ph in phs:
                type_tots[tp][ph] += va

        def tt_row(label, d):
            tot = sum(d.values())
            pct = f'{tot/tT*100:.0f}' if tT else '0'
            return (f'<tr><td>{label}</td>'
                    f'<td>{d["A"]/1000:.1f}</td>'
                    f'<td>{d["B"]/1000:.1f}</td>'
                    f'<td>{d["C"]/1000:.1f}</td>'
                    f'<td>{tot/1000:.2f}</td>'
                    f'<td>{pct}</td></tr>')

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Panel Schedule — {b.name}</title>
<style>
  body{{margin:0;padding:10px;font-family:'Segoe UI',Arial,sans-serif;
        font-size:9px;background:#fff;color:#000;}}
  table{{border-collapse:collapse;width:100%;margin-bottom:6px;}}
  th,td{{border:1px solid #666;padding:2px 3px;text-align:center;
         white-space:nowrap;font-size:9px;}}
  th{{background:#1a3a5c;color:#fff;font-size:8px;letter-spacing:0.3px;padding:3px;}}
  .hdr-lbl{{font-size:7px;color:#555;text-align:left;border:none;padding:1px 3px;}}
  .hdr-val{{font-size:11px;font-weight:bold;color:#1a3a5c;text-align:left;
             border:none;padding:0 3px 2px;}}
  .section{{background:#e8f0f8;}}
  @media print{{body{{padding:4px;font-size:8px;}}
                th,td{{font-size:8px;padding:1px 2px;}}}}
</style></head><body>

<!-- HEADER BLOCK -->
<table>
  <tr>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">PANEL NAME:</div>
      <div class="hdr-val">{b.name}</div></td>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">VOLTAGE</div>
      <div class="hdr-val">{b.voltage:.0f}V</div></td>
    <td colspan="2" style="border:1px solid #666">
      <div class="hdr-lbl">PHASE:</div>
      <div class="hdr-val">{b.phases}</div></td>
    <td colspan="2" style="border:1px solid #666">
      <div class="hdr-lbl">FREQUENCY:</div>
      <div class="hdr-val">{b.frequency:.0f}Hz</div></td>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">NEUTRAL RATING:</div>
      <div class="hdr-val">{b.busbar_A:.0f}A</div></td>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">PANEL DESCRIPTION:</div>
      <div class="hdr-val">{b.frame}</div></td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">MAINS:</div>
      <div class="hdr-val">{b.main_cb.In_CB:.0f}A {b.main_cb.cb_type}
        if b.main_cb.In_CB else "—"</div></td>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">MOUNTING:</div>
      <div class="hdr-val">{b.mounting}</div></td>
    <td colspan="2" style="border:1px solid #666">
      <div class="hdr-lbl">MAX. NO. OF CIRCUITS:</div>
      <div class="hdr-val">42</div></td>
    <td colspan="2" style="border:1px solid #666">
      <div class="hdr-lbl">PANEL A.I.C. RATING:</div>
      <div class="hdr-val">{b.Isc_board_kA*1000:.0f}A</div></td>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">LOCATION:</div>
      <div class="hdr-val">{b.location or "—"}</div></td>
    <td colspan="3" style="border:1px solid #666">
      <div class="hdr-lbl">ENGINEER:</div>
      <div class="hdr-val">{b.engineer or "—"}</div></td>
  </tr>
</table>

<!-- CIRCUIT TABLE -->
<table>
  <tr>
    <th colspan="8" style="background:#1a3a5c">← LEFT CIRCUITS (ODD)</th>
    <th style="background:#888;width:3px;padding:0"></th>
    <th colspan="8" style="background:#1a3a5c">RIGHT CIRCUITS (EVEN) →</th>
  </tr>
  <tr>
    <th>NO</th><th>DESCRIPTION</th><th>POLES</th><th>BKR</th>
    <th>VA-A</th><th>VA-B</th><th>VA-C</th><th>PHASE</th><th>mm²</th>
    <th style="background:#888;padding:0"></th>
    <th>NO</th><th>DESCRIPTION</th><th>POLES</th><th>BKR</th>
    <th>VA-A</th><th>VA-B</th><th>VA-C</th><th>PHASE</th><th>mm²</th>
  </tr>
  {rows_html}
</table>

<!-- TOTALS -->
<table style="width:auto;margin-top:4px">
  <tr>
    <th style="text-align:left;width:100px">LOAD TYPE</th>
    <th>A (kVA)</th><th>B (kVA)</th><th>C (kVA)</th>
    <th>SUM (kVA)</th><th>%</th>
  </tr>
  {tt_row('LIGHTING (L)', type_tots['LIGHTING'])}
  {tt_row('RECEPTS (R)',  type_tots['RECEPTS'])}
  {tt_row('EQUIP (E)',    type_tots['EQUIP'])}
  <tr style="font-weight:bold;background:#e8f0f8">
    <td>TOTAL</td>
    <td>{tA/1000:.1f}</td><td>{tB/1000:.1f}</td><td>{tC/1000:.1f}</td>
    <td>{tT/1000:.2f}</td><td>100</td>
  </tr>
  <tr>
    <td>TOTAL %</td>
    <td>{int(tA/tT*100) if tT else 0}</td>
    <td>{int(tB/tT*100) if tT else 0}</td>
    <td>{int(tC/tT*100) if tT else 0}</td>
    <td>—</td><td>—</td>
  </tr>
</table>

</body></html>"""


    # ── COLLABORATION ─────────────────────────────────────────────────────────

    def _set_stub_spec(self):
        """Open StubSpecDialog to define the allocation contract for a SubPanel feeder."""
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            QMessageBox.information(self, 'Set Stub Spec',
                                    'Select a SubPanel feeder row first.')
            return
        f = self._board.feeders[row]
        if f.load_type != 'SubPanel':
            QMessageBox.information(self, 'Set Stub Spec',
                                    'Select a SubPanel feeder row first.')
            return
        from .stub_dialog import StubSpecDialog
        dlg = StubSpecDialog(
            feeder_name=f.name,
            board_voltage=self._board.voltage,
            board_isc=self._board.Isc_board_kA,
            existing_spec=f.interface_spec,
            parent=self,
        )
        if dlg.exec():
            self._board.set_stub_spec(row, dlg.spec())
            self._refresh_row(row)
            self._upd_totals()
            self._refresh_status_messages(f'Interface spec set for "{f.name}"')

    def _export_subboard(self):
        """Export selected SubPanel as a standalone .swb package for a child engineer."""
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            QMessageBox.information(self, 'Export Sub-Board',
                                    'Select a SubPanel feeder row first.')
            return
        f = self._board.feeders[row]
        if f.load_type != 'SubPanel':
            QMessageBox.information(self, 'Export Sub-Board',
                                    'Select a SubPanel feeder row first.')
            return
        if not f.interface_spec.get('S_kVA'):
            QMessageBox.warning(self, 'Export Sub-Board',
                                'Set an interface specification first.\n'
                                '(COLLABORATE → Set Stub Spec)')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Sub-Board Package',
            f'{f.name}_subboard.swb',
            'Switchboard Package (*.swb)')
        if not path: return
        if not path.endswith('.swb'): path += '.swb'
        try:
            self._board.export_subboard(row, path)
            self._reload_tree()
            self._refresh_row(row)
            self._upd_totals()
            self._refresh_status_messages(f'Sub-board exported: {path}')
            QMessageBox.information(
                self, 'Sub-Board Exported',
                f'Package exported to:\n{path}\n\n'
                f'Share this file with the child engineer.\n'
                f'Use "Import Package" when the completed design is returned.')
        except Exception as e:
            QMessageBox.critical(self, 'Export Error', str(e))

    def _import_subboard(self):
        """Import a completed sub-board package and validate against interface spec."""
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._board.feeders):
            QMessageBox.information(self, 'Import Package',
                                    'Select a SubPanel feeder row first.')
            return
        f = self._board.feeders[row]
        if f.load_type != 'SubPanel':
            QMessageBox.information(self, 'Import Package',
                                    'Select a SubPanel feeder row first.')
            return
        if not f.interface_spec:
            QMessageBox.warning(self, 'Import Package',
                                'No interface spec set on this feeder.\n'
                                'Use "Set Stub Spec" to define the allocation first.')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, 'Import Sub-Board Package', '',
            'Switchboard Package (*.swb)')
        if not path: return
        try:
            ok, errors = self._board.import_subboard(row, path)
        except Exception as e:
            QMessageBox.critical(self, 'Import Error', str(e))
            return

        from .stub_dialog import ImportResultDialog, ImportSuccessDialog
        if not ok:
            dlg = ImportResultDialog(path, f.name, f.interface_spec, errors, self)
            dlg.exec()
            err_txt = '; '.join(errors[:2]) if errors else 'interface mismatch'
            self._refresh_status_messages(
                f'Import failed — {f.name}: {err_txt}')
        else:
            self._reload_tree()
            self._fill_grid()
            self._upd_totals()
            child = self._root.find_board(f.subpanel_id) if f.subpanel_id else None
            actual_S  = child.total_S_kVA if child else 0
            actual_Ib = child.total_Ib    if child else 0
            actual_vd = (child.primary_feeder.result_vdrop_pct
                         if child and child.primary_feeder_selected else 0)
            dlg = ImportSuccessDialog(
                f.name, f.interface_spec,
                actual_S, actual_Ib, actual_vd, self)
            dlg.exec()
            self._refresh_status_messages(f'Package imported successfully: {f.name}')

    def _fl(self, t):
        l = QLabel(t); l.setStyleSheet('font-size:9pt;color:#555;'); return l

    def _le(self):
        w = QLineEdit()
        w.setStyleSheet('background:#fff;border:1px solid #c0c0c0;'
                        'border-radius:2px;padding:2px 5px;font-size:9pt;')
        return w

    def _sp(self, mn, mx, d, step):
        w = QDoubleSpinBox()
        w.setRange(mn, mx); w.setValue(d); w.setSingleStep(step)
        w.setDecimals(2 if step < 1 else 0)
        w.setButtonSymbols(QDoubleSpinBox.NoButtons)
        w.setStyleSheet('background:#fff;border:1px solid #c0c0c0;'
                        'border-radius:2px;padding:2px;font-size:9pt;')
        return w

    def _cb(self, items):
        w = QComboBox(); w.addItems(items)
        w.setStyleSheet('background:#fff;border:1px solid #c0c0c0;'
                        'border-radius:2px;padding:2px 4px;font-size:9pt;')
        return w


# ─────────────────────────────────────────────────────────────────────────────
class BoardSettingsDialog(QDialog):
    def __init__(self, board, parent=None):
        super().__init__(parent)
        self._b = board
        self.setWindowTitle(f'Board Settings — {board.name}')
        self.setMinimumWidth(500)
        self._build()

    def _build(self):
        vl = QVBoxLayout(self); vl.setSpacing(10)

        ig = QGroupBox('Identity')
        fl = QFormLayout(ig); fl.setSpacing(6)
        self._name = QLineEdit(self._b.name)
        self._proj = QLineEdit(self._b.project)
        self._loc  = QLineEdit(self._b.location)
        self._dref = QLineEdit(self._b.drawing_ref)
        self._eng  = QLineEdit(self._b.engineer)
        for lbl, w in [('Name', self._name), ('Project', self._proj),
                        ('Location', self._loc), ('Drawing Ref', self._dref),
                        ('Engineer', self._eng)]:
            fl.addRow(lbl, w)
        vl.addWidget(ig)

        eg = QGroupBox('Electrical')
        el = QHBoxLayout(eg); el.setSpacing(10)
        def ef(lbl, mn, mx, d, step):
            col = QVBoxLayout(); col.setSpacing(2)
            col.addWidget(QLabel(lbl))
            sb = QDoubleSpinBox(); sb.setRange(mn, mx)
            sb.setValue(d); sb.setSingleStep(step)
            sb.setDecimals(0 if step >= 1 else 1)
            sb.setButtonSymbols(QDoubleSpinBox.NoButtons)
            col.addWidget(sb); el.addLayout(col); return sb
        self._volt = ef('Voltage V', 50, 35000, self._b.voltage, 10)
        freq_col = QVBoxLayout()
        freq_col.addWidget(QLabel('Frequency'))
        self._freq_lbl = QLabel(f'{KSA_FREQUENCY_HZ:.0f} Hz')
        self._freq_lbl.setStyleSheet('font-weight:bold;padding:4px 0;')
        freq_col.addWidget(self._freq_lbl)
        el.addLayout(freq_col)
        ph_col = QVBoxLayout(); ph_col.addWidget(QLabel('Phases'))
        self._ph = QComboBox(); self._ph.addItems(['3','1'])
        self._ph.setCurrentText(str(self._b.phases))
        ph_col.addWidget(self._ph); el.addLayout(ph_col)
        bus_col = QVBoxLayout(); bus_col.addWidget(QLabel('Busbar A'))
        self._bus = QComboBox()
        for a in BUSBAR_STD_A: self._bus.addItem(f'{a}A', a)
        for i in range(self._bus.count()):
            if self._bus.itemData(i) == self._b.busbar_A:
                self._bus.setCurrentIndex(i); break
        bus_col.addWidget(self._bus); el.addLayout(bus_col)
        vl.addWidget(eg)

        pg = QGroupBox('Physical')
        pl = QHBoxLayout(pg); pl.setSpacing(10)
        def pc(lbl, items, cur):
            col = QVBoxLayout(); col.addWidget(QLabel(lbl))
            cb = QComboBox(); cb.addItems(items)
            idx = cb.findText(cur)
            if idx >= 0: cb.setCurrentIndex(idx)
            col.addWidget(cb); pl.addLayout(col); return cb
        self._frame = pc('Frame',   FRAME_TYPES, self._b.frame)
        self._ip    = pc('IP',      IP_RATINGS,  self._b.IP)
        self._mount = pc('Mounting',MOUNTING,     self._b.mounting)
        # Panel size dropdown
        ps_col = QVBoxLayout(); ps_col.addWidget(QLabel('Panel Size'))
        self._psize = QComboBox()
        self._psize.addItem('Auto', 0)
        for s in PANEL_SIZES:
            self._psize.addItem(f'{s}P', s)
        cur = self._b.panel_size
        for i in range(self._psize.count()):
            if self._psize.itemData(i) == cur:
                self._psize.setCurrentIndex(i); break
        ps_col.addWidget(self._psize); pl.addLayout(ps_col)
        vl.addWidget(pg)

        if self._b.level == 0:
            tg = QGroupBox('Transformer')
            tl = QHBoxLayout(tg); tl.setSpacing(10)
            def te(lbl, mn, mx, d, step):
                col = QVBoxLayout(); col.addWidget(QLabel(lbl))
                sb = QDoubleSpinBox(); sb.setRange(mn, mx)
                sb.setValue(d); sb.setSingleStep(step)
                sb.setDecimals(1 if step < 1 else 0)
                sb.setButtonSymbols(QDoubleSpinBox.NoButtons)
                col.addWidget(sb); tl.addLayout(col); return sb
            t = self._b.transformer
            self._tSn = te('Sn kVA', 100, 10000, t.Sn_kVA, 100)
            self._tVk = te('Vk %',   1,   20,    t.Vk_pct,  0.5)
            self._tHV = te('HV V',   1000,36000, t.Un_HV,   1000)
            self._tLV = te('LV V',   100, 1000,  t.Un_LV,   50)
            vl.addWidget(tg)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        vl.addWidget(bb)

    def _apply(self):
        b = self._b
        b.name = self._name.text(); b.project = self._proj.text()
        b.location = self._loc.text(); b.drawing_ref = self._dref.text()
        b.engineer = self._eng.text()
        b.voltage = self._volt.value(); b.phases = int(self._ph.currentText())
        b.frequency = KSA_FREQUENCY_HZ
        b.standard = PROJECT_STANDARD
        b.busbar_A = self._bus.currentData()
        b.frame = self._frame.currentText(); b.IP = self._ip.currentText()
        b.mounting    = self._mount.currentText()
        b.panel_size  = self._psize.currentData()
        if b.level == 0:
            b.transformer.Sn_kVA = self._tSn.value()
            b.transformer.Vk_pct = self._tVk.value()
            b.transformer.Un_HV  = self._tHV.value()
            b.transformer.Un_LV  = self._tLV.value()
        self.accept()
