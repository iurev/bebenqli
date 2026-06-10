"""The front door: parse --bus / -V, build the one Ddc, and dispatch to the CLI
or the TUI. Calls tui.main by attribute so tests can patch it."""
import argparse
import sys
from importlib.metadata import version, PackageNotFoundError

from . import tui
from .cli import cli
from .ddc import Ddc, resolve_bus, MODEL

try:
    __version__ = version("bebenqli")        # single source of truth: pyproject
except PackageNotFoundError:                  # running from a source tree, no install
    __version__ = "0.0.0+source"


def _parse(argv):
    # Pull out our two top-level flags; everything else (the subcommand and its
    # args) flows through untouched to cli(). add_help=False keeps -h/--help for
    # cli's own usage. --bus accepts "--bus N", "--bus=N", or bare "--bus"
    # (no value -> fall back to auto-detect); last one wins.
    p = argparse.ArgumentParser(prog="bebenqli", add_help=False)
    p.add_argument("-V", "--version", action="store_true")
    p.add_argument("--bus", nargs="?", const=None, default=None)
    return p.parse_known_args(argv)


def run(argv=None):
    ns, rest = _parse(sys.argv[1:] if argv is None else argv)

    if ns.version:
        print(f"bebenqli {__version__}")
        return 0

    bus = resolve_bus(ns.bus)
    if bus is None:
        print(f"error: no monitor matching '{MODEL}' found.\n"
              f"check `ddcutil detect`, then pass --bus N or set $BEBENQLI_BUS.",
              file=sys.stderr)
        return 1
    ddc = Ddc(bus)

    if rest:
        return cli(ddc, rest)
    tui.main(ddc)
    return 0


if __name__ == "__main__":
    sys.exit(run())
