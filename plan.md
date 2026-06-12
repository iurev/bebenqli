# Plan: validate VCP values + machine-readable parsing

## Problem

Two coupled problems:

1. **Are the VCP values really valid?** Values were validated manually before, but
   not systematically. Need to double-check that `get` read-backs really match the
   numbers we `set`.
2. **Hidden cross-coupling.** One control may implicitly affect another (e.g. night
   mode changing brightness). We don't have a map of which code mutates which.

Root cause blocking both: the **read oracle is itself unreliable**. `getvcp` today
scrapes human-readable ddcutil text with a 4-regex fallback ladder
(`current value=`, `sl=0x..`, `Volume level:`, trailing `(0x..)`). Fragile and
order-dependent — the `sl=` and trailing-hex regexes can grab the *wrong* number.
You can't validate values against an untrustworthy read-back. Fix the oracle first.

---

## Phase 1 — make the oracle trustworthy (machine-readable parse)

ddcutil already emits machine output: `--terse` (`-t`). Deterministic tokens, no
prose scraping.

### Real terse output (captured live, RD280U bus 21, ddcutil 2.2.7)

```
VCP 10 C 1 100              C    -> "VCP <code> C <cur-dec> <max-dec>"
VCP DC SNC x30              SNC  -> "VCP <code> SNC x<sl>"            (1 hex byte)
VCP 60 SNC x13              SNC
VCP 62 CNC x00 x32 x00 x17  CNC  -> "VCP <code> CNC x<mh> x<ml> x<sh> x<sl>"  (4 bytes)
VCP D9 CNC x07 x0a x01 x05  CNC  (MoonHalo: sl=05 brightness; mh/ml=07 0a = color-temp chan!)
VCP C9 CNC xff xff x00 x19  CNC  (firmware: mh/ml = ff ff = no-max sentinel)
VCP AB ERR                  ERR  -> unsupported, rc=1
```

**Format facts (corrected from the original guess):**
- `C`: significant current = **2nd field** (decimal); max = 3rd field (decimal).
- `SNC`: 1 hex byte = the **SL** (low) byte. Significant value.
- `CNC`: **4** hex bytes `mh ml sh sl` (max-hi, max-lo, cur-hi, cur-lo). Significant
  current = **last token (sl)**; max = `ml` (2nd hex). *Not* 2 bytes as planned.
- Output **uppercases the code** (`dc` -> `DC`). Parser must key on the **type
  token**, never on the code's case.
- `ERR` token (rc=1) for unsupported / unreadable -> return `None`.
- For both `SNC` and `CNC` the wanted byte is the **last token** -> one code path.

### `_parse_terse(out)` — pure, total (never raises)

```python
def _parse_terse(out):
    for line in out.splitlines():
        if not line.startswith("VCP"):
            continue
        t = line.split()
        if len(t) < 4:                      # "VCP DC ERR" / malformed -> None
            return None
        typ = t[2]
        try:
            if typ == "C":
                return int(t[3])            # current; max = t[4] (ignored for now)
            if typ in ("SNC", "NC", "CNC"):
                return int(t[-1].lstrip("xX"), 16)   # SL byte, last token
        except (ValueError, IndexError):
            return None
        return None                         # ERR / T / unknown type
    return None                             # no VCP line
```

`getvcp` becomes a thin wrapper:

```python
def getvcp(self, code):
    cmd = self.cmd + ["--terse", "getvcp", code]
    if self.verbose:
        print("$ " + " ".join(cmd), file=sys.stderr)
    return _parse_terse(proc.run_proc(cmd, text=True).stdout)
```

Behavior is **value-compatible**: returns the same single int callers expect
(`cli._read`, `tui.state.seed`). d9 still yields its SL low byte (05) — matches the
existing FakeMonitor model and the "MH brightness only" contract.

Wins:
- **Pure + total -> unit-testable -> keeps 100% coverage**, no hardware. The fragile
  part stops being guesswork; the 4-regex ladder + its 6 parametrized cases are
  replaced by deterministic token parsing.
