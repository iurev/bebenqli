"""The monitor's spec: the control table, layout constants, and the discovery
candidate codes. Pure data + pure helpers — no I/O, no shared state. Everything
else in the package reads from here."""
import re


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


CONTROLS = [
    # ── Input ──────────────────────────────────────────────────────────────
    {"type": "group", "label": "Input"},
    {"label": "Source",         "vcp": "60", "type": "cycle",
     "opts": [0x0f, 0x11, 0x13], "names": ["DP", "HDMI", "USB-C"]},

    # ── Audio ──────────────────────────────────────────────────────────────
    {"type": "group", "label": "Audio"},
    {"label": "Volume",         "vcp": "62", "type": "range", "min": 0, "max": 50, "confirmed": True},
    {"label": "Mute",           "type": "dead"},  # 8d flaky on fw 0.25 — use Volume=0

    # ── Coding Booster ─────────────────────────────────────────────────────
    {"type": "group",   "label": "Coding Booster"},
    {"type": "section", "label": "Moon Halo"},
    # d9 is a 16-bit multiplexed register: write (chan<<8)|value. Only
    # brightness (0x01) and color temp (0x07) actually respond on this
    # firmware. Color temp can't be read back (d9 read only returns the
    # brightness channel), so noread=True keeps a local value.
    {"label": "MH Brightness",  "vcp": "d9", "chan": 0x01, "type": "range",
     "min": 1, "max": 10, "confirmed": True},
    {"label": "MH Color Temp",  "vcp": "d9", "chan": 0x07, "type": "range",
     "min": 1, "max": 10, "noread": True, "confirmed": True},
    {"label": "MH Switch",      "vcp": "d7", "type": "cycle",
     "opts": [0x20, 0x10], "names": ["ON", "OFF"],
     "noread": True, "noverify": True, "confirmed": True},
    {"label": "MH Light Mode",  "type": "dead"},
    {"label": "MH Non-Step",    "type": "dead"},
    {"type": "section", "label": "Other"},
    {"label": "KVM Switch",     "type": "missing"},
    {"label": "Power Key LED",  "type": "missing"},
    {"label": "LED Indicator",  "type": "missing"},
    {"label": "MST",            "type": "missing"},

    # ── Eye Care ───────────────────────────────────────────────────────────
    {"type": "group",   "label": "Eye Care"},
    {"type": "section", "label": "Night Protection"},
    {"label": "Night Mode",     "vcp": "d1", "type": "cycle",
     "opts": [0, 1, 2], "names": ["OFF", "ON", "AUTO"], "confirmed": True},
    {"label": "Night Level",    "vcp": "d0", "type": "range", "min": 1, "max": 10, "confirmed": True},
    {"type": "section", "label": "Other"},
    {"label": "Low Blue Light", "vcp": "19", "type": "range", "min": 0, "max": 5, "confirmed": True},
    {"label": "Color Weakness", "type": "missing"},  # fd — not yet verified
    # {"label": "Color Weakness", "vcp": "fd", "type": "cycle",
    #  "opts": [0, 3, 4], "names": ["OFF", "Green", "Red"]},
    {"label": "Eye Reminder",   "type": "missing"},
    {"type": "section", "label": "BI Gen2"},
    {"label": "BI Switch",      "vcp": "e2", "type": "cycle",
     "opts": [0, 255], "names": ["OFF", "ON"]},
    {"label": "BI Sensitivity", "vcp": "e5", "type": "range", "min": 1, "max": 10},

    # ── Image ──────────────────────────────────────────────────────────────
    {"type": "group", "label": "Image"},
    {"label": "Color Mode",     "vcp": "dc", "type": "cycle",
     "opts":  [0x30, 0x31, 0x0f, 0x32, 0x1f, 0x0a, 0x12],
     "names": ["Coding Dark", "Coding Light", "M-Book", "Cinema", "ePaper", "sRGB", "User"]},
    {"label": "Brightness",     "vcp": "10", "type": "range", "min": 0, "max": 100},
    {"label": "Contrast",       "vcp": "12", "type": "range", "min": 0, "max": 100},
]

W        = 44
HEADERS  = ("group", "section")               # layout rows
NONSEL   = ("group", "section", "dead", "missing")   # non-selectable rows
HIDDEN   = ("dead", "missing")                        # not rendered at all
INTERACT = [i for i, c in enumerate(CONTROLS) if c["type"] not in NONSEL]


def _header_has_child(start, stop_types, item):
    # True if any visible item follows `start` before the header's span ends
    # (the span ends at the next row whose type is in stop_types).
    for j in range(start + 1, len(CONTROLS)):
        if CONTROLS[j]["type"] in stop_types:
            return False
        if item[j]:
            return True
    return False


def _renderable():
    # Indices to draw: real items, plus headers that have ≥1 visible child.
    # A section spans until the next section/group; a group until the next group.
    n = len(CONTROLS)
    item = [CONTROLS[i]["type"] not in HIDDEN and CONTROLS[i]["type"] not in HEADERS
            for i in range(n)]
    keep = set(i for i in range(n) if item[i])
    for i, c in enumerate(CONTROLS):
        if c["type"] == "section" and _header_has_child(i, ("section", "group"), item):
            keep.add(i)
        elif c["type"] == "group" and _header_has_child(i, ("group",), item):
            keep.add(i)
    return keep

RENDER = _renderable()

# Discovery candidate codes: everything capabilities reports, plus the whole
# 0xd0..0xff custom range (BenQ hides extra features there that may not appear
# in capabilities). Codes already mapped in CONTROLS are excluded — their
# meaning is known, so we don't poll them during discovery. 04/08/0c =
# restore-defaults / save-settings, never touch. Dead codes get pruned at the
# baseline sweep.
_CAPS   = ("02 10 12 14 16 18 1a 52 60 62 72 86 87 8a 8d c1 c2 c9 ca cc d0 d1 "
           "d2 d7 d9 dc df e1 e2 e3 e5 e6 e7 e9 eb ee ef f0 f1 f8 fd").split()
_SKIP   = {"04", "08", "0c"}
# Auto-movers that change on their own (ambient/light sensor, active-control
# counters). They polluted every discovery file with random trails, so they're
# excluded from scans. e1=active-control counter, d7=BI/ambient composite,
# e3=BI light meter.
NOISE   = {"e1", "d7", "e3"}
MAPPED  = {c["vcp"].lower() for c in CONTROLS if "vcp" in c}
SCAN_CODES = [c for c in dict.fromkeys(_CAPS + [f"{c:02x}" for c in range(0xd0, 0x100)])
              if c not in _SKIP and c not in MAPPED and c not in NOISE]


# NOTE: two slugifiers on purpose — slug() uses "_" for YAML filenames,
# _cli_name() uses "-" for CLI control names. Do not merge them.
def _cli_name(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
