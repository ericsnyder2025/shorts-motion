#!/usr/bin/env python3
"""scenes.json -> a HyperFrames project -> (optionally) a rendered 1080x1920 MP4, timed to the spoken words.

    python3 scripts/build.py scenes.json --validate                         # check the spec only
    python3 scripts/build.py scenes.json --out build/my-short               # write the project, run `hyperframes check`
    python3 scripts/build.py scenes.json --out build/my-short --render build/my-short.mp4

Then run the critic on the MP4 with the plan this writes (<out>/scene-plan.json):

    python3 scripts/critic.py build/my-short.mp4 --plan build/my-short/scene-plan.json

scenes.json (paths are relative to its own folder; the full schema is in SKILL.md and references/layouts.md):
{
  "id": "my-short",
  "theme": "theme.json",                       optional; default: the skill's theme.json
  "voice": "voice.wav",                        the narration (or leave it out and use presenter.video's audio)
  "words": "words.json",                       word timings [{"w", "s", "e"}] from scripts/words.py
  "presenter": {"video": "take.mp4",           optional: a full-frame 9:16 take of someone saying the script
                "alpha": "take-alpha.webm",    the same take with the background removed (for "stack")
                "face": [0.5, 0.35]},          face centre as frame fractions (for zoom and split framing)
  "captions": {"y": 1280, "size": 70},         optional; "off" for none
  "grade": {"saturate": 0.9},                  optional picture grade on footage only (not on graphics)
  "scenes": [                                  in order; each runs until the next one starts
    {"at": "The first two", "mode": "graphic", "bg": {"type": "kinetic", "text": "..."}},
    {"at": "Here is", "mode": "avatar", "zoom": 1.15},
    ...
  ]
}
Modes: graphic (a full-frame layout from graphics.py) | cutaway (a full-frame image, video or code file) | avatar
(the presenter take full frame, "zoom" 1.0-1.4 around the face) | split (the presenter full-width in one half, a panel
in the other: "presenter" top|bottom, "seam" px, "bg" a panel graphic or image/video/code, optional "headline") |
stack (the cut-out presenter over an image/video/code background, "dim" 0-1).
A scene may set "captions": default|move|seam|top|off (+ "caption_y") and "allow": ["VOID", ...] with a "why" for
the critic. Each "at" phrase starts its scene on that spoken word. Scene changes are hard cuts.
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import graphics  # noqa: E402
from graphics import SpecError, r3, norm  # noqa: E402

HF = "hyperframes@0.8.79"
GSAP_VERSION = "3.14.2"
GSAP_URL = f"https://cdn.jsdelivr.net/npm/gsap@{GSAP_VERSION}/dist/gsap.min.js"
W, H, FPS = 1080, 1920, 30
MODES = {"graphic", "cutaway", "avatar", "split", "stack"}
FACE_MODES = {"avatar", "split", "stack"}
BG_TYPES = {"image", "video", "code"}
CAPTION_MODES = {"default", "move", "seam", "top", "off"}
ALLOW_CODES = {"VOID", "TEXT", "WALL", "HEAD", "COLLIDE", "OPEN"}  # the per-scene rules a scene may be excused from
PY_KW = r"\b(def|return|for|in|if|elif|else|import|from|not|and|or|raise|with|as|None|True|False|lambda|try|except|continue|break|while|class|yield)\b"


def frame(t):
    return round(round(t * FPS) / FPS, 3)


def load_json(p):
    return json.loads(Path(p).read_text())


# ------------------------------------------------------------------ validation

def validate(spec, base=None):
    """Every problem with a spec, as readable lines (empty: it builds). base: the spec's folder, to check files."""
    p = []
    scenes = spec.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return ["scenes: a non-empty list is required"]
    pres = spec.get("presenter") or {}
    if not spec.get("words"):
        p.append("words: the word timings file is required (python3 scripts/words.py say|transcribe ...)")
    if not spec.get("voice") and not pres.get("video"):
        p.append("voice: an audio file is required (or presenter.video, whose audio is then the voice)")
    caps = spec.get("captions", {})
    if caps != "off" and not isinstance(caps, dict):
        p.append('captions: an object like {"y": 1280, "size": 70} or "off"')
    elif isinstance(caps, dict) and not 44 <= int(caps.get("size", 70)) <= 110:
        p.append("captions.size: 44-110 px (the critic fails text under 40 px)")
    files = [("voice", spec.get("voice")), ("words", spec.get("words")), ("theme", spec.get("theme")),
             ("presenter.video", pres.get("video")), ("presenter.alpha", pres.get("alpha"))]
    for i, sc in enumerate(scenes):
        where = f"scene {i}"
        if not isinstance(sc, dict):
            p.append(f"{where}: must be an object")
            continue
        mode = sc.get("mode")
        if mode not in MODES:
            p.append(f"{where}: mode must be one of {', '.join(sorted(MODES))} (got {mode!r})")
            continue
        if i and not str(sc.get("at") or "").strip():
            p.append(f'{where}: "at" (the spoken words that start it) is required')
        bg = sc.get("bg") or {}
        t = bg.get("type")
        if mode == "graphic" and t not in graphics.RENDERERS:
            p.append(f"{where}: a graphic needs bg.type from {', '.join(sorted(graphics.RENDERERS))} (got {t!r})")
        elif mode in ("cutaway", "stack") and t not in BG_TYPES:
            p.append(f"{where}: {mode} needs bg.type image, video or code (got {t!r})")
        elif mode == "split" and t not in BG_TYPES | graphics.PANEL_TYPES:
            p.append(f"{where}: a split panel takes {', '.join(sorted(BG_TYPES | graphics.PANEL_TYPES))} (got {t!r})")
        if mode == "avatar" and not pres.get("video"):
            p.append(f"{where}: avatar needs presenter.video")
        if mode == "split" and not (pres.get("video") or pres.get("alpha")):
            p.append(f"{where}: split needs presenter.video (or presenter.alpha)")
        if mode == "stack" and not pres.get("alpha"):
            p.append(f"{where}: stack needs presenter.alpha (the take with its background removed)")
        if mode in ("avatar", "split") and "zoom" in sc and not 1.0 <= float(sc["zoom"]) <= 1.4:
            p.append(f"{where}: zoom must be 1.0-1.4 (above that the take goes soft)")
        p += [f"{where}: {x}" for x in layout_problems(t, bg)]
        for key in ("src", "plate", "file"):
            if bg.get(key):
                files.append((f"{where} bg.{key}", bg[key]))
        for half in ("top", "bottom"):
            if isinstance(bg.get(half), dict) and bg[half].get("plate"):
                files.append((f"{where} bg.{half}.plate", bg[half]["plate"]))
        if sc.get("captions") is not None and sc["captions"] not in CAPTION_MODES:
            p.append(f"{where}: captions must be one of {', '.join(sorted(CAPTION_MODES))}")
        allow = sc.get("allow") or []
        if allow:
            bad = [c for c in allow if c not in ALLOW_CODES]
            if bad:
                p.append(f"{where}: allow takes {', '.join(sorted(ALLOW_CODES))} (got {', '.join(map(str, bad))})")
            if not str(sc.get("why") or "").strip():
                p.append(f'{where}: an "allow" exception needs a "why" (the reason is printed in every critic report)')
    if base is not None:
        for what, rel in files:
            if rel and not (Path(base) / rel).exists():
                p.append(f"{what}: {rel!r} not found next to the spec")
    return p


