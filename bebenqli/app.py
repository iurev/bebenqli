"""The front door: parse --bus / -V, build the one Ddc, and dispatch to the CLI
or the TUI. Calls tui.main by attribute so tests can patch it."""
import sys

from . import tui
from .cli import cli
from .ddc import Ddc, resolve_bus, MODEL

__version__ = "0.0.1"


def run(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)

    if any(a in ("-V", "--version") for a in args):
        print(f"bebenqli {__version__}")
        return 0

    # --bus N (or --bus=N): override auto-detection.
    explicit = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--bus":
            explicit = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if a.startswith("--bus="):
            explicit = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    args = rest

    bus = resolve_bus(explicit)
    if bus is None:
        print(f"error: no monitor matching '{MODEL}' found.\n"
              f"check `ddcutil detect`, then pass --bus N or set $BEBENQLI_BUS.",
              file=sys.stderr)
        return 1
    ddc = Ddc(bus)

    if args:
        return cli(ddc, args)
    tui.main(ddc)
    return 0


if __name__ == "__main__":
    sys.exit(run())
