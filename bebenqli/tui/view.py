"""Rendering: turn a Frame snapshot into the screen's lines. `render` is pure
(no terminal) so it's unit-testable; `draw` just adds the cursor/clear escapes
and prints."""
from ..controls import CONTROLS, HEADERS, RENDER, W
from ..format import render_row


def _row_text(frame, i, ctrl):
    blink_on = frame.ticks[i] % 2 == 0
    ent      = frame.entry_buf if i == frame.entry else None
    content  = render_row(ctrl, frame.vals[i], frame.loaded[i], frame.pending[i], blink_on, ent)
    # dim non-matching rows during search (keep spacing, drop highlight)
    if frame.searching and frame.search_q and ctrl["type"] not in HEADERS and i not in frame.pool:
        content = f" {content[1:]}"
    return content


def _cycle_options(frame, i, ctrl):
    # selected cycle: numbered options below the row for direct pick
    if not (i == frame.sel and ctrl["type"] == "cycle" and frame.loaded[i]):
        return []
    cur = frame.vals[i]
    out = []
    for n, name in enumerate(ctrl["names"], 1):
        mark = "●" if ctrl["opts"][n - 1] == cur else " "
        out.append(f"│{f'       {n} {mark} {name}':<{W}}│")
    return out


def _footer(frame):
    if frame.searching:
        return f"│ {f'/ {frame.search_q}█':<{W-1}}│"
    return f"│ {'↑↓ move ←→/digit set / find ! listen q quit':<{W-1}}│"


def render(frame, reverse="", normal=""):
    # The full screen as a list of lines. reverse/normal are the terminal's
    # highlight escapes (empty by default, so the output is plain + testable).
    lines = [f"╭{'─' * W}╮",
             f"│ {'BenQ RD280U Monitor Control':<{W-1}}│",
             f"╞{'═' * W}╡"]
    for i, ctrl in enumerate(CONTROLS):
        if i not in RENDER:                   # hidden items + empty headers
            continue
        padded = f"{_row_text(frame, i, ctrl):<{W}}"
        if ctrl["type"] not in HEADERS and i == frame.sel:
            lines.append(f"│{reverse}{padded}{normal}│")
        else:
            lines.append(f"│{padded}│")
        lines += _cycle_options(frame, i, ctrl)
    lines.append(f"╞{'═' * W}╡")
    lines.append(_footer(frame))
    lines.append(f"╰{'─' * W}╯")
    return lines


def draw(term, frame):  # pragma: no cover
    body = "\n".join(render(frame, term.reverse, term.normal))
    print(term.home + term.clear + body, end="", flush=True)