def layout_problems(t, bg):
    """Missing or malformed fields for one bg type."""
    out = []
    if t in graphics.REQUIRED:
        out += [f'{t} needs "{f}"' for f in graphics.REQUIRED[t] if f not in bg]
    if t in graphics.ITEM_FIELDS and isinstance(bg.get(graphics.ITEM_FIELDS[t][0]), (list, type(None))):
        key, field = graphics.ITEM_FIELDS[t]
        items = bg.get(key) or []
        if key in bg and not items:
            out.append(f"{t}.{key} must not be empty")
        out += [f'{t}.{key}[{k}] needs "{field}"' for k, it in enumerate(items) if not isinstance(it, dict) or not it.get(field)]
    elif t in graphics.ITEM_FIELDS and graphics.ITEM_FIELDS[t][0] in bg:
        out.append(f"{t}.{graphics.ITEM_FIELDS[t][0]} must be a list")
    if t in ("kinetic", "quote") and "text" in bg and not str(bg["text"]).split():
        out.append(f"{t}.text must not be empty")
    if t == "stat" and "value" in bg:
        try:
            float(bg["value"])
        except (TypeError, ValueError):
            out.append("stat.value must be a number")
    if t == "compare":
        for half in ("top", "bottom"):
            h = bg.get(half)
            if half in bg and (not isinstance(h, dict) or not h.get("label") or not h.get("text")):
                out.append(f'compare.{half} needs "label" and "text"')
    if t == "pages":
        pg = bg.get("pages")
        if "pages" in bg and (not isinstance(pg, list) or not 1 <= len(pg) <= 6):
            out.append("pages.pages must be a list of 1-6 pages")
        for k, page in enumerate(pg if isinstance(pg, list) else []):
            if not isinstance(page, dict) or not (str(page.get("text") or "").split() or (page.get("number") or {}).get("value") is not None):
                out.append(f'pages.pages[{k}] needs "text" (or "number": {{"value"}})')
    if t in ("image", "video") and not bg.get("src"):
        out.append(f'{t} needs "src"')
    if t == "code" and not bg.get("file"):
        out.append('code needs "file"')
    return out


