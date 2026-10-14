#!/usr/bin/env python3
"""Word timings for a voice track: what build.py anchors scenes and captions on. Three ways in, all local:

    python3 scripts/words.py say script.txt --out voice.wav --words words.json [--voice Samantha] [--rate 0.5]
    python3 scripts/words.py transcribe voice.wav --words words.json [--model medium]
    python3 scripts/words.py estimate voice.wav script.txt --words words.json

say         Speaks the script with the macOS system voice and records each word's start as it is synthesized
            (scripts/tts_words.swift; exact to about 30 ms). Without swiftc it falls back to `say`, sentence by
            sentence, and estimates the words inside each sentence by length. Without macOS it uses espeak-ng the
            same way if installed.
transcribe  Any recording (your own voice, a presenter take): word timestamps from mlx_whisper (Apple silicon),
            openai-whisper or faster-whisper, whichever is installed. Check the printed transcript against the script.
estimate    No recognizer installed: spreads the script's words over the voiced parts of the audio by their length.
            Scene changes land near the right word, word captions drift; use it to get going, not to ship.

Output: [{"w": word, "s": start, "e": end}] in seconds. Words keep their punctuation ("seconds."), which is where
captions break; build.py ignores it when matching "at" phrases.
"""
import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TTS_SRC = HERE / "tts_words.swift"
TAIL = 0.6  # seconds of silence after the last word, so the last scene does not end on a clipped breath


def bin_dir():
    """Where compiled helpers go: next to the scripts, or a user cache when the skill folder is read-only."""
    d = HERE / ".bin"
    try:
        d.mkdir(exist_ok=True)
        (d / ".w").touch()
        return d
    except OSError:
        d = Path.home() / ".cache" / "shorts-motion" / "bin"
        d.mkdir(parents=True, exist_ok=True)
        return d


def compiled(src, name):
    """Compile a Swift helper on first use (and again when its source changes); None if swiftc is unavailable."""
    if platform.system() != "Darwin" or not shutil.which("swiftc"):
        return None
    dst = bin_dir() / name
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        r = subprocess.run(["swiftc", "-O", str(src), "-o", str(dst)], capture_output=True, text=True)
        if r.returncode:
            print(f"note: could not compile {src.name} ({r.stderr.strip()[:200]})", file=sys.stderr)
            return None
    return str(dst)


def ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffmpeg failed: {r.stderr.strip()[-400:]}")


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def silences(p, noise="-40dB", min_d=0.06):
    """[(start, end)] of the quiet stretches in an audio file (ffmpeg silencedetect)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", f"silencedetect=n={noise}:d={min_d}", "-f", "null", "-"],
                       capture_output=True, text=True)
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None:
        out.append((start, duration(p)))
    return out


def finish_ends(words, quiet, total):
    """A word ends where the next begins, or earlier where a silence starts in between."""
    for k, w in enumerate(words):
        nxt = words[k + 1]["s"] if k + 1 < len(words) else total
        cut = [a for a, _ in quiet if w["s"] + 0.05 < a < nxt]
        w["e"] = round(min(cut) if cut else nxt, 3)
    return words


def to_wav(src, dst, tail=TAIL):
    ffmpeg("-i", src, "-af", f"apad=pad_dur={tail}", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", dst)


def words_of(text):
    return [w for w in text.split() if re.search(r"[A-Za-z0-9]", w)]


def spread(tokens, a, b):
    """Words over [a, b] by their length (letters + a little per word for the gaps)."""
    weights = [len(re.sub(r"[^A-Za-z0-9]", "", t)) + 1.5 for t in tokens]
    total, t, out = sum(weights) or 1, a, []
    for tok, wt in zip(tokens, weights):
        d = (b - a) * wt / total
        out.append({"w": tok, "s": round(t, 3), "e": round(t + d, 3)})
        t += d
    return out


def say_exact(text, out_wav, voice, rate):
    exe = compiled(TTS_SRC, "tts_words")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as td:
        txt, caf = Path(td) / "script.txt", Path(td) / "voice.caf"
        txt.write_text(text)
        r = subprocess.run([exe, str(txt), str(caf), voice or "", "" if rate is None else str(rate)], capture_output=True, text=True)
        if r.returncode:
            print(f"note: system voice failed ({r.stderr.strip()[:200]}); falling back", file=sys.stderr)
            return None
        rows = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
        sr = rows[-1]["rate"]
        words = [{"w": m["w"], "s": round(m["sample"] / sr, 3), "e": 0.0} for m in rows[:-1] if re.search(r"[A-Za-z0-9]", m["w"])]
        to_wav(caf, out_wav)
    return finish_ends(words, silences(out_wav), duration(out_wav)), "exact (system voice markers)"


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if words_of(s)]


def say_chunked(text, out_wav, voice, rate):
    """`say` or espeak-ng, one sentence at a time: sentence edges are exact, words inside them estimated."""
    if platform.system() == "Darwin" and shutil.which("say"):
        def synth(s, dst):
            cmd = ["say", "-o", str(dst)] + (["-v", voice] if voice else []) + (["-r", str(int(360 * rate))] if rate else [])
            subprocess.run(cmd + [s], check=True)
        ext, how = ".aiff", "say"
    elif shutil.which("espeak-ng") or shutil.which("espeak"):
        exe = shutil.which("espeak-ng") or shutil.which("espeak")

        def synth(s, dst):
            cmd = [exe, "-w", str(dst)] + (["-v", voice] if voice else []) + (["-s", str(int(350 * rate))] if rate else [])
            subprocess.run(cmd + [s], check=True)
        ext, how = ".wav", Path(exe).name
    else:
        sys.exit("no local voice found: on macOS use the built-in voices; elsewhere install espeak-ng, or record your "
                 "own voice and run `words.py transcribe` (or `estimate`)")
    words, t = [], 0.0
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for k, s in enumerate(sentences(text)):
            raw, wav = Path(td) / f"s{k}{ext}", Path(td) / f"s{k}.wav"
            synth(s, raw)
            ffmpeg("-i", raw, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                   "silenceremove=start_periods=1:start_threshold=-45dB,areverse,apad=pad_dur=0.28",
                   "-ar", "48000", "-ac", "1", wav)
            d = duration(wav)
            words += spread(words_of(s), t + 0.02, t + d - 0.28)
            parts.append(wav)
            t += d
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        joined = Path(td) / "joined.wav"
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined)
        to_wav(joined, out_wav)
    return words, f"estimated inside each sentence ({how})"


def transcribe(audio, model):
    """Word timestamps from whichever local recognizer is installed."""
    try:
        import mlx_whisper
        repo = model if "/" in model else f"mlx-community/whisper-{model}-mlx"
        r = mlx_whisper.transcribe(str(audio), path_or_hf_repo=repo, word_timestamps=True, language="en")
        segs, how = r["segments"], f"mlx_whisper {repo}"
        return [{"w": w["word"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)} for s in segs for w in s["words"]], how
    except ImportError:
        pass
    try:
        import whisper
        r = whisper.load_model(model).transcribe(str(audio), word_timestamps=True, language="en")
        return [{"w": w["word"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)}
                for s in r["segments"] for w in s.get("words", [])], f"openai-whisper {model}"
    except ImportError:
        pass
    try:
        from faster_whisper import WhisperModel
        segs, _ = WhisperModel(model).transcribe(str(audio), word_timestamps=True, language="en")
        return [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)} for s in segs for w in s.words], f"faster-whisper {model}"
    except ImportError:
        pass
    return None, None


def estimate(audio, text):
    """The script's words over the voiced stretches of the audio (between silences), by length."""
    total = duration(audio)
    quiet = [q for q in silences(audio, min_d=0.18)]
    voiced, t = [], 0.0
    for a, b in quiet:
        if a - t > 0.08:
            voiced.append((t, a))
        t = b
    if total - t > 0.08:
        voiced.append((t, total))
    toks = words_of(text)
    if not voiced or not toks:
        return []
    span = sum(b - a for a, b in voiced)
    weights = [len(re.sub(r"[^A-Za-z0-9]", "", x)) + 1.5 for x in toks]
    per = span / sum(weights)
    out, k = [], 0
    for a, b in voiced:  # fill each voiced stretch with as many words as its length holds
        t = a
        while k < len(toks) and (t + weights[k] * per <= b + per * 2 or (a, b) == voiced[-1]):
            out.append({"w": toks[k], "s": round(t, 3), "e": round(min(b, t + weights[k] * per), 3)})
            t += weights[k] * per
            k += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("say", help="speak a script with a local voice and time every word")
    s.add_argument("script")
    s.add_argument("--out", required=True, help="voice file to write (.wav)")
    s.add_argument("--words", required=True)
    s.add_argument("--voice", help="system voice name or identifier")
    s.add_argument("--rate", type=float, help="speaking rate 0-1 (0.5 is the system's normal)")
    s.add_argument("--estimate", action="store_true", help="skip the exact path (testing the fallback)")
    t = sub.add_parser("transcribe", help="word timestamps for any recording (whisper, if installed)")
    t.add_argument("audio")
    t.add_argument("--words", required=True)
    t.add_argument("--model", default="medium")
    e = sub.add_parser("estimate", help="no recognizer: spread a script over the voiced parts of a recording")
    e.add_argument("audio")
    e.add_argument("script")
    e.add_argument("--words", required=True)
    a = ap.parse_args()
    if a.cmd == "say":
        text = Path(a.script).read_text()
        res = None if a.estimate else say_exact(text, a.out, a.voice, a.rate)
        words, how = res or say_chunked(text, a.out, a.voice, a.rate)
    elif a.cmd == "transcribe":
        words, how = transcribe(a.audio, a.model)
        if words is None:
            sys.exit("no recognizer installed: pip install mlx-whisper (Apple silicon), openai-whisper or faster-whisper; "
                     "or run `words.py estimate <audio> <script>` for approximate timings")
    else:
        words, how = estimate(a.audio, Path(a.script).read_text()), "estimated over the voiced parts (approximate)"
    Path(a.words).write_text(json.dumps(words, indent=0) + "\n")
    print(f"{len(words)} words, {how} -> {a.words}")
    print(" ".join(w["w"] for w in words))


if __name__ == "__main__":
    main()
