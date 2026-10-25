# ui/vdrop_override_panel.py — manual upsize train for ΔU violations (L0 → Load)
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFrame, QScrollArea, QMessageBox, QSizePolicy,
    QToolButton,
)
from PySide6.QtCore import Signal, Qt

from vdrop_optimizer import (
    collect_vdrop_failure_loads,
    VdropFailureLoad,
    FeedPathStep,
)


class _HopRow(QFrame):
    """One hop in the L0 → Load cable train."""

    changed = Signal()

    def __init__(self, step: FeedPathStep, parent=None):
        super().__init__(parent)
        self._step = step
        self.setFrameShape(QFrame.Shape.NoFrame)
        over = step.seg_vdrop_pct > step.limit_pct + 1e-6
        bg = '#fff5f5' if over else '#ffffff'
        border = '#e8c4c4' if over else '#e4e8ef'
        self.setStyleSheet(
            f'QFrame{{background:{bg};border:1px solid {border};border-radius:4px;}}')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        badge = QLabel(step.step_label)
        badge.setFixedWidth(56)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            'font-weight:bold;color:#1a3a5c;background:#e8eef5;'
            'border-radius:3px;padding:3px 0;')
        lay.addWidget(badge)

        circuit = 'INC' if step.is_primary else step.circuit_ref
        loc = QLabel(f'{step.board_name} / {circuit}')
        loc.setFixedWidth(150)
        loc.setStyleSheet('color:#333;')
        lay.addWidget(loc)

        cur = QLabel(step.current_display.replace(' mm²', ''))
        cur.setFixedWidth(72)
        cur.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        cur.setStyleSheet('color:#555;')
        lay.addWidget(cur)

        arrow = QLabel('→')
        arrow.setFixedWidth(14)
        arrow.setStyleSheet('color:#888;font-weight:bold;')
        lay.addWidget(arrow)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(130)
        self._combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for display, sz, n_par in step.options:
            self._combo.addItem(display, (sz, n_par))
        self._combo.setProperty('board_id', step.board_id)
        self._combo.setProperty('is_primary', step.is_primary)
        self._combo.setProperty('circuit_ref', step.circuit_ref)
        self._combo.setProperty('current_mm2', step.current_mm2)
        self._combo.setProperty('current_parallel', step.current_parallel)
        self._combo.currentIndexChanged.connect(self._emit_changed)
        lay.addWidget(self._combo, 1)

        self._btn_step = QToolButton()
        self._btn_step.setText('+1')
        self._btn_step.setToolTip('Upsize one catalogue step')
        self._btn_step.setFixedWidth(34)
        self._btn_step.clicked.connect(self._step_up)
        lay.addWidget(self._btn_step)

        vd_color = '#b00020' if over else '#2e7d32'
        vd = QLabel(f'ΔUc {step.seg_vdrop_pct:.2f}%')
        vd.setFixedWidth(78)
        vd.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vd.setStyleSheet(f'color:{vd_color};font-size:9pt;')
        lay.addWidget(vd)

        if step.locked:
            lock = QLabel('locked')
            lock.setStyleSheet('color:#888;font-size:8pt;font-style:italic;')
            lay.addWidget(lock)

    @property
    def combo(self) -> QComboBox:
        return self._combo

    def _emit_changed(self):
        self.changed.emit()

    def _step_up(self):
        if self._combo.currentIndex() + 1 < self._combo.count():
            self._combo.setCurrentIndex(self._combo.currentIndex() + 1)

    def reset(self):
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(0)
        self._combo.blockSignals(False)

    def is_changed(self) -> bool:
        data = self._combo.currentData()
        if not data:
            return False
        sz, n_par = data
        cur_sz = self._combo.property('current_mm2')
        cur_n = self._combo.property('current_parallel')
        return sz * n_par > cur_sz * cur_n + 1e-6 or n_par > cur_n


def collect_hop_overrides(hop_rows: list[_HopRow]) -> list[dict]:
    out: list[dict] = []
    for row in hop_rows:
        if not row.is_changed():
            continue
        combo = row.combo
        sz, n_par = combo.currentData()
        out.append({
            'board_id': combo.property('board_id'),
            'is_primary': bool(combo.property('is_primary')),
            'circuit_ref': combo.property('circuit_ref'),
            'size_mm2': float(sz),
            'n_parallel': int(n_par),
        })
    return out


