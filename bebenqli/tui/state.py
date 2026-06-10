"""The settings model: all mutable UI state + the state machine that mutates it,
with no terminal and no rendering. Pure enough to unit-test directly (drive it
with a fake ddc). The write/poll threads (worker.py) and the renderer (view.py)
read this under `lock`."""
import threading
from collections import namedtuple

from ..controls import CONTROLS, INTERACT

# An immutable snapshot the renderer draws from (taken under the model lock).
Frame = namedtuple("Frame", "vals loaded pending ticks sel searching search_q "
                            "entry entry_buf pool")


def _clamp(ctrl, v, default):
    if v is None:
        return default
    if ctrl["type"] == "range":
        return max(ctrl["min"], min(ctrl["max"], v))
    if ctrl["type"] == "cycle" and v not in ctrl["opts"]:
        return ctrl["opts"][0]
    return v


class Model:
    def __init__(self, ddc):
        self.ddc = ddc
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
        self.entry     = None    # idx in number-entry mode, or None
        self.entry_buf = ""

    # ── selection / search ────────────────────────────────────────────────
    def filtered(self):
        # Interactive rows, narrowed to the search query when searching.
        q = self.search_q.lower()
        if not self.searching or not q:
            return INTERACT
        return [i for i in INTERACT if q in CONTROLS[i]["label"].lower()]

    def move(self, direction):
        pool = self.filtered()
        if not pool:
            return
        if self.sel not in pool:
            self.sel = pool[0]
            return
        self.sel = pool[(pool.index(self.sel) + direction) % len(pool)]

    # ── value edits (each queues a coalesced write) ───────────────────────
    def _queue_write(self, idx, v):
        # caller holds self.lock. Set the value + mark it dirty for the worker.
        self.vals[idx]    = v
        self.pending[idx] = v
        self.dirty.add(idx)
        self.cv.notify()

    def change(self, idx, delta):
        ctrl = CONTROLS[idx]
        if ctrl["type"] == "missing":
            return
        with self.lock:
            if not self.loaded[idx]:
                return
            if ctrl["type"] == "cycle":
                i = ctrl["opts"].index(self.vals[idx]) if self.vals[idx] in ctrl["opts"] else 0
                v = ctrl["opts"][(i + delta) % len(ctrl["opts"])]
            else:
                v = max(ctrl["min"], min(ctrl["max"], self.vals[idx] + delta))
            self._queue_write(idx, v)

    def pick_opt(self, idx, n):
        # Jump a cycle control straight to its n-th option (1-based).
        ctrl = CONTROLS[idx]
        if ctrl["type"] != "cycle" or not (1 <= n <= len(ctrl["opts"])):
            return
        with self.lock:
            if not self.loaded[idx]:
                return
            self._queue_write(idx, ctrl["opts"][n - 1])

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
            self._queue_write(idx, v)

    # ── startup read ──────────────────────────────────────────────────────
    def seed(self, i):
        # Read one control's current value into the model. Write-only controls
        # (and headers) get a sensible default and are marked loaded.
        ctrl = CONTROLS[i]
        if ctrl["type"] in ("group", "section", "missing", "dead"):
            return
        default = ctrl["opts"][0] if ctrl["type"] == "cycle" else ctrl.get("min", 0)
        if ctrl.get("noread"):                 # can't read back; trust local state
            with self.lock:
                self.vals[i], self.loaded[i] = default, True
            return
        v = self.ddc.getvcp(ctrl["vcp"])
        with self.lock:
            self.vals[i]   = _clamp(ctrl, v, default)
            self.loaded[i] = True

    # ── queries for the loop / renderer ───────────────────────────────────
    def animating(self):
        # True while anything is still loading or has an in-flight write.
        with self.lock:
            return any(not self.loaded[i] or self.pending[i] is not None
                       for i in INTERACT if CONTROLS[i]["type"] != "missing")

    def tick(self):
        # Advance the blink counter for every pending (in-flight) control.
        with self.lock:
            for i in range(len(CONTROLS)):
                if self.pending[i] is not None:
                    self.ticks[i] += 1

    def snapshot(self):
        with self.lock:
            return Frame(
                vals=list(self.vals), loaded=list(self.loaded),
                pending=list(self.pending), ticks=list(self.ticks),
                sel=self.sel, searching=self.searching, search_q=self.search_q,
                entry=self.entry, entry_buf=self.entry_buf, pool=self.filtered())
