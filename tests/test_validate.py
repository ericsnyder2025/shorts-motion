"""scenes.json validation, scene anchoring on spoken words, and the caption cards."""
import copy
import json
import unittest

from helpers import ROOT, spoken

import build  # noqa: E402  (helpers puts scripts/ on the path)
from graphics import SpecError  # noqa: E402

DEMO = json.loads((ROOT / "examples" / "demo" / "scenes.json").read_text())


def problems(edit):
    spec = copy.deepcopy(DEMO)
    edit(spec)
    return build.validate(spec)


class Validate(unittest.TestCase):
    def test_the_demo_spec_is_valid(self):
        self.assertEqual(build.validate(DEMO), [])

    def test_missing_files_are_reported_against_the_folder(self):
        out = build.validate(DEMO, ROOT / "examples" / "demo")
        self.assertTrue(any("voice.wav" in p for p in out))   # made by words.py, not shipped
        self.assertTrue(any("words.json" in p for p in out))

    def test_bad_mode(self):
        self.assertTrue(any("mode must be" in p for p in problems(lambda s: s["scenes"][1].update(mode="pip"))))

    def test_unknown_graphic(self):
        self.assertTrue(any("bg.type" in p for p in problems(lambda s: s["scenes"][0]["bg"].update(type="chart"))))

    def test_missing_layout_field(self):
        out = problems(lambda s: s["scenes"][0]["bg"].pop("text"))
        self.assertIn('scene 0: kinetic needs "text"', out)

    def test_list_items_need_their_field(self):
        out = problems(lambda s: s["scenes"][2]["bg"]["items"].append({"sub": "no title"}))
        self.assertTrue(any('items[1] needs "title"' in p for p in out))

    def test_stat_value_is_a_number(self):
        self.assertIn("scene 3: stat.value must be a number", problems(lambda s: s["scenes"][3]["bg"].update(value="three")))

    def test_compare_halves(self):
        out = problems(lambda s: s["scenes"][5]["bg"]["bottom"].pop("label"))
        self.assertTrue(any("compare.bottom" in p for p in out))

    def test_pages_count(self):
        out = problems(lambda s: s["scenes"][1]["bg"].update(pages=[{"text": "x"}] * 7))
        self.assertTrue(any("1-6 pages" in p for p in out))

    def test_every_scene_after_the_first_needs_at(self):
        self.assertTrue(any('"at"' in p for p in problems(lambda s: s["scenes"][2].pop("at"))))
        self.assertEqual(problems(lambda s: s["scenes"][0].pop("at")), [])

    def test_allow_needs_a_reason_and_a_known_code(self):
        out = problems(lambda s: s["scenes"][0].update(allow=["VOID"]))
        self.assertTrue(any('needs a "why"' in p for p in out))
        out = problems(lambda s: s["scenes"][0].update(allow=["REPEAT"], why="x"))
        self.assertTrue(any("allow takes" in p for p in out))
        self.assertEqual(problems(lambda s: s["scenes"][0].update(allow=["VOID"], why="full-bleed title card")), [])

    def test_presenter_modes_need_footage(self):
        self.assertTrue(any("presenter.video" in p for p in problems(lambda s: s["scenes"].append({"at": "So", "mode": "avatar"}))))
        out = problems(lambda s: s["scenes"].append({"at": "So", "mode": "stack", "bg": {"type": "image", "src": "a.png"}}))
        self.assertTrue(any("presenter.alpha" in p for p in out))
        out = problems(lambda s: s["scenes"].append({"at": "So", "mode": "split", "bg": {"type": "kinetic", "text": "x"}}))
        self.assertTrue(any("split needs presenter" in p for p in out))

    def test_split_panels_take_panel_graphics_only(self):
        def edit(s):
            s["presenter"] = {"video": "take.mp4"}
            s["scenes"].append({"at": "So", "mode": "split", "bg": {"type": "compare", "top": {}, "bottom": {}}})
        self.assertTrue(any("split panel takes" in p for p in problems(edit)))

    def test_zoom_range(self):
        def edit(s):
            s["presenter"] = {"video": "take.mp4"}
            s["scenes"].append({"at": "So", "mode": "avatar", "zoom": 2})
        self.assertTrue(any("zoom must be" in p for p in problems(edit)))

    def test_captions_values(self):
        self.assertTrue(any("captions must be" in p for p in problems(lambda s: s["scenes"][0].update(captions="bottom"))))
        self.assertTrue(any("captions.size" in p for p in problems(lambda s: s.update(captions={"size": 30}))))
        self.assertEqual(problems(lambda s: s.update(captions="off")), [])

    def test_voice_and_words_required(self):
        out = problems(lambda s: (s.pop("voice"), s.pop("words")))
        self.assertTrue(any(p.startswith("voice:") for p in out))
        self.assertTrue(any(p.startswith("words:") for p in out))


class Timing(unittest.TestCase):
    def test_scenes_start_on_their_words(self):
        words = spoken()
        starts = build.anchor_times(DEMO["scenes"][:5], words)
        self.assertEqual(starts[0], 0.0)
        here = next(w["s"] for w in words if w["w"] == "Here")
        self.assertAlmostEqual(starts[1], build.frame(here - 0.03), places=3)
        self.assertEqual(starts, sorted(starts))

    def test_a_phrase_that_is_never_said_stops_the_build(self):
        with self.assertRaises(SpecError):
            build.anchor_times([{"at": "x"}, {"at": "not in the script"}], spoken())

    def test_anchors_ignore_punctuation_and_case(self):
        starts = build.anchor_times([{"at": ""}, {"at": "first open"}], spoken())
        self.assertGreater(starts[1], 0)


class Captions(unittest.TestCase):
    def plan(self, words):
        t = [w["s"] for w in words]
        cut = t[9]
        return [{"start": 0.0, "end": cut, "captions": "off"},
                {"start": cut, "end": t[-1] + 1, "captions": "move", "caption_y": 1480}]

    def test_off_scenes_get_no_captions_and_cards_stay_in_their_scene(self):
        words = spoken()
        plan = self.plan(words)
        cards = build.caption_cards(words, plan, words[-1]["e"] + 1, {"y": 1280, "size": 70})
        self.assertTrue(cards)
        for c in cards:
            self.assertGreaterEqual(c["start"], plan[1]["start"])
            self.assertEqual(c["y"], 1480)
            self.assertLessEqual(len(c["words"]), 3)
            self.assertLess(c["start"], c["end"])

    def test_cards_break_after_punctuation(self):
        words = spoken()
        cards = build.caption_cards(words, [{"start": 0, "end": 99, "captions": "default"}], 99, {"max_words": 6})
        for c in cards[:-1]:
            inner = [w["t"] for w in c["words"][:-1]]
            self.assertFalse(any(x.endswith((".", ",")) for x in inner), c)


if __name__ == "__main__":
    unittest.main()