class VdropOverridePanel(QWidget):
    """Per-load cable upsize train: Level 0 … Level N … Load."""

    apply_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._failures: list[VdropFailureLoad] = []
        self._hop_rows: list[_HopRow] = []
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr = QLabel('Voltage-drop overrides')
        hdr.setStyleSheet('font-weight:bold;color:#1a3a5c;font-size:10pt;')
        hdr_row.addWidget(hdr)
        hdr_row.addStretch()
        self._pending_lbl = QLabel('')
        self._pending_lbl.setStyleSheet('color:#5c2d91;font-size:9pt;font-weight:bold;')
        hdr_row.addWidget(self._pending_lbl)
        outer.addLayout(hdr_row)

        load_row = QHBoxLayout()
        load_row.addWidget(QLabel('Load:'))
        self._load_combo = QComboBox()
        self._load_combo.setMinimumWidth(320)
        self._load_combo.currentIndexChanged.connect(self._on_load_changed)
        load_row.addWidget(self._load_combo, 1)
        outer.addLayout(load_row)

        self._issue_lbl = QLabel('')
        self._issue_lbl.setStyleSheet('color:#8b0000;font-size:9pt;')
        self._issue_lbl.setWordWrap(True)
        outer.addWidget(self._issue_lbl)

        col_hdr = QHBoxLayout()
        col_hdr.setContentsMargins(10, 0, 10, 0)
        col_hdr.setSpacing(10)
        for text, width in (
            ('Hop', 56), ('Location', 150), ('Current', 72), ('', 14),
            ('New size [mm²]', 130), ('+1', 34), ('Segment', 78),
        ):
            lbl = QLabel(text)
            if width:
                lbl.setFixedWidth(width)
            lbl.setStyleSheet('color:#666;font-size:8pt;font-weight:bold;')
            col_hdr.addWidget(lbl)
            if text == 'New size [mm²]':
                col_hdr.addStretch(1)
        self._col_hdr_widget = QWidget()
        self._col_hdr_widget.setLayout(col_hdr)
        outer.addWidget(self._col_hdr_widget)

        self._train_host = QWidget()
        self._train_layout = QVBoxLayout(self._train_host)
        self._train_layout.setContentsMargins(0, 0, 0, 0)
        self._train_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._train_host)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(100)
        scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._train_scroll = scroll
        outer.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        self._btn_reset = QPushButton('Reset')
        self._btn_reset.setToolTip('Revert all hops to current automatic sizes')
        self._btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self._btn_reset)
        btn_row.addStretch()
        self._btn_apply = QPushButton('Apply overrides && Recalculate')
        self._btn_apply.setStyleSheet(
            'QPushButton{background:#5c2d91;color:white;padding:6px 16px;'
            'font-weight:bold;border-radius:3px;}')
        self._btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(self._btn_apply)
        outer.addLayout(btn_row)

        self._empty_lbl = QLabel(
            'No voltage-drop violations — run Calc All first.')
        self._empty_lbl.setStyleSheet('color:#666;font-style:italic;font-size:9pt;')
        outer.addWidget(self._empty_lbl)

        self._set_visible_train(False)

    def _set_visible_train(self, on: bool):
        for w in (self._train_scroll, self._btn_apply, self._btn_reset,
                  self._load_combo, self._issue_lbl, self._col_hdr_widget,
                  self._pending_lbl):
            w.setVisible(on)
        self._empty_lbl.setVisible(not on)

    def clear_pending(self) -> None:
        self._failures = []
        self._load_combo.blockSignals(True)
        self._load_combo.clear()
        self._load_combo.blockSignals(False)
        self._clear_train()
        self._issue_lbl.clear()
        self._pending_lbl.clear()
        self._set_visible_train(False)

    def refresh(self, root, min_conductor_mm2: float = 1.5) -> None:
        self._failures = collect_vdrop_failure_loads(root, min_conductor_mm2)
        self._load_combo.blockSignals(True)
        self._load_combo.clear()
        for fl in self._failures:
            board_nm = fl.path[-1].board_name if fl.path else fl.board_id
            if fl.circuit_ref == 'INC':
                text = (f'{fl.name}  ·  ΔUc {fl.seg_pct:.2f}% / '
                        f'{fl.limit_pct:.1f}%')
            else:
                text = (f'{fl.name}  ·  {board_nm}/{fl.circuit_ref}  ·  '
                        f'ΔU {fl.total_pct:.2f}% / {fl.limit_pct:.1f}%')
            self._load_combo.addItem(text, fl)
        self._load_combo.blockSignals(False)
        if self._failures:
            self._set_visible_train(True)
            self._on_load_changed(0)
        else:
            self._set_visible_train(False)
            self._clear_train()

    def _clear_train(self):
        while self._train_layout.count():
            item = self._train_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._hop_rows.clear()
        self._update_pending_label()

    def _on_load_changed(self, index: int):
        if index < 0 or index >= len(self._failures):
            self._clear_train()
            return
        fl = self._failures[index]
        self._issue_lbl.setText('  ·  '.join(fl.issues))
        self._clear_train()
        for i, step in enumerate(fl.path):
            if i > 0:
                sep = QLabel('↓')
                sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sep.setStyleSheet('color:#aab;font-size:10pt;')
                self._train_layout.addWidget(sep)
            row = _HopRow(step)
            row.changed.connect(self._update_pending_label)
            self._train_layout.addWidget(row)
            self._hop_rows.append(row)
        self._train_layout.addStretch(1)
        self._update_pending_label()

    def _update_pending_label(self):
        n = sum(1 for r in self._hop_rows if r.is_changed())
        if n:
            self._pending_lbl.setText(
                f'{n} override{"s" if n != 1 else ""} pending')
        else:
            self._pending_lbl.clear()

    def _on_reset(self):
        for row in self._hop_rows:
            row.reset()
        self._update_pending_label()

    def collect_override_requests(self) -> list[dict]:
        return collect_hop_overrides(self._hop_rows)

    def _on_apply(self):
        if not self._hop_rows:
            return
        overrides = self.collect_override_requests()
        if not overrides:
            QMessageBox.information(
                self, 'No changes',
                'Pick a larger size (+1 or dropdown) on at least one hop.')
            return
        self.apply_requested.emit()
