#!/usr/bin/env python3
"""Generate Qt Designer .ui files under ui/forms/ from declarative specs."""
from __future__ import annotations

import sys
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = os.path.join(ROOT, 'ui', 'forms')
os.makedirs(FORMS, exist_ok=True)


def _esc(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _prop(name: str, value) -> ET.Element:
    p = ET.Element('property', name=name)
    if isinstance(value, bool):
        ET.SubElement(p, 'bool').text = 'true' if value else 'false'
    elif isinstance(value, int):
        ET.SubElement(p, 'number').text = str(value)
    elif isinstance(value, tuple) and len(value) == 2:
        ET.SubElement(p, 'string').text = f'{value[0]},{value[1]}'
    else:
        ET.SubElement(p, 'string').text = str(value)
    return p


def _widget(cls: str, name: str, props: dict | None = None,
            children: list | None = None) -> ET.Element:
    w = ET.Element('widget', attrib={'class': cls, 'name': name})
    for k, v in (props or {}).items():
        w.append(_prop(k, v))
    for ch in children or []:
        w.append(ch)
    return w


def _layout(cls: str, name: str, props: dict | None = None,
            items: list | None = None) -> ET.Element:
    lay = ET.Element('layout', attrib={'class': cls, 'name': name})
    for k, v in (props or {}).items():
        lay.append(_prop(k, v))
    for it in items or []:
        lay.append(it)
    return lay


def _item(widget_el: ET.Element, row=0, col=0, rowspan=1, colspan=1) -> ET.Element:
    it = ET.Element('item', attrib={
        'row': str(row), 'column': str(col),
        'rowspan': str(rowspan), 'columnspan': str(colspan),
    })
    it.append(widget_el)
    return it


def _form_row(label: str, field_name: str, field_cls: str = 'QLineEdit') -> ET.Element:
    return _widget('QWidget', f'row_{field_name}', children=[
        _layout('QHBoxLayout', f'lay_{field_name}', items=[
            ET.Element('item', attrib={}, children=[
                _widget('QLabel', f'lbl_{field_name}', {
                    'text': label,
                    'minimumSize': (80, 0),
                }),
            ]),
            ET.Element('item', attrib={}, children=[
                _widget(field_cls, field_name),
            ]),
        ]),
    ])


def save_ui(filename: str, root_class: str, root_name: str, root_widget: ET.Element):
    ui = ET.Element('ui', version='4.0')
    cls_el = ET.Element('class')
    cls_el.text = root_class
    ui.append(cls_el)
    ui.append(root_widget)
    path = os.path.join(FORMS, filename)
    xml = ET.tostring(ui, encoding='unicode')
    pretty = minidom.parseString(xml).toprettyxml(indent=' ')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(pretty)
    print('wrote', path)


def gen_motor():
    hdr = _widget('QFrame', 'hdr', children=[
        _layout('QHBoxLayout', 'hdrLayout', props={
            'leftMargin': 8, 'topMargin': 3, 'rightMargin': 8, 'bottomMargin': 3,
        }, items=[
            ET.Element('item', children=[_widget('QLabel', 'lblTitle', {'text': 'MOTOR CIRCUIT'})]),
            ET.Element('item', children=[_widget('QLabel', 'lbl_circuit', {'text': 'Select a Motor feeder row.'})]),
            ET.Element('item', children=[_widget('QLabel', 'lbl_ib', {'text': ''})]),
        ]),
    ])
    motor_grid = _layout('QGridLayout', 'motorGrid', props={
        'horizontalSpacing': 6, 'verticalSpacing': 4,
    }, items=[
        _item(_widget('QLabel', 'capLoad', {'text': 'Load type'}), 0, 0),
        _item(_widget('QComboBox', 'cb_profile'), 0, 1, 1, 7),
        _item(_widget('QLabel', 'capPh', {'text': 'Ph'}), 1, 0),
        _item(_widget('QComboBox', 'cb_ph'), 1, 1),
        _item(_widget('QLabel', 'capPn', {'text': 'Pn kW'}), 1, 2),
        _item(_widget('QDoubleSpinBox', 'sb_pn'), 1, 3),
        _item(_widget('QLabel', 'capEta', {'text': 'η'}), 1, 4),
        _item(_widget('QDoubleSpinBox', 'sb_eta'), 1, 5),
        _item(_widget('QLabel', 'capSF', {'text': 'SF'}), 1, 6),
        _item(_widget('QDoubleSpinBox', 'sb_sf'), 1, 7),
        _item(_widget('QLabel', 'capCos', {'text': 'cos φ'}), 2, 0),
        _item(_widget('QDoubleSpinBox', 'sb_pf'), 2, 1),
        _item(_widget('QLabel', 'capIst', {'text': 'Ist/In'}), 2, 2),
        _item(_widget('QDoubleSpinBox', 'sb_ist'), 2, 3),
        _item(_widget('QLabel', 'capStart', {'text': 'Start'}), 3, 0),
        _item(_widget('QComboBox', 'cb_start'), 3, 1),
        _item(_widget('QLabel', 'lbl_starter', {'text': '—'}), 3, 2, 1, 6),
        _item(_widget('QLabel', 'capPD', {'text': 'PD'}), 4, 0),
        _item(_widget('QComboBox', 'cb_pd'), 4, 1),
        _item(_widget('QLabel', 'lbl_pd', {'text': '—'}), 4, 2, 1, 6),
        _item(_widget('QLabel', 'capIso', {'text': 'Isolator'}), 5, 0),
        _item(_widget('QComboBox', 'cb_iso'), 5, 1),
        _item(_widget('QLabel', 'lbl_iso', {'text': '—'}), 5, 2, 1, 6),
        _item(_widget('QPushButton', 'btn_calc', {'text': 'Calculate'}), 6, 6, 1, 2),
    ])
    motor_box = _widget('QFrame', 'motorBox', {
        'minimumSize': (420, 0),
    }, children=[_layout('QVBoxLayout', 'motorVBox', items=[
        ET.Element('item', children=[_widget('QLabel', 'motorTitle', {'text': 'MOTOR'})]),
        ET.Element('item', children=[motor_grid]),
    ])])
    cable_form = _layout('QFormLayout', 'cableForm', props={
        'horizontalSpacing': 8, 'verticalSpacing': 3,
    }, items=[
        ET.Element('item', children=[_widget('QLabel', 'flIns', {'text': 'Insulation'})]),
        ET.Element('item', children=[_widget('QComboBox', 'cb_ins')]),
        ET.Element('item', children=[_widget('QLabel', 'flCore', {'text': 'Cores'})]),
        ET.Element('item', children=[_widget('QComboBox', 'cb_core')]),
        ET.Element('item', children=[_widget('QLabel', 'flInstall', {'text': 'Install'})]),
        ET.Element('item', children=[_widget('QComboBox', 'cb_install')]),
        ET.Element('item', children=[_widget('QLabel', 'flLen', {'text': 'Length m'})]),
        ET.Element('item', children=[_widget('QDoubleSpinBox', 'sb_len')]),
        ET.Element('item', children=[_widget('QLabel', 'flVd', {'text': 'Max Vd %'})]),
        ET.Element('item', children=[_widget('QDoubleSpinBox', 'sb_vd')]),
        ET.Element('item', children=[_widget('QLabel', 'flBtn', {'text': ''})]),
        ET.Element('item', children=[_widget('QPushButton', 'btn_cable', {'text': 'Cable selector…'})]),
        ET.Element('item', children=[_widget('QLabel', 'flRes', {'text': 'Result'})]),
        ET.Element('item', children=[_widget('QLabel', 'lbl_cable', {'text': '—'})]),
    ])
    cable_box = _widget('QFrame', 'cableBox', {
        'minimumSize': (240, 0),
    }, children=[_layout('QVBoxLayout', 'cableVBox', items=[
        ET.Element('item', children=[_widget('QLabel', 'cableTitle', {'text': 'CABLE'})]),
        ET.Element('item', children=[cable_form]),
    ])])
    body = _widget('QFrame', 'body', children=[
        _layout('QHBoxLayout', 'bodySplit', props={
            'leftMargin': 4, 'topMargin': 4, 'rightMargin': 4, 'bottomMargin': 4,
            'spacing': 6,
        }, items=[
            ET.Element('item', children=[motor_box]),
            ET.Element('item', children=[cable_box]),
        ]),
    ])
    root = _widget('QWidget', 'MotorCircuitSizingPanel', {
        'minimumSize': (0, 152), 'maximumSize': (16777215, 152),
    }, children=[
        _layout('QVBoxLayout', 'rootLayout', props={
            'leftMargin': 0, 'topMargin': 0, 'rightMargin': 0, 'bottomMargin': 0,
            'spacing': 0,
        }, items=[
            ET.Element('item', children=[hdr]),
            ET.Element('item', children=[body]),
        ]),
    ])
    save_ui('motor_circuit_sizing.ui', 'MotorCircuitSizingPanel',
            'MotorCircuitSizingPanel', root)


def gen_simple_dialog(filename: str, class_name: str, title: str, fields: list,
                      extra_widgets: list | None = None, min_w=400):
    form_items = []
    for label, wname, wcls in fields:
        form_items.append(ET.Element('item', children=[
            _widget('QLabel', f'lbl_{wname}', {'text': label}),
        ]))
        form_items.append(ET.Element('item', children=[
            _widget(wcls, wname),
        ]))
    form = _layout('QFormLayout', 'formLayout', props={'spacing': 8}, items=form_items)
    items = [ET.Element('item', children=[form])]
    for ex in extra_widgets or []:
        items.append(ET.Element('item', children=[ex]))
    items.append(ET.Element('item', children=[
        _widget('QDialogButtonBox', 'buttonBox', {
            'standardButtons': 'QDialogButtonBox::Ok|QDialogButtonBox::Cancel',
        }),
    ]))
    root = _widget('QDialog', class_name, {
        'windowTitle': title,
        'minimumSize': (min_w, 0),
    }, children=[
        _layout('QVBoxLayout', 'verticalLayout', props={'spacing': 10}, items=items),
    ])
    save_ui(filename, class_name, class_name, root)


def main():
    import sys
    if '--force' not in sys.argv:
        print('Skipped: ui/forms/*.ui are hand-maintained for Qt Designer.')
        print('Validate:  python tools/validate_ui_forms.py')
        print('To regenerate stubs (overwrites .ui):  python tools/generate_ui_forms.py --force')
        return
    gen_motor()
    gen_simple_dialog('engineer_dialog.ui', 'EngineerDialog', 'Engineer',
                      [('Name:', 'nameEdit', 'QLineEdit'),
                       ('Email:', 'emailEdit', 'QLineEdit')])
    gen_simple_dialog('new_package_dialog.ui', 'NewPackageDialog', 'New Package',
                      [('Package name:', 'nameEdit', 'QLineEdit'),
                       ('Zone:', 'zoneEdit', 'QLineEdit')])
    gen_simple_dialog('new_project_dialog.ui', 'NewProjectDialog', 'New Project',
                      [('Project name:', 'nameEdit', 'QLineEdit'),
                       ('Standard:', 'standardCombo', 'QComboBox')])
    gen_simple_dialog('board_settings_dialog.ui', 'BoardSettingsDialog',
                      'Board Settings', [
                          ('Name', 'name', 'QLineEdit'),
                          ('Project', 'project', 'QLineEdit'),
                          ('Location', 'location', 'QLineEdit'),
                      ], min_w=500)
    print('Done. Open files in Qt Designer:', FORMS)


if __name__ == '__main__':
    main()
