"""Full-frame graphic layouts for build.py (references/design.md is the spec, references/layouts.md the catalogue).

Every graphic scene sits on a plate, never a flat colour: a drifting glow field, a dot grid, film grain and a vignette
(CSS only), with an optional image or clip of your own behind it, blurred and darkened. critic.py fails a flat region
over 22% of the frame, and flat dark fields are exactly the empty space it was built to catch. Content fills the hero
zone from the first frame as a dim skeleton (GHOST opacity) and each item lights up on the spoken word that names it
(Ctx.when): the frame is never half-built. A renderer returns (html, plan_extra); tweens go on ctx.tweens as build.py's
["ft", selector, from, to, at] or ["count", selector, from, to, at, dur, prefix, suffix, decimals].
"""
import html
import json
import re
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_THEME = ROOT / "theme.json"
W, H = 1080, 1920
MARGIN = 72
TOP, BOTTOM, LOW_CAPTION = 170, 1380, 1480  # graphic scenes fill 170-1380; their captions move below, above the platform UI
GHOST = 0.3  # opacity of an item that is laid out but not yet spoken
FIT = 0.88  # text is fitted to 88% of the column, so a pop to 1.06x and a highlighter hit never clip it
FONT_FILES = {"display": ROOT / "fonts" / "BarlowCondensed-Bold.ttf", "body": ROOT / "fonts" / "Montserrat.ttf"}
_fonts = {}


class SpecError(Exception):
    """A scene the layouts cannot draw as written (too long to fit, a missing field). build.py prints it and stops."""


# ------------------------------------------------------------------ theme

def load_theme(path=None):
    """theme.json -> {"colors": {...}, "fonts": {role: {family, file (absolute), css_weight}}}. Font files resolve
    against the theme's own folder, then the skill folder. Missing colours fall back to the default theme's."""
    path = Path(path or DEFAULT_THEME).resolve()
    t = json.loads(path.read_text())
    base = json.loads(DEFAULT_THEME.read_text()) if path != DEFAULT_THEME.resolve() else t
    colors = {**base["colors"], **t.get("colors", {})}
    fonts = {}
    for role in ("display", "body"):
        f = {**base["fonts"][role], **t.get("fonts", {}).get(role, {})}
        p = Path(f["file"])
        for cand in (p, path.parent / p, ROOT / p):
            if cand.exists():
                f["file"] = str(cand.resolve())
                break
        else:
            raise SpecError(f"theme font {role}: {f['file']!r} not found next to {path.name} or in the skill folder")
        fonts[role] = f
    for k, v in colors.items():
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(v)):
            raise SpecError(f"theme colour {k}: {v!r} must be #RRGGBB")
    texture = {**base.get("texture", {}), **t.get("texture", {})}
    return {"colors": colors, "fonts": fonts, "texture": texture, "path": str(path)}


def use_theme(theme):
    """Point the text fitting at the theme's font files (the page renders in the same files)."""
    for role in ("display", "body"):
        FONT_FILES[role] = Path(theme["fonts"][role]["file"])
    _fonts.clear()


def rgba(hex_, a):
    h = hex_.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def themed(css, theme):
    """Fill CSS tokens: $name is a theme colour (#RRGGBB), $name/0.35 the same colour at that alpha, $display and
    $body the font stacks."""
    stacks = {r: f'"{theme["fonts"][r]["family"]}", sans-serif' for r in ("display", "body")}

    def sub(m):
        name, alpha = m.group(1), m.group(2)
        if name in stacks and not alpha:
            return stacks[name]
        if name not in theme["colors"]:
            raise SpecError(f"CSS token ${name} is not a theme colour")
        return rgba(theme["colors"][name], alpha) if alpha else theme["colors"][name]
    return re.sub(r"\$([a-z_]+)(?:/([0-9.]+))?", sub, css)


# ------------------------------------------------------------------ text fitting

def font(size, face="display", weight=None):
    """PIL font for fitting. The default body font (Montserrat) is variable (wght 100-900): pass the CSS weight it
    renders at. A static font ignores the weight and measures as itself."""
    key = (face, int(size), weight)
    if key not in _fonts:
        f = ImageFont.truetype(str(FONT_FILES[face]), int(size))
        if weight:
            try:
                f.set_variation_by_axes([weight])
            except (OSError, AttributeError):
                pass
        _fonts[key] = f
    return _fonts[key]


def esc(s):
    return html.escape(str(s))


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def r3(x):
    return round(float(x), 3)


class Ctx:
    """What a renderer needs from build.py: staging, theme colours, tweens, notes and the spoken words."""

    def __init__(self, stage, base, col, tweens, notes, words):
        self.stage, self.base, self.col, self.tweens, self.notes = stage, Path(base), col, tweens, notes
        self.words = [(norm(w["w"]), w["s"], w["e"]) for w in words if norm(w["w"])]
        self.css = []             # extra page CSS
        self.box = (TOP, BOTTOM)  # vertical space a layout fills; a split panel narrows it (build.py)
        self.canvas_h = H         # height of the container the layout is drawn in (a split panel's height)

    def full(self):
        return self.box == (TOP, BOTTOM)

    def when(self, phrase, S, E, after=None):
        """Start time of `phrase` spoken inside [S, E) (after `after`), or None."""
        want = [norm(x) for x in phrase.split() if norm(x)]
        if not want:
            return None
        lo = max(S - 0.05, after if after is not None else -1)
        for j in range(len(self.words) - len(want) + 1):
            t = self.words[j][1]
            if t >= lo and t < E and [w for w, _, _ in self.words[j:j + len(want)]] == want:
                return t
        return None

    def at(self, phrase, S, E, fallback, after=None):
        t = self.when(phrase, S, E, after) if phrase else None
        if phrase and t is None:
            self.notes.append(f"graphic: {phrase!r} not spoken between {S:.2f} and {E:.2f} s; placed at {fallback:.2f} s")
        return r3(max(S, (t if t is not None else fallback) - 0.04))

    def ft(self, sel, a, b, t):
        self.tweens.append(["ft", sel, a, b, r3(t)])

    def media(self, src, what):
        """A file named in the spec, relative to the spec's folder -> its staged project path (None if missing)."""
        p = self.base / src
        if not p.exists():
            self.notes.append(f"{what}: {src!r} not found next to the spec; left out")
            return None
        return self.stage.add(p)


