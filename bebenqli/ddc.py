"""The monitor connection. A ``Ddc`` is built once (bus + verbose) and handed to
whoever needs the panel; its getvcp/setvcp are pure given the instance, which is
what replaces the old BUS/CMD/VERBOSE module globals.

A ``Ddc`` is immutable after construction, so many threads may share one and read
from it without locking.

Calls ``proc.run_proc`` by attribute so tests can replace the seam."""
import os
import re
import sys

from . import proc

MODEL = "RD280U"          # auto-detect: i2c bus whose monitor matches this


def build_cmd(bus):
    return ["ddcutil", "--bus", str(bus), "--permit-unknown-feature"]


def _parse_terse(out):
    # Parse `ddcutil --terse getvcp <code>`. Deterministic tokens, no prose:
    #   C   -> "VCP <code> C <cur-dec> <max-dec>"          -> current (decimal)
    #   SNC -> "VCP <code> SNC x<sl>"                       -> SL byte  (hex)
    #   CNC -> "VCP <code> CNC x<mh> x<ml> x<sh> x<sl>"     -> SL byte  (last token)
    #   ERR -> unsupported/unreadable                       -> None
    # For SNC and CNC the wanted byte is always the LAST token (the SL low byte),
    # so they share one path. Total: any malformed line yields None, never raises,
    # so the TUI poll loop can't crash on a garbled read.
    for line in out.splitlines():
        if not line.startswith("VCP"):
            continue
        t = line.split()
        if len(t) < 4:                       # "VCP DC ERR" / truncated
            return None
        typ = t[2]
        try:
            if typ == "C":
                return int(t[3])             # current; max = t[4], unused for now
            if typ in ("SNC", "NC", "CNC"):
                return int(t[-1].lstrip("xX"), 16)
        except (ValueError, IndexError):
            return None
        return None                          # ERR / T / unknown type
    return None                              # no VCP line at all


def _parse_raw(out):
    # Like _parse_terse but also extracts the monitor-reported max:
    #   C   -> (cur-dec, max-dec)        from "VCP <c> C <cur> <max>"
    #   CNC -> (SL, ML)                  cur = last token, max = 2nd hex (ML byte)
    #   SNC -> (SL, None)                single byte, no max reported
    #   ERR/T/malformed -> (None, None); never raises.
    for line in out.splitlines():
        if not line.startswith("VCP"):
            continue
        t = line.split()
        if len(t) < 4:
            return (None, None)
        typ = t[2]
        try:
            if typ == "C":
                return (int(t[3]), int(t[4]))
            if typ == "SNC":
                return (int(t[-1].lstrip("xX"), 16), None)
            if typ in ("NC", "CNC"):
                return (int(t[-1].lstrip("xX"), 16), int(t[4].lstrip("xX"), 16))
        except (ValueError, IndexError):
            return (None, None)
        return (None, None)
    return (None, None)


def detect_bus(model=MODEL):
    # Parse `ddcutil detect`; return the i2c bus number whose monitor model
    # string contains `model`. The bus is assigned by the kernel per GPU+port,
    # so it differs on every machine — never hardcode it.
    try:
        out = proc.run_proc(["ddcutil", "detect"], text=True).stdout
    except FileNotFoundError:
        return None
    bus = None
    for line in out.splitlines():
        m = re.search(r"/dev/i2c-(\d+)", line)
        if m:
            bus = m.group(1)                 # start of a new display block
        elif model.lower() in line.lower() and bus is not None:
            return bus                       # this block's monitor matches
    return None


def resolve_bus(explicit=None):
    # Priority: explicit --bus  >  $BEBENQLI_BUS  >  auto-detect by model.
    if explicit is not None:
        return str(explicit)
    env = os.environ.get("BEBENQLI_BUS")
    if env:
        return env
    return detect_bus()


class Ddc:
    def __init__(self, bus, verbose=False):
        self.bus     = str(bus)
        self.verbose = verbose
        self.cmd     = build_cmd(bus)        # ddcutil base command for this bus

    def setvcp(self, code, value, chan=None, noverify=False):
        # Some BenQ registers (d9 = MoonHalo) are 16-bit multiplexed:
        # high byte selects a sub-feature channel, low byte is its value.
        # Such writes never pass ddcutil's read-back verify (it only reads the
        # low byte), so use --noverify to skip the retry storm. d7 (MH on/off)
        # also needs it — its read-back returns a composite ambient value.
        extra = []
        if chan is not None:
            value = (chan << 8) | value
            extra = ["--noverify"]
        elif noverify:
            extra = ["--noverify"]
        cmd = self.cmd + extra + ["setvcp", code, str(value)]
        if self.verbose:
            print("$ " + " ".join(cmd), file=sys.stderr)
        r = proc.run_proc(cmd)
        return r.returncode == 0   # True = ddcutil accepted the write

    def getvcp(self, code):
        # --terse gives machine-readable "VCP <code> <type> <vals>" (see _parse_terse).
        cmd = self.cmd + ["--terse", "getvcp", code]
        if self.verbose:
            print("$ " + " ".join(cmd), file=sys.stderr)
        return _parse_terse(proc.run_proc(cmd, text=True).stdout)

    def read_raw(self, code):
        # Like getvcp, but also returns the monitor-reported max (None when the
        # type carries no max, e.g. SNC). Used by the idebug console to show the
        # real max and cross-check it against the hardcoded CONTROLS range.
        cmd = self.cmd + ["--terse", "getvcp", code]
        if self.verbose:
            print("$ " + " ".join(cmd), file=sys.stderr)
        return _parse_raw(proc.run_proc(cmd, text=True).stdout)
