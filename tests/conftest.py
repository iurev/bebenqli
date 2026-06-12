import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bebenqli  # noqa: E402
from bebenqli import proc  # noqa: E402


class FakeProc:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class FakeMonitor:
    """Fake ddcutil + tmux behind bebenqli.run_proc.

    Routes by argv[0]; for ddcutil it understands detect/getvcp/setvcp and
    keeps an in-memory VCP value store so read-back/verify paths behave like a
    real panel. Records every command in `.calls` for assertions.
    """

    DETECT_OUT = (
        "Display 1\n"
        "   I2C bus:  /dev/i2c-7\n"
        "   Monitor:  BenQ RD280U\n"
    )

    def __init__(self):
        self.calls = []
        self.values = {}          # vcp code (lowercase) -> int current value
        self.set_fail = set()     # codes whose setvcp returns rc!=0
        self.unreadable = set()   # codes whose getvcp yields no parseable value
        self.couples = {}         # code -> (other_code, other_value): a coupling edge
        self.detect_out = self.DETECT_OUT
        self.missing_ddcutil = False

    # the seam ----------------------------------------------------------------
    def run_proc(self, cmd, text=False):
        self.calls.append(list(cmd))
        prog = cmd[0]
        if prog == "ddcutil" and self.missing_ddcutil:
            raise FileNotFoundError("ddcutil")
        if prog == "tmux":
            return FakeProc()
        if prog == "ddcutil":
            return self._ddcutil(cmd)
        return FakeProc()

    def _ddcutil(self, cmd):
        if "detect" in cmd:
            return FakeProc(stdout=self.detect_out)
        if "getvcp" in cmd:
            code = cmd[cmd.index("getvcp") + 1].lower()
            if code in self.unreadable or code not in self.values:
                return FakeProc(stdout="VCP %s ERR\n" % code)
            # machine-readable --terse continuous form: "VCP <code> C <cur> <max>".
            # C round-trips every integer value the integration tests assert,
            # regardless of the control's real NC/C type (unit tests in test_vcp
            # cover the SNC/CNC parse branches directly).
            return FakeProc(stdout="VCP %s C %d 100\n" % (code, self.values[code]))
        if "setvcp" in cmd:
            i = cmd.index("setvcp")
            code = cmd[i + 1].lower()
            val = int(cmd[i + 2])
            if code in self.set_fail:
                return FakeProc(returncode=1, stderr="rejected\n")
            # d9 is the 16-bit multiplexed Moon Halo register: the hardware only
            # ever reads back the brightness channel's LOW byte, so model that.
            self.values[code] = (val & 0xff) if code == "d9" else val
            if code in self.couples:                 # this write silently moves another
                other_code, other_val = self.couples[code]
                self.values[other_code] = other_val
            return FakeProc(returncode=0)
        return FakeProc()

    # assertion helpers -------------------------------------------------------
    def cmds(self, *needles):
        """Recorded calls whose argv contains every given token (whole-token match)."""
        return [c for c in self.calls if all(n in c for n in needles)]


@pytest.fixture
def mon(monkeypatch):
    m = FakeMonitor()
    monkeypatch.setattr(proc, "run_proc", m.run_proc)   # attribute patch — the seam
    return m


@pytest.fixture
def ddc(mon):
    """A Ddc wired to the faked monitor on bus 7 (same instance as `mon`)."""
    return bebenqli.Ddc("7")


@pytest.fixture
def wired(mon):
    """Back-compat alias for the faked monitor (was monitor + bus globals)."""
    return mon
