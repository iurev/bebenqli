import bebenqli as b
from bebenqli.tui.state import Model, Frame, _clamp


def _idx(label):
    return next(i for i, c in enumerate(b.CONTROLS) if c.get("label") == label)


VOL  = None  # filled per-test via _idx; kept simple with helpers below
RANGE = {"type": "range", "min": 0, "max": 50}
CYCLE = {"type": "cycle", "opts": [0x30, 0x31, 0x0f], "names": ["a", "b", "c"]}


# ── _clamp ───────────────────────────────────────────────────────────────────
def test_clamp_none_returns_default():
    assert _clamp(RANGE, None, 7) == 7


def test_clamp_range_clamps_both_ends():
    assert _clamp(RANGE, 999, 0) == 50
    assert _clamp(RANGE, -5, 0) == 0


def test_clamp_cycle_invalid_falls_to_first_opt():
    assert _clamp(CYCLE, 0x99, 0) == 0x30


def test_clamp_passthrough_valid():
    assert _clamp(RANGE, 25, 0) == 25
    assert _clamp(CYCLE, 0x0f, 0) == 0x0f


# ── filtered / move ──────────────────────────────────────────────────────────
def test_filtered_not_searching_is_all(ddc):
    m = Model(ddc)
    assert m.filtered() == b.INTERACT


def test_filtered_empty_query_is_all(ddc):
    m = Model(ddc)
    m.searching = True
    assert m.filtered() == b.INTERACT


def test_filtered_narrows_to_query(ddc):
    m = Model(ddc)
    m.searching, m.search_q = True, "volume"
    assert m.filtered() == [_idx("Volume")]


def test_move_wraps(ddc):
    m = Model(ddc)
    m.sel = b.INTERACT[0]
    m.move(-1)
    assert m.sel == b.INTERACT[-1]
    m.move(1)
    assert m.sel == b.INTERACT[0]


def test_move_empty_pool_noops(ddc):
    m = Model(ddc)
    m.searching, m.search_q = True, "zzz-no-match"
    before = m.sel
    m.move(1)
    assert m.sel == before


def test_move_sel_outside_pool_jumps_to_first(ddc):
    m = Model(ddc)
    m.sel = _idx("Contrast")              # not a "volume" match
    m.searching, m.search_q = True, "volume"
    m.move(1)
    assert m.sel == _idx("Volume")


# ── change ───────────────────────────────────────────────────────────────────
def test_change_missing_noops(ddc):
    m = Model(ddc)
    i = _idx("KVM Switch")                # type "missing"
    m.change(i, 1)
    assert not m.dirty


def test_change_not_loaded_noops(ddc):
    m = Model(ddc)
    i = _idx("Volume")                    # loaded is False until seeded
    m.change(i, 1)
    assert not m.dirty and m.vals[i] == 0


def test_change_range_clamps_and_queues(ddc):
    m = Model(ddc)
    i = _idx("Volume")
    m.loaded[i], m.vals[i] = True, 50
    m.change(i, 5)
    assert m.vals[i] == 50                # clamped at max
    assert i in m.dirty and m.pending[i] == 50


def test_change_cycle_wraps(ddc):
    m = Model(ddc)
    i = _idx("Source")                    # cycle, opts [0x0f, 0x11, 0x13]
    opts = b.CONTROLS[i]["opts"]
    m.loaded[i], m.vals[i] = True, opts[-1]
    m.change(i, 1)
    assert m.vals[i] == opts[0]           # wrapped past the end


def test_change_cycle_unknown_current_starts_at_zero(ddc):
    m = Model(ddc)
    i = _idx("Source")
    opts = b.CONTROLS[i]["opts"]
    m.loaded[i], m.vals[i] = True, 0x99   # not in opts -> index 0
    m.change(i, 1)
    assert m.vals[i] == opts[1]


# ── pick_opt ─────────────────────────────────────────────────────────────────
def test_pick_opt_sets_nth(ddc):
    m = Model(ddc)
    i = _idx("Color Mode")
    m.loaded[i] = True
    m.pick_opt(i, 4)
    assert m.vals[i] == b.CONTROLS[i]["opts"][3] and i in m.dirty