# ------------------------------------------------------------------ timing

def anchor_times(scenes, words):
    """Start of each scene: scene 0 at 0, every other one on the first word of its "at" phrase (after the previous
    scene's), 30 ms early so the cut lands just before the word."""
    toks = [(norm(w["w"]), w["s"]) for w in words if norm(w["w"])]
    out, after = [], -1.0
    for i, sc in enumerate(scenes):
        if i == 0 and not str(sc.get("at") or "").strip():
            out.append(0.0)
            continue
        want = [norm(x) for x in sc["at"].split() if norm(x)]
        hit = None
        for j in range(len(toks) - len(want) + 1):
            if toks[j][1] > after and [k for k, _ in toks[j:j + len(want)]] == want:
                hit = toks[j][1]
                break
        if hit is None:
            raise SpecError(f"scene {i}: phrase {sc['at']!r} not found after {max(after, 0):.2f} s in the word timings")
        out.append(0.0 if i == 0 else frame(max(hit - 0.03, 0.0)))
        after = hit
    return out


def caption_cards(words, plan, dur, opts):
    """Word captions: short one-line cards (up to max_words) broken at punctuation, pauses and scene changes, each
    placed by its scene's caption mode; scenes with captions "off" (kinetic type) get none."""
    size, max_words, dy = int(opts.get("size", 70)), int(opts.get("max_words", 3)), int(opts.get("y", 1280))
    f = graphics.font(size, "body", 900)
    width = W - 2 * 100

    def scene_of(t):
        for e in plan:
            if t < e["end"] - 1e-6:
                return e
        return plan[-1]
    groups, cur = [], []
    for w in words:
        if not norm(w["w"]):
            continue
        if cur:
            prev = cur[-1]
            trial = " ".join(x["w"] for x in cur + [w])
            if (len(cur) >= max_words or scene_of(prev["s"]) is not scene_of(w["s"]) or w["s"] - prev["e"] > 0.35
                    or re.search(r"[.!?,;:]$", prev["w"]) or f.getlength(trial) > width):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    cards = []
    for k, grp in enumerate(groups):
        e = scene_of(grp[0]["s"])
        mode = e.get("captions", "default")
        if mode == "off":
            continue
        y = dy if mode == "default" else (300 if mode == "top" else int(e.get("caption_y", dy)))
        start = max(e["start"], grp[0]["s"] - 0.05)
        nxt = groups[k + 1][0]["s"] - 0.05 if k + 1 < len(groups) else dur
        end = min(nxt, grp[-1]["e"] + 0.5, e["end"], dur)
        if end - start < 0.12:
            continue
        cards.append({"start": r3(start), "end": r3(end), "y": y,
                      "words": [{"t": x["w"], "s": r3(x["s"]), "e": r3(x["e"])} for x in grp]})
    return cards


def captions_html(cards, size, gctx):
    out = []
    text, signal = gctx.col["text"], gctx.col["signal"]
    for k, c in enumerate(cards):
        spans = []
        for j, w in enumerate(c["words"]):
            spans.append(f'<span id="cw{k}_{j}">{html.escape(w["t"])}</span>')
            t = max(c["start"], w["s"] - 0.02)  # the word being said lights up in the signal colour
            gctx.ft(f"#cw{k}_{j}", {"color": text}, {"color": signal, "duration": 0.06, "ease": "none"}, t)
            if j + 1 < len(c["words"]):
                gctx.ft(f"#cw{k}_{j}", {"color": signal}, {"color": text, "duration": 0.06, "ease": "none"},
                        max(t + 0.07, c["words"][j + 1]["s"] - 0.02))
        gctx.ft(f"#ci{k}", {"scale": 0.9, "opacity": 0}, {"scale": 1, "opacity": 1, "duration": 0.1, "ease": "power2.out"}, c["start"])
        out.append(f'<div id="cap{k}" class="clip cap" data-start="{c["start"]}" data-duration="{r3(c["end"] - c["start"])}" data-track-index="8" '
                   f'style="top:{c["y"] - round(size * 0.62)}px"><div class="capin" id="ci{k}" style="font-size:{size}px">'
                   f'{" ".join(spans)}</div></div>')
    return out


def probe_duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


# ------------------------------------------------------------------ project

class Stage:
    """Copies each referenced file into <out>/assets once and returns its project-relative path."""

    def __init__(self, out):
        self.dir = out / "assets"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen = {}

    def add(self, src, name=None):
        src = Path(src).resolve()
        if not src.exists():
            raise SpecError(f"missing file: {src}")
        if src not in self.seen:
            dst = self.dir / (name or src.name)
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime or dst.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dst)
            self.seen[src] = f"assets/{dst.name}"
        return self.seen[src]


