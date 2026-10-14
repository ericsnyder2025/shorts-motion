#!/usr/bin/env python3
"""The design critic: fails a cut for empty space, small text, walls of text, a tiny head, caption collisions,
repeated layouts and stale stretches, and warns when it moves like a slideshow. Measured, not judged: look at the
sheet yourself for what numbers miss (polish, hierarchy, whether the graphic shows what is being said).

    python3 scripts/critic.py video.mp4 --plan project/scene-plan.json [--out dir] [--profile speaker]
    python3 scripts/critic.py video.mp4 [--out dir]          # no plan: scenes from detected cuts, fewer rules

Writes <out>/critic.json and <out>/critic-sheet.png: one frame from the middle of every scene, bordered green (pass),
amber (warn) or red (fail), with the reason codes under it. Exit 1 on any FAIL.

Frame rules, on frames at 25/50/75% of each scene. Text and face boxes come from scripts/vision_probe.swift (Apple
Vision, compiled on first use on macOS); without it TEXT, WALL, HEAD, COLLIDE and the hook size are skipped with a
note, and VOID runs without the person mask:
  VOID      an empty region (no detail after a light blur, so grain doesn't count) over 22% of the frame (WARN over
            15%), measured after an opening that drops passages under ~90 px (side margins must not join the space
            above and below a centred block into one region). The word caption counts as empty: a caption does not
            fill a frame. The presenter never counts (person segmentation), so a dark shirt is not empty space, and
            neither do the platform bands: the bottom 300 px (username, description, buttons) and the top 140 px.
  TEXT      a text line under 40 px tall (WARN under 48). Disclosure labels ("demo", "illustration", "source",
            "rule of thumb"...) may be 26.
  WALL      more than 9 lines of text on one frame besides the caption (14 with --profile layered).
  HEAD      in a layout that shows the presenter, a face under 13% of the frame height (WARN under 17% with empty
            space around it). People in B-roll are not the presenter and are not measured.
  COLLIDE   graphic text touching the caption (with a plan, the caption is the card on screen at its own y; without
            one, any line 90 px or taller between 50% and 80% of the height is taken for the caption).
Video rules, on the scene plan:
  REPEAT    two scenes in a row with the same layout, or consecutive keyframes that look the same.
  VARIETY   fewer distinct layouts than min(5, scenes // 2 + 1).
  HOG       one non-face layout over 40% of the runtime.
  STALE     over 6 s with no picture change (WARN over 4.5 s): changes inside a scene (a build, a wipe) count.
  FACE      a video with a presenter: on screen outside 10-20% of the runtime FAILS (the speaker profile wants 75%+,
            layered 50-85%). Skipped, with a note, when the plan has no presenter.
  OPEN      the hook. With a presenter: on screen at 0.1 s and 1.4 s in a face layout passes; a graphic opening FAILS
            without the hook in big type (a line 80 px or taller at 0.1 s) and otherwise WARNS (check by eye that it
            is a visual hook, not a plain screen). Without a presenter: the hook in big type passes, anything else
            FAILS. "allow": ["OPEN"] on scene 0, with a "why", skips it.
Motion rules, on the whole MP4 (scripts/motion_gate.py: the vendored huashu-art-motion film_gate measures, our
thresholds; calibration in scripts/motion/README.md; every number lands in critic.json "motion"):
  DRIFT     slow uniform zoom over 40% of the runtime (WARN).
  PUSH      over 8 push-ins a minute (WARN).
  DEAD      flat, unchanging background over 25% of the frame inside its shot (WARN).
  BLANK     an edgeless (blank) picture for 0.3 s or more mid-video (FAIL).
Per-scene exceptions go in scenes.json as "allow": ["VOID"] with a "why"; they are reported, never silent.
"""
import argparse
import json
import math
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
PROBE_SRC = HERE / "vision_probe.swift"
FONT = HERE.parent / "fonts" / "Montserrat.ttf"
FACE_TYPES = {"avatar", "split", "stack", "face"}  # layouts that show the presenter
DISCLOSURE = re.compile(r"^(demo|illustration|source|sources|example|fictional|not real|sample|rule of thumb)\b", re.I)
LIMITS = {"void_fail": 0.22, "void_warn": 0.15, "text_fail": 40, "text_warn": 48, "text_label": 26, "wall": 9,
          "head_fail": 0.13, "head_warn": 0.17, "hog": 0.40, "stale_fail": 6.0, "stale_warn": 4.5,
          "face_min": 0.10, "face_max": 0.20, "face_over": "FAIL", "hook_px": 80, "same_look": 0.93, "change": 0.15,
          "ui_band": 300, "top_band": 140}
