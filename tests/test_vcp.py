import types

import pytest

import bebenqli as b


def _stub_stdout(monkeypatch, out):
    monkeypatch.setattr(b, "run_proc",
                        lambda cmd, text=False: types.SimpleNamespace(
                            stdout=out, returncode=0, stderr=""))


# ── build_cmd ───────────────────────────────────────────────────────────────
def test_build_cmd():
    assert b.build_cmd("7") == ["ddcutil", "--bus", "7", "--permit-unknown-feature"]


# ── getvcp parse branches ───────────────────────────────────────────────────
@pytest.mark.parametrize("stdout,expected", [
    ("VCP 10: current value = 42, max value = 100", 42),
    ("VCP 60: sl=0x11 (HDMI)", 0x11),
    ("Audio: Volume level: 23", 23),
    ("Fixed (default) level (0x00)", 0),     # trailing-hex fallback, zero
    ("Something (0x1f)", 0x1f),              # trailing-hex fallback
    ("no parseable token here", None),       # nothing matches -> None
])
def test_getvcp_parses(monkeypatch, wired, stdout, expected):
    _stub_stdout(monkeypatch, stdout)
    assert b.getvcp("10") == expected


def test_getvcp_priority_current_value_wins(monkeypatch, wired):
    # both "current value" and a trailing hex present; current value takes priority
    _stub_stdout(monkeypatch, "current value = 7 ... (0x1f)")
    assert b.getvcp("10") == 7


# ── setvcp behaviour ────────────────────────────────────────────────────────
def test_setvcp_plain_write(wired):
    assert b.setvcp("10", 30) is True
    assert wired.values["10"] == 30
    call = wired.cmds("setvcp", "10")[0]
    assert call[-1] == "30"
    assert "--noverify" not in call


def test_setvcp_chan_muxes_and_noverifies(wired):
    # d9 brightness channel 0x01, value 5 -> command carries (1<<8)|5 = 261,
    # with --noverify; hardware then reads back only the low byte (5).
    assert b.setvcp("d9", 5, chan=0x01) is True
    call = wired.cmds("setvcp", "d9")[0]
    assert "--noverify" in call
    assert call[-1] == str((0x01 << 8) | 5)   # 261 sent to ddcutil
    assert wired.values["d9"] == 5            # panel reports low byte only


def test_setvcp_noverify_flag_without_chan(wired):
    b.setvcp("d7", 0x20, noverify=True)
    call = wired.cmds("setvcp", "d7")[0]
    assert "--noverify" in call
    assert call[-1] == "32"


def test_setvcp_returns_false_on_ddcutil_error(wired):
    wired.set_fail.add("10")
    assert b.setvcp("10", 30) is False


def test_setvcp_verbose_echoes_command(wired, capsys):
    b.VERBOSE = True
    b.setvcp("10", 30)
    err = capsys.readouterr().err
    assert err.startswith("$ ddcutil")
    assert "setvcp 10 30" in err


def test_getvcp_verbose_echoes_command(wired, capsys):
    wired.values["10"] = 5
    b.VERBOSE = True
    b.getvcp("10")
    err = capsys.readouterr().err
    assert "$ ddcutil" in err
    assert "getvcp 10" in err