def gsap_src(stage, notes):
    """GSAP is not shipped with this repo (it has its own licence, gsap.com/standard-license): the first build
    downloads the pinned version into ~/.cache/shorts-motion and copies it into the project; offline, the page loads
    it from the CDN at render time."""
    cache = Path.home() / ".cache" / "shorts-motion" / f"gsap-{GSAP_VERSION}.min.js"
    if not cache.exists():
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(GSAP_URL, timeout=30) as r:
                data = r.read()
            if b"GSAP" not in data[:400]:
                raise ValueError("unexpected file")
            cache.write_bytes(data)
        except Exception as e:  # noqa: BLE001
            notes.append(f"GSAP could not be cached ({str(e)[:80]}); the page loads it from {GSAP_URL}")
            return GSAP_URL
    return stage.add(cache, "gsap.min.js")


def highlight(line):
    code, _, comment = line.partition("#") if not re.search(r"[\"'].*#.*[\"']", line) else (line, "", "")
    parts = re.split(r"(\"[^\"]*\"|'[^']*')", code)
    out = []
    for k, p in enumerate(parts):
        e = html.escape(p)
        if k % 2:
            out.append(f'<span class="s">{e}</span>')
        else:
            e = re.sub(PY_KW, r'<span class="k">\1</span>', e)
            e = re.sub(r"(?<![\w#])(\d+(\.\d+)?)", r'<span class="n">\1</span>', e)
            out.append(e)
    if comment:
        out.append(f'<span class="c">#{html.escape(comment)}</span>')
    return "".join(out) or " "


def bg_html(i, bg, S, D, stage, base, tweens, notes):
    """A full-frame image, video or scrolling code file (cutaway and stack backgrounds, split panels)."""
    kind = bg["type"]
    if kind in ("video", "image"):
        path = base / bg["src"]
        src = stage.add(path)
        push = float(bg.get("push", 1.0))  # off by default: slow uniform zoom is what the motion check warns about
        if push != 1.0:
            tweens.append(["ft", f"#w{i}", {"scale": 1}, {"scale": push, "duration": D, "ease": "none"}, S])
        if kind == "video":
            dur = probe_duration(path)
            if dur and dur < D - 0.05:
                notes.append(f"scene {i}: clip {bg['src']} is {dur:.2f} s but the scene runs {D:.2f} s; its last frame will hold")
            el = (f'<video id="bg{i}" class="clip media" src="{src}" muted playsinline data-start="{S}" '
                  f'data-duration="{D}" data-media-start="{r3(bg.get("media_start", 0))}" data-track-index="1"></video>')
        else:
            el = f'<img id="bg{i}" class="clip media" src="{src}" alt="" data-start="{S}" data-duration="{D}" data-track-index="1" />'
        return f'<div class="wrap" id="w{i}" style="z-index:1">{el}</div>'
    if kind == "code":
        a, b = bg.get("lines", [1, 80])
        lines = (base / bg["file"]).read_text().splitlines()[a - 1:b]
        wrap = bool(bg.get("wrap"))  # terminal transcripts: wrap long lines, drop line numbers
        rows = "".join('<div class="ln">' + ("" if wrap else f'<span class="no">{a + k}</span>') + f'{highlight(ln)}</div>'
                       for k, ln in enumerate(lines))
        speed = bg.get("speed", 260)
        tweens.append(["ft", f"#cs{i}", {"y": 0}, {"y": -r3(speed * D), "duration": D, "ease": "none"}, S])
        title = html.escape(bg.get("title", Path(bg["file"]).name))
        fpx = int(bg.get("font_px", 34))
        return (f'<div id="bg{i}" class="clip code" data-start="{S}" data-duration="{D}" data-track-index="1" style="z-index:1">'
                f'<div class="codebar"><i></i><i></i><i></i><b>{title}</b></div>'
                f'<div class="codeview"><div id="cs{i}" class="codescroll{" wrap" if wrap else ""}" '
                f'style="font-size:{fpx}px;line-height:{round(fpx * 1.6)}px">{rows}</div></div></div>')
    raise SpecError(f"scene {i}: unknown background type {kind!r}")


EVIDS = 'video[id^="av"], video[id^="ev"], video[id^="ax"], video[id^="bg"]'  # presenter takes + clips


def grade_css(g):
    """A picture grade on the footage only (presenter takes and clips; graphics keep the theme colours as designed).
    g: {"mono": true} for black and white, or {"saturate", "brightness", "contrast"}."""
    if not g:
        return ""
    sat = 0.0 if g.get("mono") else float(g.get("saturate", 1))
    bri, con = float(g.get("brightness", 1)), float(g.get("contrast", 1.08 if g.get("mono") else 1))
    if not (0 <= sat <= 1.3 and 0.6 <= bri <= 1.2 and 0.8 <= con <= 1.4):
        raise SpecError(f"grade out of range: saturate 0-1.3, brightness 0.6-1.2, contrast 0.8-1.4 (got {g})")
    return f"{EVIDS} {{ filter: saturate({sat}) brightness({bri}) contrast({con}); }}"


