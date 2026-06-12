"""bebenqli — TUI + CLI to control BenQ RD280U monitors over DDC/CI (ddcutil).

Public facade: re-exports the package's surface so `import bebenqli as b` keeps
working and the `bebenqli:run` entry point resolves. The real code lives in the
submodules (proc / controls / format / ddc / cli / tui / app)."""
from . import idebug, proc  # noqa: F401  — re-exported for tests / dispatch patching
from .controls import (CONTROLS, W, HEADERS, NONSEL, HIDDEN, INTERACT, RENDER,  # noqa: F401
                       SCAN_CODES, NOISE, MAPPED, slug, _renderable, _cli_name)
from .format import bar, render_row, _fmt  # noqa: F401
from .ddc import Ddc, build_cmd, detect_bus, resolve_bus, MODEL  # noqa: F401
from .cli import cli, _read, _resolve, _cli_controls  # noqa: F401
from .term import set_window_title, restore_window_title  # noqa: F401
from .tui import UI, main  # noqa: F401
from .app import run, __version__  # noqa: F401
