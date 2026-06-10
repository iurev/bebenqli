"""Terminal / tmux window-title management. Kept apart from the settings screen
because it's about the *terminal*, not the UI: it names the window while
bebenqli runs and hands the name back on exit."""
import os
import sys

from . import proc


def set_window_title(name="bebenqli"):
    # tmux re-derives a window's name from its running process (so a long-lived
    # python3 just shows "python3"), and the \ek escape no longer disables that
    # on modern tmux. Renaming via the command DOES turn automatic-rename off
    # for the window, so it sticks. OSC 2 covers plain terminals.
    if os.environ.get("TMUX"):
        proc.run_proc(["tmux", "rename-window", name])
    sys.stdout.write(f"\033]2;{name}\007")
    sys.stdout.flush()


def restore_window_title():
    # Hand the window name back to tmux so it tracks the shell again on exit.
    if os.environ.get("TMUX"):
        proc.run_proc(["tmux", "set-window-option", "automatic-rename", "on"])
