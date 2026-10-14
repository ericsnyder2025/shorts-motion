"""The motion check: DRIFT, PUSH and DEAD warn at their calibrated thresholds, BLANK fails, the vendored gate is
unchanged, and (with ffmpeg installed) a blank stretch in a real file is caught."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

import motion_gate  # noqa: E402

QUIET = {"slow_zoom_share": 0.0, "push_in_per_min": 0.0, "dead_flat": 0.0, "blank_run_s": 0.0, "blank_runs_s": [],
         "push_in_times_s": []}
FILM_GATE_SHA256 = "2d375cc2bea291e7a1b837d5755b49fbda72f5f75515758c09bf7d83cd269e52"  # huashu-art-motion @2571ee0


def codes(**m):
    return {(f["level"], f["code"]) for f in motion_gate.findings({**QUIET, **m})}


class Thresholds(unittest.TestCase):
    def test_a_quiet_cut_has_no_findings(self):
        self.assertEqual(codes(), set())

    def test_drift_warns_over_40_percent_slow_zoom(self):
        self.assertEqual(codes(slow_zoom_share=0.40), set())
        self.assertEqual(codes(slow_zoom_share=0.41), {("WARN", "DRIFT")})

    def test_push_warns_over_8_a_minute(self):
        self.assertEqual(codes(push_in_per_min=8.0), set())
        self.assertEqual(codes(push_in_per_min=8.5, push_in_times_s=[1.0, 2.5]), {("WARN", "PUSH")})

    def test_dead_warns_over_25_percent(self):
        self.assertEqual(codes(dead_flat=0.25), set())
        self.assertEqual(codes(dead_flat=0.26), {("WARN", "DEAD")})

    def test_blank_fails_from_0_3_seconds(self):
        self.assertEqual(codes(blank_run_s=0.29), set())
        self.assertEqual(codes(blank_run_s=0.3, blank_runs_s=[[4.0, 4.3]]), {("FAIL", "BLANK")})

    def test_only_blank_is_a_fail(self):
        f = motion_gate.findings({**QUIET, "slow_zoom_share": 0.9, "push_in_per_min": 20, "dead_flat": 0.9})
        self.assertEqual({x["level"] for x in f}, {"WARN"})

    def test_limits_can_be_overridden(self):
        self.assertEqual({x["code"] for x in motion_gate.findings({**QUIET, "dead_flat": 0.3}, {"dead_warn": 0.5})}, set())


class Vendored(unittest.TestCase):
    def test_film_gate_is_unchanged(self):
        src = ROOT / "scripts" / "motion" / "film_gate.py"
        self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), FILM_GATE_SHA256)

    def test_licence_ships_beside_it(self):
        lic = (ROOT / "scripts" / "motion" / "LICENSE-huashu-art-motion").read_text()
        self.assertIn("MIT License", lic)
        self.assertIn("alchaincyf", lic)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class RealFile(unittest.TestCase):
    def test_a_blank_middle_is_caught(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("needs opencv-python-headless")
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td, "blank.mp4")
            src = "testsrc2=size=360x640:rate=30:duration=2"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i",
                            "color=c=0x101010:size=360x640:rate=30:duration=1.2", "-f", "lavfi", "-i", src,
                            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p", "-c:v", "libx264", str(dst)],
                           check=True)
            m = motion_gate.measure(dst)
            self.assertGreaterEqual(m["blank_run_s"], 0.3)
            self.assertIn(("FAIL", "BLANK"), {(f["level"], f["code"]) for f in motion_gate.findings(m)})


if __name__ == "__main__":
    unittest.main()
