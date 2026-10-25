# ui/status_messages.py — collect warnings/errors for status bar and CALCULATE page
from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from switchboard_class import C_Switchboard

_ERROR_HINTS = (
    'ERROR', 'VIOLATION', 'EXCEEDS', 'EXCEED', 'FAILED', 'FAIL',
    'OVERFILLED', 'OVERLOAD', 'NO CONDUCTOR', 'NOT SELECTED', 'CANNOT',
    'AMPACITY', 'PROTECTION', 'ΔU', 'VDROP', 'VD ',
)


def _is_error_message(msg: str) -> bool:
    u = msg.upper()
    return any(h in u for h in _ERROR_HINTS)


def collect_messages(root: 'C_Switchboard') -> Tuple[List[str], List[str]]:
    """Gather unique warnings and errors from the full board tree."""
    errors: List[str] = []
    warnings: List[str] = []
    seen: set[str] = set()

    def add(msg: str, prefix: str = '', *, as_error: bool | None = None) -> None:
        msg = (msg or '').strip()
        if not msg:
            return
        key = f'{prefix}{msg}'
        if key in seen:
            return
        seen.add(key)
        line = key if prefix else msg
        is_err = _is_error_message(msg) if as_error is None else as_error
        if is_err:
            errors.append(line)
        else:
            warnings.append(line)

    for w in getattr(root, 'warnings', []) or []:
        add(w, '[Project] ')

    for board in root.all_boards():
        for w in getattr(board, 'warnings', []) or []:
            add(w, f'[{board.name}] ')

        if board.busbar_A > 0 and board.busbar_loading > 100.0 + 1e-6:
            add(
                f'Busbar overloaded: {board.busbar_loading:.1f}% of '
                f'{board.busbar_A:.0f} A',
                f'[{board.name}] ',
                as_error=True,
            )
        elif board.busbar_A > 0 and board.busbar_loading > 90.0 + 1e-6:
            add(
                f'Busbar loading high: {board.busbar_loading:.1f}% of '
                f'{board.busbar_A:.0f} A',
                f'[{board.name}] ',
            )

        feeders = list(board.feeders)
        if board.primary_feeder_selected:
            feeders.append(board.primary_feeder)

        for f in feeders:
            if f.load_type in ('Space', 'Spare'):
                continue
            tag = getattr(f, 'circuit_ref', '') or f.name
            if f is board.primary_feeder:
                tag = 'INC'
            loc = f'[{board.name}/{tag}] '
            for w in getattr(f, 'warnings', []) or []:
                add(w, loc)
            for w in getattr(getattr(f, 'cable', None), 'warnings', []) or []:
                add(w, loc)
            for w in getattr(getattr(f, 'cb', None), 'warnings', []) or []:
                add(w, loc)
            motor = getattr(f, 'motor', None)
            if getattr(f, 'motor_configured', False) and motor:
                for w in getattr(motor, 'warnings', []) or []:
                    add(w, loc)

            _add_feeder_compliance(add, board, f, loc)

    return errors, warnings


