"""The layout renderers produce well-formed HTML whose tweens point at real elements."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, check_html, ctx, graphics, spoken

SAMPLES = {
    "kinetic": {"text": "The first two seconds decide who stays", "hit": ["two"], "strike": ["decide"], "sub": "fix it"},
    "pages": {"pages": [{"text": "The fix", "sub": "in one breath", "key": "one breath", "at": "fix"},
                        {"text": "Three moves", "at": "Three moves"},
                        {"text": "", "number": {"value": 3, "suffix": " s"}, "at": "three seconds"}],
              "highlight": {"page": 1, "word": "moves"}},
    "stat": {"value": 3, "suffix": " s", "label": "per picture", "sub": "at most", "at": "three seconds"},
    "steps": {"title": "The fix", "of": 3, "items": [{"title": "Open on the hook", "sub": "frame one", "at": "First"},
                                                    {"title": "Change the picture", "at": "Second"}]},
    "flow": {"title": "Cut it", "nodes": [{"title": "Draft"}, {"title": "Cut", "sub": "every spare word", "at": "cut"},
                                          {"title": "Ship", "highlight": True}]},
    "checklist": {"title": "Before you post", "items": [{"text": "Hook on frame one", "at": "hook"}, {"text": "Captions on"}]},
    "compare": {"top": {"label": "Slideshow", "text": "Feels like a lecture"},
                "bottom": {"label": "Moving type", "text": "Feels like a story", "at": "Second"}},
    "quote": {"text": "Cut every word you don't need", "mark": "every word", "by": "the edit"},
}


def render(kind, g, i=3, S=4.0, D=6.0):
    c, _ = ctx()
    html, extra = graphics.render(i, {"type": kind, **g}, S, D, S + D, c)
    return c, html, extra


class Layouts(unittest.TestCase):
    def test_every_layout_has_a_sample(self):
        self.assertEqual(set(SAMPLES) | {"phone"}, set(graphics.RENDERERS))

    def test_html_is_well_formed_and_tweens_hit_real_ids(self):
        for kind, g in SAMPLES.items():
            with self.subTest(kind=kind):
                c, html, extra = render(kind, g)
                errors, ids = check_html(html)
                self.assertEqual(errors, [])
                self.assertIn("bg3", ids)
                for tw in c.tweens:
                    m = re.match(r"#([\w-]+)", tw[1])
                    self.assertTrue(m and m.group(1) in ids, f"{kind}: tween target {tw[1]!r} not in the HTML")
                    self.assertGreaterEqual(tw[4], 4.0 - 1e-6, f"{kind}: tween before the scene starts")
                self.assertIn(extra.get("captions"), {"off", "move"})
                if extra.get("captions") == "move":
                    self.assertIsInstance(extra.get("caption_y"), int)

    def test_phone_needs_its_screen(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "screen.png").write_bytes(b"x")
            c, _ = ctx(base=Path(td))
            html, _ = graphics.render(0, {"type": "phone", "src": "screen.png", "label": "demo"}, 0, 3, 3, c)
            self.assertEqual(check_html(html)[0], [])
            with self.assertRaises(graphics.SpecError):
                graphics.render(1, {"type": "phone", "src": "missing.png"}, 0, 3, 3, c)

    def test_kinetic_words_light_on_their_spoken_word(self):
        words = spoken()
        c, _ = ctx(words)
        graphics.render(0, {"type": "kinetic", "text": "decide if anyone stays"}, 0.0, 3.0, 3.0, c)
        lose = next(w["s"] for w in words if w["w"] == "decide")
        first = next(t for t in c.tweens if t[1] == "#k0_0" and t[2].get("opacity") == graphics.GHOST)
        self.assertAlmostEqual(first[4], lose - 0.04, places=2)
        self.assertEqual(c.notes, [])

    def test_an_unspoken_cue_is_noted_not_silent(self):
        c, _ = ctx()
        graphics.render(0, {"type": "stat", "value": 9, "at": "never said"}, 0.0, 3.0, 3.0, c)
        self.assertTrue(any("never said" in n for n in c.notes))

    def test_quote_that_cannot_fit_stops_the_build(self):
        c, _ = ctx()
        with self.assertRaises(graphics.SpecError):
            graphics.render(0, {"type": "quote", "text": " ".join(["unbelievably"] * 80)}, 0, 3, 3, c)

    def test_text_fits_and_stays_big(self):
        size, lines = graphics.fit_block("Open on the hook".split(), 936, 600)
        self.assertGreaterEqual(size, 120)
        self.assertLessEqual(len(lines), 5)
        for sz, _ in graphics.justify("The first two seconds decide who stays".split(), 936, 1200):
            self.assertGreaterEqual(sz, 100)

    def test_split_panel_box_scales_the_layout(self):
        c, _ = ctx()
        c.box, c.canvas_h = (150, 870), 1000
        html, _ = graphics.render(0, {"type": "steps", "items": [{"title": "One"}]}, 0, 2, 2, c)
        self.assertEqual(check_html(html)[0], [])
        self.assertIn("--k:0.", html)

    def test_illustration_label(self):
        _, html, _ = render("stat", {"value": 3, "illustration": True, "illustration_label": "rule of thumb"})
        self.assertIn("rule of thumb", html)
        self.assertEqual(check_html(html)[0], [])

    def test_field_is_well_formed(self):
        c, _ = ctx()
        html = graphics.field(20.0, c)
        errors, ids = check_html(html)
        self.assertEqual(errors, [])
        for tw in c.tweens:
            self.assertIn(tw[1].lstrip("#"), ids)


class Theme(unittest.TestCase):
    def test_css_has_no_unfilled_tokens(self):
        theme = graphics.load_theme()
        css = graphics.css(theme)
        self.assertNotIn("$", css)
        self.assertNotIn("DOT", css)
        self.assertIn(theme["colors"]["signal"], css)

    def test_partial_theme_merges_over_the_default(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "theme.json")
            p.write_text(json.dumps({"colors": {"signal": "#FF0000"}}))
            t = graphics.load_theme(p)
            self.assertEqual(t["colors"]["signal"], "#FF0000")
            self.assertEqual(t["colors"]["ink"], json.loads((ROOT / "theme.json").read_text())["colors"]["ink"])
            self.assertTrue(Path(t["fonts"]["body"]["file"]).exists())

    def test_bad_colour_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "theme.json")
            p.write_text(json.dumps({"colors": {"signal": "orange"}}))
            with self.assertRaises(graphics.SpecError):
                graphics.load_theme(p)

    def test_alpha_tokens(self):
        t = graphics.load_theme()
        self.assertEqual(graphics.themed("a: $ink/0.5;", t), "a: " + graphics.rgba(t["colors"]["ink"], "0.5") + ";")
        self.assertIn("sans-serif", graphics.themed("$display", t))


if __name__ == "__main__":
    unittest.main()
