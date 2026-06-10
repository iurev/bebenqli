import pytest

import bebenqli as b


# ── slug / _cli_name ────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("MH Brightness", "mh_brightness"),
    ("  Hello World!  ", "hello_world"),
    ("a---b__c", "a_b_c"),
    ("ALLCAPS", "allcaps"),
])
def test_slug(raw, expected):
    assert b.slug(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Color Mode", "color-mode"),
    ("MH Color Temp", "mh-color-temp"),
    ("Low Blue Light", "low-blue-light"),
])
def test_cli_name(raw, expected):
    assert b._cli_name(raw) == expected


# ── bar ─────────────────────────────────────────────────────────────────────
def test_bar_full_and_empty():
    assert b.bar(10, 0, 10) == "█" * 12
    assert b.bar(0, 0, 10) == "░" * 12


def test_bar_midpoint_is_half_filled():
    # 5/10 over width 12 -> 6 filled, 6 empty
    assert b.bar(5, 0, 10) == "█" * 6 + "░" * 6


def test_bar_proportional_fill():
    # 25/50 over default width 12 -> half filled
    assert b.bar(25, 0, 50) == "█" * 6 + "░" * 6


# ── _resolve (cycle) ────────────────────────────────────────────────────────
CYCLE = {"type": "cycle", "opts": [0x30, 0x31, 0x0f], "names": ["Dark", "Light", "M-Book"]}


def test_resolve_cycle_by_name_case_insensitive():
    assert b._resolve(CYCLE, "light") == 0x31


def test_resolve_cycle_by_raw_hex_value():
    assert b._resolve(CYCLE, "0x0f") == 0x0f


def test_resolve_cycle_bad_value_raises():
    with pytest.raises(ValueError) as e:
        b._resolve(CYCLE, "nope")
    assert "Dark|Light|M-Book" in str(e.value)


# ── _resolve (range) ────────────────────────────────────────────────────────
RANGE = {"type": "range", "min": 0, "max": 50}


@pytest.mark.parametrize("text,expected", [
    ("30", 30),
    ("0x10", 16),
    ("-5", 0),     # clamp low
    ("999", 50),   # clamp high
])
def test_resolve_range(text, expected):
    assert b._resolve(RANGE, text) == expected


def test_resolve_range_non_integer_raises():
    with pytest.raises(ValueError) as e:
        b._resolve(RANGE, "abc")
    assert "0..50" in str(e.value)


# ── _fmt ────────────────────────────────────────────────────────────────────
def test_fmt_none():
    assert b._fmt(RANGE, None) == "?"


def test_fmt_range_value():
    assert b._fmt(RANGE, 25) == "25"


def test_fmt_cycle_known():
    assert b._fmt(CYCLE, 0x31) == "Light"


def test_fmt_cycle_unknown_shows_hex():
    assert b._fmt(CYCLE, 0x99) == "?(0x99)"
