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
        # Capture the original for restore, keyed by (vcp, chan) so multiplexed d9
        # channels don't collide. noread channels capture None -> never restored
        # (snapshot can't read their true value, so we don't guess-write one).
        key = (vcp, ctrl.get("chan"))
        orig = None if ctrl.get("noread") else before.get(vcp)
        self.originals.setdefault(key, (orig, ctrl))
        ok = self.ddc.setvcp(vcp, target, ctrl.get("chan"), ctrl.get("noverify"))
        got = None
        if not ok:
            status = "failed"
        elif not verify:
            status = "writeonly"
        else:
            got = self.ddc.read_raw(vcp)[0]
            status = ("verified" if got == target
                      else "unverified" if got is None    # read-back failed (DDC error)
                      else "mismatch")
        # else-changed = coupling (drop the focus code itself). Self-drifting
        # auto-movers (e2/e5) may also show here; the human judges those — we
        # don't guess-filter, since that would hide real edges too.
        else_changed = self.diff(before, self.snapshot())
        else_changed.pop(vcp, None)
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

    def record_watch(self, vcp, trail):
        # Persist a watch session's observed sequence so it lands in the YAML.
        self.log.append({"action": "watch", "vcp": vcp, "observed": list(trail)})

    def record_watch_all(self, events):
        # Persist a `watch all` session: every [vcp, old, new] transition seen.
        self.log.append({"action": "watch-all", "events": [list(e) for e in events]})

    def record_discovery(self, trails):
        # Persist the ranked movers from a discovery sweep (codes that actually
        # moved, most-changed first).
        movers = [{"vcp": code, "trail": trail}
                  for code, trail in self.rank_movers(trails) if len(trail) > 1]
        self.log.append({"action": "discover", "movers": movers})

    # ── formatting (pure — kept here so it's tested, not in the pragma'd shell) ─
    @staticmethod
    def spec_str(ctrl):
        if ctrl["type"] == "cycle":
            return "{" + "|".join(ctrl["names"]) + "}"
        return f"{ctrl['min']}..{ctrl['max']}"

    @staticmethod
    def report_line(ctrl, rep):
        tail = ""
        if rep.else_changed:
            tail = " · else: " + ", ".join(
                f"{vcp}:{o}→{n}" for vcp, (o, n) in rep.else_changed.items())
        if rep.status == "failed":
            return f"set {ctrl['vcp']}: FAILED (ddcutil rejected){tail}"
        if rep.status == "writeonly":
            return f"set {ctrl['vcp']}→{rep.shown} (write-only, unverified){tail}"
        if rep.status == "unverified":
            return f"set {ctrl['vcp']}→{rep.shown} (no read-back — DDC error){tail}"
        verdict = "verified" if rep.status == "verified" else "MISMATCH"
        return (f"set {ctrl['vcp']}→{rep.shown} · readback {rep.got_shown} "
                f"({verdict}){tail}")

    def restore(self):
        # Write back the originals this tool captured (best-effort). Returns count.
        n = 0
        for (vcp, _chan), (val, ctrl) in self.originals.items():
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

    def emptyline(self):
        pass                                     # bare Enter is a no-op (don't repeat)

    # ── orientation ──────────────────────────────────────────────────────────
    def _banner(self):
        c = self.s.focus
        if "vcp" not in c:
            return (f"idebug: {c['label']}  (unmapped — discovery)\n"
                    "  turn the setting on the MONITOR'S OSD, then: watch · q")
        spec = self.s.spec_str(c)
        r = self.s.read(c)
        cur = "(write-only)" if r is None else f"{_fmt(c, r[0])}" + (
            f"  max {r[1]}" if r[1] is not None else "")
        return (f"idebug: {c['label']}  (vcp {c['vcp']}, {c['type']} {spec})\n"
                f"  read: {cur}\n"
                "  cmds: set <val> (or just type <val>) · lazyset <val> · get · "
                "watch · watch all · diff · use <ctrl> · note <txt> · q")

    def _setfocus(self, name):
        self.name = name
        self.s.focus = self.targets[name]
        self.prompt = f"{name}> "

    # ── writes ───────────────────────────────────────────────────────────────
    def default(self, line):                 # bare "50" / "cinema" -> set
        self.do_set(line)

    def do_set(self, arg):
        self._do_write(arg, self.s.set_verify)

    def do_lazyset(self, arg):
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
        print("  " + self.s.report_line(c, rep))
        if rep.status in ("verified", "writeonly"):
            self._ask_visible()

    def _ask_visible(self):
        ans = input("  visible change? [y/N/skip] ").strip().lower()
        self.s.set_visible(ans or "skip")

    # ── reads ────────────────────────────────────────────────────────────────
    def do_get(self, arg):
        c = self.s.focus
        r = self.s.read(c) if "vcp" in c else None
        if r is None:
            print("  (write-only / unmapped — can't read)")
        else:
            mx = f"  (max {r[1]})" if r[1] is not None else ""
            print(f"  {c['vcp']} = {_fmt(c, r[0])}{mx}")

    def do_diff(self, arg):
        moved = self.s.diff(self.s.baseline, self.s.snapshot())
        if not moved:
            print("  no change since start")
            return
        for vcp, (o, n) in moved.items():
            tag = "  (noise)" if vcp in NOISE else ""
            print(f"  {vcp}: {o}→{n}{tag}")

    # ── watch / discover (turn the OSD; Ctrl-C stops) ─────────────────────────
    def do_watch(self, arg):
        if arg.strip() == "all":
            self._watch_all()
            return
        c = self.s.focus
        if "vcp" not in c:
            self._discover()
        elif c.get("noread"):
            print("  (write-only — nothing to watch)")
        else:
            self._watch_one(c["vcp"])

    def _watch_all(self):
        # Live coupling probe: stream every readable code so you can watch one
        # value move while you change another on the OSD.
        prev = self.s.snapshot()
        events = []
        print("  watching ALL readable codes — change anything on the OSD (Ctrl-C stops)")
        try:
            while True:
                cur = self.s.snapshot()
                for vcp, (o, n) in self.s.diff(prev, cur).items():
                    print(f"  {vcp}: {o}→{n}")
                    events.append([vcp, o, n])
                prev = cur
                time.sleep(0.3)
        except KeyboardInterrupt:
            self.s.record_watch_all(events)
            print("\n  stopped")

    def _watch_one(self, vcp):
        prev = self.s.ddc.getvcp(vcp)
        trail = [prev]
        print(f"  watching {vcp} — change it on the MONITOR'S OSD (Ctrl-C stops)")
        try:
            while True:
                v, moved = self.s.poll_once(vcp, prev)
                if moved:
                    print(f"  {vcp}: {prev}→{v}")
                    prev = v
                    trail.append(v)
                time.sleep(0.3)
        except KeyboardInterrupt:
            self.s.record_watch(vcp, trail)      # persist evidence to the YAML
            print("\n  stopped")

    def _discover(self):
        print("  baseline sweep…")
        base = self.s.baseline_codes()
        trails = {code: [v] for code, v in base.items()}
        print(f"  {len(base)} live codes — wiggle the setting on the OSD (Ctrl-C stops)")
        try:
            while True:
                changed = False
                for code in list(base):
                    v, moved = self.s.poll_once(code, trails[code][-1])
                    if moved and self.s.step(trails, code, v):
                        changed = True
                if changed:                       # print once per tick, not per code
                    top = self.s.rank_movers({c: t for c, t in trails.items()
                                              if len(t) > 1})
                    print("  " + " · ".join(f"{c}:{'→'.join(map(str, t))}"
                                            for c, t in top[:5]))
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.s.record_discovery(trails)       # persist ranked movers to the YAML
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
