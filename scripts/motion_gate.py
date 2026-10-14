#!/usr/bin/env python3
"""The slideshow check: how a cut moves, measured from the MP4 alone, for critic.py (codes DRIFT, PUSH, DEAD, BLANK).
The measuring is huashu-art-motion's film_gate.py (MIT, Copyright (c) 2026 alchaincyf, vendored unchanged in
scripts/motion/ from commit 2571ee0); the thresholds and wording are ours, calibrated on our own cuts.

    python3 scripts/motion_gate.py video.mp4 [--json]

Calibration (scripts/motion/README.md): 8 cuts we rejected, 54 of our own posted cuts, and 60 Shorts from our niches
(35 breakouts at 5x or more their creator's usual views, 25 typical posts for comparison).
  - Their hard gate, the share of fast-motion frames, does not fit talking-head explainers: rejected 0.075 vs posted
    0.083 (medians), and breakouts move LESS than typical posts (0.040 vs 0.160): they are mostly people talking. It
    is reported, never judged.
  - What set our cuts apart from the market was slow uniform camera: zoom on 27% of our runtime (breakouts 0%, 90th
    percentile 24%), slow camera drift 69% (breakouts 20%), 5.7 push-ins a minute (breakouts 2.2). On our own posts
    more slow zoom went with fewer views (Spearman -0.37 on TikTok, -0.30 on YouTube; push-ins -0.35 on TikTok), n
    about 40: a lean, not proof. Hence WARN lines, not fails.
  - Flat dead background (unchanging and texture-free inside a shot) was the one measure that separated the rejected
    cuts from the posted ones (0.23 vs 0.14).
  - A blank stretch mid-video (an almost edgeless frame for 0.3 s or more) is a plain defect: FAIL. None of the 122
    cuts had one.
Rules:
  DRIFT  WARN  slow uniform zoom over 40% of the runtime (our posted median 27%, breakouts 0%)
  PUSH   WARN  over 8 push-ins a minute (their yellow line; ours median 5.7, breakouts 2.2)
  DEAD   WARN  flat dead background over 25% of the frame (rejected median 23%, posted 14%)
  BLANK  FAIL  an edgeless (blank) stretch of 0.3 s or more after the first and before the last half second
Every number is kept in the report (critic.json "motion") so later posts can be read against their analytics.
Needs numpy and opencv-python-headless.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "motion"))

LIMITS = {"drift_warn": 0.40, "push_warn": 8.0, "dead_warn": 0.25, "blank_fail": 0.3}
KEEP = ("duration_s", "fast_ratio", "slow_zoom_share", "slow_cam_share", "push_in_per_min", "fast_push_per_min",
        "dead_bg", "dead_flat", "event_rate", "still_ratio", "longest_still_s", "blank_run_s", "blank_runs_s", "asl_s",
        "push_in_times_s", "blue_purple_share")


def measure(video):
    """film_gate's numbers for this file, cached next to it (<video>.motion.json) until the file changes."""
    video = Path(video)
    cache = video.with_suffix(".motion.json")
    stamp = f"{video.stat().st_size}:{int(video.stat().st_mtime)}"
    if cache.exists():
        try:
            c = json.loads(cache.read_text())
            if c.get("_stamp") == stamp:
                return c
        except ValueError:
            pass
    import film_gate  # numpy + opencv-python-headless
    r = film_gate.analyze(str(video))
    r["blue_purple_share"], _ = film_gate.blue_purple(str(video))
    out = {**{k: r.get(k) for k in KEEP}, "_stamp": stamp, "_source": "huashu-art-motion film_gate.py @2571ee0"}
    try:
        cache.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def findings(m, limits=None):
    L = {**LIMITS, **(limits or {})}
    out = []
    if m["slow_zoom_share"] > L["drift_warn"]:
        out.append({"level": "WARN", "code": "DRIFT", "detail": f"slow uniform zoom on {m['slow_zoom_share']:.0%} of the runtime "
                    f"(viral breakouts: about 0%): hold still while a graphic builds or the presenter talks, and save moves for a reveal"})
    if m["push_in_per_min"] > L["push_warn"]:
        times = ", ".join(f"{t:.1f}" for t in (m.get("push_in_times_s") or [])[:8])
        out.append({"level": "WARN", "code": "PUSH", "detail": f"{m['push_in_per_min']:.1f} push-ins a minute (breakouts about 2): "
                    f"keep them for the reveal, the number and the turn; pull back out after one (at {times} s)"})
    if m["dead_flat"] > L["dead_warn"]:
        out.append({"level": "WARN", "code": "DEAD", "detail": f"{m['dead_flat']:.0%} of the frame is flat and unchanging inside "
                    f"its shot: give that area texture, a plate or something that moves"})
    if m["blank_run_s"] >= L["blank_fail"]:
        spans = ", ".join(f"{a:.1f}-{b:.1f}" for a, b in m.get("blank_runs_s") or [])
        out.append({"level": "FAIL", "code": "BLANK", "detail": f"a blank (edgeless) picture for {m['blank_run_s']:.1f} s at {spans} s"})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    m = measure(a.video)
    f = findings(m)
    if a.json:
        print(json.dumps({"motion": m, "findings": f}, indent=1))
    else:
        print(f"motion: fast {m['fast_ratio']:.3f}  slow zoom {m['slow_zoom_share']:.0%}  slow camera {m['slow_cam_share']:.0%}  "
              f"push-ins {m['push_in_per_min']:.1f}/min  dead flat {m['dead_flat']:.0%}  blank {m['blank_run_s']:.1f} s  "
              f"shot {m['asl_s']:.1f} s")
        for x in f:
            print(f"  {x['level']} {x['code']}: {x['detail']}")
    sys.exit(1 if any(x["level"] == "FAIL" for x in f) else 0)


if __name__ == "__main__":
    main()