# --profile: a video type whose measured grammar differs from the default. "speaker": speaker-led Shorts keep the
# speaker on screen nearly all the time and change picture with zooms and a list or proof layer, not by rotating
# layouts, so two face scenes in a row are allowed (the "look the same" check still applies), three distinct layouts
# are enough and a mostly-face cut is fine. "layered": a busy style with stacked cards and notes behind the presenter,
# so more lines may share a frame, and a small "AI avatar" / "AI voice" disclosure tag counts as a label.
PROFILES = {"speaker": {"limits": {"face_min": 0.75, "face_max": 1.01, "stale_fail": 8.0},
                        "variety_max": 3, "repeat_faces": True},
            "layered": {"limits": {"wall": 14, "face_min": 0.50, "face_max": 0.85, "face_over": "WARN"},
                        "labels": (r"a[il1|]\s*avatar", r"a[il1|]\s*voice")}}  # OCR reads "AI" as "Al"


def bin_dir():
    d = HERE / ".bin"
    try:
        d.mkdir(exist_ok=True)
        (d / ".w").touch()
        return d
    except OSError:
        d = Path.home() / ".cache" / "shorts-motion" / "bin"
        d.mkdir(parents=True, exist_ok=True)
        return d


def probe_bin():
    """The compiled Vision probe, or None (not macOS, or no swiftc): the text and face rules are then skipped."""
    if platform.system() != "Darwin" or not shutil.which("swiftc"):
        return None
    dst = bin_dir() / "vision_probe"
    if not dst.exists() or dst.stat().st_mtime < PROBE_SRC.stat().st_mtime:
        r = subprocess.run(["swiftc", "-O", str(PROBE_SRC), "-o", str(dst)], capture_output=True, text=True)
        if r.returncode:
            print(f"note: could not compile the Vision probe ({r.stderr.strip()[:200]})", file=sys.stderr)
            return None
    return str(dst)


def vision(paths, exe):
    """Probe results by image path. Any failed analysis stops the critic: missing faces or text must never pass."""
    r = subprocess.run([exe, *map(str, paths)], capture_output=True, text=True)
    res = {d["image"]: d for d in map(json.loads, r.stdout.splitlines())}
    bad = [f"{Path(k).name}: {v['error']}" for k, v in res.items() if v.get("error")] + \
          [f"{Path(p).name}: no result" for p in map(str, paths) if p not in res]
    if r.returncode or bad:
        sys.exit("vision_probe failed, so frames were not analysed: " + "; ".join(bad or [r.stderr.strip()[:300]]))
    return res


def blind(img):
    """What the frame rules see without the probe: no text, no faces, no person mask."""
    return {"w": img.width, "h": img.height, "faces": [], "text": [], "person": None, "blind": True}


def duration(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True)
    return float(r.stdout)


