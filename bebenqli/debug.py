"""The `!`-key probe tool: watch a known VCP code (single mode) or sweep the
unmapped candidate codes to find which one a hidden setting moves (discover
mode), logging observations to /tmp/benq/<label>.yaml.

A `Prober` owns its own state + lock and runs its polling on daemon threads, so
it is independent of the settings UI — the UI just holds one and forwards the
`!` key, the stop key, and the draw call. Manual-tested (hits hardware), so the
whole module is excluded from the coverage target."""
import threading
import time
from pathlib import Path

import yaml

from .controls import CONTROLS, SCAN_CODES, slug


def _dump_yaml(label, doc):  # pragma: no cover
    # Write a probe log to /tmp/benq/<label>.yaml (insertion order preserved).
    out = Path("/tmp/benq")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{slug(label)}.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


class Prober:  # pragma: no cover
    def __init__(self, ddc):
        self.ddc   = ddc
        self.lock  = threading.Lock()
        self.idx   = None        # active control index, or None when idle
        self.mode  = None        # "single" (known vcp) | "discover" (unmapped)
        # single mode
        self.vals  = []          # ordered unique observed values
        self.seen  = set()
        # discover mode
        self.base  = {}          # code -> baseline value
        self.trail = {}          # code -> [v0, v1, ...] distinct sequence
        self.live  = []          # codes alive after baseline prune
        self.phase = ""          # "baseline" | "watching"
        self.prog  = (0, 0)      # (done, total) during baseline

    @property
    def active(self):
        return self.idx is not None

    # ── start / stop ───────────────────────────────────────────────────────
    def start(self, idx):
        ctrl = CONTROLS[idx]
        if "vcp" in ctrl:                              # known code: watch it
            with self.lock:
                self.idx, self.mode = idx, "single"
                self.vals, self.seen = [], set()
            threading.Thread(target=self._listen, args=(idx,), daemon=True).start()
        elif ctrl["type"] == "missing":                # unknown: discover code
            with self.lock:
                self.idx, self.mode = idx, "discover"
                self.base, self.trail, self.live = {}, {}, []
                self.phase = "baseline"
                self.prog  = (0, len(SCAN_CODES))
            threading.Thread(target=self._discover, args=(idx,), daemon=True).start()

    def stop(self):
        with self.lock:
            idx   = self.idx
            mode  = self.mode
            vals  = list(self.vals)
            trail = dict(self.trail)
            self.idx = None
        if idx is None:
            return
        if mode == "single":
            self._write_yaml(idx, vals)               # final flush
        else:
            self._write_discover_yaml(idx, trail)

    # ── single: watch one known code ───────────────────────────────────────
    def _listen(self, idx):
        vcp = CONTROLS[idx]["vcp"]
        while True:
            with self.lock:
                if self.idx != idx:
                    return
            v = self.ddc.getvcp(vcp)
            if v is not None:
                with self.lock:
                    if self.idx != idx:
                        return
                    new = v not in self.seen
                    if new:
                        self.seen.add(v)
                        self.vals.append(v)
                        snapshot = list(self.vals)
                if new:
                    self._write_yaml(idx, snapshot)
            time.sleep(0.25)

    def _write_yaml(self, idx, vals):
        ctrl = CONTROLS[idx]
        doc = {"label": ctrl["label"], "vcp": ctrl["vcp"], "type": ctrl["type"]}
        if ctrl["type"] == "range":
            doc["min"], doc["max"] = ctrl["min"], ctrl["max"]
        elif ctrl["type"] == "cycle":
            doc["current_opts"]  = [hex(o) for o in ctrl["opts"]]
            doc["current_names"] = list(ctrl["names"])
        doc["count"]    = len(vals)
        doc["observed"] = [{"dec": v, "hex": f"0x{v:02x}"} for v in vals]
        _dump_yaml(ctrl["label"], doc)

    # ── discover: poll all candidate codes, find which one moves ───────────
    def _discover(self, idx):
        base = self._discover_baseline(idx)
        if base is not None:                       # None = stopped mid-baseline
            self._discover_watch(idx, base)

    def _discover_baseline(self, idx):
        # Read every candidate once; keep the codes that answer. Returns the
        # baseline {code: value}, or None if the user stopped during the sweep.
        base = {}
        for n, code in enumerate(SCAN_CODES, 1):
            with self.lock:
                if self.idx != idx:
                    return None
                self.prog = (n, len(SCAN_CODES))
            v = self.ddc.getvcp(code)
            if v is not None:
                base[code] = v
        with self.lock:
            if self.idx != idx:
                return None
            self.base  = dict(base)
            self.live  = list(base)
            self.phase = "watching"
        return base

    def _discover_watch(self, idx, base):
        # Sweep the live codes forever, appending distinct new values per code.
        last = dict(base)
        while True:
            changed = False
            for code in base:
                with self.lock:
                    if self.idx != idx:
                        return
                v = self.ddc.getvcp(code)
                if v is None or v == last[code]:
                    continue
                last[code] = v
                if self._record_step(idx, code, base[code], v):
                    changed = True
            if changed:
                with self.lock:
                    snap = {c: list(t) for c, t in self.trail.items()}
                self._write_discover_yaml(idx, snap)
            time.sleep(0.05)

    def _record_step(self, idx, code, baseline, v):
        # Append v to the code's trail if it differs from the last entry.
        with self.lock:
            if self.idx != idx:
                return False
            trail = self.trail.setdefault(code, [baseline])
            if v != trail[-1]:
                trail.append(v)
                return True
        return False

    def _write_discover_yaml(self, idx, trail):
        ctrl = CONTROLS[idx]
        # Most-changed first — the code that moved most while you wiggled.
        ordered = sorted(trail.items(), key=lambda kv: -len(kv[1]))
        doc = {
            "label": ctrl["label"],
            "type": "discover",
            "scanned": len(SCAN_CODES),
            "candidates": [
                {"vcp": code,
                 "steps": len(vals),
                 "observed": list(vals),
                 "observed_hex": [f"0x{v:02x}" for v in vals]}
                for code, vals in ordered
            ],
        }
        _dump_yaml(ctrl["label"], doc)

    # ── render the debug overlay ───────────────────────────────────────────
    def draw(self, term):
        with self.lock:
            idx   = self.idx
            mode  = self.mode
            vals  = list(self.vals)
            trail = {c: list(t) for c, t in self.trail.items()}
            phase = self.phase
            prog  = self.prog
            nlive = len(self.live)
        if idx is None:
            return
        ctrl = CONTROLS[idx]
        path = f"/tmp/benq/{slug(ctrl['label'])}.yaml"
        if mode == "single":
            lines = self._draw_single(ctrl, vals, path)
        else:
            lines = self._draw_discover(ctrl, trail, phase, prog, nlive, path)
        print(term.home + term.clear + "\n".join(lines), end="", flush=True)

    @staticmethod
    def _draw_single(ctrl, vals, path):
        lines = [
            f"LISTEN  {ctrl['label']}  vcp={ctrl['vcp']}  ({len(vals)} unique)",
            f"change value via monitor OSD · ! / q / ESC to stop · {path}",
            "",
        ]
        lines += [f"{v}\t(0x{v:02x})" for v in vals]
        return lines

    @staticmethod
    def _draw_discover(ctrl, trail, phase, prog, nlive, path):
        if phase == "baseline":
            head = f"DISCOVER  {ctrl['label']}   baseline {prog[0]}/{prog[1]}…"
        else:
            head = f"DISCOVER  {ctrl['label']}   watching · {nlive} live codes"
        lines = [head, f"wiggle setting on monitor OSD · q / ESC to stop · {path}", ""]
        ordered = sorted(trail.items(), key=lambda kv: -len(kv[1]))
        if not ordered:
            lines.append("(no code moved yet — change it on the monitor)")
        for code, vs in ordered:
            lines.append(f"{code}   {' → '.join(str(v) for v in vs)}   ({len(vs)})")
        return lines
