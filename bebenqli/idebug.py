"""The `idebug` interactive probe console: validate VCP codes against the real
panel with a human in the loop.

`Session` is the pure, synchronous engine (no threads, no pragma) — it reads,
writes-and-verifies, snapshots every readable code to spot coupling, and logs an
evidence trail. `Console` (added below) is the thin `cmd.Cmd` shell around it.

This is the testable counterpart to the TUI's threaded `!` discover overlay
(`debug.Prober`), which stays as-is."""
import cmd
import time

try:
    import readline  # noqa: F401  — gives the prompt history + line editing for free
except ImportError:  # pragma: no cover
    pass

from collections import namedtuple

from .cli import _cli_controls, _resolve
from .controls import CONTROLS, NOISE, SCAN_CODES, _cli_name, slug
from .debug import _dump_yaml
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

    # ── discovery (unmapped `missing` controls) ──────────────────────────────
    def baseline_codes(self):
        # Read every discovery candidate once; keep the codes that answer.
        return {code: v for code in SCAN_CODES
                if (v := self.ddc.getvcp(code)) is not None}

    def poll_once(self, code, prev):
        # One watch tick: (value, did-it-move-since-prev).
        v = self.ddc.getvcp(code)
        return v, (v is not None and v != prev)

    @staticmethod
    def step(trails, code, v):
        # Append v to a code's trail if distinct from its last value. -> appended?
        trail = trails.setdefault(code, [])
        if not trail or trail[-1] != v:
            trail.append(v)
            return True
        return False

    @staticmethod
    def rank_movers(trails):
        # Codes that moved most while you wiggled the setting, most-changed first.
        return sorted(trails.items(), key=lambda kv: -len(kv[1]))

    def yaml_doc(self):
        return {"control": self.focus["label"] if self.focus else "discover",
                "vcp": self.focus.get("vcp") if self.focus else None,
                "entries": self.log}


def _targets():
    # cli-name -> ctrl for everything idebug can point at: mapped (has vcp) and
    # unmapped `missing` controls (probed via discovery).
    return {_cli_name(c["label"]): c for c in CONTROLS
            if "vcp" in c or c.get("type") == "missing"}


