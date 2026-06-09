import bebenqli as b


# ── usage / help / unknowns ─────────────────────────────────────────────────
def test_no_args_returns_usage(wired, capsys):
    assert b.cli([]) == 2
    assert "usage: bebenqli" in capsys.readouterr().out


def test_help_flag_returns_usage(wired, capsys):
    assert b.cli(["--help"]) == 2
    assert "usage: bebenqli" in capsys.readouterr().out


def test_unknown_command(wired, capsys):
    assert b.cli(["frob"]) == 2
    assert "unknown command: frob" in capsys.readouterr().err


# ── list ────────────────────────────────────────────────────────────────────
def test_list_shows_controls(wired, capsys):
    wired.values["62"] = 20
    assert b.cli(["list"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    vol_line = next(l for l in lines if l.startswith("volume"))
    assert "20" in vol_line           # current value actually read back
    assert "[0..50]" in vol_line      # range annotation
    sw_line = next(l for l in lines if l.startswith("mh-switch"))
    assert "{ON|OFF}" in sw_line      # cycle annotation on the right control
    assert "(write-only)" in sw_line  # noread control shown as write-only


# ── get ─────────────────────────────────────────────────────────────────────
def test_get_readable(wired, capsys):
    wired.values["62"] = 23
    assert b.cli(["get", "volume"]) == 0
    assert capsys.readouterr().out.strip() == "23"


def test_get_write_only(wired, capsys):
    assert b.cli(["get", "mh-switch"]) == 0
    assert "write-only" in capsys.readouterr().out


def test_get_unknown_control(wired, capsys):
    assert b.cli(["get", "nope"]) == 2
    assert "unknown control: nope" in capsys.readouterr().err


def test_get_wrong_arity(wired, capsys):
    assert b.cli(["get"]) == 2
    assert "unknown control" in capsys.readouterr().err


# ── set: success / verify ───────────────────────────────────────────────────
def test_set_verified(wired, capsys):
    assert b.cli(["set", "volume", "30"]) == 0
    out = capsys.readouterr().out
    assert "volume = 30" in out and "(verified)" in out
    assert wired.values["62"] == 30


def test_set_cycle_by_name_verified(wired, capsys):
    assert b.cli(["set", "color-mode", "cinema"]) == 0
    out = capsys.readouterr().out
    assert "color-mode = Cinema" in out and "(verified)" in out
    assert wired.values["dc"] == 0x32


def test_set_cycle_by_hex_value_verified(wired, capsys):
    # cycle accepts a raw/hex option value, not just the option name
    assert b.cli(["set", "color-mode", "0x32"]) == 0
    out = capsys.readouterr().out
    assert "color-mode = Cinema" in out and "(verified)" in out
    assert wired.values["dc"] == 0x32


def test_set_chan_muxed_brightness_verified(wired, capsys):
    # MH Brightness is d9 channel 0x01: command must carry the muxed 16-bit
    # value, but read-back (low byte) still verifies against the target.
    assert b.cli(["set", "mh-brightness", "5"]) == 0
    out = capsys.readouterr().out
    assert "mh-brightness = 5" in out and "(verified)" in out
    sent = wired.cmds("setvcp", "d9")[0]
    assert "--noverify" in sent
    assert sent[-1] == str((0x01 << 8) | 5)   # 261 over the wire


def test_set_write_only_unverified(wired, capsys):
    assert b.cli(["set", "mh-switch", "ON"]) == 0
    assert "(write-only, unverified)" in capsys.readouterr().out


# ── set: failures ───────────────────────────────────────────────────────────
def test_set_ddcutil_rejects(wired, capsys):
    wired.set_fail.add("62")
    assert b.cli(["set", "volume", "30"]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_set_mismatch(wired, capsys):
    wired.unreadable.add("62")          # write lands but read-back yields nothing
    assert b.cli(["set", "volume", "30"]) == 1
    assert "MISMATCH" in capsys.readouterr().err


def test_set_bad_value(wired, capsys):
    assert b.cli(["set", "color-mode", "bogus"]) == 1
    assert "bad value" in capsys.readouterr().err


def test_set_unknown_control(wired, capsys):
    assert b.cli(["set", "nope", "1"]) == 2
    assert "unknown control" in capsys.readouterr().err


# ── lazyset ─────────────────────────────────────────────────────────────────
def test_lazyset_writes_no_verify(wired, capsys):
    assert b.cli(["lazyset", "volume", "25"]) == 0
    assert capsys.readouterr().out.strip() == "volume = 25"
    assert wired.values["62"] == 25


def test_lazyset_ignores_write_failure(wired, capsys):
    wired.set_fail.add("62")            # ddcutil errors, lazyset still exits 0
    assert b.cli(["lazyset", "volume", "25"]) == 0
    assert "volume = 25" in capsys.readouterr().out


def test_lazyset_write_only_control(wired, capsys):
    # write-only d7 (MH switch): lazyset writes with --noverify, exits 0
    assert b.cli(["lazyset", "mh-switch", "OFF"]) == 0
    assert "mh-switch = OFF" in capsys.readouterr().out
    sent = wired.cmds("setvcp", "d7")[0]
    assert "--noverify" in sent and sent[-1] == "16"   # 0x10 = OFF


# ── verbose flag ────────────────────────────────────────────────────────────
def test_verbose_flag_sets_global_and_strips(wired, capsys):
    wired.values["62"] = 5
    assert b.cli(["-v", "get", "volume"]) == 0
    assert b.VERBOSE is True
    assert capsys.readouterr().out.strip() == "5"


def test_verbose_flag_echoes_set_command(wired, capsys):
    assert b.cli(["--verbose", "set", "volume", "30"]) == 0
    err = capsys.readouterr().err
    assert "$ ddcutil" in err and "setvcp 62 30" in err
