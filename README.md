# bebenqli

A terminal UI **and** CLI to control **BenQ RD280U** monitors over DDC/CI —
brightness, color mode, volume, the Moon Halo backlight, eye-care modes, and a
pile of undocumented BenQ-specific features, all without touching the on-screen
menu or BenQ's official app.

Built on [`ddcutil`](https://www.ddcutil.com/). Linux only. **v0.0.1** — expect
rough edges.

![bebenqli TUI](https://github.com/user-attachments/assets/74a4b32b-ff1a-4ccf-a0cb-66d1e9b2fc47)

---

## Why

BenQ ships no public DDC/CI documentation for this panel. The VCP codes here
were reverse-engineered by scraping the official Display Pilot 2 app's debug
log — including the fact that the entire **Moon Halo** backlight is multiplexed
into a single 16-bit register (`d9 = (channel << 8) | value`) instead of
separate codes, with on/off living on a *different* register (`d7`). The TUI
also has a built-in **listen / discover** mode (`!`) that watches VCP codes
while you change settings on the monitor, to map new ones.

## Requirements

- Linux with `i2c-dev` (`sudo modprobe i2c-dev`)
- [`ddcutil`](https://www.ddcutil.com/) installed and on `PATH`
- Your user in the `i2c` group: `sudo usermod -aG i2c $USER` (re-login after)
- Python ≥ 3.8 + [`blessed`](https://pypi.org/project/blessed/) (TUI only)
- A **BenQ RD280U** connected via DisplayPort / HDMI / USB-C

> Codes are specific to the RD280U. Other models will mostly *not* match.

## Install

**pipx** (recommended — isolated, gives you the `bebenqli` command):

```bash
pipx install git+https://github.com/iurev/bebenqli
```

**Raw script** (no packaging, just run it):

```bash
git clone https://github.com/iurev/bebenqli
cd bebenqli
pip install blessed          # only dependency
./bebenqli.py
```

`ddcutil` itself is a *system* package — install it from your distro
(`pacman -S ddcutil`, `apt install ddcutil`, …); it is not bundled.

## Usage

No arguments → launches the TUI. Any arguments → CLI mode.

### TUI

```bash
bebenqli
```

| Key        | Action                                            |
|------------|---------------------------------------------------|
| `↑` `↓`    | move between controls                             |
| `←` `→`    | change selected control                           |
| `0`–`9`    | range: type a value · cycle: jump to that option  |
| `/`        | fuzzy-find a control                              |
| `!`        | listen / discover mode (map unknown VCP codes)    |
| `q`        | quit                                              |

### CLI

```bash
bebenqli list                  # every control, current value, range/options
bebenqli get volume            # -> 20
bebenqli set volume 30         # write THEN verify (read-back compare)
bebenqli set color-mode cinema # cycle: option name (case-insensitive) or raw value
bebenqli lazyset volume 25     # write only, no verify (fire-and-forget)
```

- `set` checks `ddcutil`'s exit code, then reads the value back and compares —
  prints `(verified)`, `(write-only, unverified)`, or `MISMATCH…` (exit 1).
- Write-only controls (Moon Halo on/off, MH color temp) can't be read back.
- `lazyset` just writes and exits 0 — use when you don't care to confirm.

### Options

| Flag              | Meaning                                                       |
|-------------------|---------------------------------------------------------------|
| `--bus N`         | i2c bus override (default: auto-detect the RD280U)            |
| `-v` `--verbose`  | echo each underlying `ddcutil` command to stderr             |
| `-V` `--version`  | print version                                                 |
| `-h` `--help`     | usage                                                         |

The i2c **bus** is assigned by the kernel per GPU + port, so it differs on every
machine. `bebenqli` auto-detects it by matching the monitor model from
`ddcutil detect`. Override with `--bus N` or `$BEBENQLI_BUS`.

## VCP code map

Reverse-engineered from Display Pilot 2 logs. ✓ confirmed live · ~ flaky · ? guessed.

| VCP  | Feature            | Values / notes                                              | Status |
|------|--------------------|------------------------------------------------------------|--------|
| `60` | Input source       | 0f=DP, 11=HDMI, 13=USB-C                                    | ✓ |
| `10` | Brightness         | 0–100                                                      | ✓ |
| `12` | Contrast           | 0–100                                                      | ✓ |
| `87` | Sharpness          | 0–100                                                      | ✓ |
| `dc` | Color mode         | 30=Coding Dark, 31=Coding Light, 0f=M-Book, 32=Cinema, 1f=ePaper, 0a=sRGB, 12=User | ✓ |
| `14` | Color preset       | 04=5000K, 05=6500K, 08=9300K, 0b=User                     | ✓ |
| `62` | Volume             | 0–50 (0=silent; max is 50, **not** 100)                    | ✓ |
| `8d` | Mute               | flaky on fw 0.25 — use Volume=0 to silence instead         | ~ |
| `d9` | Moon Halo (mux)    | `(chan<<8)\|value`: chan 01=brightness 1–10, 07=color temp 1–10 | ✓ |
| `d7` | Moon Halo on/off   | 20=on, 10=off (write-only, needs `--noverify`)             | ✓ |
| `d1` | Night protection   | 0=off, 1=on, 2=auto                                        | ✓ |
| `d0` | Night level        | 1–10                                                      | ✓ |
| `19` | Low blue light     | 0–5                                                       | ✓ |
| `fd` | Color weakness     | 00=off, 03=green-weak, 04=red-weak                         | ? |
| `e2` | BI Gen2 auto-bright| 00=off, FF=on                                             | ✓ |
| `e5` | BI Gen2 sensitivity| 1–10                                                     | ✓ |
| `e7` | Eco privacy        | 00=off                                                    | ✓ |
| `cc` | OSD language       | 02=en, 03=fr, 04=de, …                                    | ✓ |
| `c9` | Firmware version   | read-only                                                 | ✓ |

**Moon Halo detail:** it is *not* separate VCP codes. Write
`d9 = (channel << 8) | value`; the high byte selects the sub-feature, the low
byte is its value. Reads only ever return the brightness channel's low byte, so
other sub-features are write-only. On/off is a separate register (`d7`).

## Limitations / scope

- **RD280U only**, **Linux only**, v0.0.1. No Windows/macOS, no other models.
- Several codes are write-only (can't be read back to verify state).
- Mute (`8d`) is unreliable on this firmware; use Volume=0.
- Minimally maintained — issues/PRs welcome but responses may be slow.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"     # blessed + pytest + pytest-cov
pytest                       # runs the suite under a 100% coverage gate
```

The monitor (and `tmux`) are faked behind a single `run_proc` seam, so the
whole suite runs with no hardware and no `ddcutil` installed. The TUI layer is
excluded from the coverage target (smoke-tested only); CLI and helpers are
covered 100%.

## License

[MIT](LICENSE) © Vitalii Iurev
