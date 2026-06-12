import types

import pytest

import bebenqli as b


def _stub_stdout(monkeypatch, out):
    monkeypatch.setattr(b.proc, "run_proc",
                        lambda cmd, text=False: types.SimpleNamespace(
                            stdout=out, returncode=0, stderr=""))


# ── build_cmd ───────────────────────────────────────────────────────────────
def test_build_cmd():
    assert b.build_cmd("7") == ["ddcutil", "--bus", "7", "--permit-unknown-feature"]


# ── getvcp --terse parse branches ───────────────────────────────────────────
@pytest.mark.parametrize("stdout,expected", [
    ("VCP 10 C 42 100", 42),                      # continuous -> current decimal
    ("VCP 10 C 0 100", 0),                         # continuous zero
    ("VCP 60 SNC x11", 0x11),                      # simple NC -> SL byte (hex)
    ("VCP DC SNC x30", 0x30),                       # output uppercases the code
    ("VCP 62 CNC x00 x32 x00 x17", 0x17),           # complex NC -> last token (SL)
    ("VCP D9 CNC x07 x0a x01 x05", 0x05),           # MoonHalo: SL=05, mh/ml ignored
    ("VCP AB ERR", None),                           # unsupported -> None
    ("VCP DC", None),                               # truncated line -> None
    ("VCP 10 C xx 100", None),                       # un-parseable decimal -> None
    ("VCP 60 SNC xZZ", None),                         # un-parseable hex -> None
    ("VCP 10 T 0102", None),                         # table type unsupported -> None
    ("garbage no vcp line", None),                   # no VCP line -> None
    ("", None),                                      # empty output -> None
])
def test_getvcp_parses(monkeypatch, ddc, stdout, expected):
    _stub_stdout(monkeypatch, stdout)
    assert ddc.getvcp("10") == expected


def test_getvcp_skips_noise_lines_before_vcp(monkeypatch, ddc):
    # real ddcutil may emit chatter before the VCP line; parser scans to it.
    _stub_stdout(monkeypatch, "some warning\nVCP 62 CNC x00 x32 x00 x17\n")
    assert ddc.getvcp("62") == 0x17


# ── read_raw (cur, max) ──────────────────────────────────────────────────────
@pytest.mark.parametrize("stdout,expected", [
    ("VCP 10 C 42 100", (42, 100)),                 # continuous -> (cur, max)
    ("VCP 60 SNC x11", (0x11, None)),               # simple NC -> no max
    ("VCP 60 NC x11", (0x11, None)),                 # NC alias -> single byte, no max
    ("VCP 62 CNC x00 x32 x00 x17", (0x17, 0x32)),   # complex NC -> (SL, ML=max)
    ("VCP AB ERR", (None, None)),                    # unsupported
    ("VCP 10 C xx 100", (None, None)),               # bad decimal
    ("VCP 62 CNC x00 xzz x00 x17", (None, None)),    # bad max hex
    ("VCP 10 T 0102", (None, None)),                  # table unsupported
    ("nothing here", (None, None)),                   # no VCP line
])
def test_read_raw_parses(monkeypatch, ddc, stdout, expected):
    _stub_stdout(monkeypatch, stdout)
    assert ddc.read_raw("10") == expected


def test_read_raw_uses_terse_flag(monkeypatch, ddc):
    seen = {}

    def fake(cmd, text=False):
        seen["cmd"] = cmd
        return types.SimpleNamespace(stdout="VCP 10 C 5 100", returncode=0, stderr="")

    monkeypatch.setattr(b.proc, "run_proc", fake)
    assert ddc.read_raw("10") == (5, 100)
    assert "--terse" in seen["cmd"]


def test_read_raw_verbose_echoes(mon, ddc, capsys):
    mon.values["10"] = 5
    ddc.verbose = True
    ddc.read_raw("10")
    assert "getvcp 10" in capsys.readouterr().err


def test_getvcp_uses_terse_flag(monkeypatch, ddc):
    seen = {}

    def fake(cmd, text=False):
        seen["cmd"] = cmd
        return types.SimpleNamespace(stdout="VCP 10 C 5 100", returncode=0, stderr="")

    monkeypatch.setattr(b.proc, "run_proc", fake)
    assert ddc.getvcp("10") == 5
    assert "--terse" in seen["cmd"]


# ── setvcp behaviour ────────────────────────────────────────────────────────
def test_setvcp_plain_write(mon, ddc):
    assert ddc.setvcp("10", 30) is True
    assert mon.values["10"] == 30
    call = mon.cmds("setvcp", "10")[0]
    assert call[-1] == "30"
    assert "--noverify" not in call


def test_setvcp_chan_muxes_and_noverifies(mon, ddc):
    # d9 brightness channel 0x01, value 5 -> command carries (1<<8)|5 = 261,
    # with --noverify; hardware then reads back only the low byte (5).
    assert ddc.setvcp("d9", 5, chan=0x01) is True
    call = mon.cmds("setvcp", "d9")[0]
    assert "--noverify" in call
    assert call[-1] == str((0x01 << 8) | 5)   # 261 sent to ddcutil
    assert mon.values["d9"] == 5              # panel reports low byte only


def test_setvcp_noverify_flag_without_chan(mon, ddc):
    ddc.setvcp("d7", 0x20, noverify=True)
    call = mon.cmds("setvcp", "d7")[0]
    assert "--noverify" in call
    assert call[-1] == "32"


def test_setvcp_returns_false_on_ddcutil_error(mon, ddc):
    mon.set_fail.add("10")
    assert ddc.setvcp("10", 30) is False


def test_setvcp_verbose_echoes_command(ddc, capsys):
    ddc.verbose = True
    ddc.setvcp("10", 30)
    err = capsys.readouterr().err
    assert err.startswith("$ ddcutil")
    assert "setvcp 10 30" in err


def test_getvcp_verbose_echoes_command(mon, ddc, capsys):
    mon.values["10"] = 5
    ddc.verbose = True
    ddc.getvcp("10")
    err = capsys.readouterr().err
    assert "$ ddcutil" in err
    assert "getvcp 10" in err
