# ui/ribbon_window.py — MainAppWindow: ribbon + embedded switchboard + project management
import sys, os
if not getattr(sys, 'frozen', False):
    _HERE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _CABLE = os.path.join(_HERE, 'VSEngCableSelector')
    if _HERE in sys.path:
        sys.path.remove(_HERE)
    sys.path.insert(0, _HERE)
    if _CABLE not in sys.path:
        sys.path.insert(1, _CABLE)

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFileDialog, QMessageBox,
    QFrame, QSizePolicy, QDialog, QFormLayout, QLineEdit,
    QComboBox, QDialogButtonBox, QApplication, QTextEdit, QSplitter,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QColor

from switchboard_class import C_Switchboard
from project_class import (
    C_Project, C_Package, STATUS_LIST, PROJECT_STANDARD, KSA_FREQUENCY_HZ, _now,
)
from version import APP_VERSION
from .project_tab import ProjectTab
from .qt_helpers import disconnect_signal

# ── Ribbon geometry ───────────────────────────────────────────────────────────
TAB_H   = 34   # tab button strip height
BAND_H  = 62   # ribbon action band height
RIBBON_H = TAB_H + BAND_H


# ─────────────────────────────────────────────────────────────────────────────
# Helper widgets
# ─────────────────────────────────────────────────────────────────────────────

def _tab_btn(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(True)
    b.setFixedHeight(TAB_H)
    b.setMinimumWidth(100)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        'QPushButton{background:#1a3a5c;color:#8ab4d4;border:none;'
        'font-size:10pt;font-weight:bold;padding:0 18px;border-bottom:2px solid transparent;}'
        'QPushButton:hover{color:#fff;background:#243f5c;}'
        'QPushButton:checked{color:#f0a500;background:#0d2137;'
        'border-bottom:2px solid #f0a500;}'
    )
    return b


def _grp_sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.VLine)
    f.setStyleSheet('color:#355a7a;')
    f.setFixedWidth(1)
    f.setContentsMargins(0, 8, 0, 8)
    return f


def _act(text: str, color='#2d5a8a', tip='', small=False) -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    h = 26 if small else 36
    b.setFixedHeight(h)
    b.setStyleSheet(
        f'QPushButton{{background:{color};color:#fff;border:none;'
        f'font-weight:bold;padding:2px 10px;border-radius:2px;font-size:9pt;}}'
        f'QPushButton:hover{{background:#4a7aaa;}}'
        f'QPushButton:disabled{{background:#3a4a5a;color:#666;}}'
    )
    return b


def _grp_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet('color:#8ab4d4;font-size:7pt;letter-spacing:1px;')
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


def _grp(title: str, *widgets) -> QWidget:
    """Vertical group: label at bottom, buttons stacked above."""
    w  = QWidget()
    vl = QVBoxLayout(w)
    vl.setContentsMargins(4, 4, 4, 2)
    vl.setSpacing(2)
    bh = QHBoxLayout()
    bh.setSpacing(3)
    for wi in widgets:
        bh.addWidget(wi)
    vl.addLayout(bh)
    vl.addWidget(_grp_label(title))
    return w


# ─────────────────────────────────────────────────────────────────────────────
# New Project dialog
# ─────────────────────────────────────────────────────────────────────────────