def build(spec_path, out):
    spec_path = Path(spec_path).resolve()
    base = spec_path.parent
    spec = load_json(spec_path)
    problems = validate(spec, base)
    if problems:
        raise SpecError("the spec has problems:\n  " + "\n  ".join(problems))
    theme = graphics.load_theme(base / spec["theme"] if spec.get("theme") else None)
    graphics.use_theme(theme)
    col = theme["colors"]
    pres = spec.get("presenter") or {}
    words = load_json(base / spec["words"])
    voice_src = base / (spec.get("voice") or pres["video"])
    dur = frame(probe_duration(voice_src) or 0)
    if dur <= 0:
        raise SpecError(f"could not read the length of {voice_src.name} (is ffprobe installed?)")
    scenes = spec["scenes"]
    starts = anchor_times(scenes, words)
    ends = starts[1:] + [dur]

    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stage = Stage(out)
    video = stage.add(base / pres["video"], "presenter" + Path(pres["video"]).suffix) if pres.get("video") else None
    alpha = stage.add(base / pres["alpha"], "presenter-alpha" + Path(pres["alpha"]).suffix) if pres.get("alpha") else None
    voice = stage.add(voice_src, "voice" + voice_src.suffix) if spec.get("voice") else video
    tweens, notes, plan, layers = [], [], [], []
    gsap = gsap_src(stage, notes)
    fonts = {r: stage.add(theme["fonts"][r]["file"]) for r in ("display", "body")}
    fx, fy = (pres.get("face") or [0.5, 0.35])[:2]
    gctx = graphics.Ctx(stage, base, col, tweens, notes, words)
    for i, (sc, S, E) in enumerate(zip(scenes, starts, ends)):
        S, D = r3(S), r3(E - S)
        if D <= 0:
            raise SpecError(f"scene {i} ({sc.get('at')!r}) has no length: two anchors resolve to the same time")
        mode = sc["mode"]
        btype = (sc.get("bg") or {}).get("type")
        layout = mode if mode in FACE_MODES else ("broll" if btype in ("image", "video") else btype)
        entry = {"scene": i, "mode": mode, "layout": layout, "start": r3(S), "end": r3(E), "at": sc.get("at", ""),
                 "bg": btype, "captions": "default"}
        if sc.get("allow"):
            entry.update(allow=list(sc["allow"]), why=sc["why"])
        plan.append(entry)
        if mode == "graphic":
            gh, extra = graphics.render(i, sc["bg"], S, D, r3(E), gctx)
            entry.update(extra)
            layers.append(gh)
        elif mode == "split":
            gpanel = btype in graphics.PANEL_TYPES  # a graphic in the panel: the presenter stays on screen while it reads
            top_p = sc.get("presenter", "bottom" if gpanel else "top") == "top"
            seam = int(sc.get("seam", 900 if top_p else 1000))
            ey0, ey1 = (0, seam) if top_p else (seam, H)
            py0, py1 = (seam, H) if top_p else (0, seam)
            entry.update(captions="move", caption_y=seam)
            if gpanel:
                # panel-relative box: clear of the caption band on the seam (+-130) and the platform bands
                gctx.box = (130, (H - 300) - seam) if top_p else (150, seam - 130)
                gctx.canvas_h = py1 - py0
                pb, _ = graphics.render(i, sc["bg"], S, D, r3(E), gctx)
                gctx.box, gctx.canvas_h = (graphics.TOP, graphics.BOTTOM), H
            else:
                pb = bg_html(i, sc["bg"], S, D, stage, base, tweens, notes)
            head = ""
            if sc.get("headline"):
                head = f'<div class="sphead {"low" if top_p else "high"}" id="sh{i}">{html.escape(sc["headline"])}</div>'
                tweens.append(["ft", f"#sh{i}", {"opacity": 0, "y": 40}, {"opacity": 1, "y": 0, "duration": 0.3, "ease": "power3.out"}, S])
            shade = "" if gpanel else f'<div class="panelshade {"low" if top_p else "high"}"></div>'
            # panels are untimed wrappers (HyperFrames forbids a timed <video> inside a timed element): this tween
            # hides one after its scene, the reveal below before it
            layers.append(f'<div class="panel" id="sp{i}" style="top:{py0}px;height:{py1 - py0}px">{pb}{shade}{head}</div>')
            tweens.append(["ft", f"#sp{i}", {"autoAlpha": 1}, {"autoAlpha": 0, "duration": 0.001}, r3(S + D)])
            if S > 0.05:  # a split that opens the video is the cover: no wipe, or frame 0 is half black
                tweens.append(["ft", f"#sp{i}", {"clipPath": "inset(0% 0% 100% 0%)" if top_p else "inset(100% 0% 0% 0%)"},
                               {"clipPath": "inset(0% 0% 0% 0%)", "duration": 0.3, "ease": "power3.out"}, S])
            z = float(sc.get("zoom", 1.0))
            vw, vh, ph = W * z, H * z, ey1 - ey0
            left = max(min(0.0, W / 2 - fx * vw), W - vw)
            top = max(min(0.0, ph * 0.5 - fy * vh), ph - vh)
            layers.append(f'<div class="panel pres" style="top:{ey0}px;height:{ph}px">'
                          f'<video id="ev{i}" class="clip" data-layout-allow-overflow src="{video or alpha}" muted playsinline '
                          f'data-start="{S}" data-duration="{D}" data-media-start="{S}" data-track-index="2" '
                          f'style="position:absolute;left:{left:.1f}px;top:{top:.1f}px;width:{vw:.1f}px;height:{vh:.1f}px"></video></div>')
            layers.append(f'<div id="sm{i}" class="clip seam" data-start="{S}" data-duration="{D}" data-track-index="3" style="top:{seam - 4}px"></div>')
            if S > 0.05:
                tweens.append(["ft", f"#sm{i}", {"scaleX": 0}, {"scaleX": 1, "duration": 0.35, "ease": "power3.out"}, S])
        elif mode == "avatar":
            z = float(sc.get("zoom", 1.0))
            zoom_css = f";transform:scale({z});transform-origin:{fx * 100:.1f}% {fy * 100:.1f}%" if z != 1.0 else ""
            layers.append(f'<video id="av{i}" class="clip media" src="{video}" muted playsinline data-start="{S}" '
                          f'data-duration="{D}" data-media-start="{S}" data-track-index="2" style="z-index:3{zoom_css}"></video>')
        else:  # cutaway, stack
            bgl = bg_html(i, sc["bg"], S, D, stage, base, tweens, notes)
            if mode == "stack":  # the background is meant to sit behind the cut-out: tell the layout check it's intentional
                bgl = bgl.replace('class="clip', 'data-layout-allow-occlusion class="clip', 1)
            layers.append(bgl)
            if mode == "stack":
                dim = float(sc.get("dim", 0.2))
                if dim:
                    layers.append(f'<div id="dim{i}" class="clip full" data-start="{S}" data-duration="{D}" data-track-index="3" '
                                  f'style="z-index:2;background:linear-gradient(180deg,rgba(0,0,0,{dim * 0.6:.2f}),rgba(0,0,0,{dim:.2f}))"></div>')
                layers.append(f'<video id="ax{i}" class="clip media" data-layout-allow-occlusion src="{alpha}" muted playsinline data-start="{S}" '
                              f'data-duration="{D}" data-media-start="{S}" data-track-index="2" style="z-index:3"></video>')
        if sc.get("captions"):  # the scene's own choice wins over the layout's
            entry["captions"] = sc["captions"]
        if sc.get("caption_y") is not None:
            entry["caption_y"] = int(sc["caption_y"])
        if entry["captions"] in ("move", "seam") and entry.get("caption_y") is None:
            raise SpecError(f"scene {i}: captions {entry['captions']!r} needs caption_y")
    if any(sc["mode"] == "graphic" for sc in scenes):  # one shared background field under every graphic scene
        layers.insert(0, graphics.field(dur, gctx))
    copts = spec.get("captions", {})
    cards = [] if copts == "off" else caption_cards(words, plan, dur, copts)
    layers += captions_html(cards, int((copts or {}).get("size", 70)) if copts != "off" else 70, gctx)
    if spec.get("grade"):
        gctx.css.append(grade_css(spec["grade"]))
    voice_html = f'<audio id="voice" src="{voice}" data-start="0" data-duration="{dur}" data-track-index="9" data-volume="1"></audio>'
    write_project(out, spec.get("id", spec_path.stem), dur, theme, fonts, gsap, layers, tweens, voice_html, gctx)
    meta = out / "meta.json"
    created = load_json(meta).get("createdAt") if meta.exists() else datetime.now(timezone.utc).isoformat()
    meta.write_text(json.dumps({"id": spec.get("id", spec_path.stem), "name": spec.get("id", spec_path.stem), "createdAt": created}, indent=2) + "\n")
    report = {"duration": dur, "presenter": bool(video or alpha), "spec": str(spec_path), "scenes": plan,
              "captions": {"y_center": int((copts or {}).get("y", 1280)) if copts != "off" else None, "cards": cards},
              "notes": notes}
    (out / "scene-plan.json").write_text(json.dumps(report, indent=1) + "\n")
    return dur, plan, notes


