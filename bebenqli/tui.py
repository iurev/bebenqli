"""Interactive blessed TUI: the settings screen, its write/poll worker threads,
and the key-driven event loop. The `!` probe tool lives in debug.py, the
window-title helpers in term.py. Excluded from coverage (can't drive a real
terminal in CI)."""
import atexit
import threading
import time

from blessed import Terminal

from .controls import CONTROLS, HEADERS, INTERACT, RENDER, W
from .debug import Prober
from .format import render_row
from .term import set_window_title, restore_window_title


class UI:  # pragma: no cover
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
        self.prober    = Prober(ddc)   # the ! probe/discover tool (own state)
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
            self.ddc.setvcp(ctrl["vcp"], target, ctrl.get("chan"), ctrl.get("noverify"))
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

    def _poll(self, idx, target):
        deadline = time.time() + 8.0
        while time.time() < deadline:
            actual = self.ddc.getvcp(CONTROLS[idx]["vcp"])
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

    def _row_text(self, i, ctrl, vals, loaded, pending, ticks, pool, q):
        blink_on = ticks[i] % 2 == 0
        ent      = self.entry_buf if i == self.entry else None
        content  = render_row(ctrl, vals[i], loaded[i], pending[i], blink_on, ent)
        # dim non-matching rows during search (keep spacing, drop highlight)
        if self.searching and q and ctrl["type"] not in HEADERS and i not in pool:
            content = f" {content[1:]}"
        return content

    def _cycle_options(self, i, ctrl, vals, loaded):
        # selected cycle: numbered options below the row for direct pick
        if not (i == self.sel and ctrl["type"] == "cycle" and loaded[i]):
            return []
        cur = vals[i]
        out = []
        for n, name in enumerate(ctrl["names"], 1):
            mark = "●" if ctrl["opts"][n - 1] == cur else " "
            out.append(f"│{f'       {n} {mark} {name}':<{W}}│")
        return out

    def _footer(self):
        if self.searching:
            return f"│ {f'/ {self.search_q}█':<{W-1}}│"
        return f"│ {'↑↓ move ←→/digit set / find ! listen q quit':<{W-1}}│"

    def draw(self, term):
        with self.lock:
            vals    = list(self.vals)
            loaded  = list(self.loaded)
            pending = list(self.pending)
            ticks   = list(self.ticks)
        pool = self._filtered()
        q    = self.search_q.lower()

        lines = [f"╭{'─' * W}╮",
                 f"│ {'BenQ RD280U Monitor Control':<{W-1}}│",
                 f"╞{'═' * W}╡"]
        for i, ctrl in enumerate(CONTROLS):
            if i not in RENDER:                   # hidden items + empty headers
                continue
            padded = f"{self._row_text(i, ctrl, vals, loaded, pending, ticks, pool, q):<{W}}"
            if ctrl["type"] not in HEADERS and i == self.sel:
                lines.append(f"│{term.reverse}{padded}{term.normal}│")
            else:
                lines.append(f"│{padded}│")
            lines += self._cycle_options(i, ctrl, vals, loaded)
        lines.append(f"╞{'═' * W}╡")
        lines.append(self._footer())
        lines.append(f"╰{'─' * W}╯")
        print(term.home + term.clear + "\n".join(lines), end="", flush=True)

    # ── Startup read + event loop ──────────────────────────────────────────
    def seed(self, i):
        # Read one control's current value into the model at startup. Write-only
        # controls (and headers) get a sensible default and are marked loaded.
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
            self.vals[i]   = self._clamp(ctrl, v, default)
            self.loaded[i] = True

    @staticmethod
    def _clamp(ctrl, v, default):
        if v is None:
            return default
        if ctrl["type"] == "range":
            return max(ctrl["min"], min(ctrl["max"], v))
        if ctrl["type"] == "cycle" and v not in ctrl["opts"]:
            return ctrl["opts"][0]
        return v

    def _timeout(self):
        # Poll fast while anything is animating (unloaded / pending) or probing;
        # otherwise block until the next key.
        with self.lock:
            animating = any(not self.loaded[i] or self.pending[i] is not None
                            for i in INTERACT if CONTROLS[i]["type"] != "missing")
        return 0.25 if (animating or self.prober.active) else None

    def _tick(self):
        with self.lock:
            for i in range(len(CONTROLS)):
                if self.pending[i] is not None:
                    self.ticks[i] += 1

    def run_loop(self, term):
        self.draw(term)
        while True:
            key = term.inkey(timeout=self._timeout())
            if self.prober.active:
                self._handle_debug(term, key)
                continue
            if self.entry is not None:
                self._handle_entry(key)
                self.draw(term)
                continue
            if self.searching:
                self._handle_search(key)
            elif self._handle_normal(key):
                break                          # q in normal mode -> quit
            self._tick()
            self.draw(term)

    def _handle_debug(self, term, key):
        if str(key) == "!" or key.name == "KEY_ESCAPE" or str(key).lower() == "q":
            self.prober.stop()
        if self.prober.active:
            self.prober.draw(term)
        else:
            self.draw(term)

    def _handle_entry(self, key):
        if key.name == "KEY_ENTER" or str(key) in ("\n", "\r"):
            self.commit_entry()
        elif key.name == "KEY_ESCAPE":
            self.entry, self.entry_buf = None, ""
        elif key.name in ("KEY_BACKSPACE", "KEY_DELETE"):
            self.entry_buf = self.entry_buf[:-1]
            if not self.entry_buf:
                self.entry = None
        elif str(key).isdigit():
            self.entry_buf += str(key)

    def _handle_search(self, key):
        if key.name == "KEY_ESCAPE" or str(key) in ("\n", "\r"):
            self.searching = False
        elif key.name == "KEY_UP":
            self.move(-1)
        elif key.name == "KEY_DOWN":
            self.move(1)
        elif key.name in ("KEY_BACKSPACE", "KEY_DELETE"):
            self.search_q = self.search_q[:-1]
        elif not key.is_sequence and str(key).isprintable():
            self.search_q += str(key)
            pool = self._filtered()            # auto-jump to first match
            if pool and self.sel not in pool:
                self.sel = pool[0]

    def _handle_normal(self, key):
        # Returns True to quit. Digit keys open number-entry (range) or jump to
        # an option (cycle); the type test picks which.
        if key.name in ("KEY_UP", "KEY_DOWN"):
            self.move(-1 if key.name == "KEY_UP" else 1)
        elif key.name in ("KEY_LEFT", "KEY_RIGHT"):
            self.change(self.sel, -1 if key.name == "KEY_LEFT" else 1)
        elif str(key) == "/":
            self.searching, self.search_q = True, ""
        elif str(key) == "!":
            self.prober.start(self.sel)
        elif str(key).isdigit():
            self._handle_digit(str(key))
        elif str(key).lower() == "q":
            return True
        return False

    def _handle_digit(self, digit):
        kind = CONTROLS[self.sel]["type"]
        if kind == "range":
            self.entry, self.entry_buf = self.sel, digit
        elif kind == "cycle":
            self.pick_opt(self.sel, int(digit))


def main(ddc):  # pragma: no cover
    set_window_title()
    atexit.register(restore_window_title)   # revert name on quit / Ctrl-C
    term = Terminal()
    ui   = UI(ddc)

    for i in range(len(CONTROLS)):          # read every control in parallel
        threading.Thread(target=ui.seed, args=(i,), daemon=True).start()

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        ui.run_loop(term)
