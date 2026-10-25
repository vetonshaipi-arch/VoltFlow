# ui/project_tab.py — PROJECT tab content widget
import os, sys, json
from datetime import datetime
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
    QSplitter, QGroupBox, QTextEdit, QMessageBox, QFileDialog,
    QFrame, QCheckBox, QSizePolicy, QScrollArea, QStackedWidget,
    QDoubleSpinBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont

from project_class import (
    C_Project, C_Package, C_Engineer,
    STATUS_LIST, PROJECT_STANDARD, KSA_FREQUENCY_HZ, _now,
)

STATUS_COLORS = {
    'Draft':                   '#888888',
    '15%':                     '#e67e00',
    '30%':                     '#d4a000',
    '60%':                     '#0070c0',
    '90%':                     '#5c2d91',
    '100%':                    '#107c10',
    'Issued for Construction': '#c42b1c',
    'As-Built':                '#1a3a5c',
}


def _mono(size=10):
    from .qt_helpers import app_font
    return app_font('Courier New', size)

def _btn(text, color='#0078d4', tip=''):
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f'QPushButton{{background:{color};color:#fff;border:none;'
        f'font-weight:bold;padding:4px 12px;border-radius:2px;}}'
        f'QPushButton:hover{{background:{color};border:1px solid rgba(255,255,255,0.55);'
        f'padding:3px 11px;}}'
        f'QPushButton:disabled{{background:#aaa;color:#eee;}}'
    )
    return b


# ─────────────────────────────────────────────────────────────────────────────
# Engineer dialog
# ─────────────────────────────────────────────────────────────────────────────