class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('New Project')
        self.setMinimumWidth(420)
        fl = QFormLayout(self)
        self._name     = QLineEdit('New Project')
        self._client   = QLineEdit()
        self._location = QLineEdit()
        self._engineer = QLineEdit()
        self._folder   = QLineEdit()
        self._folder.setReadOnly(True)
        self._folder.setPlaceholderText('Choose project folder…')
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        fh = QHBoxLayout()
        fh.addWidget(self._folder, 1); fh.addWidget(browse)
        fl.addRow('Project name', self._name)
        fl.addRow('Client',       self._client)
        fl.addRow('Location',     self._location)
        fl.addRow('Lead engineer',self._engineer)
        fl.addRow('Region',       QLabel(f'{PROJECT_STANDARD} · {KSA_FREQUENCY_HZ:.0f} Hz'))
        fl.addRow('Folder',       fh)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        fl.addRow(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, 'Project folder')
        if d: self._folder.setText(d)

    def values(self):
        return {
            'name':     self._name.text().strip() or 'New Project',
            'client':   self._client.text().strip(),
            'location': self._location.text().strip(),
            'engineer': self._engineer.text().strip(),
            'standard': PROJECT_STANDARD,
            'folder':   self._folder.text().strip(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# RIBBON WIDGET
# ─────────────────────────────────────────────────────────────────────────────

class RibbonWidget(QWidget):
    """Tab bar + action band. Caller connects action buttons."""

    TABS = ['PROJECT', 'NETWORK', 'CALCULATE', 'REPORTS', 'HELP']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(RIBBON_H)
        self.setStyleSheet('background:#0d2137;')
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # ── Tab button strip ──────────────────────────────────────────────────
        tab_row = QWidget(); tab_row.setFixedHeight(TAB_H)
        tab_row.setStyleSheet('background:#1a3a5c;')
        thl = QHBoxLayout(tab_row)
        thl.setContentsMargins(0, 0, 0, 0)
        thl.setSpacing(0)

        logo = QLabel('VoltFlow')
        logo.setContentsMargins(10, 0, 10, 0)
        logo.setStyleSheet(
            'background:#f0a500;color:#000;font-size:11pt;'
            'font-weight:bold;letter-spacing:2px;')
        logo.setAlignment(Qt.AlignCenter)
        thl.addWidget(logo)

        self._tabs = {}
        for name in self.TABS:
            b = _tab_btn(name)
            b.clicked.connect(lambda checked, n=name: self._select(n))
            thl.addWidget(b)
            self._tabs[name] = b
        thl.addStretch()

        # Project / board context label (right side of tab row)
        self._ctx = QLabel('')
        self._ctx.setStyleSheet('color:#8ab4d4;font-size:9pt;padding-right:12px;')
        self._ctx.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        thl.addWidget(self._ctx)

        vl.addWidget(tab_row)

        # ── Action band (stacked per tab) ─────────────────────────────────────
        self._band = QStackedWidget()
        self._band.setFixedHeight(BAND_H)
        self._band.setStyleSheet('background:#112233;')
        for name in self.TABS:
            self._band.addWidget(self._mk_band(name))
        vl.addWidget(self._band)

        self._select('PROJECT')

    def _select(self, name: str):
        for n, b in self._tabs.items():
            b.setChecked(n == name)
        self._band.setCurrentIndex(self.TABS.index(name))

    def set_context(self, text: str):
        self._ctx.setText(text)

    def select_tab(self, name: str):
        self._select(name)

    # ── Band builders ─────────────────────────────────────────────────────────

    def _mk_band(self, name: str) -> QWidget:
        makers = {
            'PROJECT':   self._band_project,
            'NETWORK':   self._band_network,
            'CALCULATE': self._band_calculate,
            'REPORTS':   self._band_reports,
            'HELP':      self._band_help,
        }
        return makers[name]()

    def _band_project(self):
        w  = QWidget()
        hl = QHBoxLayout(w); hl.setContentsMargins(8, 4, 8, 4); hl.setSpacing(4)
        self.btn_new_project  = _act('+ New Project',   '#107c10', 'Create a new project')
        self.btn_open_project = _act('Open Project',    '#0078d4', 'Open existing .vsproj')
        self.btn_save_project = _act('Save Project',    '#2d5a8a', 'Save project manifest')
        self.btn_close_proj   = _act('Close Project',   '#555',    'Close current project')
        hl.addWidget(_grp('PROJECT',
                          self.btn_new_project,
                          self.btn_open_project,
                          self.btn_save_project,
                          self.btn_close_proj))
        hl.addWidget(_grp_sep())
        self.btn_new_pkg  = _act('+ Package',  '#107c10', 'Add a new package/zone')
        self.btn_open_pkg = _act('Open Pkg',   '#0078d4', 'Open selected package for editing')
        self.btn_lock_pkg = _act('Lock',       '#e67e00', 'Lock package for exclusive editing')
        hl.addWidget(_grp('PACKAGES',
                          self.btn_new_pkg,
                          self.btn_open_pkg,
                          self.btn_lock_pkg))
        hl.addWidget(_grp_sep())
        self.btn_history = _act('History', '#444', 'View revision log')
        self.btn_snaps   = _act('Snapshots','#1a6b8a', 'View snapshots')
        hl.addWidget(_grp('AUDIT', self.btn_history, self.btn_snaps))
        hl.addStretch()
        return w

    def _band_network(self):
        w  = QWidget()
        hl = QHBoxLayout(w); hl.setContentsMargins(8, 4, 8, 4); hl.setSpacing(4)
        self.btn_add_feeder  = _act('+ Feeder',    '#107c10', 'Add feeder row')
        self.btn_add_sub     = _act('+ Sub-Panel', '#e67e00', 'Add child distribution board')
        self.btn_remove      = _act('Remove',      '#c42b1c', 'Remove selected row')
        hl.addWidget(_grp('ADD / REMOVE',
                          self.btn_add_feeder,
                          self.btn_add_sub,
                          self.btn_remove))
        hl.addWidget(_grp_sep())
        self.btn_board_set   = _act('Board',       '#2d5a8a', 'Board settings')
        self.btn_calc_all    = _act('Calc All',    '#5c2d91', 'Calculate all feeders')
        self.btn_calc_sel    = _act('Calc Sel.',   '#2d6e2d', 'Calculate selected rows')
        self.btn_balance     = _act('Balance',     '#1a6b8a', 'Phase balance')
        self.btn_spare       = _act('Spare/Space', '#607d8b', 'Generate spares and spaces')
        hl.addWidget(_grp('BOARD',
                          self.btn_board_set,
                          self.btn_calc_all,
                          self.btn_calc_sel,
                          self.btn_balance,
                          self.btn_spare))
        hl.addWidget(_grp_sep())
        self.btn_save_board  = _act('Save',     '#2d5a8a', 'Save board file (.swb)')
        self.btn_load_board  = _act('Load',     '#2d5a8a', 'Load board file (.swb)')
        self.btn_save_as     = _act('Save As',  '#444',    'Save board as…')
        hl.addWidget(_grp('FILE',
                          self.btn_save_board,
                          self.btn_load_board,
                          self.btn_save_as))
        hl.addWidget(_grp_sep())
        self.btn_set_spec    = _act('Set Stub Spec', '#1a6b8a',
                                    'Define interface spec (allocation contract) for a SubPanel feeder')
        self.btn_export_sub  = _act('Export Sub',    '#e67e00',
                                    'Export selected SubPanel as a standalone package for a child engineer')
        self.btn_import_sub  = _act('Import Pkg',    '#107c10',
                                    'Import a completed sub-board package and validate against spec')
        hl.addWidget(_grp('COLLABORATE',
                          self.btn_set_spec,
                          self.btn_export_sub,
                          self.btn_import_sub))
        hl.addStretch()
        return w

    def _band_calculate(self):
        w  = QWidget()
        hl = QHBoxLayout(w); hl.setContentsMargins(8, 4, 8, 4); hl.setSpacing(4)
        self.btn_crun_all = _act('Calc All',      '#5c2d91', 'Full recursive recalculation')
        self.btn_crun_sel = _act('Calc Selected', '#2d6e2d', 'Calculate selected rows only')
        self.btn_cbalance = _act('Phase Balance', '#1a6b8a', 'LDM phase balancing')
        self.btn_cspare   = _act('Spare/Space',   '#607d8b', 'Generate spares and spaces')
        hl.addWidget(_grp('RUN',
                          self.btn_crun_all,
                          self.btn_crun_sel,
                          self.btn_cbalance,
                          self.btn_cspare))
        hl.addWidget(_grp_sep())
        # Summary labels
        sum_w = QWidget()
        sl    = QHBoxLayout(sum_w); sl.setContentsMargins(8, 4, 8, 4); sl.setSpacing(16)
        def mk_kpi(label):
            col = QWidget(); cv = QVBoxLayout(col)
            cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(0)
            k = QLabel(label); k.setStyleSheet('color:#8ab4d4;font-size:7pt;')
            v = QLabel('—')
            v.setStyleSheet('color:#fff;font-size:12pt;font-weight:bold;'
                            'font-family:"Courier New";')
            cv.addWidget(k); cv.addWidget(v)
            return col, v
        c1, self.kpi_boards   = mk_kpi('Boards')
        c2, self.kpi_feeders  = mk_kpi('Feeders')
        c3, self.kpi_worst_vd = mk_kpi('Worst Vd%')
        c4, self.kpi_max_bus  = mk_kpi('Max Bus%')
        for c in [c1, c2, c3, c4]: sl.addWidget(c)
        hl.addWidget(_grp('SUMMARY', sum_w))
        hl.addStretch()
        return w

    def _band_reports(self):
        w  = QWidget()
        hl = QHBoxLayout(w); hl.setContentsMargins(8, 4, 8, 4); hl.setSpacing(4)
        self.btn_print_sld    = _act('SLD',        '#0078d4',
                                     'Print single line diagram (with voltage drop)')
        self.btn_conduit      = _act('Conduit',    '#5c2d91', 'Conduit fill sizing tool')
        hl.addWidget(_grp('PRINT',
                          self.btn_print_sld,
                          self.btn_conduit))
        hl.addWidget(_grp_sep())
        self.btn_export_xls  = _act('Excel (.xlsx)', '#107c10', 'Export panel schedule as Excel')
        self.btn_export_dxf  = _act('DXF',           '#c06800', 'Export SLD as DXF (AutoCAD)')
        hl.addWidget(_grp('EXPORT', self.btn_export_xls, self.btn_export_dxf))
        hl.addStretch()
        return w

    def _band_help(self):
        w  = QWidget()
        hl = QHBoxLayout(w); hl.setContentsMargins(8, 4, 8, 4); hl.setSpacing(4)
        self.btn_about    = _act('About',          '#2d5a8a', 'About VoltFlow')
        self.btn_support  = _act('Report Issue',   '#c42b1c', 'Open issue tracker')
        hl.addWidget(_grp('HELP', self.btn_about, self.btn_support))
        hl.addStretch()
        return w


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APP WINDOW
# ─────────────────────────────────────────────────────────────────────────────

class MainAppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('VoltFlow')
        self.setMinimumSize(1380, 820)

        self._project: C_Project  = None
        self._sw                  = None   # SwitchboardWindow instance
        self._active_pkg: C_Package = None

        self._build()
        self._connect_ribbon()
        self._show_tab('PROJECT')

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        vl   = QVBoxLayout(root)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self._ribbon = RibbonWidget()
        vl.addWidget(self._ribbon)

        self._stack = QStackedWidget()
        vl.addWidget(self._stack, 1)

        # Page 0 — PROJECT
        self._proj_tab = ProjectTab()
        self._proj_tab.open_package_requested.connect(self._on_open_pkg)
        self._proj_tab.project_changed.connect(self._on_project_changed)
        self._proj_tab.open_recent_requested.connect(self._open_recent_project)
        self._stack.addWidget(self._proj_tab)

        # Page 1 — NETWORK (placeholder until a board is loaded)
        self._net_placeholder = self._mk_net_placeholder()
        self._stack.addWidget(self._net_placeholder)

        # Page 2 — CALCULATE (delegated to NETWORK + summary)
        self._calc_page = self._mk_calc_page()
        self._stack.addWidget(self._calc_page)

        # Page 3 — REPORTS (delegated to NETWORK print actions)
        self._rep_page = self._mk_reports_page()
        self._stack.addWidget(self._rep_page)

        # Page 4 — HELP
        self._help_page = self._mk_help_page()
        self._stack.addWidget(self._help_page)

    def _mk_net_placeholder(self):
        w  = QWidget()
        vl = QVBoxLayout(w)
        lbl = QLabel('Open a board file or a project package to begin designing.')
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet('color:#888;font-size:14pt;')
        vl.addStretch()
        vl.addWidget(lbl)
        open_btn = QPushButton('Open Board (.swb)…')
        open_btn.setFixedSize(220, 36)
        open_btn.setStyleSheet(
            'QPushButton{background:#0078d4;color:#fff;font-weight:bold;'
            'font-size:11pt;border:none;border-radius:3px;}'
            'QPushButton:hover{background:#005fa3;}')
        open_btn.clicked.connect(self._load_standalone)
        align = QWidget(); ah = QHBoxLayout(align)
        ah.addStretch(); ah.addWidget(open_btn); ah.addStretch()
        vl.addWidget(align)
        vl.addStretch()
        return w

    def _mk_calc_page(self):
        w  = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 20, 20, 20); vl.setSpacing(12)
        hdr = QLabel('Calculation results — errors and warnings from the full project tree')
        hdr.setStyleSheet('color:#333;font-size:11pt;font-weight:bold;')
        hdr.setWordWrap(True)
        hint = QLabel(
            'Run Calc All or Calc Selected from the ribbon, then review all messages here.')
        hint.setStyleSheet('color:#555;font-size:10pt;')
        hint.setWordWrap(True)
        self._calc_log = QTextEdit()
        self._calc_log.setReadOnly(True)
        self._calc_log.setMinimumHeight(160)
        self._calc_log.setStyleSheet(
            'font-family:"Courier New";font-size:10pt;color:#1a1a1a;'
            'background:#f8f9fc;padding:10px;border:1px solid #c8cfe8;'
            'border-radius:2px;')
        self._calc_log.setPlaceholderText(
            'No calculation results yet. Open a board and run Calc All.')
        from .vdrop_override_panel import VdropOverridePanel
        self._vdrop_override = VdropOverridePanel()
        self._vdrop_override.setMinimumHeight(180)
        self._vdrop_override.apply_requested.connect(self._apply_vdrop_overrides)
        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(6)
        log_wrap = QWidget()
        log_vl = QVBoxLayout(log_wrap)
        log_vl.setContentsMargins(0, 0, 0, 0)
        log_vl.addWidget(hdr)
        log_vl.addWidget(hint)
        log_vl.addWidget(self._calc_log, 1)
        split.addWidget(log_wrap)
        split.addWidget(self._vdrop_override)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        vl.addWidget(split, 1)
        return w

    def _mk_reports_page(self):
        w  = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 20, 20, 20)
        lbl = QLabel('Select a report from the ribbon to generate output.')
        lbl.setStyleSheet('color:#555;font-size:11pt;')
        vl.addWidget(lbl)
        vl.addStretch()
        return w

    def _mk_help_page(self):
        w  = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(40, 40, 40, 40); vl.setSpacing(16)
        title = QLabel('VoltFlow')
        title.setStyleSheet('font-size:20pt;font-weight:bold;color:#1a3a5c;')
        sub   = QLabel(
            f'VoltFlow v{APP_VERSION} — KSA LV distribution design (60 Hz)\n\n'
            'Features: board hierarchy, cable selection, CB sizing & coordination,\n'
            'phase balancing, voltage-drop chain, panel schedule, SLD, DXF export.\n\n'
            'Multi-engineer workflow: federated project packages with locking,\n'
            'stage-gate snapshots, revision history, and interface cable tracking.'
        )
        sub.setStyleSheet('font-size:11pt;color:#444;')
        sub.setWordWrap(True)
        vl.addWidget(title)
        vl.addWidget(sub)
        vl.addStretch()
        return w

    # ── Connect ribbon buttons ────────────────────────────────────────────────

    def _connect_ribbon(self):
        rb = self._ribbon

        # Tab navigation
        for name in RibbonWidget.TABS:
            rb._tabs[name].clicked.connect(
                lambda checked, n=name: self._show_tab(n))

        # PROJECT tab
        rb.btn_new_project.clicked.connect(self._new_project)
        rb.btn_open_project.clicked.connect(self._open_project)
        rb.btn_save_project.clicked.connect(self._save_all)
        rb.btn_close_proj.clicked.connect(self._close_project)
        rb.btn_new_pkg.clicked.connect(self._proj_tab._new_pkg)
        rb.btn_open_pkg.clicked.connect(self._proj_tab._open_pkg)
        rb.btn_lock_pkg.clicked.connect(self._proj_tab._lock_pkg)
        rb.btn_history.clicked.connect(self._proj_tab._show_history)
        rb.btn_snaps.clicked.connect(self._proj_tab._show_snaps)

        # NETWORK tab — wired after board loaded (see _wire_network)

        # CALCULATE tab
        rb.btn_crun_all.clicked.connect(self._calc_all)
        rb.btn_crun_sel.clicked.connect(self._calc_sel)
        rb.btn_cbalance.clicked.connect(self._calc_balance)
        rb.btn_cspare.clicked.connect(self._calc_spare)

        # REPORTS tab
        rb.btn_print_sld.clicked.connect(self._print_sld)
        rb.btn_conduit.clicked.connect(self._open_conduit)
        rb.btn_export_xls.clicked.connect(self._export_xls)
        rb.btn_export_dxf.clicked.connect(self._export_dxf)

        # HELP
        rb.btn_about.clicked.connect(self._show_about)
        rb.btn_support.clicked.connect(lambda: None)

    def _wire_network(self):
        """Wire ribbon NETWORK buttons to the loaded SwitchboardWindow."""
        if self._sw is None:
            return
        sw_id = id(self._sw)
        if getattr(self, '_wired_sw_id', None) == sw_id:
            return
        rb = self._ribbon
        pairs = [
            (rb.btn_add_feeder, self._sw._add_feeder),
            (rb.btn_add_sub, self._sw._add_subpanel),
            (rb.btn_remove, self._sw._del_row),
            (rb.btn_board_set, self._sw._board_settings),
            (rb.btn_calc_all, self._calc_all),
            (rb.btn_calc_sel, self._calc_sel),
            (rb.btn_balance, self._sw._balance_phases),
            (rb.btn_spare, self._sw._gen_spare_space),
            (rb.btn_save_board, self._sw._save),
            (rb.btn_load_board, self._load_standalone),
            (rb.btn_save_as, self._sw._save_as),
            (rb.btn_set_spec, self._sw._set_stub_spec),
            (rb.btn_export_sub, self._sw._export_subboard),
            (rb.btn_import_sub, self._sw._import_subboard),
        ]
        for btn, slot in getattr(self, '_wired_btn_slots', ()):
            disconnect_signal(btn.clicked, slot)
        self._wired_btn_slots = pairs
        for btn, slot in pairs:
            btn.clicked.connect(slot)
        self._wired_sw_id = sw_id

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _show_tab(self, name: str, *, refresh_calc: bool = True):
        self._ribbon.select_tab(name)
        page_map = {
            'PROJECT': 0,
            'NETWORK': 1,
            'CALCULATE': 2,
            'REPORTS': 3,
            'HELP': 4,
        }
        if name in ('CALCULATE', 'REPORTS') and self._sw is None:
            self._set_status('Open a board first to use this tab.')
        idx = page_map.get(name, 0)
        self._stack.setCurrentIndex(idx)
        if name == 'CALCULATE' and refresh_calc:
            self._populate_calc_page()

    def _clear_calc_page(self) -> None:
        """Blank the CALCULATE tab while a run is in progress."""
        if not hasattr(self, '_calc_log'):
            return
        self._calc_log.clear()
        self._calc_log.setPlainText('Calculating…')
        if hasattr(self, '_vdrop_override'):
            self._vdrop_override.clear_pending()

    def _populate_calc_page(self) -> None:
        """Replace CALCULATE tab content with the current error/warning set."""
        if self._sw is None:
            self._calc_log.clear()
            self._calc_log.setPlainText('No board loaded.')
            return
        from .status_messages import collect_messages, format_calc_page_text
        root = self._sw._root
        errors, warnings = collect_messages(root)
        self._calc_log.clear()
        self._calc_log.setPlainText(format_calc_page_text(root, errors, warnings))
        boards = root.all_boards()
        feeders = [f for b in boards for f in b.feeders
                   if f.load_type not in ('Space', 'Spare')]
        worst_vd = max((f.result_vdrop_pct for f in feeders if f.result_vdrop_pct),
                       default=0)
        max_bus = max((b.busbar_loading for b in boards), default=0)
        rb = self._ribbon
        rb.kpi_boards.setText(str(len(boards)))
        rb.kpi_feeders.setText(str(len(feeders)))
        rb.kpi_worst_vd.setText(f'{worst_vd:.2f}%')
        rb.kpi_max_bus.setText(f'{max_bus:.1f}%')
        if hasattr(self, '_vdrop_override'):
            self._vdrop_override.refresh(
                root, self._sw._min_conductor_mm2)

    def _apply_vdrop_overrides(self):
        if self._sw is None:
            return
        overrides = self._vdrop_override.collect_override_requests()
        if not overrides:
            return
        n = self._sw.apply_vdrop_train_overrides(overrides)
        if n > 0:
            self._populate_calc_page()
            self._show_tab('CALCULATE', refresh_calc=False)

    def _update_calc_summary(self):
        """Refresh CALCULATE tab (manual tab switch)."""
        self._populate_calc_page()

    # ── Project actions ───────────────────────────────────────────────────────

    def _new_project(self):
        dlg = NewProjectDialog(self)
        if dlg.exec() != QDialog.Accepted: return
        v = dlg.values()
        if not v['folder']:
            QMessageBox.warning(self, 'No folder', 'Please select a project folder.')
            return
        proj              = C_Project()
        proj.name         = v['name']
        proj.client       = v['client']
        proj.location     = v['location']
        proj.standard     = v['standard']
        proj.project_dir  = v['folder']
        if v['engineer']:
            eng = proj.add_engineer(v['engineer'])
        proj.save()
        self._load_project(proj)
        self._set_status(f'Project "{proj.name}" created.')

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open Project', '', 'VoltFlow Project (*.vsproj)')
        if not path: return
        try:
            proj = C_Project.load(path)
            self._load_project(proj)
            self._set_status(f'Project "{proj.name}" opened.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to open project:\n{e}')

    def _open_recent_project(self, path: str):
        try:
            proj = C_Project.load(path)
            self._load_project(proj)
            self._set_status(f'Project "{proj.name}" opened.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to open project:\n{e}')

    def _load_project(self, proj: C_Project):
        self._project = proj
        self._proj_tab.load_project(proj)
        self._proj_tab.update_recent(proj.name, proj.vsproj_path())
        self._ribbon.set_context(f'{proj.name}  ·  {proj.client}')
        self._show_tab('PROJECT')

    def _save_project(self):
        if self._project is None: return
        self._project.touch()
        self._project.save()
        self._proj_tab.update_recent(self._project.name, self._project.vsproj_path())
        self._set_status(f'Project saved: {self._project.vsproj_path()}')

    def _close_project(self):
        if self._project is None: return
        ans = QMessageBox.question(self, 'Close project',
                                   'Save project before closing?',
                                   QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if ans == QMessageBox.Cancel: return
        if ans == QMessageBox.Yes: self._save_project()
        self._project = None
        self._proj_tab.load_project(None) if hasattr(self._proj_tab, '_project') else None
        self._ribbon.set_context('')
        self._set_status('Project closed.')

    def _on_project_changed(self):
        if self._project:
            self._ribbon.set_context(
                f'{self._project.name}  ·  {self._project.client}')
            if self._sw is not None:
                self._sw._min_conductor_mm2 = self._project.min_conductor_mm2
                self._sw._min_cb_A          = self._project.min_cb_A
                self._sw.set_df_settings(
                    getattr(self._project, 'df_mode', 'per_load'),
                    getattr(self._project, 'project_df_pct', 100.0))
                from vdrop_settings import VdropProjectSettings
                self._sw.set_vd_settings(
                    VdropProjectSettings.from_project(self._project))
            if self._project.project_dir:
                self._project.touch()
                self._project.save()

    # ── Package open ──────────────────────────────────────────────────────────

    def _on_open_pkg(self, pkg_id: str, swb_path: str):
        """Open a package .swb for editing in the NETWORK tab."""
        pkg = self._project.find_package(pkg_id) if self._project else None
        if pkg and pkg.is_locked() and not pkg.is_lock_stale():
            if pkg.locked_by != self._proj_tab._current_user:
                QMessageBox.warning(
                    self, 'Locked',
                    f'Package is locked by {pkg.locked_by}.\n'
                    f'Ask them to release the lock, or wait until the lock expires.')
                return
        self._open_board_file(swb_path)
        if pkg: self._active_pkg = pkg

    def _load_standalone(self):
        """Open a .swb file without a project context."""
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open Board', '',
            'Switchboard file (*.swb);;All files (*)')
        if not path: return
        self._open_board_file(path)

    def _open_board_file(self, path: str):
        try:
            if os.path.exists(path):
                board = C_Switchboard.load(path)
            else:
                # New board — apply project standard's default frequency
                board = C_Switchboard(
                    standard=PROJECT_STANDARD, frequency=KSA_FREQUENCY_HZ)
            self._load_sw(board, path)
            self._set_status(f'Board loaded: {path}')
            self._show_tab('NETWORK')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to open board:\n{e}')

    def _load_sw(self, board: C_Switchboard, path: str = ''):
        """Instantiate (or replace) the SwitchboardWindow widget."""
        from .switchboard_window import SwitchboardWindow
        if self._sw is not None:
            self._stack.removeWidget(self._sw)
            self._sw.deleteLater()
            self._sw = None

        min_mm2 = self._project.min_conductor_mm2 if self._project else 1.5
        min_cb  = self._project.min_cb_A          if self._project else 6.0
        df_mode = getattr(self._project, 'df_mode', 'per_load') if self._project else 'per_load'
        df_pct  = getattr(self._project, 'project_df_pct', 100.0) if self._project else 100.0
        from vdrop_settings import VdropProjectSettings
        vd_set  = (VdropProjectSettings.from_project(self._project)
                   if self._project else VdropProjectSettings())
        self._sw = SwitchboardWindow(
            board, min_conductor_mm2=min_mm2, min_cb_A=min_cb,
            df_mode=df_mode, project_df_pct=df_pct,
            vd_settings=vd_set, parent=self)
        self._sw._file = path or None
        # Errors/warnings shown once on the switchboard status bar (no app duplicate).
        # Replace stack page 1
        self._stack.insertWidget(1, self._sw)
        # Remove old placeholder if still there
        if self._net_placeholder.parent() == self._stack:
            self._stack.removeWidget(self._net_placeholder)
        self._wire_network()
        ctx = os.path.basename(path) if path else board.name
        self._ribbon.set_context(
            (f'{self._project.name}  ·  ' if self._project else '')
            + ctx
        )

    # ── Calc tab delegates ────────────────────────────────────────────────────

    def _begin_calc_run(self) -> None:
        """Clear CALCULATE tab before a user-initiated calc run."""
        self._clear_calc_page()
        self._show_tab('CALCULATE', refresh_calc=False)

    def _finish_calc_run(self) -> None:
        """Populate CALCULATE tab with results from the latest calc only."""
        self._populate_calc_page()

    def _calc_all(self):
        if self._sw is None:
            return
        self._begin_calc_run()
        self._sw._calc_all()
        self._finish_calc_run()

    def _calc_sel(self):
        if self._sw is None:
            return
        self._begin_calc_run()
        self._sw._calc_selected()
        self._finish_calc_run()

    def _calc_balance(self):
        if self._sw is None: return
        self._sw._balance_phases()
        self._show_tab('NETWORK')

    def _calc_spare(self):
        if self._sw is None: return
        self._sw._gen_spare_space()
        self._show_tab('NETWORK')

    # ── Report delegates ──────────────────────────────────────────────────────

    def _print_sld(self):
        if self._sw is None:
            QMessageBox.information(
                self, 'SLD', 'Open a board first (NETWORK tab), then run SLD.')
            return
        self._sw._print_sld()

    def _open_conduit(self):
        from .conduit_dialog import ConduitDialog
        root = self._sw._root if self._sw else None
        dlg  = ConduitDialog(root_board=root, parent=self)
        dlg.exec()

    def _export_xls(self):
        if self._sw is None:
            QMessageBox.information(
                self, 'Export', 'Open a board first, then export Excel.')
            return
        self._sw._export_xls()

    def _export_dxf(self):
        if self._sw is None:
            QMessageBox.information(
                self, 'DXF', 'Open a board first, then export DXF.')
            return
        self._sw._export_dxf()
    # ── Help ──────────────────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.about(
            self,
            'About VoltFlow',
            f'<b>VoltFlow</b> v{APP_VERSION}<br><br>'
            'KSA LV distribution design (60 Hz).<br><br>'
            'Board hierarchy, cable selection, CB sizing &amp; coordination, '
            'phase balancing, voltage-drop chain, panel schedules, SLD, and DXF export.<br><br>'
            'Multi-engineer workflow: federated project packages with locking, '
            'snapshots, and interface tracking.',
        )
        self._show_tab('HELP')

    # ── Close ─────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        has_project = self._project is not None
        has_board   = self._sw is not None

        if has_project or has_board:
            name = self._project.name if has_project else (
                os.path.basename(self._sw._file) if (has_board and self._sw._file)
                else 'Untitled board')
            ans = QMessageBox.question(
                self, 'Save before closing?',
                f'Save changes to "{name}" before closing VoltFlow?',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if ans == QMessageBox.Cancel:
                event.ignore()
                return
            if ans == QMessageBox.Save:
                self._save_all()

        # Release lock and stamp last-edited regardless of save choice
        if has_project:
            self._project.touch()
            if self._active_pkg is not None:
                self._project.unlock_package(
                    self._active_pkg.id,
                    self._proj_tab._current_user, force=False)
            try:
                self._project.save()
            except Exception as e:
                QMessageBox.warning(
                    self, 'Save failed',
                    f'Could not save project on exit:\n{e}')

        event.accept()

    def _save_all(self):
        """Save both the open board and the project manifest."""
        if self._sw is not None:
            if self._sw._file:
                try:
                    self._sw._root.save(self._sw._file)
                except Exception as e:
                    QMessageBox.warning(self, 'Save failed',
                                        f'Could not save board:\n{e}')
            else:
                self._sw._save_as()   # prompt for path if never saved

        if self._project is not None:
            self._project.touch()
            try:
                self._project.save()
            except Exception as e:
                QMessageBox.warning(self, 'Save failed',
                                    f'Could not save project:\n{e}')

    # ── Status (switchboard window only — no duplicate app-level bar) ─────────

    def _apply_app_status(self, text: str, tooltip: str,
                          has_errors: bool, has_warnings: bool):
        pass

    def _set_status(self, msg: str):
        pass