def _add_feeder_compliance(add, board, f, loc: str) -> None:
    """Synthesise errors for failed checks not already captured as warnings."""
    has_load = bool(f.P or f.S or f.Ib)
    if not has_load:
        return

    c = getattr(f, 'cable', None)
    cb = getattr(f, 'cb', None)
    rec = getattr(c, 'recommended', None) if c else None

    if not rec:
        add('No conductor selected — run Cable Selector or Calc All', loc,
            as_error=True)
        return

    if f.Ib <= 0:
        return

    if c and not c.passes_ampacity:
        add(
            f'Ampacity fail: Ib {f.Ib:.1f} A > Iz {f.Iz:.1f} A '
            f'({getattr(c, "parallel_cables", 1)}×{rec.size_mm2:.0f} mm²)',
            loc, as_error=True)

    if c and not c.passes_vdrop:
        add(
            f'Segment ΔUc {f.result_vdrop_pct:.2f}% exceeds limit '
            f'{f.max_vdrop_pct:.1f}%',
            loc, as_error=True)

    if getattr(f, 'passes_vdrop_total', True) is False:
        total = getattr(f, 'result_vdrop_total_pct', 0.0) or 0.0
        add(
            f'ΔUtotal {total:.2f}% exceeds limit {f.max_vdrop_pct:.1f}%',
            loc, as_error=True)

    if cb and cb.In_CB:
        if not cb.passes_protection:
            add(
                f'CB protection fail: In={cb.In_CB:.0f} A, Iz={f.Iz:.1f} A',
                loc, as_error=True)
        if board.Isc_board_kA > 0 and not cb.passes_Isc:
            add(
                f'CB breaking capacity fail: Icu={cb.Icu_kA:.1f} kA < '
                f'Isc={board.Isc_board_kA:.2f} kA at busbars',
                loc, as_error=True)

    if not f.passes_all and f.Ib > 0:
        specific = (
            (c and not c.passes_ampacity)
            or (c and not c.passes_vdrop)
            or not getattr(f, 'passes_vdrop_total', True)
            or (cb and cb.In_CB and not cb.passes_protection)
            or (cb and board.Isc_board_kA > 0 and not cb.passes_Isc)
        )
        if not specific:
            add('One or more design checks failed', loc, as_error=True)


def format_status_line(info: str, errors: List[str], warnings: List[str],
                       max_chars: int = 220) -> str:
    """Single-line status text for the bottom bar."""
    parts: List[str] = []
    if info:
        parts.append(info.strip())
    if errors:
        detail = '; '.join(errors[:2])
        if len(errors) > 2:
            detail += f'; +{len(errors) - 2} more'
        parts.append(f'✘ {len(errors)} error(s): {detail}')
    elif warnings:
        detail = '; '.join(warnings[:2])
        if len(warnings) > 2:
            detail += f'; +{len(warnings) - 2} more'
        parts.append(f'⚠ {len(warnings)} warning(s): {detail}')
    elif info:
        parts.append('✔ OK')
    text = '  |  '.join(parts) if parts else 'Ready'
    if len(text) > max_chars:
        return text[: max_chars - 1] + '…'
    return text


def status_tooltip(errors: List[str], warnings: List[str]) -> str:
    lines: List[str] = []
    for e in errors:
        lines.append(f'✘ {e}')
    for w in warnings:
        lines.append(f'⚠ {w}')
    return '\n'.join(lines)


def format_calc_page_text(
        root: 'C_Switchboard',
        errors: List[str],
        warnings: List[str],
) -> str:
    """Full message list for the CALCULATE tab."""
    boards = root.all_boards()
    feeders = [f for b in boards for f in b.feeders
               if f.load_type not in ('Space', 'Spare')]
    worst_vd = max((f.result_vdrop_pct for f in feeders if f.result_vdrop_pct),
                   default=0.0)
    max_bus = max((b.busbar_loading for b in boards), default=0.0)

    lines: List[str] = [
        '── Summary ──',
        f'Boards: {len(boards)}    Feeders: {len(feeders)}',
        f'Worst segment ΔUc: {worst_vd:.2f}%',
        f'Max busbar loading: {max_bus:.1f}%',
        '',
    ]

    if errors:
        lines.append(f'── ERRORS ({len(errors)}) ──')
        for e in errors:
            lines.append(f'✘  {e}')
        lines.append('')

    if warnings:
        lines.append(f'── WARNINGS ({len(warnings)}) ──')
        for w in warnings:
            lines.append(f'⚠  {w}')
        lines.append('')

    if not errors and not warnings:
        lines.append('✔  All checks passed — no errors or warnings.')
    elif not errors:
        lines.append('✔  No errors (warnings only).')

    return '\n'.join(lines).rstrip()


def status_stylesheet(has_errors: bool, has_warnings: bool) -> str:
    base = 'font-size:10px;padding:0 4px;'
    if has_errors:
        return base + 'color:#8b0000;background:#ffe8e8;'
    if has_warnings:
        return base + 'color:#7a4f00;background:#fff8e6;'
    return base + 'color:#444;background:transparent;'
