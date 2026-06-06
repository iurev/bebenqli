#!/usr/bin/env python3
import subprocess
import os
import re
import sys
import threading
import time
from blessed import Terminal


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

__version__ = "0.0.1"

MODEL   = "RD280U"          # auto-detect: i2c bus whose monitor matches this
BUS     = None              # resolved at startup (--bus / $BEBENQLI_BUS / detect)
CMD     = None              # ddcutil base command, built once bus is known
VERBOSE = False             # CLI -v: echo each ddcutil command to stderr


def build_cmd(bus):
    return ["ddcutil", "--bus", str(bus), "--permit-unknown-feature"]


def detect_bus(model=MODEL):
    # Parse `ddcutil detect`; return the i2c bus number whose monitor model
    # string contains `model`. The bus is assigned by the kernel per GPU+port,
    # so it differs on every machine — never hardcode it.
    try:
        out = subprocess.run(["ddcutil", "detect"], capture_output=True,
                             text=True).stdout
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

CONTROLS = [
    # ── Input ──────────────────────────────────────────────────────────────
    {"type": "group", "label": "Input"},
    {"label": "Source",         "vcp": "60", "type": "cycle",
     "opts": [0x0f, 0x11, 0x13], "names": ["DP", "HDMI", "USB-C"]},

    # ── Audio ──────────────────────────────────────────────────────────────
    {"type": "group", "label": "Audio"},
    {"label": "Volume",         "vcp": "62", "type": "range", "min": 0, "max": 50, "confirmed": True},
    {"label": "Mute",           "type": "dead"},  # 8d flaky on fw 0.25 — use Volume=0

    # ── Coding Booster ─────────────────────────────────────────────────────
    {"type": "group",   "label": "Coding Booster"},
    {"type": "section", "label": "Moon Halo"},
    # d9 is a 16-bit multiplexed register: write (chan<<8)|value. Only
    # brightness (0x01) and color temp (0x07) actually respond on this
    # firmware. Color temp can't be read back (d9 read only returns the
    # brightness channel), so noread=True keeps a local value.
    {"label": "MH Brightness",  "vcp": "d9", "chan": 0x01, "type": "range",
     "min": 1, "max": 10, "confirmed": True},
    {"label": "MH Color Temp",  "vcp": "d9", "chan": 0x07, "type": "range",
     "min": 1, "max": 10, "noread": True, "confirmed": True},
    {"label": "MH Switch",      "vcp": "d7", "type": "cycle",
     "opts": [0x20, 0x10], "names": ["ON", "OFF"],
     "noread": True, "noverify": True, "confirmed": True},
    {"label": "MH Light Mode",  "type": "dead"},
    {"label": "MH Non-Step",    "type": "dead"},
    {"type": "section", "label": "Other"},
    {"label": "KVM Switch",     "type": "missing"},
    {"label": "Power Key LED",  "type": "missing"},
    {"label": "LED Indicator",  "type": "missing"},
    {"label": "MST",            "type": "missing"},

    # ── Eye Care ───────────────────────────────────────────────────────────
    {"type": "group",   "label": "Eye Care"},
    {"type": "section", "label": "Night Protection"},
    {"label": "Night Mode",     "vcp": "d1", "type": "cycle",
     "opts": [0, 1, 2], "names": ["OFF", "ON", "AUTO"], "confirmed": True},
    {"label": "Night Level",    "vcp": "d0", "type": "range", "min": 1, "max": 10, "confirmed": True},
    {"type": "section", "label": "Other"},
    {"label": "Low Blue Light", "vcp": "19", "type": "range", "min": 0, "max": 5, "confirmed": True},
    {"label": "Color Weakness", "type": "missing"},  # fd — not yet verified
    # {"label": "Color Weakness", "vcp": "fd", "type": "cycle",
    #  "opts": [0, 3, 4], "names": ["OFF", "Green", "Red"]},
    {"label": "Eye Reminder",   "type": "missing"},
    {"type": "section", "label": "BI Gen2"},
    {"label": "BI Switch",      "vcp": "e2", "type": "cycle",
     "opts": [0, 255], "names": ["OFF", "ON"]},
    {"label": "BI Sensitivity", "vcp": "e5", "type": "range", "min": 1, "max": 10},

    # ── Image ──────────────────────────────────────────────────────────────
    {"type": "group", "label": "Image"},
    {"label": "Color Mode",     "vcp": "dc", "type": "cycle",
     "opts":  [0x30, 0x31, 0x0f, 0x32, 0x1f, 0x0a, 0x12],
     "names": ["Coding Dark", "Coding Light", "M-Book", "Cinema", "ePaper", "sRGB", "User"]},
    {"label": "Brightness",     "vcp": "10", "type": "range", "min": 0, "max": 100},
    {"label": "Contrast",       "vcp": "12", "type": "range", "min": 0, "max": 100},
]