class EngineerDialog(QDialog):
    def __init__(self, engineer: C_Engineer = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Engineer' if engineer else 'New Engineer')
        self.setMinimumWidth(360)
        fl = QFormLayout(self)
        self._name    = QLineEdit(engineer.name    if engineer else '')
        self._init    = QLineEdit(engineer.initials if engineer else '')
        self._email   = QLineEdit(engineer.email   if engineer else '')
        self._company = QLineEdit(engineer.company  if engineer else '')
        fl.addRow('Name',     self._name)
        fl.addRow('Initials', self._init)
        fl.addRow('Email',    self._email)
        fl.addRow('Company',  self._company)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        fl.addRow(bb)

    def values(self):
        return (self._name.text().strip(),
                self._init.text().strip(),
                self._email.text().strip(),
                self._company.text().strip())


# ─────────────────────────────────────────────────────────────────────────────
# New Package dialog
# ─────────────────────────────────────────────────────────────────────────────

class NewPackageDialog(QDialog):
    def __init__(self, project: C_Project, parent=None):
        super().__init__(parent)
        self.setWindowTitle('New Package')
        self.setMinimumWidth(380)
        fl = QFormLayout(self)
        self._name = QLineEdit('Package-A')
        self._zone = QLineEdit('A')
        self._zone.setMaximumWidth(60)
        self._desc = QLineEdit()
        self._eng  = QComboBox()
        self._eng.addItem('— unassigned —', '')
        for e in project.engineers:
            self._eng.addItem(e.name, e.id)
        self._status = QComboBox()
        self._status.addItems(STATUS_LIST)
        fl.addRow('Package name', self._name)
        fl.addRow('Zone / Area',  self._zone)
        fl.addRow('Description',  self._desc)
        fl.addRow('Engineer',     self._eng)
        fl.addRow('Status',       self._status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        fl.addRow(bb)

    def values(self):
        return (self._name.text().strip(),
                self._zone.text().strip() or 'A',
                self._eng.currentData() or '',
                self._status.currentText(),
                self._desc.text().strip())


# ─────────────────────────────────────────────────────────────────────────────
# History panel
# ─────────────────────────────────────────────────────────────────────────────

class HistoryPanel(QDialog):
    def __init__(self, project: C_Project, pkg_id: str = '', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Revision History')
        self.setMinimumSize(640, 400)
        vl = QVBoxLayout(self)
        tbl = QTableWidget()
        tbl.setColumnCount(5)
        tbl.setHorizontalHeaderLabels(['Date', 'User', 'Package', 'Action', 'Snapshot'])
        tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.verticalHeader().setVisible(False)
        entries = project.history_for(pkg_id)
        tbl.setRowCount(len(entries))
        for ri, h in enumerate(entries):
            pkg = project.find_package(h.pkg_id)
            pkg_name = pkg.name if pkg else h.pkg_id
            for ci, val in enumerate([h.date, h.user, pkg_name, h.action, h.snapshot]):
                item = QTableWidgetItem(val)
                item.setFont(_mono(9))
                tbl.setItem(ri, ci, item)
            tbl.setRowHeight(ri, 22)
        vl.addWidget(tbl)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        vl.addWidget(close)


# ─────────────────────────────────────────────────────────────────────────────
# Snapshots panel
# ─────────────────────────────────────────────────────────────────────────────

class SnapshotPanel(QDialog):
    def __init__(self, project: C_Project, pkg: C_Package, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Snapshots — {pkg.name}')
        self.setMinimumSize(500, 300)
        vl = QVBoxLayout(self)
        snaps = project.list_snapshots(pkg.id)
        lbl = QLabel(f'{len(snaps)} snapshot(s) for package "{pkg.name}"')
        lbl.setStyleSheet('font-weight:bold;')
        vl.addWidget(lbl)
        tbl = QTableWidget()
        tbl.setColumnCount(2)
        tbl.setHorizontalHeaderLabels(['Snapshot file', 'Size'])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.verticalHeader().setVisible(False)
        tbl.setRowCount(len(snaps))
        snap_dir = os.path.join(project.project_dir, 'snapshots')
        for ri, s in enumerate(snaps):
            path = os.path.join(snap_dir, s)
            sz   = f'{os.path.getsize(path)//1024} KB' if os.path.exists(path) else '—'
            tbl.setItem(ri, 0, QTableWidgetItem(s))
            tbl.setItem(ri, 1, QTableWidgetItem(sz))
            tbl.setRowHeight(ri, 22)
        vl.addWidget(tbl)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        vl.addWidget(close)


# ─────────────────────────────────────────────────────────────────────────────
# Recent projects persistence
# ─────────────────────────────────────────────────────────────────────────────

_RECENT_FILE = os.path.join(os.path.expanduser('~'), '.voltflow', 'recent_projects.json')
_MAX_RECENT  = 20


class RecentProjects:
    @staticmethod
    def load() -> list:
        try:
            with open(_RECENT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    @staticmethod
    def add(name: str, path: str) -> None:
        entries = RecentProjects.load()
        entries = [e for e in entries if e.get('path') != path]
        entries.insert(0, {
            'name':   name,
            'path':   path,
            'opened': datetime.now().strftime('%Y-%m-%d %H:%M'),
        })
        entries = entries[:_MAX_RECENT]
        os.makedirs(os.path.dirname(_RECENT_FILE), exist_ok=True)
        with open(_RECENT_FILE, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=2)

    @staticmethod
    def remove(path: str) -> None:
        entries = [e for e in RecentProjects.load() if e.get('path') != path]
        os.makedirs(os.path.dirname(_RECENT_FILE), exist_ok=True)
        with open(_RECENT_FILE, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT TAB WIDGET
# ─────────────────────────────────────────────────────────────────────────────

class ProjectTab(QWidget):
    open_package_requested = Signal(str, str)   # pkg_id, swb_path
    project_changed        = Signal()
    open_recent_requested  = Signal(str)         # .vsproj path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: C_Project = None
        self._current_user: str  = ''
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(self._mk_project_bar())
        vl.addWidget(self._mk_body(), 1)

    def _mk_project_bar(self):
        bar = QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet('background:#1a3a5c;')
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(12, 6, 12, 6)
        hl.setSpacing(8)

        self._lbl_proj = QLabel('No project open')
        self._lbl_proj.setStyleSheet(
            'color:#fff;font-size:14pt;font-weight:bold;')
        self._lbl_meta = QLabel('')
        self._lbl_meta.setStyleSheet('color:#8ab4d4;font-size:9pt;')
        hl.addWidget(self._lbl_proj)
        hl.addWidget(self._lbl_meta)
        hl.addStretch()

        self._user_le = QLineEdit()
        self._user_le.setPlaceholderText('Your name (engineer)')
        self._user_le.setFixedWidth(180)
        self._user_le.setStyleSheet(
            'background:#0d2137;color:#fff;border:1px solid #355;padding:2px 6px;')
        self._user_le.textChanged.connect(lambda t: setattr(self, '_current_user', t.strip()))
        hl.addWidget(QLabel('<span style="color:#8ab4d4;font-size:9pt;">Engineer:</span>'))
        hl.addWidget(self._user_le)
        return bar

    def _mk_body(self):
        sp = QSplitter(Qt.Horizontal)

        # ── Left: stacked (recent projects | package grid) ─────────────────
        self._left_stack = QStackedWidget()

        # Page 0 — recent projects (shown when no project is open)
        self._left_stack.addWidget(self._mk_recent_panel())

        # Page 1 — package grid (shown when a project is loaded)
        left = QWidget()
        lv   = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.setSpacing(4)

        # Package toolbar
        pt = QHBoxLayout()
        self._btn_new_pkg  = _btn('+ Package',    '#107c10', 'Add a new package/zone')
        self._btn_open_pkg = _btn('Open',          '#0078d4', 'Open selected package for editing')
        self._btn_lock_pkg = _btn('Lock',          '#e67e00', 'Lock package for exclusive editing')
        self._btn_unlock   = _btn('Unlock',        '#888',    'Release lock')
        self._btn_status   = _btn('Set Status',   '#5c2d91', 'Change status & freeze snapshot')
        self._btn_snaps    = _btn('Snapshots',     '#1a6b8a', 'View snapshots for this package')
        self._btn_history  = _btn('History',       '#444',    'View revision log')
        self._btn_del_pkg  = _btn('Remove',        '#c42b1c', 'Remove package from project')

        for b in [self._btn_new_pkg, self._btn_open_pkg,
                  self._btn_lock_pkg, self._btn_unlock,
                  self._btn_status, self._btn_snaps,
                  self._btn_history, self._btn_del_pkg]:
            pt.addWidget(b)
        pt.addStretch()
        lv.addLayout(pt)

        # Package table
        self._pkg_tbl = QTableWidget()
        self._pkg_tbl.setColumnCount(7)
        self._pkg_tbl.setHorizontalHeaderLabels(
            ['Zone', 'Package Name', 'Engineer', 'Status', 'Locked By', 'Last Modified', 'File'])
        hdr = self._pkg_tbl.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.Stretch)
        self._pkg_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pkg_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pkg_tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self._pkg_tbl.setAlternatingRowColors(True)
        self._pkg_tbl.verticalHeader().setVisible(False)
        self._pkg_tbl.verticalHeader().setDefaultSectionSize(24)
        self._pkg_tbl.setFont(_mono(9))
        self._pkg_tbl.selectionModel().selectionChanged.connect(self._on_pkg_sel)
        self._pkg_tbl.doubleClicked.connect(self._open_pkg)
        lv.addWidget(self._pkg_tbl, 1)
        self._left_stack.addWidget(left)   # page 1
        sp.addWidget(self._left_stack)

        # ── Right: project info + engineers + interfaces ───────────────────
        right = QWidget()
        rv    = QVBoxLayout(right)
        rv.setContentsMargins(4, 8, 8, 8)
        rv.setSpacing(8)

        # Project info group
        info_box = QGroupBox('Project Info')
        info_fl  = QFormLayout(info_box)
        info_fl.setSpacing(4)
        self._fi_name     = QLineEdit()
        self._fi_client   = QLineEdit()
        self._fi_location = QLineEdit()
        self._fi_standard    = QLabel(f'{PROJECT_STANDARD} · {KSA_FREQUENCY_HZ:.0f} Hz')
        self._fi_standard.setStyleSheet('font-weight:bold;')
        self._fi_status      = QComboBox(); self._fi_status.addItems(STATUS_LIST)
        self._fi_min_cond    = QComboBox()
        self._fi_min_cond.addItems(['1.5 mm²', '2.5 mm²', '4 mm²'])
        self._fi_min_cb      = QComboBox()
        self._fi_min_cb.addItems(['6 A', '10 A', '16 A', '20 A'])
        self._fi_df_mode = QComboBox()
        self._fi_df_mode.addItem('Per load', 'per_load')
        self._fi_df_mode.addItem('Project overall (L0 only)', 'project')
        self._fi_project_df = QLineEdit('100')
        self._fi_project_df.setMaximumWidth(56)
        self._fi_project_df.setPlaceholderText('%')
        self._fi_vd_hint = QLabel(
            'Per-circuit defaults (editable on each feeder / incomer):')
        self._fi_vd_hint.setStyleSheet('color:#555;font-size:9pt;')
        self._vd_spin = {}
        for key, label, default in [
            ('vd_pct_light', 'Lighting', 3.0),
            ('vd_pct_motor', 'Motor', 5.0),
            ('vd_pct_socket', 'Socket', 5.0),
            ('vd_pct_hvac', 'HVAC', 5.0),
            ('vd_pct_other', 'Other', 5.0),
            ('vd_pct_subpanel', 'Sub-panel', 5.0),
        ]:
            vd_sp = QDoubleSpinBox()
            vd_sp.setRange(0.1, 20.0)
            vd_sp.setDecimals(1)
            vd_sp.setSingleStep(0.5)
            vd_sp.setValue(default)
            vd_sp.setSuffix(' %')
            vd_sp.setMaximumWidth(72)
            vd_sp.valueChanged.connect(self._push_info)
            self._vd_spin[key] = vd_sp
        self._fi_created  = QLabel()
        self._fi_edited   = QLabel()
        for w in [self._fi_name, self._fi_client, self._fi_location]:
            w.textChanged.connect(self._push_info)
        self._fi_status.currentTextChanged.connect(self._push_info)
        self._fi_min_cond.currentIndexChanged.connect(self._push_info)
        self._fi_min_cb.currentIndexChanged.connect(self._push_info)
        self._fi_df_mode.currentIndexChanged.connect(self._on_df_mode_ui)
        self._fi_project_df.textChanged.connect(self._push_info)
        info_fl.addRow('Name',              self._fi_name)
        info_fl.addRow('Client',            self._fi_client)
        info_fl.addRow('Location',          self._fi_location)
        info_fl.addRow('Region',            self._fi_standard)
        info_fl.addRow('Status',            self._fi_status)
        info_fl.addRow('Min. Conductor',    self._fi_min_cond)
        info_fl.addRow('Min. CB Size',      self._fi_min_cb)
        info_fl.addRow('Demand factor',     self._fi_df_mode)
        df_row = QHBoxLayout()
        df_row.setContentsMargins(0, 0, 0, 0)
        df_row.addWidget(QLabel('L0 overall DF'))
        df_row.addWidget(self._fi_project_df)
        df_row.addWidget(QLabel('%'))
        df_row.addStretch()
        info_fl.addRow('',                  df_row)
        info_fl.addRow('Voltage drop',      self._fi_vd_hint)
        for key, label, _ in [
            ('vd_pct_light', 'Lighting ΔU', 3.0),
            ('vd_pct_motor', 'Motor ΔU', 5.0),
            ('vd_pct_socket', 'Socket ΔU', 5.0),
            ('vd_pct_hvac', 'HVAC ΔU', 5.0),
            ('vd_pct_other', 'Other ΔU', 5.0),
            ('vd_pct_subpanel', 'Sub-panel ΔU', 5.0),
        ]:
            info_fl.addRow(label, self._vd_spin[key])
        info_fl.addRow('Created',           self._fi_created)
        info_fl.addRow('Edited',            self._fi_edited)
        rv.addWidget(info_box)

        # Engineers group
        eng_box = QGroupBox('Engineers')
        ev      = QVBoxLayout(eng_box)
        et      = QHBoxLayout()
        self._btn_add_eng  = _btn('+ Engineer',  '#107c10')
        self._btn_edit_eng = _btn('Edit',         '#0078d4')
        self._btn_del_eng  = _btn('Remove',       '#c42b1c')
        et.addWidget(self._btn_add_eng)
        et.addWidget(self._btn_edit_eng)
        et.addWidget(self._btn_del_eng)
        et.addStretch()
        ev.addLayout(et)
        self._eng_tbl = QTableWidget()
        self._eng_tbl.setColumnCount(4)
        self._eng_tbl.setHorizontalHeaderLabels(['Name', 'Initials', 'Email', 'Company'])
        self._eng_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._eng_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._eng_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._eng_tbl.verticalHeader().setVisible(False)
        self._eng_tbl.verticalHeader().setDefaultSectionSize(22)
        self._eng_tbl.setFixedHeight(130)
        ev.addWidget(self._eng_tbl)
        rv.addWidget(eng_box)

        # Interface warnings
        self._iface_lbl = QLabel('')
        self._iface_lbl.setWordWrap(True)
        self._iface_lbl.setStyleSheet(
            'color:#c42b1c;font-size:8pt;font-style:italic;')
        rv.addWidget(self._iface_lbl)
        rv.addStretch()

        sp.addWidget(right)
        sp.setSizes([700, 340])

        # Connect package toolbar buttons
        self._btn_new_pkg.clicked.connect(self._new_pkg)
        self._btn_open_pkg.clicked.connect(self._open_pkg)
        self._btn_lock_pkg.clicked.connect(self._lock_pkg)
        self._btn_unlock.clicked.connect(self._unlock_pkg)
        self._btn_status.clicked.connect(self._set_status)
        self._btn_snaps.clicked.connect(self._show_snaps)
        self._btn_history.clicked.connect(self._show_history)
        self._btn_del_pkg.clicked.connect(self._del_pkg)

        self._btn_add_eng.clicked.connect(self._add_eng)
        self._btn_edit_eng.clicked.connect(self._edit_eng)
        self._btn_del_eng.clicked.connect(self._del_eng)

        self._set_pkg_btns_enabled(False)
        return sp

    # ── Recent projects panel ─────────────────────────────────────────────────

    def _mk_recent_panel(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet('background:#f0f4f8;')
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 20, 20, 16)
        vl.setSpacing(10)

        title = QLabel('RECENT PROJECTS')
        title.setStyleSheet(
            'font-size:11pt;font-weight:bold;color:#1a3a5c;'
            'letter-spacing:2px;padding-bottom:6px;'
            'border-bottom:2px solid #1a3a5c;background:transparent;')
        vl.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet('background:transparent;')
        self._recent_container = QWidget()
        self._recent_container.setStyleSheet('background:transparent;')
        self._recent_vl = QVBoxLayout(self._recent_container)
        self._recent_vl.setContentsMargins(0, 4, 0, 4)
        self._recent_vl.setSpacing(4)
        self._recent_vl.addStretch()
        scroll.setWidget(self._recent_container)
        vl.addWidget(scroll, 1)

        self._refresh_recent_list()
        return w

    def _refresh_recent_list(self):
        # Clear all but the trailing stretch
        while self._recent_vl.count() > 1:
            item = self._recent_vl.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        entries = RecentProjects.load()
        if not entries:
            lbl = QLabel('No recent projects yet.\nOpen or create a project to get started.')
            lbl.setStyleSheet('color:#888;font-style:italic;padding:16px 4px;background:transparent;')
            lbl.setWordWrap(True)
            self._recent_vl.insertWidget(0, lbl)
            return

        for entry in entries:
            self._recent_vl.insertWidget(
                self._recent_vl.count() - 1,
                self._mk_recent_item(entry))

    def _mk_recent_item(self, entry: dict) -> QFrame:
        path   = entry.get('path', '')
        name   = entry.get('name', os.path.basename(path))
        opened = entry.get('opened', '')
        exists = os.path.exists(path)

        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setCursor(Qt.PointingHandCursor if exists else Qt.ArrowCursor)
        frame.setStyleSheet(
            'QFrame{background:#ffffff;border:1px solid #d0d8e0;border-radius:4px;}'
            'QFrame:hover{background:#e8f0f8;border-color:#1a3a5c;}' if exists else
            'QFrame{background:#f5f5f5;border:1px solid #ddd;border-radius:4px;}')

        hl = QHBoxLayout(frame)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(8)

        icon = QLabel('📁' if exists else '⚠')
        icon.setStyleSheet('font-size:14pt;background:transparent;border:none;')
        icon.setFixedWidth(24)
        hl.addWidget(icon)

        info = QVBoxLayout(); info.setSpacing(1)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f'font-weight:bold;font-size:10pt;background:transparent;border:none;'
            f'color:{"#1a3a5c" if exists else "#999"};')
        path_lbl = QLabel(path)
        path_lbl.setStyleSheet(
            'color:#888;font-size:8pt;background:transparent;border:none;')
        path_lbl.setWordWrap(False)
        info.addWidget(name_lbl)
        info.addWidget(path_lbl)
        hl.addLayout(info, 1)

        date_lbl = QLabel(opened)
        date_lbl.setStyleSheet(
            'color:#aaa;font-size:8pt;background:transparent;border:none;')
        date_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(date_lbl)

        if exists:
            frame.mousePressEvent = lambda _e, p=path: self._open_recent(p)
        else:
            warn = QLabel('  (not found)')
            warn.setStyleSheet('color:#c42b1c;font-size:8pt;background:transparent;border:none;')
            hl.addWidget(warn)

        return frame

    def _open_recent(self, path: str):
        if not os.path.exists(path):
            QMessageBox.warning(self, 'Not found',
                                f'Project file no longer exists:\n{path}\n\nRemoving from list.')
            RecentProjects.remove(path)
            self._refresh_recent_list()
            return
        self.open_recent_requested.emit(path)

    def update_recent(self, name: str, path: str):
        """Call after any project open or save to keep the list current."""
        RecentProjects.add(name, path)
        self._refresh_recent_list()

    # ── Load project into UI ──────────────────────────────────────────────────

    def load_project(self, project: C_Project) -> None:
        self._project = project
        if project is None:
            self._lbl_proj.setText('No project open')
            self._lbl_meta.setText('')
            self._left_stack.setCurrentIndex(0)   # show recent projects
            self._refresh_recent_list()
            return
        self._left_stack.setCurrentIndex(1)        # show package table
        self._refresh_info()
        self._refresh_pkg_table()
        self._refresh_eng_table()
        self._refresh_iface_warnings()
        self._set_pkg_btns_enabled(False)

    _MIN_COND_VALUES = [1.5, 2.5, 4.0]
    _MIN_CB_VALUES   = [6.0, 10.0, 16.0, 20.0]

    def _refresh_info(self):
        p = self._project
        if p is None: return
        vd_widgets = list(self._vd_spin.values())
        for w in [self._fi_name, self._fi_client, self._fi_location,
                  self._fi_status,
                  self._fi_min_cond, self._fi_min_cb,
                  self._fi_df_mode, self._fi_project_df] + vd_widgets:
            w.blockSignals(True)
        self._fi_name.setText(p.name)
        self._fi_client.setText(p.client)
        self._fi_location.setText(p.location)
        self._fi_standard.setText(f'{PROJECT_STANDARD} · {KSA_FREQUENCY_HZ:.0f} Hz')
        self._fi_status.setCurrentText(p.status)
        cond_idx = self._MIN_COND_VALUES.index(p.min_conductor_mm2) \
                   if p.min_conductor_mm2 in self._MIN_COND_VALUES else 0
        self._fi_min_cond.setCurrentIndex(cond_idx)
        cb_idx = self._MIN_CB_VALUES.index(p.min_cb_A) \
                 if p.min_cb_A in self._MIN_CB_VALUES else 0
        self._fi_min_cb.setCurrentIndex(cb_idx)
        idx_df = self._fi_df_mode.findData(getattr(p, 'df_mode', 'per_load'))
        self._fi_df_mode.setCurrentIndex(idx_df if idx_df >= 0 else 0)
        self._fi_project_df.setText(
            f'{getattr(p, "project_df_pct", 100.0):.0f}')
        self._on_df_mode_ui()
        for key, sp in self._vd_spin.items():
            sp.setValue(float(getattr(p, key, sp.value())))
        p.vd_mode = 'per_load'
        self._fi_created.setText(p.created)
        self._fi_edited.setText(p.last_edited)
        for w in [self._fi_name, self._fi_client, self._fi_location,
                  self._fi_status,
                  self._fi_min_cond, self._fi_min_cb,
                  self._fi_df_mode, self._fi_project_df] + vd_widgets:
            w.blockSignals(False)
        self._lbl_proj.setText(p.name)
        self._lbl_meta.setText(
            f'{p.client}  ·  {p.location}  ·  {p.standard}  ·  {p.status}')

    def _refresh_pkg_table(self):
        if self._project is None: return
        pkgs = self._project.packages
        self._pkg_tbl.setRowCount(len(pkgs))
        for ri, pkg in enumerate(pkgs):
            eng  = self._project.engineer_name(pkg.engineer_id)
            lock = pkg.lock_summary()
            vals = [pkg.zone, pkg.name, eng, pkg.status,
                    lock, pkg.last_modified, pkg.rel_path]
            for ci, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, pkg.id)
                if ci == 3:  # status colour
                    col = STATUS_COLORS.get(v, '#444')
                    item.setForeground(QBrush(QColor(col)))
                    f = _mono(9)
                    f.setBold(True)
                    item.setFont(f)
                if ci == 4 and v:  # locked
                    item.setForeground(QBrush(QColor('#c42b1c')))
                self._pkg_tbl.setItem(ri, ci, item)
            self._pkg_tbl.setRowHeight(ri, 24)

    def _refresh_eng_table(self):
        if self._project is None: return
        engs = self._project.engineers
        self._eng_tbl.setRowCount(len(engs))
        for ri, e in enumerate(engs):
            for ci, v in enumerate([e.name, e.initials, e.email, e.company]):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, e.id)
                self._eng_tbl.setItem(ri, ci, item)
            self._eng_tbl.setRowHeight(ri, 22)

    def _refresh_iface_warnings(self):
        if self._project is None: return
        stale = self._project.stale_interfaces()
        if stale:
            self._iface_lbl.setText(
                f'⚠  {len(stale)} interface connection(s) are stale — '
                f'upstream package changed since last sync.')
        else:
            self._iface_lbl.setText('')

    # ── Push info back to project ─────────────────────────────────────────────

    def _on_df_mode_ui(self):
        is_proj = (self._fi_df_mode.currentData() == 'project')
        self._fi_project_df.setEnabled(is_proj)

    def _push_info(self):
        if self._project is None: return
        self._project.name               = self._fi_name.text().strip() or self._project.name
        self._project.client             = self._fi_client.text().strip()
        self._project.location           = self._fi_location.text().strip()
        self._project.standard           = PROJECT_STANDARD
        self._project.status             = self._fi_status.currentText()
        self._project.min_conductor_mm2  = self._MIN_COND_VALUES[self._fi_min_cond.currentIndex()]
        self._project.min_cb_A           = self._MIN_CB_VALUES[self._fi_min_cb.currentIndex()]
        self._project.df_mode            = self._fi_df_mode.currentData() or 'per_load'
        try:
            self._project.project_df_pct = float(self._fi_project_df.text().strip() or '100')
        except ValueError:
            self._project.project_df_pct = 100.0
        self._project.project_df_pct = max(0.0, min(100.0, self._project.project_df_pct))
        self._project.vd_mode = 'per_load'
        for key, sp in self._vd_spin.items():
            setattr(self._project, key, round(sp.value(), 1))
        self._lbl_proj.setText(self._project.name)
        self._lbl_meta.setText(
            f'{self._project.client}  ·  {self._project.location}  ·  '
            f'{self._project.standard}  ·  {self._project.status}')
        self.project_changed.emit()

    # ── Package selection ─────────────────────────────────────────────────────

    def _on_pkg_sel(self):
        self._set_pkg_btns_enabled(self._sel_pkg() is not None)

    def _sel_pkg(self) -> C_Package:
        rows = self._pkg_tbl.selectionModel().selectedRows()
        if not rows or self._project is None: return None
        pid = self._pkg_tbl.item(rows[0].row(), 0).data(Qt.UserRole)
        return self._project.find_package(pid)

    def _set_pkg_btns_enabled(self, on: bool):
        for b in [self._btn_open_pkg, self._btn_lock_pkg,
                  self._btn_unlock, self._btn_status,
                  self._btn_snaps, self._btn_history,
                  self._btn_del_pkg]:
            b.setEnabled(on)

    # ── Package actions ───────────────────────────────────────────────────────

    def _new_pkg(self):
        if self._project is None: return
        dlg = NewPackageDialog(self._project, self)
        if dlg.exec() != QDialog.Accepted: return
        name, zone, eid, status, desc = dlg.values()
        if not name: return
        pkg = self._project.add_package(name, zone, eid, status)
        pkg.description = desc
        self._project.save()
        self._refresh_pkg_table()
        self.project_changed.emit()

    def _open_pkg(self):
        pkg = self._sel_pkg()
        if pkg is None or self._project is None: return
        swb = os.path.join(self._project.project_dir, pkg.rel_path)
        self.open_package_requested.emit(pkg.id, swb)

    def _lock_pkg(self):
        pkg = self._sel_pkg()
        if pkg is None: return
        user = self._current_user or 'Unknown'
        ok, msg = self._project.lock_package(pkg.id, user)
        if not ok:
            QMessageBox.warning(self, 'Lock failed', msg)
            return
        self._refresh_pkg_table()

    def _unlock_pkg(self):
        pkg = self._sel_pkg()
        if pkg is None: return
        user = self._current_user or ''
        if pkg.locked_by and pkg.locked_by != user:
            ans = QMessageBox.question(
                self, 'Force unlock',
                f'Package is locked by {pkg.locked_by}.\nForce-unlock?',
                QMessageBox.Yes | QMessageBox.No)
            if ans != QMessageBox.Yes: return
            self._project.unlock_package(pkg.id, user, force=True)
        else:
            self._project.unlock_package(pkg.id, user)
        self._refresh_pkg_table()

    def _set_status(self):
        pkg = self._sel_pkg()
        if pkg is None: return
        dlg = QDialog(self)
        dlg.setWindowTitle('Set Package Status')
        fl  = QFormLayout(dlg)
        cb  = QComboBox(); cb.addItems(STATUS_LIST); cb.setCurrentText(pkg.status)
        freeze = QCheckBox('Freeze snapshot at this stage')
        freeze.setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        fl.addRow('New status', cb)
        fl.addRow('', freeze)
        fl.addRow(bb)
        if dlg.exec() != QDialog.Accepted: return
        user = self._current_user or 'Unknown'
        snap = self._project.set_package_status(
            pkg.id, cb.currentText(), user, freeze.isChecked())
        if snap:
            QMessageBox.information(self, 'Snapshot saved',
                                    f'Snapshot saved:\n{snap}')
        self._refresh_pkg_table()
        self.project_changed.emit()

    def _show_snaps(self):
        pkg = self._sel_pkg()
        if pkg is None: return
        SnapshotPanel(self._project, pkg, self).exec()

    def _show_history(self):
        if self._project is None: return
        pkg = self._sel_pkg()
        HistoryPanel(self._project, pkg.id if pkg else '', self).exec()

    def _del_pkg(self):
        pkg = self._sel_pkg()
        if pkg is None: return
        ans = QMessageBox.question(
            self, 'Remove package',
            f'Remove package "{pkg.name}" from project?\n'
            f'(The .swb file will NOT be deleted.)',
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes: return
        self._project.remove_package(pkg.id)
        self._project.save()
        self._refresh_pkg_table()
        self.project_changed.emit()

    # ── Engineer actions ──────────────────────────────────────────────────────

    def _add_eng(self):
        if self._project is None: return
        dlg = EngineerDialog(parent=self)
        if dlg.exec() != QDialog.Accepted: return
        name, initials, email, company = dlg.values()
        if not name: return
        self._project.add_engineer(name, initials, email, company)
        self._project.save()
        self._refresh_eng_table()

    def _edit_eng(self):
        rows = self._eng_tbl.selectionModel().selectedRows()
        if not rows or self._project is None: return
        eid = self._eng_tbl.item(rows[0].row(), 0).data(Qt.UserRole)
        eng = self._project.find_engineer(eid)
        if eng is None: return
        dlg = EngineerDialog(eng, self)
        if dlg.exec() != QDialog.Accepted: return
        name, initials, email, company = dlg.values()
        if name: eng.name = name
        eng.initials = initials; eng.email = email; eng.company = company
        self._project.save()
        self._refresh_eng_table()
        self._refresh_pkg_table()

    def _del_eng(self):
        rows = self._eng_tbl.selectionModel().selectedRows()
        if not rows or self._project is None: return
        eid = self._eng_tbl.item(rows[0].row(), 0).data(Qt.UserRole)
        self._project.remove_engineer(eid)
        self._project.save()
        self._refresh_eng_table()
