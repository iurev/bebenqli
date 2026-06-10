import bebenqli as b
from bebenqli.tui.state import Model
from bebenqli.tui import view


def _idx(label):
    return next(i for i, c in enumerate(b.CONTROLS) if c.get("label") == label)


def _loaded_model(ddc):
    m = Model(ddc)
    m.loaded = [True] * len(b.CONTROLS)   # pretend every control has been read
    return m


def test_render_has_title_footer_and_rows(ddc):
    lines = view.render(_loaded_model(ddc).snapshot())
    joined = "\n".join(lines)
    assert "BenQ RD280U Monitor Control" in joined
    assert any("Volume" in l for l in lines)
    assert "↑↓ move" in joined                       # normal footer
    assert lines[0].startswith("╭") and lines[-1].startswith("╰")


def test_render_selected_row_wrapped_in_escapes(ddc):
    m = _loaded_model(ddc)
    m.sel = _idx("Volume")
    lines = view.render(m.snapshot(), reverse="<R>", normal="<N>")
    assert any("<R>" in l and "<N>" in l and "Volume" in l for l in lines)


def test_render_shows_cycle_options_for_selected_cycle(ddc):
    m = _loaded_model(ddc)
    i = _idx("Color Mode")
    m.sel, m.vals[i] = i, b.CONTROLS[i]["opts"][0]
    lines = view.render(m.snapshot())
    assert any("● Coding Dark" in l for l in lines)   # marked current option


def test_render_search_dims_and_footer(ddc):
    m = _loaded_model(ddc)
    m.searching, m.search_q = True, "volume"
    joined = "\n".join(view.render(m.snapshot()))
    assert "/ volume█" in joined                      # search footer branch
    assert "Contrast" in joined                       # a dimmed non-match still drawn


def test_footer_normal_and_search(ddc):
    m = Model(ddc)
    assert "↑↓ move" in view._footer(m.snapshot())
    m.searching, m.search_q = True, "x"
    assert "/ x█" in view._footer(m.snapshot())
