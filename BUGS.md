# Known issues / smells

Surfaced while writing the test suite. Tests currently **pin existing
behavior** (bugs included) so the suite is a safe net for the planned
architecture refactor. Fix these *after* the net is green, updating the
relevant test in the same commit.

## Low severity

- **Dead branch: `_read()` write-only path.** `_read()` returns `None` for
  `noread` controls, but every caller (`cli list`, `cli get`) special-cases
  `noread` *before* calling `_read`, so that path is never reached in normal
  flow. Covered only by a direct unit test. Either route the callers through
  `_read` or drop the dead branch.

- **`VERBOSE` is process-global, never reset.** `cli()` sets the module global
  `VERBOSE = True` and leaves it. Fine for a one-shot CLI process, but it makes
  the function stateful and forces tests to reset it. Candidate for the
  refactor: thread verbosity (and `bus`/`CMD`) through an explicit context
  object instead of module globals.

- **`bar()` divides by `(hi - lo)` unguarded.** A range control with
  `min == max` would raise `ZeroDivisionError`. No current control hits this
  (all have `min < max`), so it's latent; add a guard when touching `bar`.

- **`getvcp` parsing is positional-fragile.** Five regex fallbacks tried in
  order; a line containing both `current value =` and a trailing `(0x..)`
  silently prefers the former. Intended, but undocumented and easy to break.

## Architecture notes (for the refactor, not bugs)

- Module-level mutable globals `BUS` / `CMD` / `VERBOSE` couple every function
  to import-time state. Encapsulate in a small `Ddc`/context object; inject it
  into `cli()` and the UI.
- `setvcp` / `getvcp` reach for the global `CMD`; pass the bus/command builder
  in instead so they're pure given inputs.