def write_project(out, title, dur, theme, fonts, gsap, layers, tweens, voice_html, gctx):
    """index.html, hyperframes.json and package.json for a scene project."""
    f = theme["fonts"]
    fill = {
        "TITLE": html.escape(title), "DUR": str(dur), "W": str(W), "H": str(H), "FPS": str(FPS), "GSAP": gsap,
        "FONTFACES": "\n      ".join(
            f'@font-face {{ font-family: "{f[r]["family"]}"; src: url("{fonts[r]}"); font-weight: {f[r].get("css_weight", "400")}; }}'
            for r in ("display", "body")),
        "LAYERS": "\n      ".join(layers), "VOICE": voice_html,
        "TWEENS": json.dumps(tweens, separators=(",", ":")).replace("</", "<\\/"),
        "CSS": graphics.themed(BASE_CSS, theme) + graphics.css(theme) + "\n      " + "\n      ".join(gctx.css),
    }
    (out / "index.html").write_text(re.sub(r"\{\{([A-Z]+)\}\}", lambda m: fill[m.group(1)], TEMPLATE))
    (out / "hyperframes.json").write_text(json.dumps({
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}}, indent=2) + "\n")
    (out / "package.json").write_text(json.dumps({
        "name": re.sub(r"[^a-z0-9-]", "-", title.lower()), "private": True, "type": "module",
        "scripts": {c: f"npx --yes {HF} {v}" for c, v in (("dev", "preview"), ("check", "check"), ("render", "render"))}},
        indent=2) + "\n")


