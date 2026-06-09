import bebenqli as b


# ── detect_bus ──────────────────────────────────────────────────────────────
def test_detect_bus_matches_model(mon):
    assert b.detect_bus() == "7"


def test_detect_bus_no_matching_model(mon):
    mon.detect_out = (
        "Display 1\n"
        "   I2C bus:  /dev/i2c-3\n"
        "   Monitor:  Some Other LCD\n"
    )
    assert b.detect_bus() is None


def test_detect_bus_model_before_any_bus_line(mon):
    # model string appears but no i2c bus seen yet -> bus is None -> no match
    mon.detect_out = "Monitor: BenQ RD280U\n   I2C bus:  /dev/i2c-5\n"
    assert b.detect_bus() is None


def test_detect_bus_ddcutil_missing(mon):
    mon.missing_ddcutil = True
    assert b.detect_bus() is None


# ── resolve_bus ─────────────────────────────────────────────────────────────
def test_resolve_bus_explicit_int(mon):
    assert b.resolve_bus(9) == "9"


def test_resolve_bus_explicit_str(mon):
    assert b.resolve_bus("12") == "12"


def test_resolve_bus_env(mon, monkeypatch):
    monkeypatch.setenv("BEBENQLI_BUS", "4")
    assert b.resolve_bus() == "4"


def test_resolve_bus_env_ignored_when_explicit(mon, monkeypatch):
    monkeypatch.setenv("BEBENQLI_BUS", "4")
    assert b.resolve_bus(8) == "8"


def test_resolve_bus_falls_back_to_detect(mon, monkeypatch):
    monkeypatch.delenv("BEBENQLI_BUS", raising=False)
    assert b.resolve_bus() == "7"
