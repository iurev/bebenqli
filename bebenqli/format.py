"""Pure presentation: turn a control + value into a display string. No I/O, no
state — every input arrives as an argument, so these are trivially testable."""


def bar(val, lo, hi, w=12):
    f = round((val - lo) / (hi - lo) * w)
    return "█" * max(0, min(w, f)) + "░" * max(0, min(w, w - f))


def render_row(ctrl, val, loaded, pending, blink_on, entry=None):
    t = ctrl["type"]
    if t == "group":                                  # top level, flush-left
        return f"▌{ctrl['label'].upper()}"
    if t == "section":                                # sub level, indent 2
        return f"  ▎{ctrl['label']}"

    label = f"{ctrl['label']:<14}"                    # items, indent 4

    if t == "missing":
        return f"    {label}  [not mapped]"
    if t == "dead":
        return f"    {label}  [hw n/a]"

    blank = pending is not None and not blink_on
    if not loaded:
        return f"    {label}  @"

    if t == "cycle":
        idx  = ctrl["opts"].index(val) if val in ctrl["opts"] else 0
        name = ctrl["names"][idx]
        return f"    {label}  {'':18}" if blank else f"    {label}  {name:<18}"
    else:
        lo, hi = ctrl["min"], ctrl["max"]
        if entry is not None:
            return f"    {label}  type: {entry}█  (={lo}..{hi})"
        d = len(str(hi))
        b = bar(val, lo, hi)
        vs = f"{val:{d}}/{hi}"
        return f"    {label}  {'':12}  {'':7}" if blank else f"    {label}  {b}  {vs:>7}"


def _fmt(c, v):
    if v is None:
        return "?"
    if c["type"] == "cycle":
        return c["names"][c["opts"].index(v)] if v in c["opts"] else f"?(0x{v:02x})"
    return str(v)