- Kills the "grabbed the wrong hex" false-readback class (old `sl=0x..` /
  trailing-`(0x..)` regexes could match a max or an unrelated byte).

### Corner cases handled / deferred

- **Total parser** — wrap int() in try/except so a garbled line can't crash the TUI
  poll loop; returns `None` like the old no-match path.
- **Multi-line / noise** — scan for the line starting `VCP`; ignore the rest
  (groups, `--ddcdata` chatter). Phase 1 only queries single codes.
- **Code case / hex prefix** — key on type token; `lstrip("xX")` the value.
- **max for free** (C 3rd field, CNC `ml`) — *not* surfaced in Phase 1 (would change
  the return type and break callers). Deferred to Phase 2 as a separate
  `read_raw()` returning `(cur, max)` for the range-vs-hardcoded cross-check.
- **`--sleep-multiplier`** — deferred to Phase 2 (sweep). It slows every call and is
  a reliability knob, not a parse fix; keep Phase 1 minimal.

### Test impact (must stay green at 100%)

- `tests/test_vcp.py` — rewrite `test_getvcp_parses` parametrize from verbose
  strings to terse ones: `VCP 10 C 42 100`->42, `VCP 60 SNC x11`->0x11,
  `VCP 62 CNC x00 x32 x00 x17`->0x17, `VCP DC ERR`->None, `garbage`->None,
  `VCP 10 C xx 100` (bad int)->None. Drop the now-obsolete `current value`/`sl=`/
  `Volume level:`/trailing-hex cases and `test_getvcp_priority_*`.
- Command assertion: `getvcp` cmd now contains `--terse`; verbose-echo test still
  matches `getvcp 10`.
- `tests/conftest.py` `FakeMonitor._ddcutil` — emit terse instead of verbose:
  readable -> `"VCP %s C %d 100" % (code, val)`; unreadable -> `"VCP %s ERR"`.
  (C-format round-trips every integer value the integration tests assert,
  regardless of the control's real NC/C type — the unit tests above cover the
  SNC/CNC branches directly.)
- `re` import stays in `ddc.py` (still used by `detect_bus`).

---

## Phase 1 — DONE

Shipped in v0.0.3: `Ddc.getvcp` parses `ddcutil --terse` via pure `_parse_terse`.
Trustworthy read oracle, 100% covered, verified live on the RD280U.

---

## Phase 2 — interactive probe console (`idebug`)

Replaces the originally-planned batch sweep, and **absorbs Phase 3** (coupling).
A non-batch, human-in-the-loop REPL is the only thing that gives a *real* oracle:
a software-only round-trip (`set`->`getvcp`) just proves "the register stores what
I wrote" — it can't prove the code maps to the labelled feature, nor that anything
visibly happened. The human + the monitor's own OSD break that circularity.

### Three oracle directions (why two-way)

- **A. software -> panel** — `set` then read-back. Weak: stores != controls.
- **B. panel -> software** — human turns the OSD, we watch *which code moves*.
  Proves code identity. (Same idea as the TUI's `!` discover, standalone.)
- **C. software -> eyes** — after a write, ask "did the panel visibly change?".
  Catches dead / mislabelled registers (write ACKs, read-back matches, nothing
  happens) — the highest-value finding, and only a human sees it.

Changing values **on the monitor's OSD** (not just in-app) is the high-value path:
it is the external ground truth and it surfaces coupling (turn night-mode on at the
panel, watch brightness drop on its own).

### Tech (decided)

- Shell: stdlib **`cmd.Cmd`** + `import readline` (free help/history/tab-complete;
  `onecmd("set 50")` is unit-testable). No new deps (keeps the "only dep = blessed"
  promise). Reject prompt_toolkit (weight) and blessed (this is deliberately *not*
  the TUI).
- `watch` sub-loop: plain `while: snapshot; sleep(0.3); print diffs`, stop on
  **Ctrl-C** (`KeyboardInterrupt` returns to the prompt). No threads, no lock —
  stays out of the TUI's concurrency model. (`select.select` on stdin to also stop
  on `q`+Enter is a later nicety.)

