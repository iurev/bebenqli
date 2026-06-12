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

## Phase 2 — round-trip sweep (does set actually take?)

Per readable+settable control: read original -> for each candidate (cycle: every
opt; range: min/max/few mids) set -> settle -> read back -> compare -> restore.
Emit YAML report. Home = `debug.py` `Prober` (already writes `/tmp/benq/*.yaml`) or
a `scripts/sweep_hw.py` gated out of CI.

**`returncode==0 != applied.`** ddcutil reports success on the i2c ACK, not semantic
acceptance. Read-back is the only truth. Corner cases that produce a "mismatch"
which is NOT a bug:

1. **Settle latency** — read too fast -> old value. Delay 100–500ms or read-until-stable.
2. **Quantization / snap** — set 37, monitor snaps to step grid -> reads 35. Detect grid, allow tolerance.
3. **Clamp** — set > max -> clamps. Expected.
4. **Self-drift** — auto modes (BI Gen2 `e2=on`, ambient sensor `e5`) move brightness
   on their own. Read twice 2s apart with no write; if it moved -> sensor-driven,
   exclude from strict verify.
5. **Flaky** — N reads of same set disagree -> mark `~`, don't fail.
6. **DDC transient errors** — retry N, distinguish "DDC error" from "wrong value".
7. **min/max truth** — `C` max from terse vs hardcoded `CONTROLS` range
   (volume 0–50). Mismatch = doc bug, auto-flag.

Output regenerates the README status column (✓/~/?) **from real evidence**, not memory.

---

## Phase 3 — cross-coupling detection (the night-mode worry)

Likely edges on RD280U:

- **Color mode (`dc`) resets brightness/contrast/color-preset** to that mode's
  defaults. Set brightness=80, then color-mode=cinema -> brightness silently jumps.
  Stored 80 is now a lie.
- **Night / eye-care (`d1`/`d0`/`19`/`e7`) forces warm temp + lower brightness, may
  LOCK brightness** (writes ACK but ignored) while active.
- **BI Gen2 auto-bright (`e2=on`) overrides manual brightness continuously** —
  read-back drifts forever.
- **sRGB / ePaper modes lock color-preset.**
- **Input switch (`60`) resets a batch.**

Detection = **snapshot-diff**: `getvcp ALL --terse` -> change ONE control ->
`getvcp ALL --terse` -> diff. Any code that moved besides the one touched = a
coupling edge. Build the dependency graph. Test **both orders** (A->B vs B->A) for
suspected pairs — hysteresis is real. Add a sleep/wake + input-switch cycle to
catch non-persistent settings.

**Make the detector CI-testable without hardware:** snapshot/diff/graph logic is
pure. Extend `FakeMonitor` (already models d9 low-byte) with coupling rules — e.g.
"setvcp dc resets 10 to a default" — then unit-test that the detector reports that
edge. Hardware run stays manual; detection logic stays covered.

---

## Recommended order

1. **Phase 1 now** — terse parse + `_parse_terse` unit tests. Safe, pure, keeps
   100%, every later phase depends on a trustworthy read. Smallest blast radius.
2. Phase 2 sweep script (manual, gated out of CI).
3. Phase 3 coupling diff — run on real panel, turn findings into the README map +
   maybe a "conflicts with" field in `CONTROLS`.

Manual-only truths no code can verify: d7/d9 write-only channels, and whether a mode
*locks* a control (needs eyes on the panel).
