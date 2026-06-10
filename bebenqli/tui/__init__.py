"""The interactive settings TUI, split into: state (the model), view
(rendering), worker (the ddc write threads), and loop (the controller +
event loop). This facade re-exports what the rest of the package uses."""
from .loop import UI, main  # noqa: F401