def test_pick_opt_non_cycle_noops(ddc):
    m = Model(ddc)
    i = _idx("Volume")
    m.loaded[i] = True
    m.pick_opt(i, 1)
    assert not m.dirty


def test_pick_opt_out_of_range_noops(ddc):
    m = Model(ddc)
    i = _idx("Color Mode")
    m.loaded[i] = True
    m.pick_opt(i, 99)
    assert not m.dirty


def test_pick_opt_not_loaded_noops(ddc):
    m = Model(ddc)
    i = _idx("Color Mode")                # loaded False
    m.pick_opt(i, 1)
    assert not m.dirty


# ── commit_entry ─────────────────────────────────────────────────────────────
def test_commit_entry_clamps_and_queues(ddc):
    m = Model(ddc)
    i = _idx("Volume")
    m.loaded[i] = True
    m.entry, m.entry_buf = i, "80"
    m.commit_entry()
    assert m.vals[i] == 50 and i in m.dirty
    assert m.entry is None and m.entry_buf == ""


def test_commit_entry_empty_buffer_noops(ddc):
    m = Model(ddc)
    m.entry, m.entry_buf = _idx("Volume"), ""
    m.commit_entry()
    assert not m.dirty and m.entry is None


def test_commit_entry_none_noops(ddc):
    m = Model(ddc)
    m.commit_entry()
    assert not m.dirty


def test_commit_entry_not_loaded_noops(ddc):
    m = Model(ddc)
    i = _idx("Volume")                    # loaded False
    m.entry, m.entry_buf = i, "30"
    m.commit_entry()
    assert not m.dirty and m.vals[i] == 0


# ── seed ─────────────────────────────────────────────────────────────────────
def test_seed_header_noops(ddc):
    m = Model(ddc)
    i = next(i for i, c in enumerate(b.CONTROLS) if c["type"] == "group")
    m.seed(i)                             # just must not raise / change values
    assert m.vals[i] == 0


def test_seed_write_only_uses_default(ddc):
    m = Model(ddc)
    i = _idx("MH Switch")                 # cycle, noread
    m.seed(i)
    assert m.loaded[i] and m.vals[i] == b.CONTROLS[i]["opts"][0]


def test_seed_reads_and_clamps(mon, ddc):
    m = Model(ddc)
    i = _idx("Volume")
    mon.values["62"] = 999                # over max -> clamped
    m.seed(i)
    assert m.loaded[i] and m.vals[i] == 50


def test_seed_unreadable_uses_default(ddc):
    m = Model(ddc)
    i = _idx("Volume")                    # nothing in mon.values -> getvcp None
    m.seed(i)
    assert m.loaded[i] and m.vals[i] == 0


def test_seed_cycle_unknown_value_falls_to_first(mon, ddc):
    m = Model(ddc)
    i = _idx("Source")
    mon.values["60"] = 0x99               # not a valid opt
    m.seed(i)
    assert m.vals[i] == b.CONTROLS[i]["opts"][0]


# ── animating / tick / snapshot ──────────────────────────────────────────────
def test_animating_true_until_loaded(ddc):
    assert Model(ddc).animating() is True


def test_animating_false_when_settled(ddc):
    m = Model(ddc)
    m.loaded = [True] * len(b.CONTROLS)
    m.pending = [None] * len(b.CONTROLS)
    assert m.animating() is False


def test_tick_advances_only_pending(ddc):
    m = Model(ddc)
    i = _idx("Volume")
    m.pending[i] = 5
    m.tick()
    assert m.ticks[i] == 1
    j = _idx("Contrast")
    assert m.ticks[j] == 0                # not pending -> untouched


def test_snapshot_is_a_frame(ddc):
    m = Model(ddc)
    snap = m.snapshot()
    assert isinstance(snap, Frame)
    assert snap.sel == m.sel and snap.pool == b.INTERACT
