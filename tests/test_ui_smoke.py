import bebenqli as b


class FakeTerm:
    """Minimal stand-in for blessed.Terminal: draw() only touches these."""
    home = ""
    clear = ""
    reverse = ""
    normal = ""


def test_ui_constructs_and_renders_once(wired, capsys):
    # Smoke only: the TUI is excluded from the coverage target. We just assert
    # it builds (spawns its writer thread) and paints a frame without raising.
    ui = b.UI()
    ui.draw(FakeTerm())
    out = capsys.readouterr().out
    assert "BenQ RD280U Monitor Control" in out
    assert "Volume" in out
