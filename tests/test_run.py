import bebenqli as b


# ── version ─────────────────────────────────────────────────────────────────
def test_version_flag(capsys):
    assert b.run(["-V"]) == 0
    assert capsys.readouterr().out.strip() == f"bebenqli {b.__version__}"


def test_version_long_flag(capsys):
    assert b.run(["--version"]) == 0
    assert "bebenqli" in capsys.readouterr().out


# ── bus resolution + dispatch ───────────────────────────────────────────────
def test_run_explicit_bus_dispatches_cli(mon, capsys):
    mon.values["62"] = 20
    assert b.run(["--bus", "9", "get", "volume"]) == 0
    assert capsys.readouterr().out.strip() == "20"
    # exactly one ddcutil getvcp, carrying the explicit bus
    assert len(mon.cmds("--bus", "9", "getvcp", "62")) == 1


def test_run_bus_equals_form(mon, capsys):
    mon.values["62"] = 1
    assert b.run(["--bus=9", "get", "volume"]) == 0
    assert len(mon.cmds("--bus", "9", "getvcp", "62")) == 1


def test_run_bus_after_subcommand(mon, capsys):
    # --bus is stripped from anywhere in argv, not just the front
    mon.values["62"] = 7
    assert b.run(["get", "volume", "--bus", "9"]) == 0
    assert capsys.readouterr().out.strip() == "7"
    assert len(mon.cmds("--bus", "9", "getvcp", "62")) == 1


def test_run_multiple_bus_flags_last_wins(mon, capsys):
    mon.values["62"] = 1
    assert b.run(["--bus", "3", "--bus", "9", "get", "volume"]) == 0
    assert mon.cmds("--bus", "9", "getvcp", "62")
    assert not mon.cmds("--bus", "3", "getvcp", "62")


def test_run_bus_flag_without_value(mon, monkeypatch):
    # trailing "--bus" with no value -> explicit None -> falls back to detect
    monkeypatch.delenv("BEBENQLI_BUS", raising=False)
    called = {}
    monkeypatch.setattr(b.tui, "main", lambda ddc: called.update(hit=True, ddc=ddc))
    assert b.run(["--bus"]) == 0
    assert called["hit"] and called["ddc"].bus == "7"


def test_run_no_monitor_found(mon, monkeypatch, capsys):
    monkeypatch.delenv("BEBENQLI_BUS", raising=False)
    mon.detect_out = "Display 1\n   I2C bus:  /dev/i2c-3\n   Monitor: Other\n"
    assert b.run(["get", "volume"]) == 1
    assert "no monitor matching" in capsys.readouterr().err


def test_run_no_args_launches_tui(mon, monkeypatch):
    called = {}
    monkeypatch.setattr(b.tui, "main", lambda ddc: called.update(hit=True, ddc=ddc))
    assert b.run([]) == 0
    assert called.get("hit") is True
    assert called["ddc"].cmd == b.build_cmd("7")


def test_run_idebug_dispatches(mon, monkeypatch):
    called = {}
    monkeypatch.setattr(b.idebug, "main",
                        lambda ddc, name: called.update(ddc=ddc, name=name) or 0)
    assert b.run(["--bus", "9", "idebug", "brightness"]) == 0
    assert called["name"] == "brightness" and called["ddc"].bus == "9"


def test_run_idebug_without_name(mon, monkeypatch):
    called = {}
    monkeypatch.setattr(b.idebug, "main",
                        lambda ddc, name: called.update(name=name) or 0)
    assert b.run(["idebug"]) == 0
    assert called["name"] is None