FAIL_MARK = "✗"  # how `hyperframes check` marks an error line


def hf_check(out, plan):
    """`hyperframes check` on the project. A background behind a stack scene's cut-out is the design, but HyperFrames
    0.8.79 ignores data-layout-allow-occlusion, so a check whose ONLY errors are text_occluded under a cut-out (#ax)
    is accepted and logged."""
    chk = subprocess.run(["npx", "-y", HF, "check"], cwd=out, capture_output=True, text=True)
    lines = [x for x in (chk.stdout + chk.stderr).splitlines() if x.strip()]
    summary = [x.strip() for x in lines if "error(s)" in x or "text checks" in x or "Check passed" in x or "Check failed" in x]
    print("  check:", " | ".join(summary[-4:]) or " | ".join(x.strip() for x in lines[-3:]))
    if chk.returncode == 0:
        return True
    errs = [x.strip() for x in lines if FAIL_MARK in x]
    if errs and any(p["mode"] == "stack" for p in plan) and all("text_occluded" in x and "inside #ax" in x for x in errs):
        print(f"  check: {len(errs)} text_occluded error(s), all under the stack cut-out (intended layering); continuing")
        return True
    for x in errs[:20]:
        print("   ", x[:220])
    if len(errs) > 20:
        print(f"    ... {len(errs) - 20} more")
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--out", help="HyperFrames project folder to write")
    ap.add_argument("--render", help="also render the video to this MP4")
    ap.add_argument("--validate", action="store_true", help="check the spec and stop")
    ap.add_argument("--no-check", action="store_true", help="skip `hyperframes check`")
    a = ap.parse_args()
    if a.validate or not a.out:
        spec_path = Path(a.spec).resolve()
        problems = validate(load_json(spec_path), spec_path.parent)
        print("\n".join(f"  {p}" for p in problems) or "  spec ok")
        sys.exit(1 if problems else 0)
    try:
        dur, plan, notes = build(a.spec, a.out)
    except SpecError as e:
        sys.exit(f"build stopped: {e}")
    for p in plan:
        print(f"  {p['start']:6.2f}-{p['end']:6.2f}  {p['mode']:<8} {p['bg'] or '':<9} {p['at']}")
    for n in notes:
        print("  NOTE", n)
    if not a.no_check and not hf_check(a.out, plan):
        sys.exit("hyperframes check failed; run `npx hyperframes@0.8.79 check` in the project for details")
    if a.render:
        dst = Path(a.render).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["npx", "-y", HF, "render", "-f", str(FPS), "-q", "high", "-o", str(dst)], cwd=a.out, check=True)
        print(f"video: {dst} ({dur:.2f} s)")
        print(f"next: python3 {HERE / 'critic.py'} {dst} --plan {Path(a.out).resolve() / 'scene-plan.json'}")