W        = 44
HEADERS  = ("group", "section")               # layout rows
NONSEL   = ("group", "section", "dead", "missing")   # non-selectable rows
HIDDEN   = ("dead", "missing")                        # not rendered at all
INTERACT = [i for i, c in enumerate(CONTROLS) if c["type"] not in NONSEL]


def _renderable():
    # Indices to draw: real items, plus headers that have ≥1 visible child.
    # A section spans until the next section/group; a group until the next group.
    n = len(CONTROLS)
    item = [CONTROLS[i]["type"] not in HIDDEN and CONTROLS[i]["type"] not in HEADERS
            for i in range(n)]
    keep = set(i for i in range(n) if item[i])
    for i, c in enumerate(CONTROLS):
        if c["type"] == "section":
            j = i + 1
            while j < n and CONTROLS[j]["type"] not in ("section", "group"):
                if item[j]:
                    keep.add(i); break
                j += 1
        elif c["type"] == "group":
            j = i + 1
            while j < n and CONTROLS[j]["type"] != "group":
                if item[j]:
                    keep.add(i); break
                j += 1
    return keep

RENDER = _renderable()

# Discovery candidate codes: everything capabilities reports, plus the whole
# 0xd0..0xff custom range (BenQ hides extra features there that may not appear
# in capabilities). Codes already mapped in CONTROLS are excluded — their
# meaning is known, so we don't poll them during discovery. 04/08/0c =
# restore-defaults / save-settings, never touch. Dead codes get pruned at the
# baseline sweep.
_CAPS   = ("02 10 12 14 16 18 1a 52 60 62 72 86 87 8a 8d c1 c2 c9 ca cc d0 d1 "
           "d2 d7 d9 dc df e1 e2 e3 e5 e6 e7 e9 eb ee ef f0 f1 f8 fd").split()
_SKIP   = {"04", "08", "0c"}
# Auto-movers that change on their own (ambient/light sensor, active-control
# counters). They polluted every discovery file with random trails, so they're
# excluded from scans. e1=active-control counter, d7=BI/ambient composite,
# e3=BI light meter.
NOISE   = {"e1", "d7", "e3"}
MAPPED  = {c["vcp"].lower() for c in CONTROLS if "vcp" in c}
SCAN_CODES = [c for c in dict.fromkeys(_CAPS + [f"{c:02x}" for c in range(0xd0, 0x100)])
              if c not in _SKIP and c not in MAPPED and c not in NOISE]


