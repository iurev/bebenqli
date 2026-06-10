"""The background write worker: a single coalescing thread that drains the
model's dirty set and pushes the latest value per control to the monitor, then
polls the read-back so the UI can clear the "pending" marker. Threads + hardware
I/O, so excluded from coverage."""
import threading
import time

from ..controls import CONTROLS


class Writer:  # pragma: no cover
    def __init__(self, model):
        self.model = model
        self.ddc   = model.ddc

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        # Drain dirty -> write latest value. Rapid presses collapse to one write
        # because only the newest value per idx survives in the model. Runs off
        # the input loop so keys never block on ddcutil.
        m = self.model
        while True:
            with m.lock:
                while not m.dirty:
                    m.cv.wait()
                idx    = m.dirty.pop()
                target = m.vals[idx]
                m.pending[idx] = target
            ctrl = CONTROLS[idx]
            self.ddc.setvcp(ctrl["vcp"], target, ctrl.get("chan"), ctrl.get("noverify"))
            if ctrl.get("noread"):
                with m.lock:                          # can't read back; trust write
                    if m.pending[idx] == target:
                        m.pending[idx] = None
            else:
                threading.Thread(target=self._poll, args=(idx, target), daemon=True).start()

    def _poll(self, idx, target):
        m = self.model
        deadline = time.time() + 8.0
        while time.time() < deadline:
            actual = self.ddc.getvcp(CONTROLS[idx]["vcp"])
            with m.lock:
                if m.pending[idx] != target:          # superseded by a newer write
                    return
                if actual == target:
                    m.pending[idx] = None
                    return
            time.sleep(0.3)
        with m.lock:
            if m.pending[idx] == target:
                m.pending[idx] = None