BASE_CSS = """
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden; background: #000; }
      #root { position: relative; width: 100%; height: 100%; overflow: hidden; font-family: $body; }
      .full { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; }
      .wrap { position: absolute; inset: 0; overflow: hidden; transform-origin: 50% 50%; }
      .media { position: absolute; left: 0; top: 0; width: 100%; height: 100%; object-fit: cover; }
      /* code background: a real file, scrolling */
      .code { position: absolute; inset: 0; background: $ink_deep; overflow: hidden; }
      .codebar { height: 96px; margin-top: 150px; display: flex; align-items: center; gap: 14px; padding: 0 60px;
                 background: $ink_lift; border-bottom: 1px solid $accent/0.5; }
      .codebar i { width: 20px; height: 20px; border-radius: 50%; background: $accent/0.6; }
      .codebar b { margin-left: 18px; font: 600 34px Menlo, monospace; color: $accent_light; }
      .codeview { position: absolute; top: 246px; left: 0; right: 0; bottom: 0; overflow: hidden; padding: 36px 0 0 0; }
      .codescroll { font-family: Menlo, monospace; color: #E4E8EE; white-space: pre; }
      .ln { padding-left: 34px; }
      .codescroll.wrap { white-space: pre-wrap; word-break: break-word; padding-right: 90px; }
      .codescroll.wrap .ln { padding-left: 90px; }
      .ln .no { display: inline-block; width: 86px; color: $accent_light/0.6; text-align: right; margin-right: 30px; }
      .k { color: $accent_light; } .s { color: #A8DCA0; } .n { color: $signal; } .c { color: #9AA3B2; }
      /* split: the presenter full-width in one half, a panel in the other, captions on the seam */
      .panel { position: absolute; left: 0; width: 1080px; overflow: hidden; }
      .panelshade { position: absolute; inset: 0; pointer-events: none; z-index: 2; }  /* over the media's z-index 1 */
      .panelshade.low { background: linear-gradient(180deg, $ink_deep/0.55 0%, $ink_deep/0 30%, $ink_deep/0 55%, $ink_deep/0.75 100%); }
      .panelshade.high { background: linear-gradient(180deg, $ink_deep/0.75 0%, $ink_deep/0 40%, $ink_deep/0.55 100%); }
      .sphead { position: absolute; left: 72px; right: 72px; text-align: center; color: $text; font: 700 112px/0.95 $display;
                text-transform: uppercase; text-shadow: 0 8px 30px rgba(0,0,0,0.6); z-index: 3; }
      .sphead.low { bottom: 380px; }
      .sphead.high { top: 150px; }
      .seam { position: absolute; left: 0; width: 1080px; height: 8px; background: $signal; transform-origin: 50% 50%; z-index: 6; }
      /* word captions */
      .cap { position: absolute; left: 60px; right: 60px; z-index: 20; text-align: center; pointer-events: none; }
      .capin { display: inline-block; padding: 6px 26px 10px; border-radius: 22px; background: $ink_deep/0.62;
               font-family: $body; font-weight: 900; line-height: 1.15; letter-spacing: -0.5px; color: $text;
               white-space: nowrap; text-shadow: 0 4px 14px rgba(0,0,0,0.5); transform-origin: 50% 50%; }
"""

TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={{W}}, height={{H}}" />
    <title>{{TITLE}}</title>
    <!-- Generated by shorts-motion scripts/build.py. Edit scenes.json, not this file. -->
    <script src="{{GSAP}}"></script>
    <style>
      {{FONTFACES}}
{{CSS}}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{{DUR}}" data-width="{{W}}" data-height="{{H}}" data-fps="{{FPS}}">
      {{LAYERS}}
      {{VOICE}}
    </div>
    <script>
      const T = {{TWEENS}};
      const tl = gsap.timeline({ paused: true });
      // Every element starts in the from-state of its earliest tween (per property). With immediateRender:false a tween
      // applies nothing before it starts, so a word waiting for its cue would otherwise show at full strength on any
      // frame seeked before the cue.
      var first = {};
      T.slice().sort(function (a, b) { return a[4] - b[4]; }).forEach(function (t) {
        if (t[0] !== "ft") return;
        var f = first[t[1]] || (first[t[1]] = {});
        for (var k in t[2]) if (!(k in f)) f[k] = t[2][k];
      });
      for (var sel in first) gsap.set(sel, first[sel]);
      T.forEach(function (t) {
        if (t[0] === "count") {  // ["count", sel, from, to, at, dur, prefix, suffix, decimals]
          var el = document.querySelector(t[1]), o = { v: t[2] };
          tl.fromTo(o, { v: t[2] }, { v: t[3], duration: t[5], ease: "power2.out", immediateRender: false, onUpdate: function () {
            el.textContent = t[6] + o.v.toLocaleString("en-US", { minimumFractionDigits: t[8], maximumFractionDigits: t[8] }) + t[7];
          } }, t[4]);
          return;
        }
        tl.fromTo(t[1], t[2], Object.assign({}, t[3], { immediateRender: false }), t[4]);
      });
      window.__timelines = window.__timelines || {};
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""

if __name__ == "__main__":
    main()
