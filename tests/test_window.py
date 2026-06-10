import bebenqli as b


def test_set_window_title_in_tmux(mon, monkeypatch, capsys):
    monkeypatch.setenv("TMUX", "/tmp/tmux-sock")
    b.set_window_title("bebenqli")
    assert len(mon.cmds("tmux", "rename-window", "bebenqli")) == 1
    assert "\033]2;bebenqli\007" in capsys.readouterr().out


def test_set_window_title_no_tmux(mon, monkeypatch, capsys):
    monkeypatch.delenv("TMUX", raising=False)
    b.set_window_title("bebenqli")
    assert not mon.cmds("tmux")               # no tmux call outside tmux
    assert "\033]2;bebenqli\007" in capsys.readouterr().out


def test_restore_window_title_in_tmux(mon, monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-sock")
    b.restore_window_title()
    assert len(mon.cmds("tmux", "set-window-option", "automatic-rename", "on")) == 1


def test_restore_window_title_no_tmux(mon, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    b.restore_window_title()
    assert not mon.cmds("tmux")
