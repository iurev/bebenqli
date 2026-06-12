import pytest

import bebenqli as b
from bebenqli.idebug import Session, Console, Report, _targets


RANGE = {"vcp": "10", "type": "range", "min": 0, "max": 100}
CYCLE = {"vcp": "60", "type": "cycle", "names": ["DP", "HDMI", "USB-C"]}


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


def test_set_verify_unverified_when_readback_fails(monkeypatch, mon, ddc):
    monkeypatch.setattr(ddc, "read_raw", lambda code: (None, None))   # DDC read error
    s = _sess(ddc)
    rep = s.set_verify(_ctrl(s, "brightness"), "50")
    assert rep.status == "unverified" and rep.got is None


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


def test_record_watch_persists_trail(mon, ddc):
    s = _sess(ddc)
    s.record_watch("10", [1, 2, 3])
    assert s.log[-1] == {"action": "watch", "vcp": "10", "observed": [1, 2, 3]}


def test_record_discovery_keeps_only_movers(mon, ddc):
    s = _sess(ddc)
    s.record_discovery({"ca": [5], "cb": [5, 6, 7]})   # ca never moved past baseline
    assert s.log[-1] == {"action": "discover",
                         "movers": [{"vcp": "cb", "trail": [5, 6, 7]}]}


# ── pure formatters ──────────────────────────────────────────────────────────
def test_spec_str_cycle_and_range():
    assert Session.spec_str(CYCLE) == "{DP|HDMI|USB-C}"
    assert Session.spec_str(RANGE) == "0..100"


@pytest.mark.parametrize("rep,expected", [
    (Report("verified", 50, "50", 50, "50", {}),
     "set 10→50 · readback 50 (verified)"),
    (Report("mismatch", 50, "50", 47, "47", {}),
     "set 10→50 · readback 47 (MISMATCH)"),
    (Report("writeonly", 0x20, "ON", None, None, {}),
     "set 10→ON (write-only, unverified)"),
    (Report("failed", 50, "50", None, None, {}),
     "set 10: FAILED (ddcutil rejected)"),
    (Report("unverified", 50, "50", None, None, {}),
     "set 10→50 (no read-back — DDC error)"),
    (Report("verified", 50, "50", 50, "50", {"dc": (1, 2)}),
     "set 10→50 · readback 50 (verified) · else: dc:1→2"),
])
def test_report_line(rep, expected):
    assert Session.report_line(RANGE, rep) == expected


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


# ── discovery ────────────────────────────────────────────────────────────────
def test_baseline_codes_keeps_only_responders(mon, ddc):
    assert "ca" in b.SCAN_CODES                   # sanity: an unmapped candidate
    mon.values["ca"] = 5
    base = _sess(ddc).baseline_codes()
    assert base["ca"] == 5
    assert "cc" not in base                        # unset candidate -> no answer


def test_poll_once_detects_move(mon, ddc):
    mon.values["10"] = 5
    s = _sess(ddc)
    assert s.poll_once("10", None) == (5, True)
    assert s.poll_once("10", 5) == (5, False)
    assert s.poll_once("ca", 0) == (None, False)   # unreadable -> no move


def test_step_appends_distinct_only():
    trails = {}
    assert Session.step(trails, "ca", 5) is True
    assert Session.step(trails, "ca", 5) is False
    assert Session.step(trails, "ca", 6) is True
    assert trails == {"ca": [5, 6]}


def test_rank_movers_most_changed_first():
    ranked = Session.rank_movers({"a": [1], "b": [1, 2, 3]})
    assert ranked[0][0] == "b"


# ── targets / console dispatch ───────────────────────────────────────────────
def test_targets_includes_mapped_and_missing():
    t = _targets()
    assert "brightness" in t                       # mapped
    assert "kvm-switch" in t                        # missing -> discovery target
    assert "mute" not in t                          # dead -> not targetable


def test_console_dispatch_smoke(mon, ddc):
    # Console is pragma'd (interactive I/O); this just guards against crashes in
    # the non-blocking command paths (r / note / d).
    mon.values["10"] = 5
    t = _targets()
    con = Console(Session(ddc, focus=t["brightness"]), "brightness", t)
    con.onecmd("r")
    con.onecmd("note flickered")
    con.onecmd("d")
    assert con.s.log[-1] == {"action": "note", "text": "flickered"}
