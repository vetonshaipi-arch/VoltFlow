# motor_coordination_data.py
# Type 2 coordination stubs (IEC 60947-4-1) — replace with manufacturer tables.
# Each row: max motor FLC (A), minimum Icu (kA), device references.

from __future__ import annotations

# topology key → list of coordination rows
# ib_max_A: maximum motor full-load current this kit supports
# icu_min_kA: minimum required breaking capacity at MCC
TYPE2_GENERIC = [
  # MPCB + OL + contactor (typical DOL, Ib ≤ 32 A)
  {'topology': 'MPCB + OL relay', 'ib_max_A': 6.3,
   'mpcb': 'MS116-6.3', 'contactor': 'A9-30-10', 'ol_relay': 'TA25DU',
   'isolator': 'OT63F3', 'Icu_kA': 50, 'In_A': 6.3},
  {'topology': 'MPCB + OL relay', 'ib_max_A': 10,
   'mpcb': 'MS116-10', 'contactor': 'A12-30-10', 'ol_relay': 'TA25DU',
   'isolator': 'OT63F3', 'Icu_kA': 50, 'In_A': 10},
  {'topology': 'MPCB + OL relay', 'ib_max_A': 16,
   'mpcb': 'MS116-16', 'contactor': 'A16-30-10', 'ol_relay': 'TA32DU',
   'isolator': 'OT63F3', 'Icu_kA': 50, 'In_A': 16},
  {'topology': 'MPCB + OL relay', 'ib_max_A': 25,
   'mpcb': 'MS116-25', 'contactor': 'A26-30-10', 'ol_relay': 'TA45DU',
   'isolator': 'OT63F3', 'Icu_kA': 50, 'In_A': 25},
  {'topology': 'MPCB + OL relay', 'ib_max_A': 32,
   'mpcb': 'MS132-32', 'contactor': 'A30-30-10', 'ol_relay': 'TA65DU',
   'isolator': 'OT63F3', 'Icu_kA': 50, 'In_A': 32},
  {'topology': 'MPCB + OL relay', 'ib_max_A': 45,
   'mpcb': 'MS495-45', 'contactor': 'A50-30-11', 'ol_relay': 'TA75DU',
   'isolator': 'OT63F3', 'Icu_kA': 50, 'In_A': 45},
  {'topology': 'MPCB + OL relay', 'ib_max_A': 63,
   'mpcb': 'MS495-63', 'contactor': 'A50-30-11', 'ol_relay': 'TA75DU',
   'isolator': 'OT63F3', 'Icu_kA': 50, 'In_A': 63},
  # MCCB thermal-magnetic + contactor (larger motors)
  {'topology': 'MCCB thermal-magnetic', 'ib_max_A': 63,
   'mccb': 'T4N250 PR221DS-63', 'contactor': 'A50-30-11', 'ol_relay': '—',
   'isolator': 'OT160E03', 'Icu_kA': 50, 'In_A': 63},
  {'topology': 'MCCB thermal-magnetic', 'ib_max_A': 100,
   'mccb': 'T4N250 PR221DS-100', 'contactor': 'A63-30-11', 'ol_relay': '—',
   'isolator': 'OT160E03', 'Icu_kA': 50, 'In_A': 100},
  {'topology': 'MCCB thermal-magnetic', 'ib_max_A': 160,
   'mccb': 'T5N400 PR221DS-160', 'contactor': 'A75-30-11', 'ol_relay': '—',
   'isolator': 'OT200E03', 'Icu_kA': 50, 'In_A': 160},
  {'topology': 'MCCB thermal-magnetic', 'ib_max_A': 250,
   'mccb': 'T5N400 PR221DS-250', 'contactor': 'AF96-30-11', 'ol_relay': '—',
   'isolator': 'OT250E03', 'Icu_kA': 50, 'In_A': 250},
]

MANUFACTURER_TABLES: dict[str, list] = {
    'Generic': TYPE2_GENERIC,
    'ABB': TYPE2_GENERIC,
    'Schneider': TYPE2_GENERIC,
    'Siemens': TYPE2_GENERIC,
    'alfanar': TYPE2_GENERIC,
}