def field(dur, ctx):
    """The shared background field under every dark graphic scene: two soft glows that drift, a tint, the dot grid,
    film grain and a vignette, all CSS. One field for the whole video, not one per scene: blur and gradient layers
    are costly to capture, and HyperFrames warns that around 40 of them can turn frames black (critic BLANK).
    The dot grid sits over the tint: it is the texture that keeps a plain field from reading as empty space (VOID)."""
    seg, k, t = 6.0, 0, 0.0
    while t < dur:  # slow back-and-forth drifts (sideways, never a zoom: the motion check warns on slow zoom)
        d = min(seg, dur - t)
        a, b = ((-60, 0), (80, 120)) if k % 2 == 0 else ((80, 120), (-60, 0))
        ctx.ft("#fga", {"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1], "duration": r3(d), "ease": "sine.inOut"}, t)
        a, b = ((40, 0), (-90, -80)) if k % 2 == 0 else ((-90, -80), (40, 0))
        ctx.ft("#fgb", {"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1], "duration": r3(d), "ease": "sine.inOut"}, t)
        t, k = t + d, k + 1
    ctx.ft("#fgr", {"backgroundPosition": "0px 0px"}, {"backgroundPosition": "137px 211px", "duration": dur, "ease": f"steps({max(2, round(dur * 12))})"}, 0)
    return ('<div id="field" class="field"><div class="glow ga" id="fga" data-layout-allow-overflow></div>'
            '<div class="glow gb" id="fgb" data-layout-allow-overflow></div><div class="tint"></div><div class="dots"></div>'
            '<div class="grain" id="fgr"></div><div class="vig"></div></div>')


def plate(i, src, S, D, ctx, theme):
    """A scene's own plate, over the shared field: your image or clip (blurred, darkened, drifting sideways) with the
    tint and dot grid on top, and/or the light theme's paper ground. Empty for a dark scene without an image."""
    layers = []
    if theme == "light":
        layers.append('<div class="paperbg"></div>')
    rel = ctx.media(src, f"scene {i} plate") if src else None
    if rel:
        is_vid = Path(src).suffix.lower() in (".mp4", ".mov", ".webm")
        tag = (f'<video id="pl{i}" class="platemedia" src="{rel}" muted playsinline data-start="{S}" data-duration="{D}" '
               f'data-track-index="1"></video>') if is_vid else f'<img id="pl{i}" class="platemedia" src="{rel}" alt="" />'
        layers.append(tag)
        # a sideways drift, not a slow zoom: the motion check warns when slow uniform zoom fills the runtime
        ctx.ft(f"#pl{i}", {"scale": 1.12, "x": -18}, {"scale": 1.12, "x": 18, "duration": D, "ease": "none"}, S)
    if rel or theme == "light":
        layers.append(f'<div class="tint {theme}"></div><div class="dots {theme}"></div>')
    return "".join(layers)


def wrap_lines(words, size, width, face="display", upper=True, weight=None, pad=8):
    f = font(size, face, weight)
    lines, cur = [], []
    for w in words:
        t = w.upper() if upper else w
        trial = " ".join([x for x in cur] + [t])
        if cur and f.getlength(trial) + pad * (len(cur) + 1) > width:
            lines.append(cur)
            cur = [t]
        else:
            cur.append(t)
    if cur:
        lines.append(cur)
    return lines


def fit_block(words, width, height, sizes=range(236, 100, -6), lead=0.96, max_lines=5, face="display",
              upper=True, weight=None):
    width = width * FIT
    for s in sizes:
        lines = wrap_lines(words, s, width, face, upper, weight)
        widest = max(font(s, face, weight).getlength(" ".join(ln)) + 8 * len(ln) for ln in lines)  # + per-word padding
        if len(lines) <= max_lines and len(lines) * s * lead <= height and widest <= width:
            return s, lines
    s = list(sizes)[-1]  # nothing fitted: the smallest size, measured the same way (callers decide if that is ok)
    return s, wrap_lines(words, s, width, face, upper, weight)


# ------------------------------------------------------------------ layouts

def justify(words, width, height, max_size=300, lead=0.94, max_lines=5):
    """Impact type: break into lines, then size each line to the column width (capped), and scale the whole block
    down if the lines are taller than the space. Returns [(size, [words])]."""
    base, lines = fit_block(words, width, height, lead=lead, max_lines=max_lines)
    col = width * FIT
    out = []
    for ln in lines:
        w1 = font(100).getlength(" ".join(ln)) / 100 + 0.08 * len(ln) + 0.2 * (len(ln) - 1)  # + word padding and the gap
        out.append([min(max_size, col / w1), ln])
    total = sum(sz * lead for sz, _ in out)
    if total > height:
        out = [[sz * height / total, ln] for sz, ln in out]
    return [(int(sz), ln) for sz, ln in out]


def kinetic(i, g, S, D, E, ctx):
    """Big type that builds word by word on the spoken words; the captions are off (the type IS the line).
    g: text, hit [words in the signal colour], strike [words struck through on their word], sub, instant (every word
    on screen from the scene's first frame: a title that is also the cover frame), push (hold zoom, e.g. 1.04; off by
    default: the motion check warns on slow uniform zoom)."""
    words = g["text"].split()
    ktop, kbot = (180, 1540) if ctx.full() else (ctx.box[0] + 10, ctx.box[1])  # full frame: captions are off
    room = g.get("height", (kbot - ktop) - (110 if g.get("sub") else 0) - 100)
    sized = justify(words, W - 2 * MARGIN, room)
    lead = min(1.3, max(0.94, 0.86 * room / sum(sz for sz, _ in sized)))  # width-limited lines spread to fill the height
    size = max(sz for sz, _ in sized)
    hits = {norm(h) for h in g.get("hit", [])}
    strikes = {norm(h) for h in g.get("strike", [])}
    out, k, t_prev = [], 0, S
    ptr = S
    for sz, ln in sized:
        spans = []
        for w in ln:
            t = ctx.when(w, S, E, after=ptr)
            t = t if t is not None else t_prev + 0.12
            t_prev, ptr = t, t + 0.01
            cls = "kw" + (" hit" if norm(w) in hits else "") + (" strike" if norm(w) in strikes else "")
            spans.append(f'<span id="k{i}_{k}" class="{cls}">{esc(w)}</span>')
            if not g.get("instant"):
                t0 = max(S, t - 0.04)
                ctx.ft(f"#k{i}_{k}", {"opacity": GHOST}, {"opacity": 1, "duration": 0.12, "ease": "none"}, t0)
                # the pop goes up and back from 1: a waiting word sits at its fitted size, so it never clips the frame
                ctx.ft(f"#k{i}_{k}", {"scale": 1}, {"scale": 1.06, "duration": 0.08, "ease": "power2.out"}, t0)
                ctx.ft(f"#k{i}_{k}", {"scale": 1.06}, {"scale": 1, "duration": 0.16, "ease": "power2.inOut"}, r3(t0 + 0.08))
            if norm(w) in strikes:
                ctx.ft(f"#k{i}_{k}", {"backgroundSize": "0% 16px"}, {"backgroundSize": "100% 16px", "duration": 0.25, "ease": "power2.inOut"}, max(S, t + 0.25))
            if norm(w) in hits:
                ctx.ft(f"#k{i}_{k}", {"backgroundSize": "0% 22px"}, {"backgroundSize": "100% 22px", "duration": 0.3, "ease": "power2.out"}, max(S, t + 0.12))
            k += 1
        out.append(f'<div class="kline" style="font-size:{sz}px;line-height:{round(sz * lead)}px">{" ".join(spans)}</div>')
    sub = ""
    if g.get("sub"):
        ts = ctx.at(g.get("sub_at"), S, E, S + D * 0.6) if g.get("sub_at") else r3(S + min(D * 0.6, 1.2))
        sub = f'<div class="ksub" id="ks{i}">{esc(g["sub"])}</div>'
        ctx.ft(f"#ks{i}", {"opacity": 0, "y": 30}, {"opacity": 1, "y": 0, "duration": 0.3, "ease": "power2.out"}, ts)
    if g.get("push"):
        ctx.ft(f"#kb{i}", {"scale": 1.0}, {"scale": float(g["push"]), "duration": D, "ease": "none"}, S)
    body = (f'<div class="kblock" id="kb{i}" style="top:{ktop}px;bottom:{ctx.canvas_h - kbot}px;font-size:{size}px;line-height:{round(size * 0.96)}px">'
            f'{"".join(out)}{sub}</div>')
    return body, {"captions": "off"}


def stat(i, g, S, D, E, ctx):
    """One number, big, counting or popping. A number that is not a sourced fact says so: "illustration": true.
    g: value (number), prefix, suffix, decimals, label, sub, note, at (phrase that starts the count), count (bool)."""
    t0 = ctx.at(g.get("at"), S, E, S + 0.1)
    val = float(g["value"])
    dec = int(g.get("decimals", 0))
    shown = f'{g.get("prefix", "")}{val:,.{dec}f}{g.get("suffix", "")}'
    k = min(1.0, (ctx.box[1] - ctx.box[0]) / (BOTTOM - TOP))
    size = min(int(420 * max(k, 0.6)), int(420 * 6 / max(3, len(shown))))
    start_txt = f'{g.get("prefix", "")}{0:.{dec}f}{g.get("suffix", "")}' if g.get("count", True) else shown
    if g.get("count", True):
        ctx.tweens.append(["count", f"#sv{i}", 0, val, t0, min(1.0, max(0.5, D * 0.35)), g.get("prefix", ""), g.get("suffix", ""), dec])
    # laid out dim from the scene's first frame (never an empty field while the number waits for its word)
    ctx.ft(f"#sv{i}", {"scale": 0.86, "opacity": GHOST}, {"scale": 1, "opacity": 1, "duration": 0.3, "ease": "back.out(2)"}, t0)
    rows = [f'<div class="sval" id="sv{i}" style="font-size:{size}px">{esc(start_txt)}</div>']
    for n, key in enumerate(("label", "sub")):
        if g.get(key):
            rows.append(f'<div class="s{key}" id="s{key}{i}">{esc(g[key])}</div>')
            ctx.ft(f"#s{key}{i}", {"opacity": GHOST, "y": 30}, {"opacity": 1, "y": 0, "duration": 0.3, "ease": "power2.out"}, r3(t0 + 0.35 + 0.25 * n))
    if g.get("note"):
        rows.append(f'<div class="snote">{esc(g["note"])}</div>')
    return (f'<div class="statblock" style="top:{ctx.box[0]}px;height:{ctx.box[1] - ctx.box[0]}px">{"".join(rows)}</div>',
            {"captions": "move", "caption_y": LOW_CAPTION})


def steps(i, g, S, D, E, ctx):
    """A numbered list told one item at a time: the current item fills the hero zone, a numbered rail shows progress.
    g: title, items [{title, sub, at}], of (total count shown on the rail, default len(items)), first (number of item 0).
    Split one list across scenes with first/of to put another layout between its items."""
    items = g["items"]
    first = int(g.get("first", 1))
    total = int(g.get("of", first + len(items) - 1))
    signal, ink_deep, accent = ctx.col["signal"], ctx.col["ink_deep"], ctx.col["accent"]
    times, after = [], None
    for k, it in enumerate(items):
        t = ctx.at(it.get("at"), S, E, S + k * D / len(items), after)
        times.append(t)
        after = t + 0.01
    times[0] = min(times[0], r3(S + 0.02))
    rail = []
    for n in range(1, total + 1):
        rail.append(f'<div class="dot" id="d{i}_{n}"><span>{n}</span></div>')
    cards = []
    for k, it in enumerate(items):
        n = first + k
        t = times[k]
        end = times[k + 1] if k + 1 < len(items) else None
        sub = f'<div class="stsub">{esc(it["sub"])}</div>' if it.get("sub") else ""
        cards.append(f'<div class="stcard" id="sc{i}_{k}"><div class="stnum">{n:02d}</div>'
                     f'<div class="sttitle">{esc(it["title"])}</div>{sub}</div>')
        ctx.ft(f"#sc{i}_{k}", {"opacity": 0, "x": 260}, {"opacity": 1, "x": 0, "duration": 0.28, "ease": "power3.out"}, t)
        ctx.ft(f"#sc{i}_{k} .stnum", {"scale": 0.6}, {"scale": 1, "duration": 0.35, "ease": "back.out(2.2)"}, t)
        ctx.ft(f"#d{i}_{n}", {"backgroundColor": "rgba(255,255,255,0.10)", "color": "rgba(255,255,255,0.55)", "scale": 1},
               {"backgroundColor": signal, "color": ink_deep, "scale": 1.18, "duration": 0.2, "ease": "power2.out"}, t)
        if end is not None:
            ctx.ft(f"#sc{i}_{k}", {"opacity": 1, "x": 0}, {"opacity": 0, "x": -260, "duration": 0.22, "ease": "power2.in"}, r3(end - 0.2))
            ctx.ft(f"#d{i}_{n}", {"scale": 1.18, "backgroundColor": signal}, {"scale": 1, "backgroundColor": accent, "duration": 0.2}, end)
    for n in range(1, first):  # items told in an earlier scene show as done
        ctx.ft(f"#d{i}_{n}", {"backgroundColor": accent}, {"backgroundColor": accent, "duration": 0.01}, S)
    t0, t1 = ctx.box
    k = min(1.0, (t1 - t0) / (BOTTOM - TOP))  # a split panel is shorter: the card's type scales with it
    title = f'<div class="sthead" style="top:{t0}px">{esc(g["title"])}</div>' if g.get("title") else ""
    return (f'{title}<div class="rail" style="top:{t0 + 100}px">{"".join(rail)}</div>'
            f'<div class="ststage" style="top:{t0 + 250}px;height:{t1 - t0 - 250}px;--k:{k:.3f}">{"".join(cards)}</div>',
            {"captions": "move", "caption_y": LOW_CAPTION})


def flow(i, g, S, D, E, ctx):
    """A vertical chain that builds node by node on the spoken words, arrows drawing between them.
    g: title, nodes [{title, sub, at, highlight}], direction ('down' default, 'up' reads bottom to top: work backward)."""
    nodes = g["nodes"]
    n = len(nodes)
    ks = min(1.0, (ctx.box[1] - ctx.box[0]) / (BOTTOM - TOP))  # a split panel is shorter: spacing and type scale
    gap = round(56 * max(ks, 0.45))
    top, bottom = ctx.box[0] + (round(160 * max(ks, 0.7)) if g.get("title") else 20), ctx.box[1]
    box_h = min(290, (bottom - top - gap * (n - 1)) / n)
    tsz = round(min(112, box_h * 0.5))
    ssz = round(max(50, min(56, box_h * 0.27)))  # 50 px type reads as a ~48 px line box: over the critic's 40 px floor
    subs_fit = box_h >= tsz * 0.95 + ssz * 1.1 + 34  # title + sub + padding; otherwise the sub is dropped
    if any(nd.get("sub") for nd in nodes) and not subs_fit:
        ctx.notes.append(f"scene {i}: flow nodes too short for their sub lines ({n} nodes); subs left out")
    top += ((bottom - top) - (n * box_h + gap * (n - 1))) / 2  # centre the chain in the space
    times, after = [], None
    for k, nd in enumerate(nodes):
        t = ctx.at(nd.get("at"), S, E, S + 0.15 + k * min(0.9, D / (n + 1)), after)
        times.append(t)
        after = t + 0.01
    order = list(range(n)) if g.get("direction", "down") == "down" else list(range(n))[::-1]
    out = [f'<div class="flhead" id="fh{i}" style="top:{ctx.box[0] + 5}px;font-size:{round(110 * max(ks, 0.7))}px">{esc(g["title"])}</div>'] if g.get("title") else []
    if g.get("title"):
        ctx.ft(f"#fh{i}", {"opacity": 0, "y": -30}, {"opacity": 1, "y": 0, "duration": 0.3}, S)
    for slot, k in enumerate(order):
        nd = nodes[k]
        y = top + slot * (box_h + gap)
        sub = f'<div class="flsub" style="font-size:{ssz}px">{esc(nd["sub"])}</div>' if nd.get("sub") and subs_fit else ""
        hl = " hl" if nd.get("highlight") else ""
        out.append(f'<div class="flnode{hl}" id="fn{i}_{k}" style="top:{y:.0f}px;height:{box_h:.0f}px">'
                   f'<div class="fltitle" style="font-size:{tsz}px">{esc(nd["title"])}</div>{sub}</div>')
        ctx.ft(f"#fn{i}_{k}", {"opacity": GHOST}, {"opacity": 1, "duration": 0.15, "ease": "none"}, times[k])
        ctx.ft(f"#fn{i}_{k}", {"scale": 0.92}, {"scale": 1, "duration": 0.3, "ease": "back.out(2)"}, times[k])
        if slot:
            ay = y - gap
            out.append(f'<div class="flarrow" id="fa{i}_{k}" style="top:{ay:.0f}px;height:{gap}px"></div>')
            ctx.ft(f"#fa{i}_{k}", {"opacity": GHOST}, {"opacity": 1, "duration": 0.2, "ease": "power2.out"}, max(S, times[k] - 0.1))
    return "".join(out), {"captions": "move", "caption_y": LOW_CAPTION}


def checklist(i, g, S, D, E, ctx):
    """Items that appear and tick on their spoken words. g: title, items [{text, at}]."""
    items = g["items"]
    ks = min(1.0, (ctx.box[1] - ctx.box[0]) / (BOTTOM - TOP))  # a split panel is shorter: the heading scales with it
    out = [f'<div class="clhead" id="ch{i}" style="top:{ctx.box[0] + 10}px;font-size:{round(150 * max(ks, 0.6))}px">'
           f'{esc(g["title"])}</div>'] if g.get("title") else []
    top = ctx.box[0] + (round(250 * max(ks, 0.6)) if g.get("title") else 40)
    bottom = ctx.box[1]
    n = max(1, len(items))
    gap = 70 if ctx.full() else 36
    row_h = min(300, ((bottom - top) - (n - 1) * gap) / n)
    tsize = round(min(150, row_h * 0.46))
    step = row_h + gap
    top += max(0, ((bottom - top) - (n * row_h + (n - 1) * gap)) / 2)
    after = None
    for k, it in enumerate(items):
        t = ctx.at(it.get("at"), S, E, S + 0.2 + k * D / (len(items) + 1), after)
        after = t + 0.01
        out.append(f'<div class="clrow" id="cr{i}_{k}" style="top:{top + k * step:.0f}px;height:{row_h:.0f}px"><div class="clbox"><svg viewBox="0 0 40 40">'
                   f'<path id="cp{i}_{k}" d="M8 21 L17 30 L33 11" /></svg></div><div class="cltext" style="font-size:{tsize}px">{esc(it["text"])}</div></div>')
        ctx.ft(f"#cr{i}_{k}", {"opacity": GHOST + 0.1}, {"opacity": 1, "duration": 0.15, "ease": "none"}, t)
        ctx.ft(f"#cr{i}_{k}", {"x": -40}, {"x": 0, "duration": 0.3, "ease": "back.out(2)"}, t)
        ctx.ft(f"#cp{i}_{k}", {"strokeDashoffset": 60}, {"strokeDashoffset": 0, "duration": 0.25, "ease": "power2.out"}, r3(t + 0.25))
    if g.get("title"):
        ctx.ft(f"#ch{i}", {"opacity": 0, "y": -30}, {"opacity": 1, "y": 0, "duration": 0.3}, S)
    return "".join(out), {"captions": "move", "caption_y": LOW_CAPTION}


def compare(i, g, S, D, E, ctx):
    """Two states, top and bottom halves, the second lighting up on its word; captions sit on the seam (y 960).
    g: top {label, text, plate}, bottom {label, text, plate, at}."""
    out = []
    for k, (key, y0, y1) in enumerate((("top", 0, 900), ("bottom", 1020, 1620))):
        half = g[key]
        t = S if k == 0 else ctx.at(half.get("at"), S, E, S + D * 0.45)
        cls = "cmp " + key + (" good" if k else "")
        img = ""
        if half.get("plate"):
            rel = ctx.media(half["plate"], f"scene {i} compare plate")
            if rel:
                img = f'<img class="cmplate" id="cq{i}_{k}" src="{rel}" alt="" />'
                ctx.ft(f"#cq{i}_{k}", {"scale": 1.1, "x": -14}, {"scale": 1.1, "x": 14, "duration": D, "ease": "none"}, S)
        out.append(f'<div class="{cls}" id="cm{i}_{k}" style="top:{y0}px;height:{y1 - y0}px">{img}<div class="cmshade"></div><div class="cmdots"></div>'
                   f'<div class="cmin"><div class="cmlabel">{esc(half["label"])}</div><div class="cmtext">{esc(half["text"])}</div></div></div>')
        if k:
            ctx.ft(f"#cm{i}_{k} .cmin", {"opacity": GHOST}, {"opacity": 1, "duration": 0.2, "ease": "none"}, t)  # only the words wait
            ctx.ft(f"#cm{i}_{k} .cmtext", {"x": 60}, {"x": 0, "duration": 0.35, "ease": "power3.out"}, t)
        else:
            ctx.ft(f"#cm{i}_{k}", {"opacity": 0, "y": -40}, {"opacity": 1, "y": 0, "duration": 0.3}, S)
    out.append(f'<div class="cmseam" id="cs{i}"></div>')
    ctx.ft(f"#cs{i}", {"scaleX": 0}, {"scaleX": 1, "duration": 0.35, "ease": "power3.out"}, S)
    return "".join(out), {"captions": "move", "caption_y": 960}


def quote(i, g, S, D, E, ctx):
    """A pull line with a marker sweep across the phrase that matters. g: text, mark (phrase), mark_at, by, at."""
    words = g["text"].split()
    # measured in what it renders in: the body font at 900, sentence case, in the 900 px quote column
    q0, q1 = (200, 1350) if ctx.full() else (ctx.box[0] + 20, ctx.box[1])
    size, lines = fit_block(words, W - 180, (q1 - q0) - 250, sizes=range(150, 60, -6), lead=1.02, face="body",
                            upper=False, weight=900)
    if len(lines) * size * 1.02 > (q1 - q0) - 250:
        raise SpecError(f"scene {i}: the quote is too long to fit its space ({len(words)} words); shorten it")
    mark = [norm(x) for x in g.get("mark", "").split()]
    t0 = ctx.at(g.get("at"), S, E, S + 0.05)
    out, k = [], 0
    flat = [w for ln in lines for w in ln]
    marked = set()
    for j in range(len(flat) - len(mark) + 1):
        if mark and [norm(x) for x in flat[j:j + len(mark)]] == mark:
            marked = set(range(j, j + len(mark)))
    for ln in lines:
        spans = []
        for w in ln:
            cls = "qw mk" if k in marked else "qw"
            spans.append(f'<span class="{cls}" id="q{i}_{k}">{esc(w)}</span>')
            k += 1
        out.append(f'<div class="qline">{" ".join(spans)}</div>')
    ctx.ft(f"#qb{i}", {"opacity": 0, "y": 40}, {"opacity": 1, "y": 0, "duration": 0.35, "ease": "power2.out"}, t0)
    tm = ctx.at(g.get("mark_at") or g.get("mark"), S, E, t0 + 0.6)
    for j in sorted(marked):
        ctx.ft(f"#q{i}_{j}", {"backgroundSize": "0% 100%"}, {"backgroundSize": "100% 100%", "duration": 0.18, "ease": "none"}, r3(tm + 0.08 * (j - min(marked))))
    by = f'<div class="qby">{esc(g["by"])}</div>' if g.get("by") else ""
    return (f'<div class="qblock" id="qb{i}" style="top:{q0}px;height:{q1 - q0}px;font-size:{size}px;line-height:{round(size * 1.02)}px">'
            f'<div class="qmark">&ldquo;</div>{"".join(out)}{by}</div>'), {"captions": "move", "caption_y": LOW_CAPTION}


def phone(i, g, S, D, E, ctx):
    """A phone showing a screen (image or video), the same screen blurred as the plate. g: src, label, scroll (px),
    push (hold zoom, off by default). Anything not real on screen says so in the label ("demo")."""
    rel = ctx.media(g["src"], f"scene {i} phone screen")
    if not rel:
        raise SpecError(f"scene {i}: phone src {g['src']!r} not found next to the spec")
    is_vid = Path(g["src"]).suffix.lower() in (".mp4", ".mov", ".webm")
    scr = (f'<video class="phmedia" src="{rel}" muted playsinline data-start="{S}" data-duration="{D}" data-track-index="1"></video>'
           if is_vid else f'<img class="phmedia" id="pm{i}" src="{rel}" alt="" />')
    if not is_vid and g.get("scroll"):
        ctx.ft(f"#pm{i}", {"y": 0}, {"y": -int(g["scroll"]), "duration": D * 0.8, "ease": "power1.inOut"}, S + D * 0.1)
    ctx.ft(f"#ph{i}", {"y": 120, "rotation": 4, "opacity": 0}, {"y": 0, "rotation": 0, "opacity": 1, "duration": 0.4, "ease": "power3.out"}, S)
    if g.get("push"):
        ctx.ft(f"#ph{i}", {"scale": 1}, {"scale": float(g["push"]), "duration": max(0.1, D - 0.4), "ease": "none"}, S + 0.4)
    label = f'<div class="phlabel">{esc(g["label"])}</div>' if g.get("label") else ""
    return (f'<div class="phone" id="ph{i}"><div class="phscreen">{scr}</div><div class="phisland"></div></div>{label}',
            {"captions": "move", "caption_y": LOW_CAPTION})


def pages(i, g, S, D, E, ctx):
    """Kinetic pages: the type is the actor, one page per beat. Adapted from the y5 kinetic type grammar of
    huashu-art-motion (MIT, Copyright (c) 2026 alchaincyf, github.com/alchaincyf/huashu-art-motion; see NOTICE),
    rebuilt in HTML on the theme's colours. A page's key word slams in on its spoken word (spring overshoot about 8%),
    the sub line rises under it, the next page wipes in behind a colour band (the wipe lands on the word), a list page
    carries a giant low-contrast numeral that drifts and a progress track (01 / 02 / 03), and one word can take a
    highlighter hit.
    g: pages [{text, sub, key (a word of sub in the key colour), at, label, number: {value, prefix, suffix, decimals}
    (a count page: the number lands on `at`)}], highlight {page, word, at}, start (which page colour comes first:
    0 ink, 1 accent, 2 paper, 3 signal), plate."""
    c = ctx.col
    page_colors = [(c["ink"], c["text"]), (c["accent"], c["text"]), (c["paper"], c["ink"]), (c["signal"], c["ink"])]
    pg = g["pages"]
    times, after = [], None
    for k, p in enumerate(pg):
        t = ctx.at(p.get("at"), S, E, S + k * D / len(pg), after)
        times.append(t)
        after = t + 0.01
    times[0] = r3(S + 0.02) if not pg[0].get("number") else max(times[0], r3(S + 0.72))
    listed = [k for k, p in enumerate(pg) if not p.get("number")]
    track = len(listed) >= 2
    t0, t1 = ctx.box
    hl = g.get("highlight") or {}
    c0 = int(g.get("start", 0))
    plate_rel = None
    if g.get("plate") and Path(g["plate"]).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        plate_rel = ctx.media(g["plate"], f"scene {i} pages plate")
    out = []
    for k, p in enumerate(pg):
        ci = (c0 + k) % 4
        bg, fg = page_colors[ci]
        dark = ci in (0, 1)
        t = times[k]
        shown_at = r3(t - 0.7) if p.get("number") else t          # a count page is up while its number runs
        wipe_at = r3(max(S, shown_at - 0.3))
        key_col = c["signal"] if dark else (c["accent"] if ci == 2 else c["ink"])
        mark_col = c["signal"] if ci != 3 else c["accent"]
        band_col = c["signal"] if ci != 3 else c["accent"]
        layers = []
        if plate_rel:
            layers.append(f'<img class="pgplate" src="{plate_rel}" alt="" />')
        layers.append(f'<div class="pgcol" style="background:{bg};opacity:{(0.86 if dark else 0.90) if plate_rel else 1}"></div><div class="pgdots {"dk" if dark else "lt"}"></div>')
        if k in listed and track:
            num = listed.index(k) + 1
            layers.append(f'<div class="pgnum" id="pn{i}_{k}" style="color:{fg}">{num}</div>')
            ctx.ft(f"#pn{i}_{k}", {"x": 40, "y": 30}, {"x": -50, "y": -40, "duration": max(0.5, (times[k + 1] if k + 1 < len(pg) else E) - shown_at + 0.3), "ease": "none"}, wipe_at)
        if p.get("label") or (k in listed and track):
            lab = p.get("label") or f"{listed.index(k) + 1:02d}"
            layers.append(f'<div class="pglabel" style="top:{t0 + 30}px;color:{fg}">{esc(lab)}</div>')
        if p.get("number"):
            n = p["number"]
            dec = int(n.get("decimals", 0))
            val = float(n["value"])
            shown = f'{n.get("prefix", "")}{val:,.{dec}f}{n.get("suffix", "")}'
            size = min(420, int(420 * 6 / max(3, len(shown))))
            layers.append(f'<div class="pgword" style="top:{t0}px;height:{t1 - t0 - 260}px;color:{fg}">'
                          f'<div class="pgval" id="pv{i}_{k}" style="font-size:{size}px">{esc(n.get("prefix", ""))}0{esc(n.get("suffix", ""))}</div>'
                          f'<div class="pgsub" id="ps{i}_{k}" style="color:{fg}">{esc(p.get("text", ""))}</div></div>')
            ctx.tweens.append(["count", f"#pv{i}_{k}", 0, val, shown_at, 0.7, n.get("prefix", ""), n.get("suffix", ""), dec])
            ctx.ft(f"#pv{i}_{k}", {"scale": 0.86}, {"scale": 1, "duration": 0.5, "ease": "back.out(1.8)"}, r3(t - 0.08))
            ctx.ft(f"#ps{i}_{k}", {"opacity": 0, "y": 40}, {"opacity": 1, "y": 0, "duration": 0.35, "ease": "power3.out"}, r3(t + 0.1))
        else:
            words = p["text"].split()
            size, lines = fit_block(words, W - 2 * MARGIN, 560, sizes=range(300, 110, -8), lead=1.0, max_lines=1,
                                    face="body", upper=False, weight=900)
            if size < 200:  # one line only while it stays big ("A plug"); otherwise two bigger lines
                size, lines = fit_block(words, W - 2 * MARGIN, 560, sizes=range(300, 110, -8), lead=1.0, max_lines=2,
                                        face="body", upper=False, weight=900)
            hw = norm(hl.get("word", "")) if hl and int(hl.get("page", -1)) == k else None
            spans = []
            for w in words:
                cls = "pgw" + (" pghl" if hw and norm(w) == hw else "")
                mark = f' style="background-image:linear-gradient({mark_col},{mark_col})"' if "pghl" in cls else ""
                spans.append(f'<span class="{cls}"{mark}>{esc(w)}</span>')
            sub = ""
            if p.get("sub"):
                s_html = esc(p["sub"])
                if p.get("key") and p["key"] in p["sub"]:
                    s_html = s_html.replace(esc(p["key"]), f'<b style="color:{key_col}">{esc(p["key"])}</b>', 1)
                sub = f'<div class="pgsub" id="ps{i}_{k}" style="color:{fg}">{s_html}</div>'
                ctx.ft(f"#ps{i}_{k}", {"opacity": 0, "y": 44}, {"opacity": 1, "y": 0, "duration": 0.38, "ease": "power3.out"}, r3(t + 0.22))
            layers.append(f'<div class="pgword" style="top:{t0}px;height:{t1 - t0 - 260}px;color:{fg}">'
                          f'<div class="pgmain" id="pm{i}_{k}" style="font-size:{size}px;line-height:{round(size * 1.02)}px">{" ".join(spans)}</div>{sub}</div>')
            # the slam: in from 1.22x and settle with a small overshoot (about 8%), landing on the spoken word
            # (starts as the wipe finishes, so a new page is never blank behind its band)
            ctx.ft(f"#pm{i}_{k}", {"opacity": 0, "scale": 1.22}, {"opacity": 1, "scale": 1, "duration": 0.42, "ease": "back.out(2.4)"}, r3(max(S, t - 0.16)))
            if hw:
                th = ctx.at(hl.get("at"), S, E, r3(t + 0.9)) if hl.get("at") else r3(t + 0.9)
                ctx.ft(f"#pm{i}_{k} .pghl", {"backgroundSize": "0% 42%"}, {"backgroundSize": "100% 42%", "duration": 0.32, "ease": "power2.out"}, th)
                ctx.ft(f"#pm{i}_{k} .pghl", {"scale": 1}, {"scale": 1.07, "duration": 0.12, "ease": "power2.out"}, th)
                ctx.ft(f"#pm{i}_{k} .pghl", {"scale": 1.07}, {"scale": 1, "duration": 0.22, "ease": "power2.inOut"}, r3(th + 0.12))
        if track:
            segs = []
            for j, kk in enumerate(listed):
                state = "on" if kk < k else ("cur" if kk == k else "off")
                segs.append(f'<div class="pgseg {state}" style="--fg:{fg}"><span>{j + 1:02d}</span><i id="pt{i}_{k}_{j}"></i></div>')
            layers.append(f'<div class="pgtrack" style="top:{t1 - 170}px">{"".join(segs)}</div>')
            if k in listed:
                ctx.ft(f"#pt{i}_{k}_{listed.index(k)}", {"scaleX": 0}, {"scaleX": 1, "duration": 0.5, "ease": "power2.out"}, t)
        layers.append(f'<div class="grain" id="pgr{i}_{k}"></div>')
        ctx.ft(f"#pgr{i}_{k}", {"backgroundPosition": "0px 0px"}, {"backgroundPosition": "137px 211px", "duration": D, "ease": f"steps({max(2, round(D * 12))})"}, S)
        clip = "" if k == 0 else 'style="clip-path:inset(0% 100% 0% 0%)"'
        band = f'<div class="pgband" id="pb{i}_{k}" style="background:{band_col}"></div>' if k else ""  # page 0 has no wipe
        out.append(f'<div class="pgpage" id="pg{i}_{k}" {clip}>{"".join(layers)}{band}</div>')
        if k:  # the colour band leads the wipe; the new page is fully in on its word
            ctx.ft(f"#pg{i}_{k}", {"clipPath": "inset(0% 100% 0% 0%)"}, {"clipPath": "inset(0% 0% 0% 0%)", "duration": 0.3, "ease": "power3.inOut"}, wipe_at)
            ctx.ft(f"#pb{i}_{k}", {"x": -140}, {"x": 1080, "duration": 0.3, "ease": "power3.inOut"}, wipe_at)
            # the page underneath is fully covered once the wipe lands: hide it (covered text otherwise reads as 1:1
            # contrast in the HyperFrames check, and nothing renders twice)
            ctx.ft(f"#pg{i}_{k - 1}", {"opacity": 1}, {"opacity": 0, "duration": 0.01, "ease": "none"}, r3(wipe_at + 0.31))
    return "".join(out), {"captions": "move", "caption_y": LOW_CAPTION, "plate": False}


PANEL_TYPES = {"kinetic", "stat", "steps", "flow", "checklist", "quote"}  # graphics that fit a split panel's box

RENDERERS = {"kinetic": kinetic, "stat": stat, "steps": steps, "flow": flow, "checklist": checklist,
             "compare": compare, "quote": quote, "phone": phone, "pages": pages}

# the fields a layout cannot draw without (build.validate checks them; references/layouts.md lists the rest)
REQUIRED = {"kinetic": ["text"], "stat": ["value"], "steps": ["items"], "flow": ["nodes"], "checklist": ["items"],
            "compare": ["top", "bottom"], "quote": ["text"], "phone": ["src"], "pages": ["pages"]}
ITEM_FIELDS = {"steps": ("items", "title"), "flow": ("nodes", "title"), "checklist": ("items", "text")}


def render(i, g, S, D, E, ctx):
    """Full-frame graphic scene -> (html, plan_extra)."""
    theme = g.get("theme", "dark")
    body, extra = RENDERERS[g["type"]](i, g, S, D, E, ctx)
    own = plate(i, g.get("plate"), S, D, ctx, theme) if extra.pop("plate", True) else ""
    sibling = ""
    if g.get("illustration"):  # a number that is not a sourced fact says so on screen
        sibling += (f'<div id="il{i}" class="clip illus" data-start="{S}" data-duration="{D}" data-track-index="4">'
                    f'{esc(g.get("illustration_label", "illustration"))}</div>')
    return (f'<div id="bg{i}" class="clip gfx {theme} g-{g["type"]}" data-start="{S}" data-duration="{D}" data-track-index="1" '
            f'style="z-index:1">{own}<div class="gbody">{body}</div></div>' + sibling), extra


GRAIN = ("url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'>"
         "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' seed='7' stitchTiles='stitch'/>"
         "<feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.55 0'/></filter>"
         "<rect width='100%' height='100%' filter='url(%23n)'/></svg>\")")

# Theme tokens: $name is a colour from theme.json, $name/0.35 that colour at 35% alpha, $display / $body the fonts.
CSS = """
      /* ---- graphic scenes (scripts/graphics.py; spec references/design.md) ---- */
      .gfx { position: absolute; inset: 0; overflow: hidden; color: $text; }  /* transparent: the field shows through */
      .gfx.light { color: $ink; }
      .field { position: absolute; inset: 0; overflow: hidden; z-index: 0; background: $ink_deep; }
      .paperbg { position: absolute; inset: 0; background: $paper; }
      .platemedia { position: absolute; left: -5%; top: -5%; width: 110%; height: 110%; object-fit: cover;
                    filter: blur(9px) brightness(0.42) saturate(0.85); }
      .gfx.light .platemedia { filter: blur(12px) brightness(1.15) saturate(0.5); opacity: 0.35; }
      .glow { position: absolute; border-radius: 50%; filter: blur(60px); }
      .glow.ga { width: 900px; height: 900px; left: -300px; top: -200px; background: $accent/0.45; }
      .glow.gb { width: 800px; height: 800px; right: -320px; bottom: 80px; background: $accent_light/0.22; }
      .dots, .pgdots, .cmdots { position: absolute; inset: 0; background-size: DOTGAP DOTGAP; }
      .dots, .pgdots.dk, .cmdots { background-image: radial-gradient(DOTDARK DOTR, transparent DOTR2); }
      .dots.light, .pgdots.lt { background-image: radial-gradient(DOTLIGHT DOTR, transparent DOTR2); }
      .tint { position: absolute; inset: 0; background: linear-gradient(180deg, $ink_deep/0.35, $ink_deep/0.15 45%, $ink_deep/0.55); }
      .tint.light { background: linear-gradient(180deg, $paper/0.55, $paper/0.2 50%, $paper/0.6); }
      .grain { position: absolute; inset: -10%; background-image: GRAIN; opacity: 0.10; mix-blend-mode: overlay; }
      .vig { position: absolute; inset: 0; background: radial-gradient(120% 90% at 50% 45%, transparent 55%, $ink_deep/0.65 100%); }
      .vig.light { background: radial-gradient(120% 90% at 50% 45%, transparent 60%, $ink/0.18 100%); }
      .gbody { position: absolute; inset: 0; }
      .illus { position: absolute; left: 72px; top: 150px; z-index: 5; font: 700 32px $body; color: $text;
               opacity: 0.85; background: $ink_deep/0.55; padding: 6px 16px; border-radius: 10px; }
      /* kinetic type. No centring transform: kinetic() sets top/bottom inline and centres with flex (a translate
         here fights the GSAP scale on the same node) */
      .kblock { position: absolute; left: 72px; right: 72px; text-align: center; display: flex; flex-direction: column;
                justify-content: center; font-family: $display; font-weight: 700; text-transform: uppercase;
                letter-spacing: -1px; transform-origin: 50% 50%; }
      .kline { white-space: nowrap; }
      .kline .kw + .kw { margin-left: 0.2em; }  /* a real gap between words: the render drops the whitespace */
      .kw { display: inline-block; background-image: linear-gradient($signal, $signal); background-repeat: no-repeat;
            background-position: 0 88%; background-size: 0% 22px; padding: 0 4px; }
      .kw.hit { color: $signal; background-image: linear-gradient($signal/0.35, $signal/0.35); }
      .kw.strike { color: rgba(255,255,255,0.55); background-image: linear-gradient($signal, $signal); background-position: 0 55%; background-size: 0% 16px; }
      .gfx.light .kw.strike { color: $ink/0.45; }
      /* light (paper) scenes: the signal and accent_light tints are too pale on paper for text; use the accent */
      .gfx.light .kw.hit, .gfx.light .sval, .gfx.light .sthead, .gfx.light .ssub, .gfx.light .qby { color: $accent; }
      .ksub { margin-top: 44px; font: 800 54px/1.2 $body; text-transform: none; letter-spacing: 0; color: $accent_light; }
      .gfx.light .ksub { color: $accent; }
      /* stat */
      .statblock { position: absolute; left: 72px; right: 72px; display: flex; flex-direction: column;
                   justify-content: center; align-items: center; text-align: center; }
      .sval { font-family: $display; font-weight: 700; line-height: 0.9; color: $signal; letter-spacing: -4px; }
      .slabel { margin-top: 30px; font: 900 76px/1.05 $body; }
      .ssub { margin-top: 18px; font: 700 56px/1.2 $body; color: $accent_light; }
      .snote { margin-top: 40px; font: 700 32px/1.2 $body; opacity: 0.7; }
      /* pages (kinetic pages; see pages()) */
      .pgpage { position: absolute; inset: 0; overflow: hidden; }
      .pgplate { position: absolute; left: -5%; top: -5%; width: 110%; height: 110%; object-fit: cover; filter: blur(9px) saturate(0.6); }
      .pgcol { position: absolute; inset: 0; }
      .pgnum { position: absolute; right: -40px; bottom: 120px; font: 700 1250px/0.8 $display; opacity: 0.13; letter-spacing: -20px; }
      .pglabel { position: absolute; left: 72px; font: 800 52px/1 $body; letter-spacing: 4px; opacity: 0.85; }
      .pgword { position: absolute; left: 72px; right: 72px; display: flex; flex-direction: column; justify-content: center;
                align-items: center; text-align: center; }
      .pgmain { font-family: $body; font-weight: 900; letter-spacing: -2px; transform-origin: 50% 60%; }
      .pgw { display: inline-block; background-repeat: no-repeat; background-position: 0 78%; background-size: 0% 42%;
             padding: 0 10px; transform-origin: 50% 60%; }
      .pgsub { margin-top: 40px; font: 800 66px/1.2 $body; max-width: 900px; }
      .pgval { font-family: $display; font-weight: 700; line-height: 0.9; letter-spacing: -6px; }
      .pgtrack { position: absolute; left: 72px; right: 72px; display: flex; justify-content: center; gap: 28px; }
      .pgseg { width: 160px; color: var(--fg); font: 800 48px/1 $body; }
      .pgseg span { display: block; margin-bottom: 14px; opacity: 0.55; }
      .pgseg.cur span, .pgseg.on span { opacity: 1; }
      .pgseg i { display: block; height: 10px; border-radius: 5px; background: var(--fg); opacity: 0.25; transform-origin: 0 50%; }
      .pgseg.on i, .pgseg.cur i { opacity: 1; }
      .pgband { position: absolute; top: 0; bottom: 0; left: 0; width: 140px; }
      /* steps */
      .sthead { position: absolute; left: 72px; right: 72px; text-align: center; font: 700 64px/1 $display;
                text-transform: uppercase; letter-spacing: 3px; color: $accent_light; }
      .rail { position: absolute; left: 72px; right: 72px; display: flex; justify-content: center; gap: 18px; }
      .gfx.light .dot { border-color: $ink/0.35; }
      .dot { width: 96px; height: 96px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
             background: rgba(255,255,255,0.10); color: rgba(255,255,255,0.55); font: 700 54px $display;
             border: 2px solid rgba(255,255,255,0.25); }
      .ststage { position: absolute; left: 72px; right: 72px; --k: 1; }
      .stcard { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: center; align-items: center;
                text-align: center; color: $text; background: $ink_lift/0.78; border: 2px solid $accent_light/0.35; border-radius: 44px;
                box-shadow: 0 40px 90px rgba(0,0,0,0.45); padding: 40px 50px; }
      .stnum { font: 700 calc(300px * var(--k)) / 0.85 $display; color: $signal; }
      .sttitle { margin-top: 24px; font: 700 calc(160px * var(--k)) / 0.95 $display; text-transform: uppercase; }
      .stsub { margin-top: 30px; font: 800 max(48px, calc(62px * var(--k))) / 1.15 $body; color: $accent_light; }
      /* flow */
      .flhead { position: absolute; left: 72px; right: 72px; text-align: center; font: 700 110px/1 $display; text-transform: uppercase; }
      .flnode { position: absolute; left: 80px; right: 80px; display: flex; flex-direction: column; justify-content: center;
                align-items: center; text-align: center; border-radius: 34px; color: $text; background: $ink_lift/0.82;
                border: 3px solid $accent_light/0.5; box-shadow: 0 24px 60px rgba(0,0,0,0.4); }
      .flnode.hl { background: $signal; color: $ink; border-color: $signal; }
      .fltitle { font: 700 112px/0.95 $display; text-transform: uppercase; }
      .flsub { margin-top: 12px; font: 800 52px/1.1 $body; color: $accent_light; }
      .flnode.hl .flsub { color: $ink; }
      .flarrow { position: absolute; left: 536px; width: 8px; background: $signal; border-radius: 4px; transform-origin: 50% 0%; }
      /* checklist */
      .clhead { position: absolute; left: 72px; right: 72px; font: 700 150px/0.95 $display; text-transform: uppercase; }
      .clrow { position: absolute; left: 60px; right: 60px; display: flex; align-items: center; gap: 40px; padding: 0 40px; color: $text;
               background: $ink_lift/0.78; border: 2px solid $accent_light/0.35; border-radius: 40px; box-shadow: 0 30px 70px rgba(0,0,0,0.45); }
      .clbox { flex: none; width: 124px; height: 124px; border-radius: 28px; background: rgba(255,255,255,0.08); border: 5px solid $accent_light; }
      .clbox svg { width: 100%; height: 100%; }
      .clbox path { fill: none; stroke: $signal; stroke-width: 6; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 60; stroke-dashoffset: 60; }
      .cltext { font: 700 104px/0.95 $display; text-transform: uppercase; }
      /* compare */
      .cmp { position: absolute; left: 0; right: 0; overflow: hidden; color: $text; }
      .cmplate { position: absolute; left: -4%; top: -4%; width: 108%; height: 108%; object-fit: cover; filter: blur(3px) brightness(0.55) saturate(0.8); }
      .cmshade { position: absolute; inset: 0; background: linear-gradient(180deg, $ink_lift/0.55, $ink_deep/0.75); }
      .cmp.good .cmshade { background: linear-gradient(180deg, $accent/0.6, $ink_deep/0.65); }
      .cmin { position: absolute; left: 90px; right: 90px; top: 0; bottom: 0; display: flex; flex-direction: column; justify-content: center; }
      .cmp.top .cmin { top: 120px; bottom: 40px; }
      .cmlabel { font: 700 76px/1 $display; letter-spacing: 6px; text-transform: uppercase; color: $accent_light; }
      .cmp.top .cmtext { color: rgba(255,255,255,0.72); }
      .cmp.good .cmlabel { color: $signal; }
      .cmtext { margin-top: 22px; font: 700 168px/0.92 $display; text-transform: uppercase; }
      .cmseam { position: absolute; left: 0; right: 0; top: 956px; height: 8px; background: $signal; transform-origin: 50% 50%; }
      /* quote */
      .qblock { position: absolute; left: 90px; right: 90px; display: flex; flex-direction: column; justify-content: center;
                font-family: $body; font-weight: 900; }
      .qmark { font: 700 260px/0.6 $display; color: $signal; height: 120px; }
      .qw { display: inline; background-image: linear-gradient($signal/0.9, $signal/0.9); background-repeat: no-repeat;
            background-size: 0% 100%; padding: 0 4px; }
      .qw.mk { color: $text; }
      .gfx.light .qw.mk { color: $ink; }
      .qby { margin-top: 40px; font: 800 44px/1.2 $body; color: $accent_light; }
      /* phone */
      .phone { position: absolute; left: 50%; top: 170px; width: 610px; height: 1180px; margin-left: -305px; border-radius: 84px;
               background: #05080F; padding: 22px; box-shadow: 0 60px 120px rgba(0,0,0,0.6), 0 0 0 3px rgba(255,255,255,0.18); }
      .phscreen { position: relative; width: 100%; height: 100%; border-radius: 56px; overflow: hidden; background: #fff; }
      .phmedia { position: absolute; left: 0; top: 0; width: 100%; height: auto; min-height: 100%; object-fit: cover; object-position: top; }
      .phisland { position: absolute; left: 50%; top: 40px; width: 150px; height: 42px; margin-left: -75px; border-radius: 21px; background: #05080F; }
      .phlabel { position: absolute; left: 72px; right: 72px; top: 1372px; text-align: center; font: 700 34px $body; opacity: 0.8; }
""".replace("GRAIN", GRAIN)


def css(theme):
    """The layouts' CSS in the theme's colours, fonts and texture."""
    tx = theme.get("texture", {})
    size, gap, a = float(tx.get("dot_size", 10)), float(tx.get("dot_gap", 44)), float(tx.get("dot_alpha", 0.18))
    out = CSS
    for k, v in (("DOTGAP", f"{gap:g}px"), ("DOTR2", f"{size / 2 + 0.6:g}px"), ("DOTR", f"{size / 2:g}px"),
                 ("DOTDARK", f"rgba(255,255,255,{a:g})"), ("DOTLIGHT", rgba(theme["colors"]["ink"], round(a * 1.1, 3)))):
        out = out.replace(k, v)
    return themed(out, theme)