def setvcp(code, value, chan=None, noverify=False):
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
    cmd = CMD + extra + ["setvcp", code, str(value)]
    if VERBOSE:
        print("$ " + " ".join(cmd), file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0   # True = ddcutil accepted the write


def getvcp(code):
    cmd = CMD + ["getvcp", code]
    if VERBOSE:
        print("$ " + " ".join(cmd), file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True)
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


def bar(val, lo, hi, w=12):
    f = round((val - lo) / (hi - lo) * w)
    return "█" * max(0, min(w, f)) + "░" * max(0, min(w, w - f))


def render_row(ctrl, val, loaded, pending, blink_on, entry=None):
    t = ctrl["type"]
    if t == "group":                                  # top level, flush-left
        return f"▌{ctrl['label'].upper()}"
    if t == "section":                                # sub level, indent 2
        return f"  ▎{ctrl['label']}"

    label = f"{ctrl['label']:<14}"                    # items, indent 4

    if t == "missing":
        return f"    {label}  [not mapped]"
    if t == "dead":
        return f"    {label}  [hw n/a]"

    blank = pending is not None and not blink_on
    if not loaded:
        return f"    {label}  @"

    if t == "cycle":
        idx  = ctrl["opts"].index(val) if val in ctrl["opts"] else 0
        name = ctrl["names"][idx]
        return f"    {label}  {'':18}" if blank else f"    {label}  {name:<18}"
    else:
        lo, hi = ctrl["min"], ctrl["max"]
        if entry is not None:
            return f"    {label}  type: {entry}█  (={lo}..{hi})"
        d = len(str(hi))
        b = bar(val, lo, hi)
        vs = f"{val:{d}}/{hi}"
        return f"    {label}  {'':12}  {'':7}" if blank else f"    {label}  {b}  {vs:>7}"


class UI:
    def __init__(self):
        n = len(CONTROLS)
        self.vals      = [0] * n
        self.loaded    = [c["type"] in ("group", "section", "missing", "dead") for c in CONTROLS]
        self.pending   = [None] * n
        self.ticks     = [0] * n
        self.lock      = threading.Lock()
        self.cv        = threading.Condition(self.lock)
        self.dirty     = set()
        self.sel       = INTERACT[0]
        self.searching = False
        self.search_q  = ""
        self.debug     = None    # idx being listened to, or None
        self.dbg_mode  = None    # "single" (known vcp) | "discover" (unmapped)
        self.dbg_vals  = []      # single: ordered unique observed values
        self.dbg_seen  = set()
        self.dbg_base  = {}      # discover: code -> baseline value
        self.dbg_trail = {}      # discover: code -> [v0, v1, ...] distinct seq
        self.dbg_live  = []      # discover: codes alive after baseline prune
        self.dbg_phase = ""      # discover: "baseline" | "watching"
        self.dbg_prog  = (0, 0)  # discover: (done, total) during baseline
        self.entry     = None    # idx in number-entry mode, or None
        self.entry_buf = ""
        threading.Thread(target=self._writer, daemon=True).start()

    def _filtered(self):
        q = self.search_q.lower()
        if not self.searching or not q:
            return INTERACT
        return [i for i in INTERACT
                if q in CONTROLS[i]["label"].lower()]

    def move(self, direction):
        pool = self._filtered()
        if not pool:
            return
        if self.sel not in pool:
            self.sel = pool[0]
            return
        idx = pool.index(self.sel)
        self.sel = pool[(idx + direction) % len(pool)]

    def change(self, idx, delta):
        ctrl = CONTROLS[idx]
        if ctrl["type"] in ("missing",):
            return
        with self.lock:
            if not self.loaded[idx]:
                return
            if ctrl["type"] == "cycle":
                i = ctrl["opts"].index(self.vals[idx]) if self.vals[idx] in ctrl["opts"] else 0
                self.vals[idx] = ctrl["opts"][(i + delta) % len(ctrl["opts"])]
            else:
                self.vals[idx] = max(ctrl["min"], min(ctrl["max"], self.vals[idx] + delta))
            self.pending[idx] = self.vals[idx]
            self.dirty.add(idx)
            self.cv.notify()

    def pick_opt(self, idx, n):
        # Jump a cycle control straight to its n-th option (1-based).
        ctrl = CONTROLS[idx]
        if ctrl["type"] != "cycle" or not (1 <= n <= len(ctrl["opts"])):
            return
        with self.lock:
            if not self.loaded[idx]:
                return
            self.vals[idx]    = ctrl["opts"][n - 1]
            self.pending[idx] = self.vals[idx]
            self.dirty.add(idx)
            self.cv.notify()

    def _writer(self):
        # Single coalescing worker: drains dirty set, writes the *latest*
        # value per control. Rapid left/right presses collapse to one write.
        # Runs off the main loop so input never blocks on ddcutil.
        while True:
            with self.lock:
                while not self.dirty:
                    self.cv.wait()
                idx    = self.dirty.pop()
                target = self.vals[idx]
                self.pending[idx] = target
            ctrl = CONTROLS[idx]
            setvcp(ctrl["vcp"], target, ctrl.get("chan"), ctrl.get("noverify"))
            if ctrl.get("noread"):
                with self.lock:                       # can't read back; trust write
                    if self.pending[idx] == target:
                        self.pending[idx] = None
            else:
                threading.Thread(target=self._poll, args=(idx, target), daemon=True).start()

    def commit_entry(self):
        idx, buf = self.entry, self.entry_buf
        self.entry, self.entry_buf = None, ""
        if idx is None or not buf:
            return
        ctrl = CONTROLS[idx]
        v = max(ctrl["min"], min(ctrl["max"], int(buf)))
        with self.lock:
            if not self.loaded[idx]:
                return
            self.vals[idx]    = v
            self.pending[idx] = v
            self.dirty.add(idx)
            self.cv.notify()

    # ── Listen / debug mode ────────────────────────────────────────────────
    def start_debug(self):
        idx  = self.sel
        ctrl = CONTROLS[idx]
        if "vcp" in ctrl:                              # known code: watch it
            with self.lock:
                self.debug    = idx
                self.dbg_mode = "single"
                self.dbg_vals = []
                self.dbg_seen = set()
            threading.Thread(target=self._listen, args=(idx,), daemon=True).start()
        elif ctrl["type"] == "missing":                # unknown: discover code
            with self.lock:
                self.debug    = idx
                self.dbg_mode = "discover"
                self.dbg_base = {}
                self.dbg_trail = {}
                self.dbg_live = []
                self.dbg_phase = "baseline"
                self.dbg_prog = (0, len(SCAN_CODES))
            threading.Thread(target=self._discover, args=(idx,), daemon=True).start()

    def stop_debug(self):
        with self.lock:
            idx  = self.debug
            mode = self.dbg_mode
            vals = list(self.dbg_vals)
            trail = dict(self.dbg_trail)
            self.debug = None
        if idx is None:
            return
        if mode == "single":
            self._write_yaml(idx, vals)               # final flush
        else:
            self._write_discover_yaml(idx, trail)

    # ── Discovery: poll all candidate codes, find which one moves ───────────
    def _discover(self, idx):
        # Baseline: read every candidate, keep ones that answer.
        base, live = {}, []
        for n, code in enumerate(SCAN_CODES, 1):
            with self.lock:
                if self.debug != idx:
                    return
                self.dbg_prog = (n, len(SCAN_CODES))
            v = getvcp(code)
            if v is not None:
                base[code] = v
                live.append(code)
        with self.lock:
            if self.debug != idx:
                return
            self.dbg_base  = dict(base)
            self.dbg_live  = list(live)
            self.dbg_phase = "watching"

        last = dict(base)
        # Watch loop: sweep live codes, append distinct new values per code.
        while True:
            changed = False
            for code in live:
                with self.lock:
                    if self.debug != idx:
                        return
                v = getvcp(code)
                if v is None or v == last[code]:
                    continue
                last[code] = v
                with self.lock:
                    if self.debug != idx:
                        return
                    trail = self.dbg_trail.setdefault(code, [base[code]])
                    if v != trail[-1]:
                        trail.append(v)
                        changed = True
            if changed:
                with self.lock:
                    snap = {c: list(t) for c, t in self.dbg_trail.items()}
                self._write_discover_yaml(idx, snap)
            time.sleep(0.05)

    def _write_discover_yaml(self, idx, trail):
        ctrl = CONTROLS[idx]
        os.makedirs("/tmp/benq", exist_ok=True)
        # Most-changed first — the code that moved most while you wiggled.
        ordered = sorted(trail.items(), key=lambda kv: -len(kv[1]))
        lines = [
            f"label: {ctrl['label']}",
            "type: discover",
            f"scanned: {len(SCAN_CODES)}",
            "candidates:",
        ]
        if not ordered:
            lines.append("  []   # nothing moved — try widening to mapped codes")
        for code, vals in ordered:
            lines.append(f'  - vcp: "{code}"')
            lines.append(f"    steps: {len(vals)}")
            lines.append(f"    observed: [{', '.join(str(v) for v in vals)}]")
            lines.append(f"    observed_hex: [{', '.join(f'0x{v:02x}' for v in vals)}]")
        with open(f"/tmp/benq/{slug(ctrl['label'])}.yaml", "w") as f:
            f.write("\n".join(lines) + "\n")

    def _listen(self, idx):
        vcp = CONTROLS[idx]["vcp"]
        while True:
            with self.lock:
                if self.debug != idx:
                    return
            v = getvcp(vcp)
            if v is not None:
                with self.lock:
                    if self.debug != idx:
                        return
                    new = v not in self.dbg_seen
                    if new:
                        self.dbg_seen.add(v)
                        self.dbg_vals.append(v)
                        snapshot = list(self.dbg_vals)
                if new:
                    self._write_yaml(idx, snapshot)
            time.sleep(0.25)

    def _write_yaml(self, idx, vals):
        ctrl = CONTROLS[idx]
        os.makedirs("/tmp/benq", exist_ok=True)
        lines = [
            f"label: {ctrl['label']}",
            f'vcp: "{ctrl["vcp"]}"',
            f"type: {ctrl['type']}",
        ]
        if ctrl["type"] == "range":
            lines += [f"min: {ctrl['min']}", f"max: {ctrl['max']}"]
        elif ctrl["type"] == "cycle":
            lines.append(f"current_opts: [{', '.join(hex(o) for o in ctrl['opts'])}]")
            lines.append(f"current_names: [{', '.join(ctrl['names'])}]")
        lines.append(f"count: {len(vals)}")
        lines.append("observed:")
        for v in vals:
            lines.append(f"  - dec: {v}")
            lines.append(f'    hex: "0x{v:02x}"')
        with open(f"/tmp/benq/{slug(ctrl['label'])}.yaml", "w") as f:
            f.write("\n".join(lines) + "\n")

    def draw_debug(self, term):
        with self.lock:
            idx   = self.debug
            mode  = self.dbg_mode
            vals  = list(self.dbg_vals)
            trail = {c: list(t) for c, t in self.dbg_trail.items()}
            phase = self.dbg_phase
            prog  = self.dbg_prog
            nlive = len(self.dbg_live)
        if idx is None:
            return
        ctrl = CONTROLS[idx]
        path = f"/tmp/benq/{slug(ctrl['label'])}.yaml"

        if mode == "single":
            lines = [
                f"LISTEN  {ctrl['label']}  vcp={ctrl['vcp']}  ({len(vals)} unique)",
                f"change value via monitor OSD · ! / q / ESC to stop · {path}",
                "",
            ]
            for v in vals:
                lines.append(f"{v}\t(0x{v:02x})")
        else:
            if phase == "baseline":
                head = f"DISCOVER  {ctrl['label']}   baseline {prog[0]}/{prog[1]}…"
            else:
                head = f"DISCOVER  {ctrl['label']}   watching · {nlive} live codes"
            lines = [
                head,
                f"wiggle setting on monitor OSD · q / ESC to stop · {path}",
                "",
            ]
            ordered = sorted(trail.items(), key=lambda kv: -len(kv[1]))
            if not ordered:
                lines.append("(no code moved yet — change it on the monitor)")
            for code, vs in ordered:
                seq = " → ".join(str(v) for v in vs)
                lines.append(f"{code}   {seq}   ({len(vs)})")
        print(term.home + term.clear + "\n".join(lines), end="", flush=True)

    def _poll(self, idx, target):
        deadline = time.time() + 8.0
        while time.time() < deadline:
            actual = getvcp(CONTROLS[idx]["vcp"])
            with self.lock:
                if self.pending[idx] != target:
                    return
                if actual == target:
                    self.pending[idx] = None
                    return
            time.sleep(0.3)
        with self.lock:
            if self.pending[idx] == target:
                self.pending[idx] = None

    def draw(self, term):
        with self.lock:
            vals    = list(self.vals)
            loaded  = list(self.loaded)
            pending = list(self.pending)
            ticks   = list(self.ticks)

        pool = self._filtered()
        q    = self.search_q.lower()

        lines = []
        lines.append(f"╭{'─' * W}╮")
        lines.append(f"│ {'BenQ RD280U Monitor Control':<{W-1}}│")
        lines.append(f"╞{'═' * W}╡")

        for i, ctrl in enumerate(CONTROLS):
            if i not in RENDER:                   # hidden items + empty headers
                continue
            blink_on = ticks[i] % 2 == 0
            ent      = self.entry_buf if i == self.entry else None
            content  = render_row(ctrl, vals[i], loaded[i], pending[i], blink_on, ent)
            # dim non-matching rows during search
            if self.searching and q and ctrl["type"] not in HEADERS:
                in_pool = i in pool
                if not in_pool:
                    content = f" {content[1:]}"  # keep spacing, no highlight
            padded = f"{content:<{W}}"
            if ctrl["type"] not in HEADERS and i == self.sel:
                lines.append(f"│{term.reverse}{padded}{term.normal}│")
            else:
                lines.append(f"│{padded}│")

            # selected cycle: show numbered options below for direct pick
            if i == self.sel and ctrl["type"] == "cycle" and loaded[i]:
                cur = vals[i]
                for n, name in enumerate(ctrl["names"], 1):
                    mark = "●" if ctrl["opts"][n - 1] == cur else " "
                    opt  = f"       {n} {mark} {name}"
                    lines.append(f"│{opt:<{W}}│")

        lines.append(f"╞{'═' * W}╡")
        if self.searching:
            hint = f"/ {self.search_q}█"
            lines.append(f"│ {hint:<{W-1}}│")
        else:
            lines.append(f"│ {'↑↓ move ←→/digit set / find ! listen q quit':<{W-1}}│")
        lines.append(f"╰{'─' * W}╯")

        print(term.home + term.clear + "\n".join(lines), end="", flush=True)


# ── CLI (no UI): same CONTROLS, same setvcp/getvcp ─────────────────────────
def _cli_name(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def _cli_controls():
    # name -> ctrl, only controls that carry a vcp (settable/gettable)
    out = {}
    for c in CONTROLS:
        if "vcp" in c:
            out[_cli_name(c["label"])] = c
    return out


def _fmt(c, v):
    if v is None:
        return "?"
    if c["type"] == "cycle":
        return c["names"][c["opts"].index(v)] if v in c["opts"] else f"?(0x{v:02x})"
    return str(v)


def _read(c):
    if c.get("noread"):
        return None                       # write-only (d7 / d9 color temp)
    return getvcp(c["vcp"])


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


def cli(args):
    global VERBOSE
    if any(a in ("-v", "--verbose") for a in args):
        VERBOSE = True
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
            cur = "(write-only)" if c.get("noread") else _fmt(c, _read(c))
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
        print(_fmt(c, _read(c)))
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
        ok = setvcp(c["vcp"], target, c.get("chan"), c.get("noverify"))
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
        got = _read(c)                               # read-back compare
        if got == target:
            print(f"{name} = {shown}  (verified)")
            return 0
        print(f"{name}: MISMATCH wanted {shown} got {_fmt(c, got)}", file=sys.stderr)
        return 1

    print(f"unknown command: {cmd}", file=sys.stderr)
    return usage()


def set_window_title(name="bebenqli"):
    # tmux names a window after its running process (so it'd show "python3").
    # \ek..\e\\ sets the tmux window name; OSC 2 sets the terminal/pane title
    # for plain xterm-likes. Harmless where unsupported.
    sys.stdout.write(f"\033k{name}\033\\")
    sys.stdout.write(f"\033]2;{name}\007")
    sys.stdout.flush()


def main():
    set_window_title()
    term = Terminal()
    ui   = UI()

    def read(i):
        ctrl = CONTROLS[i]
        if ctrl["type"] in ("group", "section", "missing", "dead"):
            return
        if ctrl.get("noread"):                 # can't read back; seed a default,
            with ui.lock:                      # trust local state thereafter
                ui.vals[i]   = ctrl["opts"][0] if ctrl["type"] == "cycle" else ctrl.get("min", 0)
                ui.loaded[i] = True
            return
        v = getvcp(ctrl["vcp"])
        with ui.lock:
            if v is None:
                v = ctrl["opts"][0] if ctrl["type"] == "cycle" else ctrl.get("min", 0)
            elif ctrl["type"] == "range":
                v = max(ctrl["min"], min(ctrl["max"], v))
            elif ctrl["type"] == "cycle" and v not in ctrl["opts"]:
                v = ctrl["opts"][0]
            ui.vals[i]   = v
            ui.loaded[i] = True

    threads = [threading.Thread(target=read, args=(i,), daemon=True)
               for i in range(len(CONTROLS))]
    for t in threads:
        t.start()

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        ui.draw(term)
        while True:
            with ui.lock:
                any_anim = any(
                    not ui.loaded[i] or ui.pending[i] is not None
                    for i in INTERACT if CONTROLS[i]["type"] not in ("missing",)
                )
            key = term.inkey(timeout=0.25 if (any_anim or ui.debug is not None) else None)

            if ui.debug is not None:
                if (str(key) == "!" or key.name == "KEY_ESCAPE"
                        or str(key).lower() == "q"):
                    ui.stop_debug()
                ui.draw_debug(term) if ui.debug is not None else ui.draw(term)
                continue

            if ui.entry is not None:
                if key.name == "KEY_ENTER" or str(key) in ("\n", "\r"):
                    ui.commit_entry()
                elif key.name == "KEY_ESCAPE":
                    ui.entry, ui.entry_buf = None, ""
                elif key.name in ("KEY_BACKSPACE", "KEY_DELETE"):
                    ui.entry_buf = ui.entry_buf[:-1]
                    if not ui.entry_buf:
                        ui.entry = None
                elif str(key).isdigit():
                    ui.entry_buf += str(key)
                ui.draw(term)
                continue

            if ui.searching:
                if key.name == "KEY_ESCAPE" or str(key) in ("\n", "\r"):
                    ui.searching = False
                elif key.name == "KEY_UP":
                    ui.move(-1)
                elif key.name == "KEY_DOWN":
                    ui.move(1)
                elif key.name in ("KEY_BACKSPACE", "KEY_DELETE"):
                    ui.search_q = ui.search_q[:-1]
                elif not key.is_sequence and str(key).isprintable():
                    ui.search_q += str(key)
                    # auto-jump to first match when query changes
                    pool = ui._filtered()
                    if pool and ui.sel not in pool:
                        ui.sel = pool[0]
            else:
                if key.name == "KEY_UP":
                    ui.move(-1)
                elif key.name == "KEY_DOWN":
                    ui.move(1)
                elif key.name == "KEY_LEFT":
                    ui.change(ui.sel, -1)
                elif key.name == "KEY_RIGHT":
                    ui.change(ui.sel, 1)
                elif str(key) == "/":
                    ui.searching = True
                    ui.search_q  = ""
                elif str(key) == "!":
                    ui.start_debug()
                elif str(key).isdigit() and CONTROLS[ui.sel]["type"] == "range":
                    ui.entry     = ui.sel
                    ui.entry_buf = str(key)
                elif str(key).isdigit() and CONTROLS[ui.sel]["type"] == "cycle":
                    ui.pick_opt(ui.sel, int(str(key)))
                elif str(key).lower() == "q":
                    break

            with ui.lock:
                for i in range(len(CONTROLS)):
                    if ui.pending[i] is not None:
                        ui.ticks[i] += 1

            ui.draw(term)


def run():
    global BUS, CMD
    args = sys.argv[1:]

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

    BUS = resolve_bus(explicit)
    if BUS is None:
        print(f"error: no monitor matching '{MODEL}' found.\n"
              f"check `ddcutil detect`, then pass --bus N or set $BEBENQLI_BUS.",
              file=sys.stderr)
        return 1
    CMD = build_cmd(BUS)

    if args:
        return cli(args)
    main()
    return 0


if __name__ == "__main__":
    sys.exit(run())