class Console(cmd.Cmd):  # pragma: no cover
    """Line-based REPL over a Session. All I/O lives here; the logic is in Session."""

    def __init__(self, session, name, targets):
        super().__init__()
        self.s = session
        self.name = name
        self.targets = targets
        self.prompt = f"{name}> "
        self.intro = self._banner()

    # ── orientation ──────────────────────────────────────────────────────────
    def _banner(self):
        c = self.s.focus
        if "vcp" not in c:
            return (f"idebug: {c['label']}  (unmapped — discovery)\n"
                    "  turn the setting on the MONITOR'S OSD, then: watch · q")
        spec = ("{" + "|".join(c["names"]) + "}" if c["type"] == "cycle"
                else f"{c['min']}..{c['max']}")
        r = self.s.read(c)
        cur = "(write-only)" if r is None else f"{_fmt(c, r[0])}" + (
            f"  max {r[1]}" if r[1] is not None else "")
        return (f"idebug: {c['label']}  (vcp {c['vcp']}, {c['type']} {spec})\n"
                f"  read: {cur}\n"
                "  cmds: <v> set+verify · w <v> write-only · r read · watch · "
                "d diff-all · use <ctrl> · note <txt> · q")

    def _setfocus(self, name):
        self.name = name
        self.s.focus = self.targets[name]
        self.prompt = f"{name}> "

    # ── writes ───────────────────────────────────────────────────────────────
    def default(self, line):                 # bare "50" / "cinema" -> set
        self.do_set(line)

    def do_set(self, arg):
        self._do_write(arg, self.s.set_verify)

    def do_w(self, arg):
        self._do_write(arg, self.s.write_only)

    def _do_write(self, arg, fn):
        c = self.s.focus
        if "vcp" not in c:
            print("  unmapped control — use `watch` to discover its code")
            return
        try:
            rep = fn(c, arg)
        except ValueError as e:
            print(f"  {e}")
            return
        print("  " + self._report(c, rep))
        if rep.status in ("verified", "writeonly"):
            self._ask_visible()

    def _report(self, c, rep):
        tail = ""
        if rep.else_changed:
            tail = " · else: " + ", ".join(
                f"{vcp}:{o}→{n}" for vcp, (o, n) in rep.else_changed.items())
        if rep.status == "failed":
            return f"set {c['vcp']}: FAILED (ddcutil rejected){tail}"
        if rep.status == "writeonly":
            return f"set {c['vcp']}→{rep.shown} (write-only, unverified){tail}"
        verdict = "verified" if rep.status == "verified" else "MISMATCH"
        return f"set {c['vcp']}→{rep.shown} · readback {rep.got_shown} ({verdict}){tail}"

    def _ask_visible(self):
        ans = input("  visible change? [y/N/skip] ").strip().lower()
        self.s.set_visible(ans or "skip")

    # ── reads ────────────────────────────────────────────────────────────────
    def do_r(self, arg):
        c = self.s.focus
        r = self.s.read(c) if "vcp" in c else None
        if r is None:
            print("  (write-only / unmapped — can't read)")
        else:
            mx = f"  (max {r[1]})" if r[1] is not None else ""
            print(f"  {c['vcp']} = {_fmt(c, r[0])}{mx}")

    def do_d(self, arg):
        moved = self.s.diff(self.s.baseline, self.s.snapshot())
        if not moved:
            print("  no change since start")
            return
        for vcp, (o, n) in moved.items():
            tag = "  (noise)" if vcp in NOISE else ""
            print(f"  {vcp}: {o}→{n}{tag}")

    do_diff = do_d

    # ── watch / discover (turn the OSD; Ctrl-C stops) ─────────────────────────
    def do_watch(self, arg):
        c = self.s.focus
        if "vcp" not in c:
            self._discover()
        elif c.get("noread"):
            print("  (write-only — nothing to watch)")
        else:
            self._watch_one(c["vcp"])

    def _watch_one(self, vcp):
        prev = self.s.ddc.getvcp(vcp)
        print(f"  watching {vcp} — change it on the MONITOR'S OSD (Ctrl-C stops)")
        try:
            while True:
                v, moved = self.s.poll_once(vcp, prev)
                if moved:
                    print(f"  {vcp}: {prev}→{v}")
                    prev = v
                time.sleep(0.3)
        except KeyboardInterrupt:
            print("\n  stopped")

    def _discover(self):
        print("  baseline sweep…")
        base = self.s.baseline_codes()
        trails = {code: [v] for code, v in base.items()}
        print(f"  {len(base)} live codes — wiggle the setting on the OSD (Ctrl-C stops)")
        try:
            while True:
                for code in list(base):
                    v, moved = self.s.poll_once(code, trails[code][-1])
                    if moved and self.s.step(trails, code, v):
                        top = self.s.rank_movers({c: t for c, t in trails.items()
                                                  if len(t) > 1})
                        print("  " + " · ".join(f"{c}:{'→'.join(map(str, t))}"
                                                for c, t in top[:5]))
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n  stopped")

    # ── meta ─────────────────────────────────────────────────────────────────
    def do_use(self, arg):
        name = arg.strip()
        if name not in self.targets:
            print("  unknown control. options: " + ", ".join(sorted(self.targets)))
            return
        self._setfocus(name)
        print(self._banner())

    def do_note(self, arg):
        self.s.add_note(arg.strip())
        print("  noted")

    def do_q(self, arg):
        return self._quit()

    def do_EOF(self, arg):
        print()
        return self._quit()

    def _quit(self):
        if self.s.originals:
            ans = input(f"  restore {len(self.s.originals)} change(s)? [y/N] ")
            if ans.strip().lower() == "y":
                print(f"  restored {self.s.restore()}")
        if self.s.log:
            _dump_yaml(self.s.focus["label"], self.s.yaml_doc())
            print(f"  log: /tmp/benq/{slug(self.s.focus['label'])}.yaml")
        return True


def main(ddc, name):  # pragma: no cover
    targets = _targets()
    if name not in targets:
        print("usage: bebenqli idebug <control>\ncontrols: "
              + ", ".join(sorted(targets)))
        return 2
    Console(Session(ddc, focus=targets[name]), name, targets).cmdloop()
    return 0
