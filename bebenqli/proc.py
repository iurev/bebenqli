"""The single place the package shells out (ddcutil, tmux). Tests fake the
monitor by replacing this one function, so it is the whole hardware boundary.

Callers MUST reference it as ``proc.run_proc`` (module attribute), never
``from .proc import run_proc`` — binding the name at import time would hide it
from monkeypatching and silently hit real hardware in tests."""
import subprocess


def run_proc(cmd, text=False):
    # Single seam for every external command (ddcutil, tmux). Tests replace
    # this to fake the monitor without touching real hardware.
    return subprocess.run(cmd, capture_output=True, text=text)  # pragma: no cover
