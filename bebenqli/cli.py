"""The non-interactive commands: list / get / set / lazyset. Takes a Ddc as its
first argument (no globals) and reads the control table + formatter."""
import sys

from .controls import CONTROLS, _cli_name
from .format import _fmt


def _cli_controls():
    # name -> ctrl, only controls that carry a vcp (settable/gettable)
    out = {}
    for c in CONTROLS:
        if "vcp" in c:
            out[_cli_name(c["label"])] = c
    return out


def _read(ddc, c):
    if c.get("noread"):
        return None                       # write-only (d7 / d9 color temp)
    return ddc.getvcp(c["vcp"])


def _resolve(c, valstr):
    # cycle: accept option name (case-insensitive) or a raw/hex opt value.
    # range: accept int (dec or 0x..), clamped to min/max.
    if c["type"] == "cycle":
        for opt, nm in zip(c["opts"], c["names"]):
            if valstr.lower() == nm.lower():
                return opt
        try:
            iv = int(valstr, 0)
        except ValueError:
            iv = None
        if iv in c["opts"]:
            return iv
        names = "|".join(c["names"])
        raise ValueError(f"bad value '{valstr}'; expected one of: {names}")
    try:
        iv = int(valstr, 0)
    except ValueError:
        raise ValueError(f"bad value '{valstr}'; expected integer {c['min']}..{c['max']}")
    return max(c["min"], min(c["max"], iv))


def cli(ddc, args):
    if any(a in ("-v", "--verbose") for a in args):
        ddc.verbose = True
        args = [a for a in args if a not in ("-v", "--verbose")]
    controls = _cli_controls()

    def usage():
        print("usage: bebenqli [list | get <name> | set <name> <value> | lazyset <name> <value>]")
        print("       set     = write then verify (read-back when possible)")
        print("       lazyset = write only, no verify")
        print("       --bus N        : i2c bus override (default: auto-detect RD280U)")
        print("       -v/--verbose   : echo each ddcutil command to stderr")
        print("       -V/--version   : print version")
        print("       bebenqli              (no args -> TUI)")
        return 2

    if not args or args[0] in ("-h", "--help", "help"):
        return usage()

    cmd = args[0]

    if cmd == "list":
        width = max(len(n) for n in controls)
        for name, c in controls.items():
            cur = "(write-only)" if c.get("noread") else _fmt(c, _read(ddc, c))
            if c["type"] == "cycle":
                extra = "  {" + "|".join(c["names"]) + "}"
            else:
                extra = f"  [{c['min']}..{c['max']}]"
            print(f"{name:<{width}}  {cur}{extra}")
        return 0

    if cmd == "get":
        if len(args) != 2 or args[1] not in controls:
            print(f"unknown control: {args[1] if len(args) > 1 else ''}", file=sys.stderr)
            return usage()
        c = controls[args[1]]
        if c.get("noread"):
            print("(write-only — cannot read)")
            return 0
        print(_fmt(c, _read(ddc, c)))
        return 0

    if cmd in ("set", "lazyset"):
        if len(args) != 3 or args[1] not in controls:
            print(f"unknown control: {args[1] if len(args) > 1 else ''}", file=sys.stderr)
            return usage()
        name = args[1]
        c    = controls[name]
        try:
            target = _resolve(c, args[2])
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        ok = ddc.setvcp(c["vcp"], target, c.get("chan"), c.get("noverify"))
        shown = _fmt(c, target)

        if cmd == "lazyset":                         # fire-and-forget, no check
            print(f"{name} = {shown}")
            return 0

        # set: verify when possible
        if not ok:                                   # ddcutil itself errored
            print(f"{name}: FAILED (ddcutil rejected write)", file=sys.stderr)
            return 1
        if c.get("noread"):                          # can't read back this control
            print(f"{name} = {shown}  (write-only, unverified)")
            return 0
        got = _read(ddc, c)                          # read-back compare
        if got == target:
            print(f"{name} = {shown}  (verified)")
            return 0
        print(f"{name}: MISMATCH wanted {shown} got {_fmt(c, got)}", file=sys.stderr)
        return 1

    print(f"unknown command: {cmd}", file=sys.stderr)
    return usage()
