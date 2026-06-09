import bebenqli as b


# ── usage / help / unknowns ─────────────────────────────────────────────────
def test_no_args_returns_usage(ddc, capsys):
    assert b.cli(ddc, []) == 2
    assert "usage: bebenqli" in capsys.readouterr().out


def test_help_flag_returns_usage(ddc, capsys):
    assert b.cli(ddc, ["--help"]) == 2
    assert "usage: bebenqli" in capsys.readouterr().out


def test_unknown_command(ddc, capsys):
    assert b.cli(ddc, ["frob"]) == 2
    assert "unknown command: frob" in capsys.readouterr().err


# ── list ────────────────────────────────────────────────────────────────────
def test_list_shows_controls(mon, ddc, capsys):
    mon.values["62"] = 20
    assert b.cli(ddc, ["list"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    vol_line = next(l for l in lines if l.startswith("volume"))
    assert "20" in vol_line           # current value actually read back
    assert "[0..50]" in vol_line      # range annotation
    sw_line = next(l for l in lines if l.startswith("mh-switch"))
    assert "{ON|OFF}" in sw_line      # cycle annotation on the right control
    assert "(write-only)" in sw_line  # noread control shown as write-only


# ── get ─────────────────────────────────────────────────────────────────────
def test_get_readable(mon, ddc, capsys):
    mon.values["62"] = 23
    assert b.cli(ddc, ["get", "volume"]) == 0
    assert capsys.readouterr().out.strip() == "23"


def test_get_write_only(ddc, capsys):
    assert b.cli(ddc, ["get", "mh-switch"]) == 0
    assert "write-only" in capsys.readouterr().out


def test_get_unknown_control(ddc, capsys):
    assert b.cli(ddc, ["get", "nope"]) == 2
    assert "unknown control: nope" in capsys.readouterr().err


def test_get_wrong_arity(ddc, capsys):
    assert b.cli(ddc, ["get"]) == 2
    assert "unknown control" in capsys.readouterr().err


# ── set: success / verify ───────────────────────────────────────────────────
def test_set_verified(mon, ddc, capsys):
    assert b.cli(ddc, ["set", "volume", "30"]) == 0
    out = capsys.readouterr().out
    assert "volume = 30" in out and "(verified)" in out
    assert mon.values["62"] == 30


def test_set_cycle_by_name_verified(mon, ddc, capsys):
    assert b.cli(ddc, ["set", "color-mode", "cinema"]) == 0
    out = capsys.readouterr().out
    assert "color-mode = Cinema" in out and "(verified)" in out
    assert mon.values["dc"] == 0x32


def test_set_cycle_by_hex_value_verified(mon, ddc, capsys):
    # cycle accepts a raw/hex option value, not just the option name
    assert b.cli(ddc, ["set", "color-mode", "0x32"]) == 0
    out = capsys.readouterr().out
    assert "color-mode = Cinema" in out and "(verified)" in out
    assert mon.values["dc"] == 0x32


def test_set_chan_muxed_brightness_verified(mon, ddc, capsys):
    # MH Brightness is d9 channel 0x01: command must carry the muxed 16-bit
    # value, but read-back (low byte) still verifies against the target.
    assert b.cli(ddc, ["set", "mh-brightness", "5"]) == 0
    out = capsys.readouterr().out
    assert "mh-brightness = 5" in out and "(verified)" in out
    sent = mon.cmds("setvcp", "d9")[0]
    assert "--noverify" in sent
    assert sent[-1] == str((0x01 << 8) | 5)   # 261 over the wire


def test_set_write_only_unverified(ddc, capsys):
    assert b.cli(ddc, ["set", "mh-switch", "ON"]) == 0
    assert "(write-only, unverified)" in capsys.readouterr().out


# ── set: failures ───────────────────────────────────────────────────────────
def test_set_ddcutil_rejects(mon, ddc, capsys):
    mon.set_fail.add("62")
    assert b.cli(ddc, ["set", "volume", "30"]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_set_mismatch(mon, ddc, capsys):
    mon.unreadable.add("62")            # write lands but read-back yields nothing
    assert b.cli(ddc, ["set", "volume", "30"]) == 1
    assert "MISMATCH" in capsys.readouterr().err


def test_set_bad_value(ddc, capsys):
    assert b.cli(ddc, ["set", "color-mode", "bogus"]) == 1
    assert "bad value" in capsys.readouterr().err


def test_set_unknown_control(ddc, capsys):
    assert b.cli(ddc, ["set", "nope", "1"]) == 2
    assert "unknown control" in capsys.readouterr().err


# ── lazyset ─────────────────────────────────────────────────────────────────
def test_lazyset_writes_no_verify(mon, ddc, capsys):
    assert b.cli(ddc, ["lazyset", "volume", "25"]) == 0
    assert capsys.readouterr().out.strip() == "volume = 25"
    assert mon.values["62"] == 25


def test_lazyset_ignores_write_failure(mon, ddc, capsys):
    mon.set_fail.add("62")              # ddcutil errors, lazyset still exits 0
    assert b.cli(ddc, ["lazyset", "volume", "25"]) == 0
    assert "volume = 25" in capsys.readouterr().out


def test_lazyset_write_only_control(mon, ddc, capsys):
    # write-only d7 (MH switch): lazyset writes with --noverify, exits 0
    assert b.cli(ddc, ["lazyset", "mh-switch", "OFF"]) == 0
    assert "mh-switch = OFF" in capsys.readouterr().out
    sent = mon.cmds("setvcp", "d7")[0]
    assert "--noverify" in sent and sent[-1] == "16"   # 0x10 = OFF


# ── verbose flag ────────────────────────────────────────────────────────────
def test_verbose_flag_sets_ddc_verbose_and_strips(mon, ddc, capsys):
    mon.values["62"] = 5
    assert b.cli(ddc, ["-v", "get", "volume"]) == 0
    assert ddc.verbose is True
    assert capsys.readouterr().out.strip() == "5"


def test_verbose_flag_echoes_set_command(ddc, capsys):
    assert b.cli(ddc, ["--verbose", "set", "volume", "30"]) == 0
    err = capsys.readouterr().err
    assert "$ ddcutil" in err and "setvcp 62 30" in err
