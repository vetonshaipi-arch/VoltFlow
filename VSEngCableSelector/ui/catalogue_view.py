# ui/catalogue_view.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QBrush
from ..cable_class import C_Cable, ConductorRow


class CatalogueView(QWidget):
    # Emitted when the user clicks a row; carries the ConductorRow object
    row_selected = Signal(object)

    # Column definitions: (header, attr)
    COLS_1C = [
        ("mm²",           "size_mm2"),
        ("DC 20°C\nΩ/km", "dc20"),
        ("AC 70°C\nΩ/km", "ac70"),
        ("AC 90°C\nΩ/km", "ac90"),
        ("Iₙ (A)",        "In"),
        ("X\nΩ/km",       "X"),
        ("Z\nΩ/km",       "Z"),
        ("C\nµF/km",      "C"),
        ("Ø mm",          "diameter"),
        ("kg/km",         "weight"),
        ("Cable Code",    "cable_code"),
    ]
    COLS_MC = [
        ("mm²",           "size_mm2"),
        ("Shape",         "shape"),
        ("DC 20°C\nΩ/km", "dc20"),
        ("AC 70°C\nΩ/km", "ac70"),
        ("AC 90°C\nΩ/km", "ac90"),
        ("Iₙ (A)",        "In"),
        ("X\nΩ/km",       "X"),
        ("Z\nΩ/km",       "Z"),
        ("C\nµF/km",      "C"),
        ("Ø mm",          "diameter"),
        ("kg/km",         "weight"),
        ("Cable Code",    "cable_code"),
    ]

    # Light-theme colors
    C_BG_EVEN   = QColor("#ffffff")
    C_BG_ODD    = QColor("#f5f5f5")
    C_HL_BG     = QColor("#d4edda")   # auto-selected row (green)
    C_HL_FG     = QColor("#107c10")
    C_MANUAL_BG = QColor("#fff3cd")   # manually locked row (amber)
    C_MANUAL_FG = QColor("#856404")
    C_CODE_FG   = QColor("#1a3a5c")
    C_MUTED   = QColor("#888888")
    C_TEXT    = QColor("#1a1a1a")

    def __init__(self, cable: C_Cable, parent=None):
        super().__init__(parent)
        self._cable = cable
        self._build_ui()
        self.refresh(cable)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Header bar ──
        self._header_bar = QWidget()
        self._header_bar.setStyleSheet(
            "background:#f0f4f8;border-bottom:1px solid #d0d0d0;padding:0;")
        hbl = QHBoxLayout(self._header_bar)
        hbl.setContentsMargins(12, 8, 12, 8)

        title_col = QVBoxLayout(); title_col.setSpacing(2)
        self._lbl_title = QLabel()
        self._lbl_title.setStyleSheet(
            "font-size:10pt;font-weight:bold;color:#1a3a5c;letter-spacing:1px;")
        self._lbl_subtitle = QLabel()
        self._lbl_subtitle.setStyleSheet("font-size:8pt;color:#555555;")
        title_col.addWidget(self._lbl_title)
        title_col.addWidget(self._lbl_subtitle)
        hbl.addLayout(title_col)
        hbl.addStretch()

        self._badge_method = self._make_badge("", "#1a3a5c")
        self._badge_arr    = self._make_badge("", "#107c10")
        hbl.addWidget(self._badge_method)
        hbl.addWidget(self._badge_arr)
        layout.addWidget(self._header_bar)

        # ── X/Z warning note (shown when non-trefoil 1C) ──
        self._warn_note = QLabel()
        self._warn_note.setStyleSheet(
            "font-size:9pt;color:#856404;font-style:italic;"
            "background:#fff3cd;border-left:3px solid #f0a500;padding:6px 12px;")
        self._warn_note.setWordWrap(True)
        self._warn_note.hide()
        layout.addWidget(self._warn_note)

        # ── Table ──
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setStyleSheet(
            "QTableWidget{background:#ffffff;gridline-color:#e0e0e0;}"
            "QHeaderView::section{background:#f0f4f8;color:#1a1a1a;font-size:8pt;"
            "font-weight:bold;padding:4px;border:1px solid #d0d0d0;}"
        )

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table)

        # ── Laying note ──
        note = QLabel(
            "Laying Conditions: Ambient air 40°C · Ground 35°C · "
            "Soil resistivity 1.5 K·m/W · Depth 0.5 m")
        note.setStyleSheet(
            "font-size:8pt;color:#555555;font-style:italic;"
            "background:#f0f4f8;border-left:3px solid #1a3a5c;padding:6px 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

    def _make_badge(self, text: str, bg: str, fg: str = "#ffffff") -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"background:{bg};color:{fg};font-size:8pt;font-weight:bold;"
            f"padding:2px 8px;letter-spacing:1px;margin-left:6px;")
        lbl.setVisible(bool(text))
        return lbl

    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self, cable: C_Cable):
        self._cable = cable
        c = cable
        is_1c = c.core_config == '1C'
        is_trefoil = c.arrangement in ('a', 'c', 'e')

        # ── Update header ──
        self._lbl_title.setText("POWER CABLES · KSA 60 Hz")
        method_str = {
            'air':    'In Free Air',
            'buried': 'Direct Buried in Ground',
            'duct':   'Buried in Conduit / Duct',
        }[c.install_method]
        core_str = 'Single Conductor (1C)' if is_1c else f'{c.core_config} Multi-Core'
        self._lbl_subtitle.setText(
            f"CU / {c.insulation} / PVC · 0.6/1 kV  ·  {core_str}  ·  {method_str}")

        self._badge_method.setText(method_str)
        self._badge_method.setVisible(True)

        arr_labels = {
            'a': 'Fig.(a) Trefoil — Buried',
            'b': 'Fig.(b) Flat Touched — Buried',
            'c': 'Fig.(c) Trefoil — In Duct',
            'd': 'Fig.(d) Flat Touched — In Duct',
            'e': 'Fig.(e) Trefoil — Free Air',
            'f': 'Fig.(f) Flat Touched — Free Air',
            'g': 'Fig.(g) Flat Spaced — Free Air',
        }
        if is_1c:
            self._badge_arr.setText(arr_labels.get(c.arrangement, ''))
            self._badge_arr.setVisible(True)
        else:
            self._badge_arr.setVisible(False)

        # ── X/Z warning note ──
        if is_1c and not is_trefoil:
            self._warn_note.setText(
                f"Note: Reactance (X) and Impedance (Z) are not available for non-trefoil "
                f"arrangement {arr_labels.get(c.arrangement,'('+c.arrangement+')')}. "
                f"X and Z values from Annex E (Table E.1/E.3) apply to trefoil formation only. "
                f"When calculating voltage drop for this arrangement, X = 0 will be assumed "
                f"(resistive drop only — conservative result).")
            self._warn_note.show()
        else:
            self._warn_note.hide()

        # ── Build columns ──
        cols = self.COLS_1C if is_1c else self.COLS_MC
        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels([h for h, _ in cols])

        # Highlight column index (Iₙ)
        hl_col = next((i for i, (h, _) in enumerate(cols) if "Iₙ" in h), 4)

        font_bold = QFont("Segoe UI", 9); font_bold.setBold(True)
        for i, (h, _) in enumerate(cols):
            item = self._table.horizontalHeaderItem(i)
            if item and i == hl_col:
                item.setForeground(QBrush(self.C_HL_FG))
                item.setBackground(QBrush(QColor("#d4edda")))
                item.setFont(font_bold)

        # ── Populate rows ──
        rows = c.conductor_table
        self._table.setRowCount(len(rows))
        mono = QFont("Courier New", 9)

        for r_idx, row in enumerate(rows):
            bg = self.C_BG_EVEN if r_idx % 2 == 0 else self.C_BG_ODD

            for c_idx, (_, attr) in enumerate(cols):
                val = getattr(row, attr, None)

                # ── Format value ──
                if attr in ('X', 'Z', 'C'):
                    text = "N/A" if val is None else f"{val:.3f}"
                elif attr in ('dc20', 'ac70', 'ac90'):
                    text = f"{val:.4f}"
                elif attr == 'size_mm2':
                    text = str(int(val)) if val == int(val) else str(val)
                elif attr == 'In':
                    text = str(int(val)) if isinstance(val, float) and val == int(val) else str(val)
                elif attr == 'weight':
                    text = str(int(val))
                elif attr == 'diameter':
                    text = f"{val:.1f}"
                elif attr in ('cable_code', 'shape'):
                    text = str(val)
                elif val is None:
                    text = "—"
                elif isinstance(val, float):
                    text = f"{val:.3f}"
                else:
                    text = str(val)

                item = QTableWidgetItem(text)
                item.setFont(mono)
                item.setTextAlignment(Qt.AlignCenter)

                # ── Colors ──
                if c_idx == hl_col:
                    item.setBackground(QBrush(self.C_HL_BG))
                    item.setForeground(QBrush(self.C_HL_FG))
                    item.setFont(font_bold)
                elif attr == 'cable_code':
                    item.setForeground(QBrush(self.C_CODE_FG))
                    item.setBackground(QBrush(bg))
                elif attr in ('X', 'Z', 'C') and val is None:
                    item.setForeground(QBrush(self.C_MUTED))
                    item.setBackground(QBrush(bg))
                    item.setToolTip("Not applicable for non-trefoil arrangement. X=0 assumed for voltage drop.")
                else:
                    item.setForeground(QBrush(self.C_TEXT))
                    item.setBackground(QBrush(bg))

                self._table.setItem(r_idx, c_idx, item)
            self._table.setRowHeight(r_idx, 24)

        # ── Auto-resize columns ──
        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(len(cols) - 1, QHeaderView.Stretch)
        for i in range(len(cols) - 1):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)

        # ── Auto height ──
        total_h = sum(self._table.rowHeight(i) for i in range(len(rows)))
        total_h += self._table.horizontalHeader().height() + 4
        self._table.setFixedHeight(min(total_h, 520))

        # ── Highlight manually locked row (amber) ──
        if c.manual_sizing and c.recommended is not None:
            for r_idx, row in enumerate(rows):
                if row.size_mm2 == c.recommended.size_mm2:
                    for c_idx in range(self._table.columnCount()):
                        it = self._table.item(r_idx, c_idx)
                        if it:
                            it.setBackground(QBrush(self.C_MANUAL_BG))
                            it.setForeground(QBrush(self.C_MANUAL_FG))
                    break

    # ─────────────────────────────────────────────────────────────────────────
    def _on_cell_clicked(self, row: int, _col: int):
        """Emit row_selected only when manual sizing mode is active."""
        if not self._cable.manual_sizing:
            return
        if 0 <= row < len(self._cable.conductor_table):
            self.row_selected.emit(self._cable.conductor_table[row])
