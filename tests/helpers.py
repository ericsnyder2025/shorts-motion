"""Shared fixtures for the tests: a fake stage, spoken words, and an HTML structure check."""
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import graphics  # noqa: E402

VOID_TAGS = {"img", "br", "meta", "input", "source", "link", "hr"}
SCRIPT = ("The first two seconds decide if anyone stays. Here is the fix. Three moves. First, open on the hook. "
          "Second, change the picture every three seconds. Third, cut every word you don't need.")


def spoken(text=SCRIPT, start=0.0, step=0.3):
    """Evenly spaced word timings for a script, like words.py writes."""
    out, t = [], start
    for w in text.split():
        out.append({"w": w, "s": round(t, 3), "e": round(t + step * 0.9, 3)})
        t += step
    return out


class FakeStage:
    """Stands in for build.Stage: records what would be copied into the project."""

    def __init__(self):
        self.added = []

    def add(self, src, name=None):
        self.added.append(str(src))
        return f"assets/{name or Path(src).name}"


def ctx(words=None, base=ROOT):
    theme = graphics.load_theme()
    graphics.use_theme(theme)
    return graphics.Ctx(FakeStage(), base, theme["colors"], [], [], words if words is not None else spoken()), theme


class Structure(HTMLParser):
    """Balanced tags and unique ids."""

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids = [], [], []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "id":
                self.ids.append(v)
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        for k, v in attrs:
            if k == "id":
                self.ids.append(v)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
        else:
            self.stack.pop()


def check_html(markup):
    p = Structure()
    p.feed(markup)
    p.close()
    errors = list(p.errors)
    if p.stack:
        errors.append(f"unclosed: {p.stack}")
    dupes = sorted({i for i in p.ids if p.ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate ids: {dupes}")
    return errors, set(p.ids)