### Layout (mirrors the existing `tui/{state,loop}` split)

- `bebenqli/debug.py` -> **`class Prober`** = pure engine: `read(code)`,
  `set_verify(ctrl,val) -> Report`, `snapshot() -> {code:val}`, `diff(a,b)`,
  `resolve(ctrl,str)` (reuse `cli._resolve`), `record(entry)` (append YAML).
  **Unit-tested, no pragma.**
- `bebenqli/idebug.py` -> **`class Console(cmd.Cmd)`** = thin `do_*` delegates +
  `cmdloop` + `watch` poll + `input()` confirms. **`# pragma: no cover`.**
- `bebenqli/app.py` -> `idebug [control]` dispatch builds `Ddc` + `Console`.
- New `Ddc.read_raw(code) -> (cur, max)` surfacing the max byte terse already gives
  (C 3rd token, CNC `ml`); d9 shown chan-aware (mh/ml leak the color-temp channel).

### Command contracts (MVP v1)

| Type        | Does                                                         | Dir |
|-------------|--------------------------------------------------------------|-----|
| `50`/`set 50` | write + verify read-back; print Δ + "else-changed"          | A   |
| `w 50`      | write-only (noread codes / fire-and-forget)                  | A   |
| `r`         | read current (+ monitor-reported max)                        | A   |
| `watch`     | poll this code until you turn the OSD; print transitions     | B   |
| *(auto)* `visible change? [y/n/skip]` after each set         | eyes oracle | C |
| `d`/`diff`  | snapshot all codes, diff vs entry baseline -> what else moved | coupling |
| `use <ctrl>`| switch focused control (test coupling live)                  | —   |
| `note <txt>`| record a human observation into the YAML log                 | —   |
| `q`         | quit; offer to restore what *this tool* changed (not OSD)    | —   |

Bare-number `> 50` handled via `cmd.Cmd.default()`. Value parsing reuses
`cli._resolve` (dec/hex/option-name). Every action appends a YAML record:
`{ts, control, vcp, action, wrote, readback, max, verified, visible, else_changed,
note, ddcutil_ver, fw}` -> becomes the README ✓/~/? evidence + a future
`conflicts:` field on `CONTROLS`.

### Corner cases (human is the classifier — no brittle heuristics)

- **`returncode==0 != applied`** — read-back is truth; the `visible?` prompt is the
  backstop for semantic no-ops.
- **Settle latency** — small delay before read-back (e.g. 150ms); `watch` re-reads.
- **Snap / clamp** — show `Δ-2 (snap?)`, let the human judge (don't auto-FAIL).
- **Self-drift** (auto-bright `e2`, sensor `e5`) — `watch`/`diff` will show motion
  with no write; flag known-auto codes as noise.
- **Write-only** (`d7`, d9 color-temp) — `watch`/read can't verify; rely on `w` +
  `visible? y/n`. Two-way is the *only* check here.
- **d9 mux** — `r`/`set`/`watch` print all four bytes (chan-aware).
- **OSD blocks DDC** — some panels garble reads while the menu is open; reads return
  None (handled) — nudge value / close menu if reads stall.

### Coverage testability without hardware

Engine is pure -> unit-test with `FakeMonitor`. Extend the fake with **coupling
rules** (e.g. "setvcp dc resets 10 to a default") so `diff` has an edge to find and
`set_verify`'s else-changed path is covered. Console I/O loop is pragma'd (like the
TUI); `onecmd()` smoke-drives dispatch.

### Out of scope (later v2)

`sweep` (snap-grid curve), `watch all` (discovery), `snap` (re-baseline),
`confirm on/off`, `log` tail, `select`-based `q`-stop, both-order coupling runs,
README status auto-regeneration.

---

## Manual-only truths

No code can verify these — needs eyes on the panel: d7/d9 write-only channels, and
whether a mode *locks* a control (write ACKs but is ignored).
