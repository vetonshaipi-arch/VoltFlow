# project_class.py — VoltFlow
# Multi-engineer, multi-package project model.
# A Project is a manifest (.vsproj) referencing Package files (.swb).
# Each Package is one zone/area, owned by one engineer at a time.

import json, os, uuid, shutil
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

STATUS_LIST = [
    'Draft', '15%', '30%', '60%', '90%', '100%',
    'Issued for Construction', 'As-Built',
]
PROJECT_STANDARD = 'KSA'
KSA_FREQUENCY_HZ = 60.0
# Legacy alias — VoltFlow is KSA-only (60 Hz).
STANDARDS = (PROJECT_STANDARD,)


def normalize_project_standard(value: str | None) -> str:
    return PROJECT_STANDARD
LOCK_STALE_HOURS = 8.0


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


# ─────────────────────────────────────────────────────────────────────────────
# ENGINEER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class C_Engineer:
    id:       str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name:     str = ''
    initials: str = ''
    email:    str = ''
    company:  str = ''

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ['id', 'name', 'initials', 'email', 'company']}

    @staticmethod
    def from_dict(d: dict) -> 'C_Engineer':
        o = C_Engineer()
        for k, v in d.items():
            if hasattr(o, k): setattr(o, k, v)
        return o

    def __str__(self) -> str:
        return self.name or self.initials or self.id


# ─────────────────────────────────────────────────────────────────────────────
# REVISION ENTRY
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class C_RevisionEntry:
    date:     str = field(default_factory=_now)
    user:     str = ''
    pkg_id:   str = ''
    action:   str = ''
    snapshot: str = ''  # snapshot basename, '' if no freeze

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ['date', 'user', 'pkg_id', 'action', 'snapshot']}

    @staticmethod
    def from_dict(d: dict) -> 'C_RevisionEntry':
        o = C_RevisionEntry()
        for k, v in d.items():
            if hasattr(o, k): setattr(o, k, v)
        return o


# ─────────────────────────────────────────────────────────────────────────────
# INTERFACE (cross-package connection)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class C_Interface:
    id:            str   = field(default_factory=lambda: uuid.uuid4().hex[:8])
    from_pkg_id:   str   = ''
    from_board_id: str   = ''
    to_pkg_id:     str   = ''
    to_board_id:   str   = ''
    Isc_kA:        float = 0.0
    voltage:       float = 400.0
    description:   str   = ''
    stale:         bool  = False  # True when upstream changed since last sync

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ['id', 'from_pkg_id', 'from_board_id',
                 'to_pkg_id', 'to_board_id',
                 'Isc_kA', 'voltage', 'description', 'stale']}

    @staticmethod
    def from_dict(d: dict) -> 'C_Interface':
        o = C_Interface()
        for k, v in d.items():
            if hasattr(o, k): setattr(o, k, v)
        return o


# ─────────────────────────────────────────────────────────────────────────────
# COMMENT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class C_Comment:
    id:       str  = field(default_factory=lambda: uuid.uuid4().hex[:8])
    pkg_id:   str  = ''
    board_id: str  = ''
    user:     str  = ''
    date:     str  = field(default_factory=_now)
    text:     str  = ''
    resolved: bool = False

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ['id', 'pkg_id', 'board_id', 'user', 'date', 'text', 'resolved']}

    @staticmethod
    def from_dict(d: dict) -> 'C_Comment':
        o = C_Comment()
        for k, v in d.items():
            if hasattr(o, k): setattr(o, k, v)
        return o


