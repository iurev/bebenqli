import bebenqli as b


def rr(ctrl, val=0, loaded=True, pending=None, blink_on=True, entry=None):
    return b.render_row(ctrl, val, loaded, pending, blink_on, entry)


def test_render_group():
    assert rr({"type": "group", "label": "Audio"}).startswith("▌AUDIO")


def test_render_section():
    assert rr({"type": "section", "label": "Moon Halo"}).startswith("  ▎Moon Halo")


def test_render_missing():
    assert "[not mapped]" in rr({"type": "missing", "label": "KVM"})


def test_render_dead():
    assert "[hw n/a]" in rr({"type": "dead", "label": "Mute"})


def test_render_not_loaded():
    out = rr({"type": "range", "label": "Volume", "min": 0, "max": 50}, loaded=False)
    assert out.rstrip().endswith("@")


def test_render_cycle_value():
    ctrl = {"type": "cycle", "label": "Source", "opts": [1, 2], "names": ["DP", "HDMI"]}
    assert "HDMI" in rr(ctrl, val=2)


def test_render_cycle_unknown_value_falls_back_to_first():
    ctrl = {"type": "cycle", "label": "Source", "opts": [1, 2], "names": ["DP", "HDMI"]}
    assert "DP" in rr(ctrl, val=99)


def test_render_cycle_blank_while_pending():
    ctrl = {"type": "cycle", "label": "Source", "opts": [1, 2], "names": ["DP", "HDMI"]}
    out = rr(ctrl, val=2, pending=2, blink_on=False)
    assert "Source" in out            # label still drawn
    assert "HDMI" not in out          # value blanked during blink-off


def test_render_range_value_has_bar():
    out = rr({"type": "range", "label": "Volume", "min": 0, "max": 50}, val=25)
    assert "█" in out or "░" in out
    assert "25/50" in out


def test_render_range_blank_while_pending():
    out = rr({"type": "range", "label": "Volume", "min": 0, "max": 50},
             val=25, pending=25, blink_on=False)
    assert "25/50" not in out


def test_render_range_entry_mode():
    out = rr({"type": "range", "label": "Volume", "min": 0, "max": 50},
             val=25, entry="3")
    assert "type: 3" in out
