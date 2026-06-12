"""The `idebug` interactive probe console: validate VCP codes against the real
panel with a human in the loop.

`Session` is the pure, synchronous engine (no threads, no pragma) — it reads,
writes-and-verifies, snapshots every readable code to spot coupling, and logs an
evidence trail. `Console` (added below) is the thin `cmd.Cmd` shell around it.

This is the testable counterpart to the TUI's threaded `!` discover overlay
(`debug.Prober`), which stays as-is."""
from collections import namedtuple

from .cli import _cli_controls, _resolve
from .format import _fmt

# status: verified | mismatch | writeonly | failed
Report = namedtuple("Report", "status target shown got got_shown else_changed")


class Session:
    def __init__(self, ddc, focus=None):
        self.ddc = ddc
        self.controls = _cli_controls()      # cli-name -> ctrl (vcp-carrying only)
        self.focus = focus                   # ctrl dict, or None during discovery
        self.log = []                        # evidence entries (-> yaml_doc)
        self.originals = {}                  # vcp -> (value, ctrl) before first write
        self.baseline = self.snapshot()      # entry state, for the `d` (diff) command

    # ── reads ────────────────────────────────────────────────────────────────
    def snapshot(self):
        # Read every readable mapped control -> {vcp: value}. The coupling surface.
        out = {}
        for c in self.controls.values():
            if c.get("noread"):
                continue
            v = self.ddc.getvcp(c["vcp"])
            if v is not None:
                out[c["vcp"]] = v
        return out

    def read(self, ctrl):
        # (cur, max) for the focused control, or None when it can't be read back.
        if ctrl.get("noread"):
            return None
        return self.ddc.read_raw(ctrl["vcp"])

    @staticmethod
    def diff(before, after):
        # Codes whose value moved between two snapshots -> {vcp: (old, new)}.
        return {vcp: (before.get(vcp), after.get(vcp))
                for vcp in set(before) | set(after)
                if before.get(vcp) != after.get(vcp)}

    # ── writes ───────────────────────────────────────────────────────────────
    def set_verify(self, ctrl, valstr):
        # write then read-back compare (unless the control can't be read).
        return self._write(ctrl, _resolve(ctrl, valstr), verify=not ctrl.get("noread"))

    def write_only(self, ctrl, valstr):
        # fire-and-forget write, never verify (the `w` command).
        return self._write(ctrl, _resolve(ctrl, valstr), verify=False)

    def _write(self, ctrl, target, verify):
        vcp = ctrl["vcp"]
        before = self.snapshot()
        self.originals.setdefault(vcp, (before.get(vcp), ctrl))   # for restore
        ok = self.ddc.setvcp(vcp, target, ctrl.get("chan"), ctrl.get("noverify"))
        got = None
        if not ok:
            status = "failed"
        elif not verify:
            status = "writeonly"
        else:
            got = self.ddc.read_raw(vcp)[0]
            status = "verified" if got == target else "mismatch"
        else_changed = self.diff(before, self.snapshot())
        else_changed.pop(vcp, None)                # the focus code itself isn't "else"
        self.log.append({"action": "set", "vcp": vcp, "wrote": target,
                         "readback": got, "status": status,
                         "else_changed": {k: list(v) for k, v in else_changed.items()},
                         "visible": None})
        return Report(status, target, _fmt(ctrl, target), got,
                      _fmt(ctrl, got) if got is not None else None, else_changed)

    # ── evidence ─────────────────────────────────────────────────────────────
    def set_visible(self, answer):
        if self.log:
            self.log[-1]["visible"] = answer

    def add_note(self, text):
        self.log.append({"action": "note", "text": text})

    def restore(self):
        # Write back the originals this tool captured (best-effort). Returns count.
        n = 0
        for vcp, (val, ctrl) in self.originals.items():
            if val is not None:
                self.ddc.setvcp(vcp, val, ctrl.get("chan"), ctrl.get("noverify"))
                n += 1
        return n

    def yaml_doc(self):
        return {"control": self.focus["label"] if self.focus else "discover",
                "vcp": self.focus.get("vcp") if self.focus else None,
                "entries": self.log}
