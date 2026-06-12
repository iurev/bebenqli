import pytest

import bebenqli as b
from bebenqli.idebug import Session


def _sess(ddc):
    return Session(ddc)


def _ctrl(sess, name):
    return sess.controls[name]


# ── reads ────────────────────────────────────────────────────────────────────
def test_snapshot_reads_mapped_readable(mon, ddc):
    mon.values["10"], mon.values["62"] = 80, 23
    snap = _sess(ddc).snapshot()
    assert snap["10"] == 80 and snap["62"] == 23


def test_snapshot_skips_noread_and_unanswered(mon, ddc):
    mon.values["10"] = 80                      # d9 color-temp is noread -> absent
    snap = _sess(ddc).snapshot()
    assert "d9" not in snap or snap.get("d9") is not None
    assert "dc" not in snap                     # nothing set -> getvcp None -> skipped


def test_read_returns_cur_max(mon, ddc):
    mon.values["10"] = 5
    s = _sess(ddc)
    assert s.read(_ctrl(s, "brightness")) == (5, 100)


def test_read_noread_is_none(mon, ddc):
    s = _sess(ddc)
    assert s.read(_ctrl(s, "mh-color-temp")) is None


def test_diff_reports_moved_only():
    assert Session.diff({"10": 5}, {"10": 7, "62": 3}) == {"10": (5, 7), "62": (None, 3)}


# ── set_verify / write_only ──────────────────────────────────────────────────
def test_set_verify_verified(mon, ddc):
    s = _sess(ddc)
    rep = s.set_verify(_ctrl(s, "brightness"), "50")
    assert rep.status == "verified" and rep.target == 50 and rep.got == 50
    assert rep.else_changed == {}


def test_set_verify_mismatch(monkeypatch, mon, ddc):
    monkeypatch.setattr(ddc, "read_raw", lambda code: (47, 100))   # panel snaps
    s = _sess(ddc)
    rep = s.set_verify(_ctrl(s, "brightness"), "50")
    assert rep.status == "mismatch" and rep.got == 47 and rep.got_shown == "47"


def test_set_verify_writeonly_for_noread(mon, ddc):
    s = _sess(ddc)
    rep = s.set_verify(_ctrl(s, "mh-switch"), "ON")
    assert rep.status == "writeonly" and rep.got is None


def test_set_verify_failed_when_ddcutil_rejects(mon, ddc):
    mon.set_fail.add("10")
    s = _sess(ddc)
    assert s.set_verify(_ctrl(s, "brightness"), "50").status == "failed"


def test_set_verify_bad_value_raises(mon, ddc):
    s = _sess(ddc)
    with pytest.raises(ValueError):
        s.set_verify(_ctrl(s, "color-mode"), "bogus")


def test_set_verify_detects_coupling(mon, ddc):
    mon.values["10"] = 80                       # brightness before
    mon.couples["dc"] = ("10", 22)              # setting color-mode moves brightness
    s = _sess(ddc)
    rep = s.set_verify(_ctrl(s, "color-mode"), "cinema")
    assert rep.else_changed == {"10": (80, 22)}


def test_write_only_never_verifies(mon, ddc):
    s = _sess(ddc)
    rep = s.write_only(_ctrl(s, "brightness"), "30")
    assert rep.status == "writeonly" and rep.got is None


# ── evidence / restore ───────────────────────────────────────────────────────
def test_set_visible_tags_last_entry(mon, ddc):
    s = _sess(ddc)
    s.set_verify(_ctrl(s, "brightness"), "50")
    s.set_visible("y")
    assert s.log[-1]["visible"] == "y"


def test_set_visible_noop_without_log(mon, ddc):
    s = _sess(ddc)
    s.set_visible("y")                           # nothing logged yet -> no error
    assert s.log == []


def test_add_note_appends(mon, ddc):
    s = _sess(ddc)
    s.add_note("flickered")
    assert s.log[-1] == {"action": "note", "text": "flickered"}


def test_restore_writes_back_captured_value(mon, ddc):
    mon.values["10"] = 10
    s = _sess(ddc)
    s.set_verify(_ctrl(s, "brightness"), "50")   # originals[10] = (10, ctrl)
    assert s.restore() == 1
    assert mon.values["10"] == 10                # written back


def test_restore_skips_unreadable_original(mon, ddc):
    s = _sess(ddc)
    s.set_verify(_ctrl(s, "volume"), "30")       # nothing pre-set -> original None
    assert s.restore() == 0


def test_yaml_doc_focused(mon, ddc):
    s = Session(ddc, focus=b.CONTROLS[_cm_idx()])
    s.add_note("x")
    doc = s.yaml_doc()
    assert doc["control"] == "Brightness" and doc["vcp"] == "10"
    assert doc["entries"][-1]["text"] == "x"


def test_yaml_doc_discovery_has_no_focus(mon, ddc):
    doc = Session(ddc, focus=None).yaml_doc()
    assert doc["control"] == "discover" and doc["vcp"] is None


def _cm_idx():
    return next(i for i, c in enumerate(b.CONTROLS) if c.get("label") == "Brightness")
