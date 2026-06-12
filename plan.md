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

```
$ ddcutil --terse getvcp 10   ->  VCP 10 C 80 100      # continuous: cur max
$ ddcutil --terse getvcp 60   ->  VCP 60 SNC x0f       # simple non-cont: sl byte
$ ddcutil --terse getvcp dc   ->  VCP DC CNC x00 x32   # complex non-cont: sh sl
```

Replace the regex ladder with one pure `_parse_terse(code, out)` keyed on the type
letter (`C` / `SNC` / `CNC` / `T`):

- `C`   -> `(current, max)` — return current, **and get max for free** (corner case 14).
- `SNC` -> low byte.
- `CNC` -> `(sh, sl)` — return sl (matches today's `sl=` behavior).
- `T`   -> table hex bytes.

Wins:

- **Pure function -> unit-testable -> keeps 100% coverage** with no hardware. The
  fragile part stops being `# pragma`'d guesswork.
- Kills the "grabbed the wrong hex" class of false read-backs.
- Add `--sleep-multiplier 2`: slows DDC I/O so slow/flaky reads stop returning
  garbage (real fix for the `~` mute and transient errors). Also
  `getvcp ALL --terse` snapshots every readable code in one shot — needed for
  Phase 3.

**Caveat:** terse does NOT fix d9 MoonHalo. Read-back still only returns the
brightness-channel low byte. Color-temp / on-off channels stay genuinely
write-only — no parse trick changes that.

New shape:

```python
def getvcp(self, code):
    r = proc.run_proc(self.cmd + ["--terse", "getvcp", code], text=True)
    return _parse_terse(code, r.stdout)   # pure, fully unit-tested
```

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
