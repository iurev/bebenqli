"""The controller: wires the model, the write worker, and the probe tool, then
runs the key loop. Input is dispatched by an explicit Mode (one source of truth
instead of scattered booleans). Needs a real terminal, so excluded from
coverage — the testable logic lives in state.py and view.py."""
import atexit
import threading
from enum import Enum, auto

from blessed import Terminal

from ..controls import CONTROLS
from ..debug import Prober
from ..term import set_window_title, restore_window_title
from . import view
from .state import Model
from .worker import Writer


class Mode(Enum):
    NORMAL = auto()   # navigate + adjust
    SEARCH = auto()   # "/" — filter the list by label
    ENTRY  = auto()   # typing a number into a range control
    PROBE  = auto()   # "!" — the debug/discover tool is running


class UI:  # pragma: no cover
    def __init__(self, ddc):
        self.model  = Model(ddc)
        self.prober = Prober(ddc)         # the ! probe/discover tool
        self.writer = Writer(self.model)  # background ddc writes
        self.writer.start()

    @property
    def mode(self):
        if self.prober.active:           return Mode.PROBE
        if self.model.entry is not None: return Mode.ENTRY
        if self.model.searching:         return Mode.SEARCH
        return Mode.NORMAL

    def draw(self, term):
        view.draw(term, self.model.snapshot())

    def _timeout(self):
        # Poll fast while animating or probing; otherwise block until a key.
        return 0.25 if (self.model.animating() or self.prober.active) else None

    def run_loop(self, term):
        self.draw(term)
        while True:
            key = term.inkey(timeout=self._timeout())
            mode = self.mode
            if mode is Mode.PROBE:
                self._on_probe(term, key)
                continue
            if mode is Mode.ENTRY:
                self._on_entry(key)
                self.draw(term)
                continue
            if mode is Mode.SEARCH:
                self._on_search(key)
            elif self._on_normal(key):       # NORMAL; returns True to quit
                break
            self.model.tick()
            self.draw(term)

    # ── per-mode key handlers ──────────────────────────────────────────────
    def _on_probe(self, term, key):
        if str(key) == "!" or key.name == "KEY_ESCAPE" or str(key).lower() == "q":
            self.prober.stop()
        if self.prober.active:
            self.prober.draw(term)
        else:
            self.draw(term)

    def _on_entry(self, key):
        m = self.model
        if key.name == "KEY_ENTER" or str(key) in ("\n", "\r"):
            m.commit_entry()
        elif key.name == "KEY_ESCAPE":
            m.entry, m.entry_buf = None, ""
        elif key.name in ("KEY_BACKSPACE", "KEY_DELETE"):
            m.entry_buf = m.entry_buf[:-1]
            if not m.entry_buf:
                m.entry = None
        elif str(key).isdigit():
            m.entry_buf += str(key)

    def _on_search(self, key):
        m = self.model
        if key.name == "KEY_ESCAPE" or str(key) in ("\n", "\r"):
            m.searching = False
        elif key.name == "KEY_UP":
            m.move(-1)
        elif key.name == "KEY_DOWN":
            m.move(1)
        elif key.name in ("KEY_BACKSPACE", "KEY_DELETE"):
            m.search_q = m.search_q[:-1]
        elif not key.is_sequence and str(key).isprintable():
            m.search_q += str(key)
            pool = m.filtered()              # auto-jump to first match
            if pool and m.sel not in pool:
                m.sel = pool[0]

    def _on_normal(self, key):
        # Returns True to quit. Digit keys open number-entry (range) or jump to
        # an option (cycle); _on_digit picks which by control type.
        m = self.model
        if key.name in ("KEY_UP", "KEY_DOWN"):
            m.move(-1 if key.name == "KEY_UP" else 1)
        elif key.name in ("KEY_LEFT", "KEY_RIGHT"):
            m.change(m.sel, -1 if key.name == "KEY_LEFT" else 1)
        elif str(key) == "/":
            m.searching, m.search_q = True, ""
        elif str(key) == "!":
            self.prober.start(m.sel)
        elif str(key).isdigit():
            self._on_digit(str(key))
        elif str(key).lower() == "q":
            return True
        return False

    def _on_digit(self, digit):
        m = self.model
        kind = CONTROLS[m.sel]["type"]
        if kind == "range":
            m.entry, m.entry_buf = m.sel, digit
        elif kind == "cycle":
            m.pick_opt(m.sel, int(digit))


def main(ddc):  # pragma: no cover
    set_window_title()
    atexit.register(restore_window_title)   # revert name on quit / Ctrl-C
    term = Terminal()
    ui   = UI(ddc)

    for i in range(len(CONTROLS)):          # read every control in parallel
        threading.Thread(target=ui.model.seed, args=(i,), daemon=True).start()

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        ui.run_loop(term)
