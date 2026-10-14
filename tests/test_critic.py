"""The critic's frame rules on synthetic frames and probe results (no video, no Vision probe needed)."""
import unittest

from PIL import Image, ImageDraw

from helpers import ROOT  # noqa: F401  (puts scripts/ on the path)

import critic  # noqa: E402


def frame(bg=(11, 12, 16), dots=None):
    im = Image.new("RGB", (1080, 1920), bg)
    if dots:
        gap, r, a = dots
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for y in range(gap // 2, 1920, gap):
            for x in range(gap // 2, 1080, gap):
                d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, int(255 * a)))
        im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
    return im


def line(s, y, h, x=0.1, w=0.8, conf=1.0):
    return {"s": s, "conf": conf, "box": {"x": x, "y": y / 1920, "w": w, "h": h / 1920}}


def probe(text=(), faces=()):
    return {"w": 1080, "h": 1920, "text": list(text), "faces": list(faces), "person": None}


def found(v, img=None, allow=(), **kw):
    out, *_ = critic.frame_findings(v, img or frame(dots=(44, 5, 0.18)), set(allow), **kw)
    return {(lv, c) for lv, c, _ in out}


class Void(unittest.TestCase):
    def test_a_flat_field_is_one_empty_region(self):
        self.assertGreater(critic.void_fraction(frame()), 0.7)

    def test_the_default_dot_grid_is_texture(self):
        # theme.json's default texture (10 px dots, 44 px apart, 18%): the CSS field must never read as empty
        self.assertLess(critic.void_fraction(frame(dots=(44, 5, 0.18))), 0.05)

    def test_platform_bands_never_count(self):
        im = frame(dots=(44, 5, 0.18))
        ImageDraw.Draw(im).rectangle([0, 1620, 1080, 1920], fill=(11, 12, 16))  # the bottom 300 px left flat
        self.assertLess(critic.void_fraction(im), 0.05)

    def test_void_fails_and_allow_excuses_it(self):
        self.assertIn(("FAIL", "VOID"), found(probe(), frame()))
        self.assertEqual(found(probe(), frame(), allow=["VOID"]), set())


class Text(unittest.TestCase):
    def test_text_floor(self):
        self.assertIn(("FAIL", "TEXT"), found(probe([line("small words here", 400, 36)])))
        self.assertIn(("WARN", "TEXT"), found(probe([line("nearly big enough", 400, 44)])))
        self.assertEqual(found(probe([line("big enough words", 400, 60)])), set())

    def test_disclosure_labels_may_be_small(self):
        self.assertEqual(found(probe([line("demo: not a real account", 400, 30)])), set())
        self.assertIn(("FAIL", "TEXT"), found(probe([line("illustration only", 400, 20)])))

    def test_wall_of_text(self):
        ten = [line(f"line number {k}", 200 + 100 * k, 60) for k in range(10)]
        self.assertIn(("FAIL", "WALL"), found(probe(ten)))
        self.assertNotIn(("FAIL", "WALL"), found(probe(ten), L={**critic.LIMITS, "wall": 14}))

    def test_collision_with_the_caption_card(self):
        cap = line("the caption words", 1450, 60)
        hit = line("graphic text here", 1470, 60)
        self.assertIn(("FAIL", "COLLIDE"), found(probe([cap, hit]), cap_y=(1480, {"the", "caption", "words"})))
        clear = line("graphic text here", 900, 60)
        self.assertEqual(found(probe([cap, clear]), cap_y=(1480, {"the", "caption", "words"})), set())


class Head(unittest.TestCase):
    def test_a_tiny_head_fails_only_in_a_presenter_layout(self):
        face = {"x": 0.4, "y": 0.2, "w": 0.1, "h": 0.10}
        self.assertIn(("FAIL", "HEAD"), found(probe(faces=[face]), face=True))
        self.assertEqual(found(probe(faces=[face]), face=False), set())
        big = {"x": 0.3, "y": 0.2, "w": 0.4, "h": 0.25}
        self.assertEqual(found(probe(faces=[big]), face=True), set())


class Profiles(unittest.TestCase):
    def test_layered_labels_include_the_ai_tag(self):
        self.assertTrue(critic.disclosure_re("layered").match("AI avatar"))
        self.assertFalse(critic.disclosure_re().match("AI avatar"))


if __name__ == "__main__":
    unittest.main()
