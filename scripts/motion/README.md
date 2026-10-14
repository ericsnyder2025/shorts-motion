# scripts/motion: the measuring half of the slideshow check

`film_gate.py` is huashu-art-motion's gate, vendored **unchanged** from
[github.com/alchaincyf/huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion) at commit `2571ee0`
(2026-10-14, v1.1.0), MIT licence (`LICENSE-huashu-art-motion`, Copyright (c) 2026 alchaincyf). Its sha256 is
`2d375cc2bea291e7a1b837d5755b49fbda72f5f75515758c09bf7d83cd269e52`; `tests/test_motion_gate.py` checks it.

It reads an MP4 only (ffmpeg, numpy, opencv-python-headless) and measures how the cut moves: fast-motion frames inside
shots, slow uniform zoom and camera drift (Lucas-Kanade tracking with RANSAC), push-ins, flat dead background, blank
frames, the blue-purple share. Its comments and messages are in Chinese. We use its numbers only:
`scripts/motion_gate.py` holds our thresholds and English wording, and `scripts/critic.py` reports them (DRIFT, PUSH,
DEAD warn; BLANK fails).

To refresh it: copy the newer file over this one, re-run a calibration like the one below on your own cuts, and
update the commit and hash here and in the test.

## Calibration (2026-10-14)

122 cuts: 8 we rejected before posting, 54 of our own posted cuts, and 60 Shorts from our niches: 35 breakouts (5x or
more their creator's usual views) and 25 typical posts from the same niches for comparison. Medians [10th-90th
percentile]:

| Measure | Rejected | Posted | Breakouts | Typical |
|---|---|---|---|---|
| fast-motion share (their gate) | 0.075 [0.025-0.110] | 0.083 [0.038-0.162] | 0.040 [0.000-0.312] | 0.160 [0.014-0.463] |
| slow uniform zoom share | 0.10 [0.00-0.88] | 0.27 [0.00-0.74] | 0.00 [0.00-0.24] | 0.00 [0.00-0.14] |
| slow camera drift share | 0.69 | 0.69 | 0.20 | 0.25 |
| push-ins a minute | 7.1 | 5.7 | 2.2 | 0.7 |
| flat dead background | 0.23 | 0.14 | 0.21 | 0.25 |
| visual events per 10 s | 8.0 | 8.2 | 3.6 | 7.2 |
| average shot | 2.8 s | 2.1 s | 4.2 s | 2.6 s |

What it says:

- Their hard gate (fast-motion share, calibrated on art animation) does not separate our rejected cuts from our
  posted ones, and breakouts in our niches move less than typical posts (they are mostly people talking). So it is
  reported, never judged.
- What set our cuts apart from the market was slow uniform camera: every plate pushing, every kinetic block scaling,
  punch-ins on every line. On our own posts (n about 40, Spearman against their analytics) more slow zoom went with
  fewer views (TikTok -0.37, YouTube -0.30) and more push-ins with fewer TikTok views (-0.35). A lean, not proof, so
  DRIFT and PUSH warn rather than fail. This is also why the layouts here ship with no slow push by default.
- Flat dead background separated rejected from posted (0.23 vs 0.14): DEAD warns over 0.25.
- No cut had a blank stretch: BLANK is a plain defect and fails.

Caveat: the gate masks only the bottom 18% of the frame (where its authors' subtitles sit); word captions mid-frame
change on every word, which raises the fast-motion share a little. Both our cuts and the viral ones carried captions.
