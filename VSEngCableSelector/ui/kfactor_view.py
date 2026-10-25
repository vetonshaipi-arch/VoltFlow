# ui/kfactor_view.py
import os as _os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QButtonGroup, QSpinBox, QDoubleSpinBox,
    QFrame, QGridLayout, QSizePolicy, QComboBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from ..cable_class import C_Cable
from ..cable_data import TC1

_IMG_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


class KFactorView(QWidget):
    k_changed = Signal()

    def __init__(self, cable: C_Cable, parent=None):
        super().__init__(parent)
        self._cable = cable
        self._build_ui()
        self._refresh_result()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(10)

        # Section title
        title = QLabel("DERATING FACTORS")
        title.setStyleSheet(
            "font-size:10pt;font-weight:bold;color:#1a3a5c;"
            "letter-spacing:2px;text-transform:uppercase;"
            "border-top:2px solid #d0d0d0;padding-top:12px;margin-top:6px;"
        )
        layout.addWidget(title)

        layout.addWidget(self._build_k1_block())
        layout.addWidget(self._build_k2_block())
        layout.addWidget(self._build_k3_block())
        self._par_widget = self._build_parallel_section()
        layout.addWidget(self._par_widget)

        self._result_bar = self._build_result_bar()
        layout.addWidget(self._result_bar)

    # ─────────────────────────────────────────────────────────────────────────
    # BLOCK BUILDER HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _block_frame(self) -> tuple[QWidget, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet("QFrame{background:#f5f5f5;border:1px solid #d0d0d0;}")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return frame, layout

    def _block_header(self, badge: str, name: str, val_attr: str) -> tuple[QWidget, QLabel]:
        hdr = QWidget()
        hdr.setStyleSheet("background:#1a3a5c;border-bottom:2px solid #f0a500;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 6, 12, 6); hl.setSpacing(10)
        b = QLabel(badge)
        b.setStyleSheet(
            "background:#f0a500;color:#000;font-size:9pt;font-weight:bold;"
            "padding:2px 8px;letter-spacing:1px;")
        nm = QLabel(name)
        nm.setStyleSheet("font-size:9pt;font-weight:bold;color:#ffffff;letter-spacing:1px;")
        val_lbl = QLabel("?")
        val_lbl.setObjectName(val_attr)
        val_lbl.setStyleSheet("font-family:'Courier New';font-size:11pt;color:#a0c4e0;")
        val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(b); hl.addWidget(nm); hl.addStretch(); hl.addWidget(val_lbl)
        return hdr, val_lbl

    def _body_layout(self) -> tuple[QWidget, QHBoxLayout]:
        body = QWidget()
        body.setStyleSheet("background:#f5f5f5;")
        bl = QHBoxLayout(body); bl.setContentsMargins(14, 12, 14, 12); bl.setSpacing(16)
        return body, bl

    def _sub_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size:8pt;color:#1a3a5c;letter-spacing:1px;"
            "text-transform:uppercase;margin-bottom:2px;")
        return lbl

    def _note(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size:9pt;color:#555555;font-style:italic;"
            "padding:5px 10px;border-left:3px solid #d0d0d0;background:#f0f4f8;"
        )
        lbl.setWordWrap(True)
        return lbl

    def _opt_btns(self, options: list, callback, current=None) -> tuple[QWidget, list]:
        container = QWidget()
        fl = QHBoxLayout(container)
        fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(4); fl.setAlignment(Qt.AlignLeft)
        buttons = []
        for val, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("optBtn")
            btn.setStyleSheet(
                "QPushButton{background:#ffffff;border:1px solid #c0c0c0;color:#1a1a1a;"
                "font-size:9pt;font-weight:600;padding:5px 9px;}"
                "QPushButton:hover{border-color:#1a3a5c;color:#1a3a5c;background:#eef2f7;}"
                "QPushButton:checked{background:#d4edda;border-color:#107c10;color:#107c10;}"
            )
            btn.setCursor(Qt.PointingHandCursor)
            if val == current:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, v=val: callback(v))
            fl.addWidget(btn)
            buttons.append((val, btn))
        return container, buttons

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:9pt;color:#555555;")
        return lbl

    # ─────────────────────────────────────────────────────────────────────────
    # K1 BLOCK
    # ─────────────────────────────────────────────────────────────────────────

    def _build_k1_block(self) -> QWidget:
        frame, fl = self._block_frame()
        hdr, self._k1_val_lbl = self._block_header("k1", "Ambient Temperature", "k1val")
        fl.addWidget(hdr)

        body, bl = self._body_layout()
        illus = self._make_illus_label("🌡")
        bl.addWidget(illus)

        ctrl = QVBoxLayout(); ctrl.setSpacing(6)
        is_air = self._cable.install_method == 'air'
        tbl_note = "Table C.2 — Ambient Air Temperature" if is_air else "Table C.1 — Ambient Ground Temperature"
        ctrl.addWidget(self._sub_title(tbl_note))
        ctrl.addWidget(self._field_label(f"Ambient {'air' if is_air else 'ground'} temperature (°C):"))

        temps = [10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
        t_cont, self._k1_btns = self._opt_btns(
            [(t, f"{t}°C") for t in temps],
            self._on_temp, self._cable.ambient_temp
        )
        flow = QWidget()
        flow_l = self._wrap_flow([btn for _, btn in self._k1_btns], cols=6)
        flow.setLayout(flow_l)
        ctrl.addWidget(flow)

        bl.addLayout(ctrl)
        body.setLayout(bl)
        fl.addWidget(body)
        frame.setLayout(fl)
        return frame

    def _on_temp(self, val):
        self._cable.ambient_temp = val
        self._uncheck_others(self._k1_btns, val)
        self._recalculate()

    # ─────────────────────────────────────────────────────────────────────────
    # K2 BLOCK
    # ─────────────────────────────────────────────────────────────────────────

    def _build_k2_block(self) -> QWidget:
        frame, fl = self._block_frame()
        hdr, self._k2_val_lbl = self._block_header("k2", "Depth & Soil Resistivity", "k2val")
        fl.addWidget(hdr)

        body, bl = self._body_layout()
        illus = self._make_illus_label("⛏")
        bl.addWidget(illus)

        ctrl = QVBoxLayout(); ctrl.setSpacing(6)
        is_air = self._cable.install_method == 'air'

        if is_air:
            ctrl.addWidget(self._note(
                "k2 = 1.000  —  Depth and soil resistivity corrections "
                "do not apply for free air installation (Tables C.3 & C.4)."
            ))
        else:
            ctrl.addWidget(self._sub_title("Table C.3 — Depth of Laying"))
            ctrl.addWidget(self._field_label("Burial depth (m):"))
            depths = [0.50, 0.60, 0.80, 1.00, 1.25, 1.50, 1.75, 2.00]
            d_cont, self._k2_depth_btns = self._opt_btns(
                [(d, f"{d}m") for d in depths], self._on_depth, self._cable.burial_depth
            )
            ctrl.addWidget(d_cont)
            ctrl.addWidget(self._sub_title("Table C.4 — Soil Thermal Resistivity (K·m/W)"))
            ctrl.addWidget(self._field_label("Soil resistivity:"))
            resis = [0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0]
            r_cont, self._k2_res_btns = self._opt_btns(
                [(r, str(r)) for r in resis], self._on_resistivity, self._cable.soil_resistivity
            )
            ctrl.addWidget(r_cont)

        bl.addLayout(ctrl)
        body.setLayout(bl)
        fl.addWidget(body)
        return frame

    def _on_depth(self, val):
        self._cable.burial_depth = val
        self._uncheck_others(self._k2_depth_btns, val)
        self._recalculate()

    def _on_resistivity(self, val):
        self._cable.soil_resistivity = val
        self._uncheck_others(self._k2_res_btns, val)
        self._recalculate()

    # ─────────────────────────────────────────────────────────────────────────
    # K3 BLOCK
    # ─────────────────────────────────────────────────────────────────────────

    def _build_k3_block(self) -> QWidget:
        frame, fl = self._block_frame()
        hdr, self._k3_val_lbl = self._block_header("k3", "Grouping / Circuit Proximity", "k3val")
        fl.addWidget(hdr)

        body = QWidget()
        body.setStyleSheet("background:#f5f5f5;")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(16)

        # Controls on the left (2/3)
        self._k3_ctrl = QVBoxLayout()
        self._k3_ctrl.setSpacing(6)
        ctrl_container = QWidget()
        ctrl_container.setStyleSheet("background:transparent;")
        ctrl_container.setLayout(self._k3_ctrl)
        bl.addWidget(ctrl_container, 2)

        # Image on the right (1/3)
        self._k3_illus = QLabel()
        self._k3_illus.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self._k3_illus.setStyleSheet("background:transparent;border:none;")
        self._k3_illus.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        bl.addWidget(self._k3_illus, 1)

        self._build_k3_controls()

        fl.addWidget(body)
        return frame

    def _build_k3_controls(self):
        method = self._cable.install_method
        is_1c  = self._cable.core_config == '1C'
        while self._k3_ctrl.count():
            item = self._k3_ctrl.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        _CB_SS = ("background:#ffffff;border:1px solid #d0d0d0;color:#1a1a1a;"
                  "padding:3px 6px;font-size:9pt;")

        def _circ_cb(vals, cur):
            """Build a compact, auto-sized QComboBox for circuit counts."""
            cb = QComboBox()
            cb.setStyleSheet(_CB_SS)
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            for v in vals: cb.addItem(str(v), v)
            best = max((v for v in vals if v <= cur), default=vals[0])
            self._cable.num_circuits = best
            cb.setCurrentIndex(cb.findData(best))
            cb.currentIndexChanged.connect(
                lambda _: self._on_num_circuits(cb.currentData()))
            return cb

        _C5_C6_VALS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 16, 20]

        if method == 'buried':
            self._k3_ctrl.addWidget(self._sub_title("Table C.5 — Direct Buried Grouping"))
            self._k3_ctrl.addWidget(self._field_label("Number of circuits:"))
            self._k3_ctrl.addWidget(_circ_cb(_C5_C6_VALS, self._cable.num_circuits))
            if self._cable.num_circuits > 1:
                self._k3_ctrl.addWidget(self._field_label("Circuit-to-circuit clearance:"))
                clr_opts = [('touch','Touching'),('1D','1 Cable Ø'),
                            ('0.125','0.125m'),('0.25','0.25m'),('0.5','0.5m')]
                c_cont, self._k3_clr_btns = self._opt_btns(clr_opts, self._on_clearance, self._cable.clearance)
                self._k3_ctrl.addWidget(c_cont)
            else:
                self._k3_ctrl.addWidget(self._note("Single circuit — k3 = 1.000"))

        elif method == 'duct':
            tbl = "Table C.6" if is_1c else "Table C.7"
            typ = "Single-core in Ducts" if is_1c else "Multi-core in Ducts"
            self._k3_ctrl.addWidget(self._sub_title(f"{tbl} — {typ}"))
            self._k3_ctrl.addWidget(self._field_label("Number of circuits:"))
            duct_vals = _C5_C6_VALS if is_1c else list(range(2, 21))
            self._k3_ctrl.addWidget(_circ_cb(duct_vals, self._cable.num_circuits))
            if self._cable.num_circuits > 1:
                self._k3_ctrl.addWidget(self._field_label("Duct-to-duct clearance:"))
                clr_opts = [('touch','Touching'),('0.25','0.25m'),('0.5','0.5m'),('1.0','1.0m')]
                c_cont, self._k3_clr_btns = self._opt_btns(clr_opts, self._on_clearance, self._cable.clearance)
                self._k3_ctrl.addWidget(c_cont)
            else:
                self._k3_ctrl.addWidget(self._note("Single circuit — k3 = 1.000"))

        elif method == 'air':
            from ..cable_data import TC9_CIRC_IDX, TC8_CABLES_IDX

            tbl = "Table C.9" if is_1c else "Table C.8"
            self._k3_ctrl.addWidget(self._sub_title(
                f"{tbl} — {'Single-core' if is_1c else 'Multi-core'} in Free Air"))

            # Tray types: 1C uses TC9 (no hunperf); MC uses TC8 (hunperf valid)
            if is_1c:
                _tray_opts = [('hperf',  'Horiz. Perforated Tray'),
                              ('vperf',  'Vert. Perforated Tray'),
                              ('ladder', 'Cable Ladder / Cleats')]
                if self._cable.tray_type not in ('hperf', 'vperf', 'ladder'):
                    self._cable.tray_type = 'hperf'
            else:
                _tray_opts = [('hperf',   'Horiz. Perforated Tray'),
                              ('vperf',   'Vert. Perforated Tray'),
                              ('hunperf', 'Horiz. Unperf. Tray'),
                              ('ladder',  'Cable Ladder / Cleats')]
                if self._cable.tray_type not in ('hperf', 'vperf', 'hunperf', 'ladder'):
                    self._cable.tray_type = 'hperf'

            self._k3_ctrl.addWidget(self._field_label("Tray / Support type:"))
            t_cont, self._k3_tray_btns = self._opt_btns(_tray_opts, self._on_tray, self._cable.tray_type)
            self._k3_ctrl.addWidget(t_cont)

            tray   = self._cable.tray_type
            row_w  = QWidget()
            row_l  = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0); row_l.setSpacing(20)

            if is_1c:
                # Formation is fixed by the cable arrangement — no separate selector
                _trefoil_1c = self._cable.arrangement in ('a', 'c', 'e')
                _form_lbl   = 'Trefoil (Spaced)' if _trefoil_1c else 'Flat (Touching)'
                self._k3_ctrl.addWidget(self._note(f"Formation: {_form_lbl} — from arrangement"))

                # Valid trays: TC9 only has 1,2,3 for all types; vperf max 2
                valid_nt = [1, 2] if tray == 'vperf' else [1, 2, 3]
                if self._cable.num_trays not in valid_nt:
                    self._cable.num_trays = valid_nt[-1] if self._cable.num_trays > valid_nt[-1] else valid_nt[0]

                nt_box = QVBoxLayout()
                nt_box.addWidget(self._field_label("Number of trays:"))
                nt_cont, self._k3_nt_btns = self._opt_btns(
                    [(v, str(v)) for v in valid_nt], self._on_num_trays, self._cable.num_trays)
                nt_box.addWidget(nt_cont)
                row_l.addLayout(nt_box)

                # Circuits per tray: vperf flat capped at 2 (no 3-circuit value in TC9)
                cpt_list = [1, 2] if (tray == 'vperf' and not _trefoil_1c) else TC9_CIRC_IDX
                if self._cable.cables_per_tray not in cpt_list:
                    below = [v for v in cpt_list if v <= self._cable.cables_per_tray]
                    self._cable.cables_per_tray = below[-1] if below else cpt_list[0]
                cb_box = QVBoxLayout()
                cb_box.addWidget(self._field_label("Circuits per tray:"))
                cpt_cont, self._k3_cpt_btns = self._opt_btns(
                    [(v, str(v)) for v in cpt_list], self._on_cpt, self._cable.cables_per_tray)
                cb_box.addWidget(cpt_cont)
                row_l.addLayout(cb_box)

            else:
                # MC — spacing selector (touch / spaced)
                spc_opts = [('touch', 'Touching'), ('spaced', 'Spaced')]
                self._k3_ctrl.addWidget(self._field_label("Cable spacing:"))
                s_cont, self._k3_spc_btns = self._opt_btns(spc_opts, self._on_spacing, self._cable.spacing)
                self._k3_ctrl.addWidget(s_cont)

                _spc = self._cable.spacing

                # Valid tray counts (Table C.8)
                _VALID_TRAYS_MC = {
                    'hperf':  [1, 2, 3] if _spc == 'spaced' else [1, 2, 3, 6],
                    'vperf':  [1, 2],
                    'hunperf':[1, 2, 3, 6],
                    'ladder': [1, 2, 3] if _spc == 'spaced' else [1, 2, 3, 6],
                }
                valid_nt = _VALID_TRAYS_MC.get(tray, [1, 2, 3])
                if self._cable.num_trays not in valid_nt:
                    below = [v for v in valid_nt if v <= self._cable.num_trays]
                    self._cable.num_trays = below[-1] if below else valid_nt[0]

                nt_box = QVBoxLayout()
                nt_box.addWidget(self._field_label("Number of trays:"))
                nt_cont, self._k3_nt_btns = self._opt_btns(
                    [(v, str(v)) for v in valid_nt], self._on_num_trays, self._cable.num_trays)
                nt_box.addWidget(nt_cont)
                row_l.addLayout(nt_box)

                # Cables per tray (Table C.8): ladder spaced max 4; other spaced max 6; touch max 9
                if tray == 'ladder' and _spc == 'spaced':
                    cpt_list = [1, 2, 3, 4]
                elif _spc == 'spaced':
                    cpt_list = [1, 2, 3, 4, 6]
                else:
                    cpt_list = TC8_CABLES_IDX
                if self._cable.cables_per_tray not in cpt_list:
                    below = [v for v in cpt_list if v <= self._cable.cables_per_tray]
                    self._cable.cables_per_tray = below[-1] if below else cpt_list[0]
                cb_box = QVBoxLayout()
                cb_box.addWidget(self._field_label("Cables per tray:"))
                cpt_cont, self._k3_cpt_btns = self._opt_btns(
                    [(v, str(v)) for v in cpt_list], self._on_cpt, self._cable.cables_per_tray)
                cb_box.addWidget(cpt_cont)
                row_l.addLayout(cb_box)

            row_l.addStretch()
            self._k3_ctrl.addWidget(row_w)

        self._update_k3_image()

    def _k3_image_name(self) -> str:
        method = self._cable.install_method
        is_1c  = self._cable.core_config == '1C'
        tray   = self._cable.tray_type

        if method == 'buried':
            return 'C5.png'
        if method == 'duct':
            return 'C6.png' if is_1c else 'C7.png'
        if method == 'air':
            if is_1c:
                _spaced = self._cable.arrangement in ('e', 'g')
                return {('hperf',  False): 'C9a.png', ('hperf',  True): 'C9b.png',
                        ('vperf',  False): 'C9c.png', ('vperf',  True): 'C9d.png',
                        ('ladder', False): 'C9e.png', ('ladder', True): 'C9f.png',
                        }.get((tray, _spaced), 'C9a.png')
            else:
                _spaced = (self._cable.spacing == 'spaced')
                return {('hperf',  False): 'C8a.png', ('hperf',  True): 'C8b.png',
                        ('vperf',  False): 'C8c.png', ('vperf',  True): 'C8d.png',
                        ('hunperf',False): 'C8e.png',
                        ('ladder', False): 'C8f.png', ('ladder', True): 'C8g.png',
                        }.get((tray, _spaced), 'C8a.png')
        return ''

    def _update_k3_image(self):
        if not hasattr(self, '_k3_illus'):
            return
        name = self._k3_image_name()
        if not name:
            self._k3_illus.clear()
            return
        path = _os.path.join(_IMG_DIR, name)
        px = QPixmap(path)
        if px.isNull():
            self._k3_illus.setText(name)
            return
        w = max(self._k3_illus.width() // 2, 90)
        self._k3_illus.setPixmap(
            px.scaledToWidth(w, Qt.SmoothTransformation))

    def _on_num_circuits(self, val):
        self._cable.num_circuits = val
        self._build_k3_controls()
        self._recalculate()

    def _on_clearance(self, val):
        self._cable.clearance = val
        if hasattr(self, '_k3_clr_btns'):
            self._uncheck_others(self._k3_clr_btns, val)
        self._recalculate()

    def _on_tray(self, val):
        self._cable.tray_type = val
        # Rebuild so tray-count and cables-per-tray options update for the new type
        self._build_k3_controls()
        self._recalculate()

    def _on_spacing(self, val):
        self._cable.spacing = val
        # Rebuild so cables-per-tray options update (vperf spaced excludes 9 cables)
        self._build_k3_controls()
        self._recalculate()

    def _on_num_trays(self, val):
        self._cable.num_trays = val
        if hasattr(self, '_k3_nt_btns'):
            self._uncheck_others(self._k3_nt_btns, val)
        self._recalculate()

    def _on_cpt(self, val):
        self._cable.cables_per_tray = val
        if hasattr(self, '_k3_cpt_btns'):
            self._uncheck_others(self._k3_cpt_btns, val)
        self._recalculate()

    def _build_parallel_section(self):
        w = QWidget()
        w.setStyleSheet('background:#f5f5f5;border:1px solid #d0d0d0;')
        vl = QVBoxLayout(w); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet('background:#1a3a5c;border-bottom:2px solid #f0a500;')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 6, 12, 6)
        badge = QLabel('k4')
        badge.setStyleSheet(
            'background:#f0a500;color:#000;font-weight:bold;'
            'font-size:9pt;padding:1px 6px;')
        lbl = QLabel('Parallel Sets')
        lbl.setStyleSheet('color:#ffffff;font-size:9pt;font-weight:bold;padding-left:8px;')
        hl.addWidget(badge); hl.addWidget(lbl, 1)
        vl.addWidget(hdr)

        inner = QWidget(); inner.setStyleSheet('background:#f5f5f5;')
        il = QVBoxLayout(inner); il.setContentsMargins(12, 8, 12, 8); il.setSpacing(4)

        desc = QLabel('Number of parallel cable sets per phase:')
        desc.setStyleSheet('font-size:9pt;color:#555555;')
        il.addWidget(desc)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        self._par_btns = []
        for n in range(1, 7):
            btn = QPushButton(str(n))
            btn.setCheckable(True); btn.setFixedWidth(34)
            btn.setStyleSheet(
                'QPushButton{background:#ffffff;border:1px solid #c0c0c0;'
                'color:#1a1a1a;font-size:9pt;font-weight:600;padding:5px;}'
                'QPushButton:hover{border-color:#1a3a5c;color:#1a3a5c;background:#eef2f7;}'
                'QPushButton:checked{background:#d4edda;border-color:#107c10;color:#107c10;}')
            btn.clicked.connect(lambda checked, v=n: self._on_parallel(v))
            btn_row.addWidget(btn)
            self._par_btns.append((n, btn))
        btn_row.addStretch()
        il.addLayout(btn_row)

        note = QLabel('Parallel cable grouping derating applied')
        note.setStyleSheet('font-size:8pt;color:#888888;font-style:italic;')
        il.addWidget(note)

        vl.addWidget(inner)

        current_n = getattr(self._cable, 'parallel_cables', 1)
        for n, btn in self._par_btns:
            btn.setChecked(n == current_n)
        return w

    def _on_parallel(self, val):
        self._cable.parallel_cables = val
        for n, btn in self._par_btns:
            btn.setChecked(n == val)
        self._recalculate()

    # ─────────────────────────────────────────────────────────────────────────
    # RESULT BAR
    # ─────────────────────────────────────────────────────────────────────────

    def _build_result_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            "background:#eef2f7;border-top:2px solid #1a3a5c;")
        bl = QHBoxLayout(bar); bl.setContentsMargins(20, 10, 20, 10); bl.setSpacing(8)

        def part(key):
            lbl_k = QLabel(key)
            lbl_k.setStyleSheet("font-family:'Courier New';font-size:9pt;color:#555555;")
            lbl_v = QLabel("?")
            lbl_v.setStyleSheet(
                "font-family:'Courier New';font-size:10pt;color:#1a1a1a;"
                "font-weight:bold;margin-left:4px;")
            return lbl_k, lbl_v

        self._res_k1_lbl, self._res_k1_val = part("k1")
        op1 = QLabel("×"); op1.setStyleSheet("font-size:11pt;color:#f0a500;")
        self._res_k2_lbl, self._res_k2_val = part("k2")
        op2 = QLabel("×"); op2.setStyleSheet("font-size:11pt;color:#f0a500;")
        self._res_k3_lbl, self._res_k3_val = part("k3")
        op3 = QLabel("="); op3.setStyleSheet("font-size:11pt;color:#f0a500;")

        k_lbl = QLabel("k =")
        k_lbl.setStyleSheet(
            "font-family:'Courier New';font-size:9pt;color:#555555;margin-left:6px;")
        self._res_k_final = QLabel("?")
        self._res_k_final.setStyleSheet(
            "font-family:'Courier New';font-size:14pt;color:#107c10;"
            "font-weight:bold;margin-left:4px;"
        )

        for w in [self._res_k1_lbl, self._res_k1_val, op1,
                  self._res_k2_lbl, self._res_k2_val, op2,
                  self._res_k3_lbl, self._res_k3_val, op3,
                  k_lbl, self._res_k_final]:
            bl.addWidget(w)
        bl.addStretch()
        return bar

    # ─────────────────────────────────────────────────────────────────────────
    # RECALCULATE
    # ─────────────────────────────────────────────────────────────────────────

    def _recalculate(self):
        self._cable.calculate_derating()
        self._refresh_result()
        self.k_changed.emit()

    def _refresh_result(self):
        c = self._cable
        _kstyle = "font-family:'Courier New';font-size:11pt;color:#107c10;"
        self._k1_val_lbl.setText(f"{c.k1:.3f}")
        self._k1_val_lbl.setStyleSheet(_kstyle)
        self._k2_val_lbl.setText(f"{c.k2:.3f}")
        self._k2_val_lbl.setStyleSheet(_kstyle)
        self._k3_val_lbl.setText(f"{c.k3:.3f}")
        self._k3_val_lbl.setStyleSheet(_kstyle)

        self._res_k1_val.setText(f"{c.k1:.3f}")
        self._res_k2_val.setText(f"{c.k2:.3f}")
        self._res_k3_val.setText(f"{c.k3:.3f}")
        self._res_k_final.setText(f"{c.k:.3f}")

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _uncheck_others(self, buttons: list, selected_val):
        for val, btn in buttons:
            btn.setChecked(val == selected_val)

    def _make_illus_label(self, emoji: str) -> QLabel:
        lbl = QLabel(emoji)
        lbl.setStyleSheet("font-size:18pt;color:#f0a500;padding:4px;")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedWidth(52)
        return lbl

    def _wrap_flow(self, buttons: list, cols: int = 6) -> QGridLayout:
        grid = QGridLayout(); grid.setSpacing(3); grid.setContentsMargins(0, 0, 0, 0)
        for i, btn in enumerate(buttons):
            grid.addWidget(btn, i // cols, i % cols)
        return grid