# ─────────────────────────────────────────────────────────────────────────────
# PACKAGE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class C_Package:
    id:            str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name:          str = 'Package-A'
    zone:          str = 'A'
    rel_path:      str = ''      # path to .swb relative to project folder
    engineer_id:   str = ''
    status:        str = 'Draft'
    locked_by:     str = ''      # engineer name; '' = not locked
    locked_at:     str = ''      # ISO datetime of lock
    last_modified: str = field(default_factory=_now)
    description:   str = ''

    # ── Lock ──────────────────────────────────────────────────────────────────

    def is_locked(self) -> bool:
        return bool(self.locked_by)

    def lock(self, user: str) -> None:
        self.locked_by = user
        self.locked_at = datetime.now().isoformat(timespec='seconds')

    def unlock(self) -> None:
        self.locked_by = ''
        self.locked_at = ''

    def is_lock_stale(self, hours: float = LOCK_STALE_HOURS) -> bool:
        if not self.locked_at:
            return False
        try:
            locked = datetime.fromisoformat(self.locked_at)
            return (datetime.now() - locked).total_seconds() > hours * 3600
        except Exception:
            return False

    def lock_summary(self) -> str:
        if not self.locked_by:
            return ''
        stale = ' (stale)' if self.is_lock_stale() else ''
        return f'{self.locked_by}{stale}'

    # ── Serialise ─────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ['id', 'name', 'zone', 'rel_path', 'engineer_id',
                 'status', 'locked_by', 'locked_at',
                 'last_modified', 'description']}

    @staticmethod
    def from_dict(d: dict) -> 'C_Package':
        o = C_Package()
        for k, v in d.items():
            if hasattr(o, k): setattr(o, k, v)
        return o


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class C_Project:
    id:          str  = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name:        str  = 'New Project'
    client:      str  = ''
    location:    str  = ''
    standard:    str  = PROJECT_STANDARD
    status:      str  = 'Draft'
    created:     str  = field(default_factory=_now)
    last_edited: str  = field(default_factory=_now)
    project_dir: str  = ''  # absolute path to project folder
    min_conductor_mm2: float = 1.5                     # project-wide minimum cable size
    min_cb_A:          float = 6.0                     # project-wide minimum CB rating
    df_mode:           str   = 'per_load'              # 'per_load' | 'project'
    project_df_pct:    float = 100.0                   # L0 incomer DF when df_mode=='project'
    # Voltage drop policy
    vd_mode:           str   = 'per_load'              # per-circuit ΔU limits
    vd_pct_light:      float = 3.0
    vd_pct_motor:      float = 5.0
    vd_pct_socket:     float = 5.0
    vd_pct_hvac:       float = 5.0
    vd_pct_other:      float = 5.0
    vd_pct_subpanel:   float = 5.0
    opt_max_iterations: int  = 30
    opt_voltage_passes: int  = 3
    engineers:   list = field(default_factory=list)   # [C_Engineer]
    packages:    list = field(default_factory=list)   # [C_Package]
    interfaces:  list = field(default_factory=list)   # [C_Interface]
    history:     list = field(default_factory=list)   # [C_RevisionEntry]
    comments:    list = field(default_factory=list)   # [C_Comment]

    # ── Engineers ─────────────────────────────────────────────────────────────

    def add_engineer(self, name: str, initials: str = '',
                     email: str = '', company: str = '') -> C_Engineer:
        e = C_Engineer(name=name, initials=initials,
                       email=email, company=company)
        self.engineers.append(e)
        return e

    def remove_engineer(self, eid: str) -> None:
        self.engineers = [e for e in self.engineers if e.id != eid]

    def find_engineer(self, eid: str) -> Optional[C_Engineer]:
        return next((e for e in self.engineers if e.id == eid), None)

    def engineer_name(self, eid: str) -> str:
        e = self.find_engineer(eid)
        return e.name if e else ''

    # ── Packages ──────────────────────────────────────────────────────────────

    def add_package(self, name: str, zone: str,
                    engineer_id: str = '',
                    status: str = 'Draft') -> C_Package:
        safe = name.replace(' ', '_').replace('/', '-')
        rel  = f'pkg_{zone}_{safe}.swb'
        pkg  = C_Package(name=name, zone=zone, rel_path=rel,
                         engineer_id=engineer_id, status=status,
                         last_modified=_now())
        self.packages.append(pkg)
        self._log(pkg.id, '', f'Package "{name}" created')
        return pkg

    def remove_package(self, pkg_id: str) -> None:
        self.packages = [p for p in self.packages if p.id != pkg_id]

    def find_package(self, pkg_id: str) -> Optional[C_Package]:
        return next((p for p in self.packages if p.id == pkg_id), None)

    def pkg_swb_path(self, pkg: C_Package) -> str:
        return os.path.join(self.project_dir, pkg.rel_path)

    # ── Lock / Unlock ─────────────────────────────────────────────────────────

    def lock_package(self, pkg_id: str, user: str) -> tuple[bool, str]:
        pkg = self.find_package(pkg_id)
        if pkg is None:
            return False, 'Package not found.'
        if pkg.is_locked():
            if pkg.is_lock_stale():
                pkg.unlock()   # auto-release stale lock
            else:
                return False, f'Locked by {pkg.locked_by}.'
        pkg.lock(user)
        self._log(pkg_id, user, f'Package locked by {user}')
        self.save()
        return True, ''

    def unlock_package(self, pkg_id: str, user: str = '',
                       force: bool = False) -> bool:
        pkg = self.find_package(pkg_id)
        if pkg is None:
            return False
        if pkg.is_locked() and not force and pkg.locked_by != user:
            return False
        was = pkg.locked_by
        pkg.unlock()
        self._log(pkg_id, user or was, 'Package unlocked')
        self.save()
        return True

    # ── Status & Snapshots ────────────────────────────────────────────────────

    def set_package_status(self, pkg_id: str, status: str, user: str,
                           freeze: bool = True) -> str:
        """Change package status, optionally freeze a snapshot. Returns snapshot path."""
        pkg = self.find_package(pkg_id)
        if pkg is None:
            return ''
        snap_path = ''
        if freeze:
            snap_path = self._freeze_snapshot(pkg, status)
        old = pkg.status
        pkg.status        = status
        pkg.last_modified = _now()
        snap_name = os.path.basename(snap_path) if snap_path else ''
        self._log(pkg_id, user,
                  f'Status {old} → {status}',
                  snap_name)
        self.save()
        return snap_path

    def _freeze_snapshot(self, pkg: C_Package, label: str) -> str:
        src = self.pkg_swb_path(pkg)
        if not os.path.exists(src):
            return ''
        snap_dir = os.path.join(self.project_dir, 'snapshots')
        os.makedirs(snap_dir, exist_ok=True)
        safe_label = label.replace('%', 'pct').replace(' ', '_')
        base       = os.path.splitext(os.path.basename(pkg.rel_path))[0]
        dst        = os.path.join(snap_dir, f'{base}_{safe_label}.swb')
        shutil.copy2(src, dst)
        return dst

    def list_snapshots(self, pkg_id: str) -> list:
        pkg = self.find_package(pkg_id)
        if pkg is None:
            return []
        snap_dir = os.path.join(self.project_dir, 'snapshots')
        if not os.path.exists(snap_dir):
            return []
        base = os.path.splitext(os.path.basename(pkg.rel_path))[0]
        return sorted(
            f for f in os.listdir(snap_dir) if f.startswith(base)
        )

    # ── Interfaces ────────────────────────────────────────────────────────────

    def add_interface(self, from_pkg: str, from_board: str,
                      to_pkg: str,   to_board: str,
                      Isc_kA: float = 0.0, voltage: float = 400.0,
                      description: str = '') -> C_Interface:
        iface = C_Interface(
            from_pkg_id=from_pkg, from_board_id=from_board,
            to_pkg_id=to_pkg,     to_board_id=to_board,
            Isc_kA=Isc_kA,        voltage=voltage,
            description=description,
        )
        self.interfaces.append(iface)
        return iface

    def mark_interfaces_stale(self, pkg_id: str) -> None:
        for iface in self.interfaces:
            if iface.from_pkg_id == pkg_id:
                iface.stale = True

    def stale_interfaces(self) -> list:
        return [i for i in self.interfaces if i.stale]

    # ── Comments ──────────────────────────────────────────────────────────────

    def add_comment(self, pkg_id: str, board_id: str,
                    user: str, text: str) -> C_Comment:
        c = C_Comment(pkg_id=pkg_id, board_id=board_id,
                      user=user, text=text)
        self.comments.append(c)
        return c

    def resolve_comment(self, comment_id: str) -> None:
        for c in self.comments:
            if c.id == comment_id:
                c.resolved = True

    def open_comments(self, pkg_id: str = '') -> list:
        return [c for c in self.comments
                if not c.resolved
                and (not pkg_id or c.pkg_id == pkg_id)]

    # ── History ───────────────────────────────────────────────────────────────

    def _log(self, pkg_id: str, user: str,
             action: str, snapshot: str = '') -> None:
        self.history.append(C_RevisionEntry(
            date=_now(), user=user, pkg_id=pkg_id,
            action=action, snapshot=snapshot,
        ))

    def history_for(self, pkg_id: str = '') -> list:
        if not pkg_id:
            return list(reversed(self.history))
        return list(reversed([h for h in self.history
                               if h.pkg_id == pkg_id]))

    # ── Touch / Save ──────────────────────────────────────────────────────────

    def touch(self) -> None:
        self.last_edited = _now()

    def vsproj_path(self) -> str:
        safe = self.name.replace(' ', '_').replace('/', '-')
        return os.path.join(self.project_dir, f'{safe}.vsproj')

    def save(self, path: str = '') -> None:
        if path:
            self.project_dir = os.path.dirname(os.path.abspath(path))
        dst = path or self.vsproj_path()
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, 'snapshots'),
                    exist_ok=True)
        with open(dst, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            'id':                 self.id,
            'name':               self.name,
            'client':             self.client,
            'location':           self.location,
            'standard':           self.standard,
            'status':             self.status,
            'created':            self.created,
            'last_edited':        self.last_edited,
            'min_conductor_mm2':  self.min_conductor_mm2,
            'min_cb_A':           self.min_cb_A,
            'df_mode':            self.df_mode,
            'project_df_pct':     self.project_df_pct,
            'vd_mode':            self.vd_mode,
            'vd_pct_light':       self.vd_pct_light,
            'vd_pct_motor':       self.vd_pct_motor,
            'vd_pct_socket':      self.vd_pct_socket,
            'vd_pct_hvac':        self.vd_pct_hvac,
            'vd_pct_other':       self.vd_pct_other,
            'vd_pct_subpanel':    self.vd_pct_subpanel,
            'opt_max_iterations': self.opt_max_iterations,
            'opt_voltage_passes': self.opt_voltage_passes,
            'engineers':   [e.to_dict() for e in self.engineers],
            'packages':    [p.to_dict() for p in self.packages],
            'interfaces':  [i.to_dict() for i in self.interfaces],
            'history':     [h.to_dict() for h in self.history],
            'comments':    [c.to_dict() for c in self.comments],
        }

    @staticmethod
    def load(path: str) -> 'C_Project':
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        p = C_Project()
        for k in ['id', 'name', 'client', 'location', 'standard',
                   'status', 'created', 'last_edited',
                   'min_conductor_mm2', 'min_cb_A',
                   'df_mode', 'project_df_pct',
                   'vd_mode', 'vd_pct_light', 'vd_pct_motor', 'vd_pct_socket',
                   'vd_pct_hvac', 'vd_pct_other', 'vd_pct_subpanel',
                   'opt_max_iterations', 'opt_voltage_passes']:
            if k in d:
                setattr(p, k, d[k])
        p.standard = normalize_project_standard(p.standard)
        p.project_dir = os.path.dirname(os.path.abspath(path))
        p.engineers  = [C_Engineer.from_dict(e)      for e in d.get('engineers',  [])]
        p.packages   = [C_Package.from_dict(pk)      for pk in d.get('packages',  [])]
        p.interfaces = [C_Interface.from_dict(i)     for i  in d.get('interfaces',[])]
        p.history    = [C_RevisionEntry.from_dict(h) for h  in d.get('history',   [])]
        p.comments   = [C_Comment.from_dict(c)       for c  in d.get('comments',  [])]
        return p

    def __repr__(self) -> str:
        return (f"C_Project('{self.name}' | {self.client} | "
                f"{len(self.packages)} packages | {self.status})")
