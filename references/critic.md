# The critic

```
python3 scripts/critic.py video.mp4 --plan project/scene-plan.json [--out dir] [--profile speaker|layered] [--no-probe]
python3 scripts/critic.py video.mp4                 # no plan: scenes from detected cuts, fewer rules, rougher guesses
python3 scripts/motion_gate.py video.mp4 [--json]   # the motion check alone
```

Writes `critic.json` (every scene, every finding, every motion number) and `critic-sheet.png` (one frame from the
middle of every scene, bordered green, amber or red, with its codes). Exit 1 on any FAIL. Measured, not judged: after
it passes, look at the sheet for what numbers miss.

Always pass `--plan`: it carries the layouts, the caption cards (for exact COLLIDE checks), whether there is a
presenter, and each scene's `allow` exceptions. Without it, scenes come from detected cuts and any big line in the
lower middle of the frame is taken for the caption.

## Frame rules

Measured on frames at 25/50/75% of each scene (the middle only for scenes under 1.6 s). Text and face boxes come from
`scripts/vision_probe.swift` (Apple Vision: text recognition, face rectangles, person segmentation), compiled with
`swiftc` on first use. Without it (not macOS, no Xcode command line tools, or `--no-probe`) the rules marked * are
skipped with a note, and VOID runs without the person mask.

| Code | Level | Rule | Fix |
|---|---|---|---|
| VOID | FAIL over 22%, WARN over 15% | the largest empty region (no detail after a light blur, so grain does not count), after an opening that drops strips under ~90 px. The caption counts as empty; the presenter and the platform bands (top 140, bottom 300 px) never do | more or bigger content, a bigger layout, a `plate`; keep the theme's dot texture |
| TEXT* | FAIL under 40 px, WARN under 48 | a text line's height on the frame; disclosure labels ("demo", "illustration", "source", "example", "rule of thumb"...) may be 26 | fewer words at a bigger size; split the scene |
| WALL* | FAIL over 9 lines | lines of text on one frame besides the caption (14 with `--profile layered`) | split the scene |
| HEAD* | FAIL under 13%, WARN under 17% with empty space | in a presenter layout, the face height as a share of the frame | a tighter `zoom`, a split instead of a small take |
| COLLIDE* | FAIL | graphic text touching the caption card | `captions` / `caption_y` on the scene, or move the text |

## Video rules

| Code | Level | Rule | Fix |
|---|---|---|---|
| REPEAT | FAIL | two scenes in a row with the same layout, or consecutive keyframes that look the same | rotate layouts |
| VARIETY | FAIL | fewer distinct layouts than min(5, scenes / 2 + 1) (3 with `--profile speaker`) | use more of the library |
| HOG | FAIL | one non-presenter layout over 40% of the runtime | rotate; split long scenes into different layouts |
| STALE | FAIL over 6 s, WARN over 4.5 s | the longest stretch with no picture change (cuts, builds and wipes count) | split the scene, add `at` cues to build items |
| FACE | FAIL outside 10-20% | with a presenter, their share of the runtime (face layouts: avatar, split, stack). `speaker`: 75%+; `layered`: 50-85% (over the top only warns). Skipped when the video has no presenter | more or fewer presenter scenes, or the right profile |
| OPEN* | FAIL / WARN | with a presenter: on screen at 0.1 s and 1.4 s passes; a graphic opening fails without the hook in big type (a line 80 px+ at 0.1 s), otherwise warns (check by eye that it is a visual hook). Without a presenter: the hook in big type passes, anything else fails | open on the presenter or a `kinetic` hook |

## Motion rules

From the whole MP4, by `scripts/motion_gate.py` on the vendored `scripts/motion/film_gate.py` (huashu-art-motion,
MIT). Every number lands in `critic.json` under `motion`.

| Code | Level | Rule | Fix |
|---|---|---|---|
| DRIFT | WARN | slow uniform zoom over 40% of the runtime | remove `push` / `zoom` holds; hold still while a graphic builds |
| PUSH | WARN | over 8 push-ins a minute | keep push-ins for the reveal, the number and the turn |
| DEAD | WARN | flat, unchanging background over 25% of the frame inside its shot | texture, a plate, or something that moves there |
| BLANK | FAIL | an edgeless (blank) picture for 0.3 s or more, after the first and before the last half second | find the empty stretch (critic.json gives the times) and fill it; check that media loaded |

Why these thresholds: calibrated on our own posted cuts (and the ones we rejected) against 60 Shorts in our niches
(35 breakouts and 25 typical posts). Viral breakouts ran about 0% slow uniform zoom and 2.2 push-ins a minute; our
cuts ran 27% and 5.7, and on our own posts more slow zoom went with fewer views (a lean, not proof, so these warn).
The table is in `scripts/motion/README.md`. The fast-motion share film_gate gates on is reported, never judged: it
did not separate good cuts from bad ones in talking-head explainers.

## Profiles

| Profile | For | Changes |
|---|---|---|
| (default) | graphics-led explainers, with or without a presenter | as above |
| `speaker` | talking-head-led videos | FACE 75%+, two presenter scenes in a row allowed (the look-the-same check still applies), VARIETY needs 3, STALE fails at 8 s |
| `layered` | busy styles with stacked cards and notes behind the presenter | WALL 14, FACE 50-85% (over only warns), "AI avatar" / "AI voice" tags count as labels |

## Exceptions

A scene that breaks a frame rule on purpose says so in `scenes.json`:

```json
{"at": "Here is my code", "mode": "stack", "bg": {"type": "code", "file": "app.py"}, "allow": ["WALL", "TEXT"], "why": "the code wall: the code is texture behind the presenter, not something to read"}
```

`allow` takes VOID, TEXT, WALL, HEAD, COLLIDE and OPEN (OPEN on scene 0 only); the build refuses an `allow` without a
`why`, and every critic report prints the reasons. Video rules (REPEAT, VARIETY, HOG, STALE, FACE) and the motion
rules have no per-scene exception: fix the cut.
