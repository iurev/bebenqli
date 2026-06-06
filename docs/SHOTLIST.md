# demo.gif — recording shot-list

Drop the finished GIF here as `docs/demo.gif` (README already links it).

Record a terminal at ~90×30, dark theme. Suggested ~15s sequence:

1. Launch: `bebenqli` (panel draws, values populate).
2. `↓` a few times down to **Color Mode**, press `→` once or a digit `4`
   (Cinema) — show the option list + the `●` marker move.
3. Down to **MH Brightness**, hold `→` to sweep the bar 1→10.
4. Press `/`, type `vol`, Enter — show fuzzy-find jumping to Volume.
5. (optional, looks great) press `!` on a control to show listen mode, then
   `q` to exit it.
6. `q` to quit.

Then 2–3 CLI lines for a second, smaller still or appended clip:

```bash
bebenqli list
bebenqli set volume 30
bebenqli -v get brightness
```

Tooling: any recorder works (peek, `wf-recorder` + `gifski`, OBS → gifski).
Keep it under ~2 MB so it loads fast on GitHub.
