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
        cmd = self.cmd + ["getvcp", code]
        if self.verbose:
            print("$ " + " ".join(cmd), file=sys.stderr)
        r = proc.run_proc(cmd, text=True)
        out = r.stdout
        m = re.search(r"current value\s*=\s*(\d+)", out)
        if m: return int(m.group(1))
        m = re.search(r"sl=0x([0-9a-fA-F]+)", out)
        if m: return int(m.group(1), 16)
        m = re.search(r"Volume level:\s*(\d+)", out)
        if m: return int(m.group(1))
        # fallback: trailing "(0x..)" / "(00x..)" hex, e.g. volume 0 = "Fixed (default) level (0x00)"
        m = re.search(r"\(0*x([0-9a-fA-F]+)\)", out)
        if m: return int(m.group(1), 16)
        return None