def detect_scenes(video, dur):
    """No plan: cut wherever ffmpeg's scene score jumps (hard cuts are the default, so this finds them)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "select='gt(scene,0.32)',showinfo", "-an",
                        "-f", "null", "-"], capture_output=True, text=True)
    cuts = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    edges = [0.0] + [c for c in cuts if 0.4 < c < dur - 0.4] + [dur]
    return [{"scene": i, "mode": "?", "start": a, "end": b, "at": ""} for i, (a, b) in enumerate(zip(edges, edges[1:]))]


def grab(video, t, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(dst)], check=True)
    return dst


def picture_changes(video, thresh):
    """Times where the picture changes (hard cut, jump cut, punch-in): ffmpeg's scene score over thresh, frame to frame
    and again on frames 1/3 s apart, so a change spread over several frames (a 0.3 s page wipe, a dissolve) counts
    too: frame to frame it never crosses the threshold."""
    out = []
    for vf in ("", "fps=3,"):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", f"{vf}select='gte(scene,0)',metadata=print:key=lavfi.scene_score",
                            "-an", "-f", "null", "-"], capture_output=True, text=True)
        t = None
        for line in r.stderr.splitlines():
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                t = float(m.group(1))
            m = re.search(r"scene_score=([\d.]+)", line)
            if m and t is not None and float(m.group(1)) > thresh:
                out.append(t)
    out.sort()
    return [t for k, t in enumerate(out) if k == 0 or t - out[k - 1] > 0.2]


def void_fraction(img, person=None, empty_boxes=()):
    """Largest empty region as a fraction of the frame. Blur first so film grain and noise are not 'detail'; person
    cells (vision_probe's 36x64 grid, same as this one) and the platform-UI bands are never empty; empty_boxes
    (the caption, as frame fractions x, y, w, h) always are. An opening (erode 2 cells, dilate 2) removes thin strips."""
    g = img.convert("L").resize((180, 320)).filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(g, dtype=np.float32)
    cell = 5
    rows, cols = a.shape[0] // cell, a.shape[1] // cell
    flat = np.zeros((rows, cols), bool)
    protected = np.zeros((rows, cols), bool)  # the presenter and the platform bands: never empty, not even under a caption
    for r in range(rows):
        for c in range(cols):
            blk = a[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell]
            gy, gx = np.abs(np.diff(blk, axis=0)).max(), np.abs(np.diff(blk, axis=1)).max()
            y0, y1 = r * cell * 6, (r + 1) * cell * 6  # grid row in 1920-px frame coordinates
            in_ui = y1 > 1920 - LIMITS["ui_band"] or y0 < LIMITS["top_band"]  # platform UI covers it: never "empty"
            protected[r, c] = in_ui or bool(person and person[r][c] == "1")
            flat[r, c] = blk.std() < 2.2 and max(gx, gy) < 4 and not protected[r, c]
    for bx in empty_boxes:
        c0, c1 = int(bx["x"] * cols), int(math.ceil((bx["x"] + bx["w"]) * cols))
        r0, r1 = int(bx["y"] * rows), int(math.ceil((bx["y"] + bx["h"]) * rows))
        flat[max(0, r0):min(rows, r1), max(0, c0):min(cols, c1)] = True
    flat &= ~protected  # a caption over the presenter's shirt must not join empty regions through them

    def shift_all(m, op, pad):
        out = m.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sh = np.pad(m, 1, constant_values=pad)[1 + dy:1 + dy + rows, 1 + dx:1 + dx + cols]
                out = op(out, sh)
        return out
    op = flat
    for _ in range(2):
        op = shift_all(op, np.logical_and, True)   # erode (the frame edge counts as empty)
    for _ in range(2):
        op = shift_all(op, np.logical_or, False)   # dilate back
    op &= flat
    seen, best = np.zeros_like(op), 0
    for r in range(rows):
        for c in range(cols):
            if op[r, c] and not seen[r, c]:
                stack, n = [(r, c)], 0
                seen[r, c] = True
                while stack:
                    y, x = stack.pop()
                    n += 1
                    for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                        if 0 <= yy < rows and 0 <= xx < cols and op[yy, xx] and not seen[yy, xx]:
                            seen[yy, xx] = True
                            stack.append((yy, xx))
                best = max(best, n)
    return best / (rows * cols)


def signature(img):
    a = np.asarray(img.convert("L").resize((27, 48)), dtype=np.float32)
    a = a - a.mean()
    return a / (np.linalg.norm(a) + 1e-6)


def disclosure_re(profile=None):
    """The label pattern: the DISCLOSURE words plus the profile's own label regexes (layered: the AI tag)."""
    extra = PROFILES.get(profile or "", {}).get("labels", ())
    if not extra:
        return DISCLOSURE
    return re.compile(DISCLOSURE.pattern[:-3] + "|" + "|".join(extra) + r")\b", re.I)


def frame_findings(v, img, allow, face=True, cap_y=None, noise_px=0, L=None, labels=DISCLOSURE):
    """Frame rules on one probed frame -> (findings [(level, code, detail)], void, face height, worst level).
    face: the layout shows the presenter (HEAD applies); cap_y: the caption card on screen (centre y, its words) from
    the plan, None when no card is up, or False when there is no plan. L: the limits (LIMITS merged with the
    profile's); labels: the disclosure-label pattern (disclosure_re)."""
    L = L or LIMITS
    H = v["h"]
    out = []
    lines = [t for t in v["text"] if t["conf"] >= 0.5 and len(t["s"].strip()) > 1]
    if cap_y is False:
        cap = [t for t in lines if t["box"]["h"] * H >= 90 and 0.5 <= t["box"]["y"] <= 0.8]  # the burned-in caption
    elif cap_y is None:
        cap = []
    else:
        # the caption is the OCR line near the card's y whose words are the card's words; graphic text at that
        # height is still graphic text (checked for size and collision), not caption
        cy, cwords = cap_y

        def mid(t):
            return (t["box"]["y"] + t["box"]["h"] / 2) * H

        def is_caption(t):
            toks = [re.sub(r"[^a-z0-9]", "", x.lower()) for x in t["s"].split()]
            toks = [x for x in toks if x]
            return toks and sum(x in cwords for x in toks) / len(toks) >= 0.6
        cap = [t for t in lines if abs(mid(t) - cy) < 110 and is_caption(t)]
    rest = [t for t in lines if t not in cap]
    pad = 20 / 1920
    vf = void_fraction(img, v.get("person"), [dict(x=c["box"]["x"] - pad, y=c["box"]["y"] - pad, w=c["box"]["w"] + 2 * pad,
                                                   h=c["box"]["h"] + 2 * pad) for c in cap])
    if vf > L["void_fail"] and "VOID" not in allow:
        out.append(("FAIL", "VOID", f"{vf:.0%} of the frame is one empty region"))
    elif vf > L["void_warn"] and "VOID" not in allow:
        out.append(("WARN", "VOID", f"{vf:.0%} empty region"))
    for t in rest:
        if len(t["s"].replace(" ", "")) <= 3:  # a fragment mid-typing reads low; too short to size
            continue
        if t["box"]["h"] * H < noise_px:  # full-frame presenter: tiny "text" is the set (book spines), not a graphic
            continue
        px = t["box"]["h"] * H
        if labels.match(re.sub(r"^[^A-Za-z0-9]+", "", t["s"]).strip()):  # "... demo: file" is a label too
            if px < L["text_label"] and "TEXT" not in allow:
                out.append(("FAIL", "TEXT", f"label {t['s'][:28]!r} {px:.0f}px"))
        elif px < L["text_fail"] and "TEXT" not in allow:
            out.append(("FAIL", "TEXT", f"{t['s'][:28]!r} {px:.0f}px"))
        elif px < L["text_warn"] and "TEXT" not in allow:
            out.append(("WARN", "TEXT", f"{t['s'][:28]!r} {px:.0f}px"))
    if len(rest) > L["wall"] and "WALL" not in allow:
        out.append(("FAIL", "WALL", f"{len(rest)} lines of text besides the caption"))
    for c in ([] if "COLLIDE" in allow else cap):  # a documented exception (e.g. a code wall under the caption)
        cy0, cy1 = c["box"]["y"] * H - 16, (c["box"]["y"] + c["box"]["h"]) * H + 16
        for t in rest:
            y0, y1 = t["box"]["y"] * H, (t["box"]["y"] + t["box"]["h"]) * H
            if y0 < cy1 and y1 > cy0:
                out.append(("FAIL", "COLLIDE", f"{t['s'][:24]!r} touches the caption"))
                break
    faces = sorted(v["faces"], key=lambda f: -f["h"])
    if faces and face and "HEAD" not in allow:
        fh = faces[0]["h"]
        if fh < L["head_fail"]:
            out.append(("FAIL", "HEAD", f"face {fh:.0%} of the frame height"))
        elif fh < L["head_warn"] and vf > L["void_warn"]:
            out.append(("WARN", "HEAD", f"small face ({fh:.0%}) with empty space around it"))
    worst = max([{"FAIL": 2, "WARN": 1}[lv] for lv, _, _ in out], default=0)
    return out, vf, (faces[0]["h"] if faces else 0.0), worst


def caption_at(caps, t):
    """The caption card on screen at t: (centre y, set of its normalised words); None when no card is up; False
    without caption data."""
    if caps is None:
        return False
    for c in caps["cards"]:
        if c["start"] <= t < c["end"]:
            words = {re.sub(r"[^a-z0-9]", "", str(w["t"]).lower()) for w in c["words"]}
            return float(c.get("y", caps.get("y_center") or 1280)), words - {""}
    return None


def critique(video, plan_path=None, out_dir=None, profile=None, use_probe=True):
    video = Path(video).resolve()
    if not video.exists():
        sys.exit(f"no such video: {video}")
    out_dir = Path(out_dir or video.with_suffix("").as_posix() + "-critic")
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    dur = duration(video)
    plan = json.loads(Path(plan_path).read_text()) if plan_path else None
    scenes = plan["scenes"] if plan else detect_scenes(video, dur)
    caps = plan.get("captions") if plan else None
    presenter = plan.get("presenter", True) if plan else None   # None: unknown (no plan)
    changes = picture_changes(video, LIMITS["change"])
    shots = []
    for sc in scenes:
        s, e = sc["start"], min(sc["end"], dur - 0.05)
        ts = [s + (e - s) * f for f in ((0.5,) if e - s < 1.6 else (0.25, 0.5, 0.75))]
        shots.append([(t, grab(video, t, out_dir / "frames" / f"s{sc['scene']:02d}_{t:06.2f}.png")) for t in ts])
    first_end = min(scenes[0]["end"], dur - 0.05) if scenes else dur
    opening = [(t, grab(video, t, out_dir / "frames" / f"open_{t:05.2f}.png")) for t in (0.1, min(1.4, max(0.1, first_end - 0.05)))]
    exe = probe_bin() if use_probe else None
    paths = [p for sh in shots for _, p in sh] + [p for _, p in opening]
    probes = vision(paths, exe) if exe else {str(p): blind(Image.open(p)) for p in paths}

    report = {"video": str(video), "duration": round(dur, 2), "scenes": [], "video_findings": [], "notes": [],
              "probe": "apple-vision" if exe else "none"}
    notes = report["notes"]
    if not exe:
        notes.append("no text/face probe (macOS with swiftc, or --no-probe): TEXT, WALL, HEAD, COLLIDE and the hook size were "
                     "skipped, and VOID ran without the person mask")
    prof = PROFILES.get(profile or "", {})
    L = {**LIMITS, **prof.get("limits", {})}
    labels = disclosure_re(profile)
    sigs = []
    for sc, sh in zip(scenes, shots):
        allow = set(sc.get("allow") or [])
        if allow:
            notes.append(f"scene {sc['scene']} allows {', '.join(sorted(allow))}: {sc.get('why', '(no reason given)')}")
        kind = (sc.get("layout") or sc.get("mode") or "?").split(":")[0]
        face = kind in FACE_TYPES or (kind == "?" and presenter is not False)
        f_all, worst, voids, heads = [], 0, [], []
        for t, p in sh:
            img = Image.open(p).convert("RGB")
            f, vf, fh, w = frame_findings(probes[str(p)], img, allow, face, caption_at(caps, t),
                                          noise_px=24 if kind == "avatar" else 0, L=L, labels=labels)
            fh = fh if face else 0.0
            f_all += [(lv, c, f"{d} @{t:.1f}s") for lv, c, d in f]
            worst, voids, heads = max(worst, w), voids + [vf], heads + [fh]
        mid = sh[len(sh) // 2][1]
        sigs.append(signature(Image.open(mid)))
        seen, uniq = set(), []
        for lv, c, d in f_all:  # one line per code per scene
            if (lv, c) not in seen:
                seen.add((lv, c))
                uniq.append({"level": lv, "code": c, "detail": d})
        report["scenes"].append({**{k: sc.get(k) for k in ("scene", "mode", "layout", "bg", "start", "end", "at")},
                                 "keyframe": str(mid), "void": round(max(voids), 3), "face_h": round(max(heads), 3),
                                 "allow": sorted(allow), "why": sc.get("why"), "findings": uniq})

    vfind = report["video_findings"]
    report["profile"] = profile or "default"
    kinds = [sc.get("layout") or sc.get("mode") or "?" for sc in scenes]
    for i in range(1, len(scenes)):
        if kinds[i] == kinds[i - 1] and kinds[i] != "?" and not (prof.get("repeat_faces") and kinds[i].split(":")[0] in FACE_TYPES):
            vfind.append({"level": "FAIL", "code": "REPEAT", "detail": f"scenes {i - 1} and {i} are both {kinds[i]}"})
        sim = float((sigs[i] * sigs[i - 1]).sum())
        if sim > LIMITS["same_look"]:
            vfind.append({"level": "FAIL", "code": "REPEAT", "detail": f"scenes {i - 1} and {i} look the same ({sim:.2f})"})
    if plan:
        want = min(prof.get("variety_max", 5), len(scenes) // 2 + 1)
        if len(set(kinds)) < want:
            vfind.append({"level": "FAIL", "code": "VARIETY", "detail": f"{len(set(kinds))} distinct layouts ({', '.join(sorted(set(kinds)))}); need {want}"})
        runtime = {}
        for k, sc in zip(kinds, scenes):
            runtime[k] = runtime.get(k, 0) + sc["end"] - sc["start"]
        for k, t in runtime.items():
            if k.split(":")[0] not in FACE_TYPES and t / dur > L["hog"]:
                vfind.append({"level": "FAIL", "code": "HOG", "detail": f"{k} fills {t / dur:.0%} of the runtime"})
    if plan:
        face_t = sum(sc["end"] - sc["start"] for sc, k in zip(scenes, kinds) if k.split(":")[0] in FACE_TYPES)
    else:
        face_t = sum(sc["end"] - sc["start"] for sc, r in zip(scenes, report["scenes"]) if r["face_h"] > 0)
        if face_t == 0:
            presenter = False  # no plan and no face anywhere: a graphics-only cut
    if presenter is False:
        notes.append("no presenter in this video: FACE skipped")
    elif not plan and not exe:
        notes.append("no plan and no probe: FACE skipped")
    elif face_t / dur < L["face_min"]:
        vfind.append({"level": "FAIL", "code": "FACE", "detail": f"presenter on screen {face_t / dur:.0%} of the runtime; needs {L['face_min']:.0%}"})
    elif face_t / dur > L["face_max"]:
        vfind.append({"level": L.get("face_over", "WARN"), "code": "FACE",
                      "detail": f"presenter on screen {face_t / dur:.0%} of the runtime; the most is {L['face_max']:.0%}"})
    open_allowed = "OPEN" in set(scenes[0].get("allow") or []) if scenes else False
    open_kind = (kinds[0] if scenes else "?").split(":")[0]
    v0 = probes[str(opening[0][1])]
    hook = max((t["box"]["h"] * v0["h"] for t in v0["text"] if t["conf"] >= 0.5 and len(t["s"].strip()) > 1), default=0)
    if open_allowed:
        pass
    elif not exe:
        if presenter is not False and plan and open_kind not in FACE_TYPES:
            vfind.append({"level": "WARN", "code": "OPEN", "detail": f"opens on {open_kind}, not the presenter; the hook "
                          "size was not measured (no probe): check by eye that frame 0 is a visual hook"})
        elif presenter is False:
            notes.append("OPEN: the hook size was not measured (no probe); check by eye that frame 0 carries the hook in big type")
    elif presenter is False:
        if hook < L["hook_px"]:
            vfind.append({"level": "FAIL", "code": "OPEN", "detail": f"opens without the hook in big type (largest line "
                          f"{hook:.0f} px at 0.1 s; needs {L['hook_px']} px): put the hook on the first frame"})
    else:
        no_face = [t for t, p in opening if not probes[str(p)]["faces"]]
        if no_face or (plan and open_kind not in FACE_TYPES):
            why = f"the first scene is {open_kind}" if plan and open_kind not in FACE_TYPES else \
                  "no face at " + ", ".join(f"{t:.1f} s" for t in no_face)
            if hook < L["hook_px"]:
                vfind.append({"level": "FAIL", "code": "OPEN", "detail": f"opens without the presenter ({why}) and without "
                              f"the hook in big type (largest line {hook:.0f} px); open on them, or put a visual hook on it"})
            else:
                vfind.append({"level": "WARN", "code": "OPEN", "detail": f"opens without the presenter ({why}): check it is "
                              f"a visual hook (a striking image, a move onto the key thing, a blur-to-sharp reveal), not a plain screen"})
    for sc in scenes:
        marks = [sc["start"]] + [c for c in changes if sc["start"] + 0.05 < c < sc["end"] - 0.05] + [sc["end"]]
        gap, at = max((b - a, a) for a, b in zip(marks, marks[1:]))
        if gap > L["stale_fail"]:
            vfind.append({"level": "FAIL", "code": "STALE", "detail": f"scene {sc['scene']}: {gap:.1f} s with no picture change from {at:.1f} s"})
        elif gap > L["stale_warn"]:
            vfind.append({"level": "WARN", "code": "STALE", "detail": f"scene {sc['scene']}: {gap:.1f} s with no picture change from {at:.1f} s"})

    # the slideshow check (motion_gate.py): how the cut moves, from the MP4 alone; DRIFT, PUSH, DEAD warn, BLANK fails
    try:
        sys.path.insert(0, str(HERE))
        import motion_gate
        m = motion_gate.measure(video)
        report["motion"] = {k: v for k, v in m.items() if not k.startswith("_")}
        vfind.extend(motion_gate.findings(m, prof.get("motion")))
    except Exception as e:  # noqa: BLE001  (a missing library must not stop the rest of the critic)
        vfind.append({"level": "WARN", "code": "MOTION", "detail": f"the motion check did not run: {str(e)[:140]}"})

    fails = sum(f["level"] == "FAIL" for s in report["scenes"] for f in s["findings"]) + sum(f["level"] == "FAIL" for f in vfind)
    warns = sum(f["level"] == "WARN" for s in report["scenes"] for f in s["findings"]) + sum(f["level"] == "WARN" for f in vfind)
    report["result"] = "FAIL" if fails else "PASS"
    report["counts"] = {"fail": fails, "warn": warns, "scenes": len(scenes), "layouts": len(set(kinds))}
    (out_dir / "critic.json").write_text(json.dumps(report, indent=1) + "\n")
    sheet(report, out_dir / "critic-sheet.png")
    return report, out_dir


def sheet(report, dst, tw=216):
    th = round(tw * 16 / 9)
    n = len(report["scenes"])
    cols = min(6, n)
    rows = math.ceil(n / cols)
    lab_h = 92
    vf_lines = [f"{f['level']} {f['code']}: {f['detail']}" for f in report["video_findings"]]
    head = 60 + 22 * len(vf_lines)
    im = Image.new("RGB", (cols * (tw + 16) + 16, head + rows * (th + lab_h + 16)), (14, 16, 22))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(str(FONT), 15) if FONT.exists() else ImageFont.load_default()
    fb = ImageFont.truetype(str(FONT), 22) if FONT.exists() else f
    c = report["counts"]
    d.text((16, 14), f"{Path(report['video']).name}  {report['result']}  fails {c['fail']}  warns {c['warn']}  "
                     f"scenes {c['scenes']}  layouts {c['layouts']}", fill=(255, 255, 255), font=fb)
    for k, line in enumerate(vf_lines):
        d.text((16, 46 + 22 * k), line[:150], fill=(255, 120, 110) if line.startswith("FAIL") else (255, 200, 90), font=f)
    col = {0: (60, 200, 110), 1: (255, 190, 60), 2: (240, 70, 60)}
    for k, s in enumerate(report["scenes"]):
        x, y = 16 + (k % cols) * (tw + 16), head + (k // cols) * (th + lab_h + 16)
        worst = max([{"FAIL": 2, "WARN": 1}[q["level"]] for q in s["findings"]], default=0)
        d.rectangle([x - 5, y - 5, x + tw + 4, y + th + 4], fill=col[worst])
        im.paste(Image.open(s["keyframe"]).convert("RGB").resize((tw, th)), (x, y))
        kind = s.get("layout") or s.get("mode") or "?"
        d.text((x, y + th + 8), f"#{s['scene']} {kind} {s['start']:.1f}-{s['end']:.1f}s", fill=(255, 255, 255), font=f)
        for j, q in enumerate(s["findings"][:3]):
            d.text((x, y + th + 28 + 19 * j), f"{q['code']} {q['detail'][:26]}", fill=col[2 if q['level'] == 'FAIL' else 1], font=f)
    im.save(dst)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--plan", help="scene-plan.json from build.py (layouts, times, captions, allow exceptions)")
    ap.add_argument("--out", help="report folder (default: <video>-critic next to the video)")
    ap.add_argument("--profile", choices=sorted(PROFILES), help="a video type with its own measured limits (see PROFILES)")
    ap.add_argument("--no-probe", action="store_true", help="run without the text/face probe (what non-macOS systems get)")
    a = ap.parse_args()
    rep, out = critique(a.video, a.plan, a.out, a.profile, use_probe=not a.no_probe)
    for s in rep["scenes"]:
        mark = "FAIL" if any(f["level"] == "FAIL" for f in s["findings"]) else ("warn" if s["findings"] else "ok")
        kind = s.get("layout") or s.get("mode") or "?"
        print(f"  #{s['scene']:<2} {s['start']:6.2f}-{s['end']:6.2f} {kind:<10} void {s['void']:.0%} face {s['face_h']:.0%}  {mark}"
              + "".join(f"\n        {f['level']} {f['code']}: {f['detail']}" for f in s["findings"]))
    for f in rep["video_findings"]:
        print(f"  {f['level']} {f['code']}: {f['detail']}")
    for n in rep["notes"]:
        print(f"  note: {n}")
    m = rep.get("motion")
    if m:
        print(f"  motion: slow zoom {m['slow_zoom_share']:.0%}  push-ins {m['push_in_per_min']:.1f}/min  "
              f"dead flat {m['dead_flat']:.0%}  blank {m['blank_run_s']:.1f} s  shot {m['asl_s']:.1f} s")
    c = rep["counts"]
    print(f"RESULT {rep['result']}  fails {c['fail']}  warns {c['warn']}  -> {out / 'critic-sheet.png'}")
    sys.exit(1 if rep["result"] == "FAIL" else 0)


if __name__ == "__main__":
    main()
