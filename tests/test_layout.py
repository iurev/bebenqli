import bebenqli as b


def test_read_returns_none_for_write_only_control(ddc):
    # _read short-circuits write-only controls; CLI never reaches this path
    # (it special-cases noread earlier), so exercise it directly.
    assert b._read(ddc, {"vcp": "d7", "noread": True}) is None


def test_read_returns_value_for_readable_control(mon, ddc):
    mon.values["62"] = 33
    assert b._read(ddc, {"vcp": "62"}) == 33


def test_renderable_skips_group_with_no_visible_children(monkeypatch):
    # A trailing group whose only following items are hidden must NOT be kept.
    controls = [
        {"type": "group",   "label": "Real"},
        {"type": "range",   "label": "Vol", "min": 0, "max": 10},
        {"type": "group",   "label": "Empty"},
        {"type": "dead",    "label": "Gone"},      # hidden -> group stays empty
    ]
    monkeypatch.setattr(b.controls, "CONTROLS", controls)
    keep = b._renderable()
    assert 0 in keep            # "Real" group has a visible child
    assert 1 in keep            # the range itself
    assert 2 not in keep        # "Empty" group dropped
    assert 3 not in keep        # dead row never rendered
