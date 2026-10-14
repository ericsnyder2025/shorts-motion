#!/usr/bin/env bash
# Build, render and critique the example Short with no paid services:
#   1. the narration from the local system voice, with word timings (scripts/words.py say)
#   2. examples/demo/scenes.json -> a HyperFrames project -> demo.mp4 (scripts/build.py)
#   3. the design critic on the MP4 (scripts/critic.py): critic/critic-sheet.png and critic/critic.json
#
#     scripts/demo.sh [work-dir]          (default: ./shorts-motion-demo)
#
# Needs python3 (numpy, Pillow, opencv-python-headless), ffmpeg and Node 22+ (npx fetches hyperframes@0.8.79 on first run).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
WORK="${1:-$PWD/shorts-motion-demo}"

for tool in python3 ffmpeg ffprobe npx; do
  command -v "$tool" >/dev/null || { echo "missing: $tool (see README.md, Requirements)" >&2; exit 2; }
done
python3 -c "import numpy, PIL, cv2" 2>/dev/null || {
  echo "missing Python packages: pip3 install numpy Pillow opencv-python-headless" >&2; exit 2; }

mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"
cp "$ROOT/examples/demo/scenes.json" "$ROOT/examples/demo/script.txt" "$WORK/"
cd "$WORK"

echo "== 1/3 voice and word timings"
if [ -f words.json ] && [ -f voice.wav ] && [ words.json -nt script.txt ]; then
  echo "  reusing voice.wav and words.json"
elif command -v say >/dev/null || command -v espeak-ng >/dev/null || command -v espeak >/dev/null; then
  python3 "$HERE/words.py" say script.txt --out voice.wav --words words.json
else
  echo "no local voice (macOS say or espeak-ng). Record script.txt as voice.wav here, then:" >&2
  echo "  python3 $HERE/words.py transcribe voice.wav --words words.json   (or: estimate voice.wav script.txt ...)" >&2
  exit 2
fi

echo "== 2/3 build and render"
python3 "$HERE/build.py" scenes.json --out project --render demo.mp4

echo "== 3/3 critic"
set +e
python3 "$HERE/critic.py" demo.mp4 --plan project/scene-plan.json --out critic
status=$?
set -e
echo
echo "video:  $WORK/demo.mp4"
echo "critic: $WORK/critic/critic-sheet.png ($WORK/critic/critic.json)"
exit $status
