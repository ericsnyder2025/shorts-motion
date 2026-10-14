---
name: shorts-motion
description: Make vertical 1080x1920 explainer Shorts (TikTok, Reels, YouTube Shorts) with HyperFrames, with animated graphic layouts timed to the spoken words, an optional talking-head or cut-out presenter and burned-in word captions, then run a measured design critic and fix what it fails until the cut passes. Use when asked to make, design, re-edit or check a short vertical explainer video, turn a script into a Short, lay out scenes for a voiceover, or critique a 9:16 cut for empty space, small text, repeated layouts or slideshow motion.
---

# shorts-motion

Turns a script into a 1080x1920 Short: you write `scenes.json` (which layout shows each beat, and the spoken words
that start it), `build.py` turns it into a HyperFrames project and renders it, and `critic.py` measures the MP4 and
fails it for the things that make Shorts look amateur. You fix the spec and go again until it passes.

`SKILL_DIR` below is the folder this file is in (for example `~/.claude/skills/shorts-motion`). Everything runs
locally: python3 (numpy, Pillow, opencv-python-headless), ffmpeg, Node 22+ with `npx hyperframes@0.8.79`, and on macOS
the system voice and Apple Vision (compiled from Swift on first use).

## When to use

- "Make a Short / Reel / TikTok explaining X", "turn this script into a vertical video", "animate this voiceover".
- "Design the scenes for this narration", "add graphics to my talking-head take".
- "Check this cut", "why does this look like a slideshow", "critique this 9:16 video".

Not for: long 16:9 videos, music videos, or footage-only edits with no graphics (plain cutting tools fit better).

## The loop

1. **Voice and word timings.** Put the script in `script.txt` in a work folder, then
   `python3 SKILL_DIR/scripts/words.py say script.txt --out voice.wav --words words.json`
   (macOS voice, exact word starts). For a recording you already have:
   `words.py transcribe voice.wav --words words.json` (needs mlx-whisper, openai-whisper or faster-whisper), or
   `words.py estimate voice.wav script.txt --words words.json` (approximate). Read the printed transcript: `at`
   phrases must match these words.
2. **Write `scenes.json`** next to them (schema below). One idea per scene, 1.5-5 s each; pick the layout that
   shows the beat, not one that decorates it. Check it: `python3 SKILL_DIR/scripts/build.py scenes.json --validate`.
3. **Build and render.**
   `python3 SKILL_DIR/scripts/build.py scenes.json --out project --render short.mp4`
   This also runs `hyperframes check` (layout, contrast); it stops on errors. Read every `NOTE` it prints (a cue
   phrase that was never spoken, a sub line dropped because it did not fit).
4. **Critique.** `python3 SKILL_DIR/scripts/critic.py short.mp4 --plan project/scene-plan.json --out critic`
   Exit 1 means FAIL. Open `critic/critic-sheet.png` and look at it yourself: the numbers catch hygiene, your eye
   catches whether the graphic actually shows what is being said, hierarchy, polish.
5. **Fix and repeat** from step 2 (or 1 if the words change) until the result is PASS and the sheet looks right.
   Fix the spec, never the generated `index.html`. Warnings are worth fixing; an `allow` is the last resort and
   always carries a `why`.

`SKILL_DIR/scripts/demo.sh [work-dir]` runs all of it on the bundled example (about 30 s on a recent Mac).

## scenes.json

Paths are relative to the file's own folder.

```json
{
  "id": "my-short",
  "voice": "voice.wav",
  "words": "words.json",
  "theme": "theme.json",
  "presenter": {"video": "take.mp4", "alpha": "take-alpha.webm", "face": [0.5, 0.35]},
  "captions": {"y": 1280, "size": 70, "max_words": 3},
  "grade": {"saturate": 0.9, "brightness": 1.0, "contrast": 1.05},
  "scenes": [
    {"at": "The first two", "mode": "graphic", "bg": {"type": "kinetic", "text": "The first two seconds decide", "hit": ["two", "seconds"]}},
    {"at": "Here is the fix", "mode": "graphic", "bg": {"type": "pages", "pages": [{"text": "The fix", "at": "fix"}, {"text": "Three moves", "at": "Three moves"}]}}
  ]
}
```

Top level:

| Key | Required | What |
|---|---|---|
| `voice` | yes, unless `presenter.video` carries the voice | the narration audio |
| `words` | yes | `[{"w", "s", "e"}]` from `words.py` |
| `theme` | no | colours, fonts, dot texture (default: `SKILL_DIR/theme.json`; a partial file merges over it) |
| `presenter` | no | `video`: a full-frame 9:16 take of the presenter saying the script, in sync with the voice from 0 s; `alpha`: the same take with its background removed (WebM with alpha), for `stack`; `face`: face centre as frame fractions. Only footage of yourself or of people who agreed to it |
| `captions` | no | `y` (default 1280), `size` 44-110 (default 70), `max_words` per card (default 3), or `"off"` |
| `grade` | no | on footage only, graphics keep the theme: `saturate` 0-1.3, `brightness` 0.6-1.2, `contrast` 0.8-1.4, or `{"mono": true}` |

Every scene: `at` (the spoken words that start it, matched to `words.json` ignoring case and punctuation; required
from scene 1 on, scene 0 always starts at 0), `mode`, and as needed `bg`, `captions` (`default`, `move`, `seam`,
`top`, `off`; layouts set a sensible one), `caption_y`, `allow` (critic codes this scene is excused from: `VOID`,
`TEXT`, `WALL`, `HEAD`, `COLLIDE`, `OPEN`) with `why` (required with `allow`).

### Modes

| Mode | Fields | Shows |
|---|---|---|
| `graphic` | `bg`: one of the layouts below | a full-frame layout on the textured field |
| `cutaway` | `bg`: `image` / `video` / `code` | a full-frame picture, clip or scrolling code file |
| `avatar` | `zoom` 1.0-1.4 | the presenter take full frame (zoom around the face for a tighter framing) |
| `split` | `bg`: a panel layout (`kinetic`, `stat`, `steps`, `flow`, `checklist`, `quote`) or `image` / `video` / `code`; `presenter`: `top` / `bottom`; `seam` (px, default 900 or 1000); `headline`; `zoom` | the presenter full-width in one half, the panel in the other, captions on the seam |
| `stack` | `bg`: `image` / `video` / `code`; `dim` 0-1 (default 0.2) | the cut-out presenter in front of the background |

Backgrounds: `image` / `video`: `src`, `push` (a hold zoom, off by default), `media_start` (video). `code`: `file`,
`lines` [from, to], `title`, `speed` (px/s), `wrap`, `font_px` (default 34).

### Layouts (`"mode": "graphic", "bg": {"type": ...}`)

Every layout also takes `theme` (`dark` default, `light`), `plate` (an image or clip of your own behind it, blurred
and darkened), `illustration` + `illustration_label` (a small on-screen label for anything not real or not a
sourced fact). Any `at` inside a layout is a spoken phrase within that scene; the item lights up on it.

| Layout | Use for | Fields (required in bold) | Captions |
|---|---|---|---|
| `kinetic` | the hook, the lesson line, a reversal | **`text`**, `hit` [words in the signal colour], `strike` [words struck on their word], `sub`, `sub_at`, `instant` (all words lit from frame 0: a cover title), `push` | off (the type is the line) |
| `pages` | 2-5 short beats as slides: one page per 2-4 s, a key word of 1-3 words | **`pages`** [{`text`, `sub`, `key` (a phrase of `sub` in the key colour), `at`, `label`, `number` {`value`, `prefix`, `suffix`, `decimals`}}] (1-6 pages), `highlight` {`page`, `word`, `at`}, `start` (first page colour: 0 ink, 1 accent, 2 paper, 3 signal) | low, y 1480 |
| `stat` | one number that matters | **`value`**, `prefix`, `suffix`, `decimals`, `label`, `sub`, `note`, `at` (starts the count), `count` (default true) | low |
| `steps` | a numbered list, one item at a time | **`items`** [{**`title`**, `sub`, `at`}], `title`, `first` (number of item 0), `of` (total on the rail) | low |
| `flow` | a chain or process, node by node | **`nodes`** [{**`title`**, `sub`, `at`, `highlight`}], `title`, `direction` (`down` / `up`) | low |
| `checklist` | checks the viewer can run | **`items`** [{**`text`**, `at`}], `title` | low |
| `compare` | before/after, this vs that | **`top`** {**`label`**, **`text`**, `plate`}, **`bottom`** {**`label`**, **`text`**, `plate`, `at`} | on the seam, y 960 |
| `quote` | a line worth pausing on | **`text`**, `mark` (phrase that gets the marker sweep), `mark_at`, `by`, `at` | low |
| `phone` | a demo screen | **`src`** (image or clip), `label` (say "demo" if it is not real), `scroll` (px), `push` | low |

Split one list across scenes with `steps` `first`/`of` to put another layout between its items. Full field notes and
examples: `references/layouts.md`.

## Design rules (short)

The full rules are in `references/design.md`; the critic enforces the numbers.

- **Frame:** 1080x1920. Nothing readable in the top 140 px or the bottom 300 px (platform UI), keep the right 150 px
  clear of anything critical. Side margins 72 px. Graphics fill y 170-1380; captions sit at 1280, or 1480 under a
  graphic, never on graphic text.
- **Fill:** no empty region over 22% of the frame. Every graphic sits on the textured field or a plate. The
  presenter is big (full frame, a full-width half, a near-full cut-out) or absent: no corner picture-in-picture.
- **Type:** nothing under 40 px tall (labels like "demo" may be 26); at most 9 lines on a frame besides the
  caption. More words means more scenes.
- **One idea per scene,** one highlight colour per scene, light theme at most every third scene.
- **Motion:** everything enters (0.2-0.4 s) and lights up on the word that names it. Change the picture at least
  every 4.5 s. Do not park a slow zoom on every scene: hold still while a graphic builds and save moves for a reveal.
  Hard cuts between scenes.
- **Variety:** never the same layout twice in a row, at least min(5, scenes / 2 + 1) layouts, no non-presenter
  layout over 40% of the runtime. With a presenter, keep them on screen 10-20% (`--profile speaker` for talking-head
  led videos: 75%+).
- **Open on the hook:** the presenter saying it from frame 0, or the hook in big type (80 px+) on frame 0.
- **Honesty:** anything not real on screen is labelled ("demo", "illustration"); no credentials or personal data on
  screen.

## The critic

`critic.py video.mp4 --plan scene-plan.json [--profile speaker|layered] [--no-probe]`: rule codes, levels and fixes
in `references/critic.md`. FAIL: `VOID` (empty region over 22%), `TEXT` (under 40 px), `WALL` (over 9 lines),
`HEAD` (presenter face under 13% of the height), `COLLIDE` (text touching the caption), `REPEAT`, `VARIETY`, `HOG`
(a layout over 40%), `STALE` (6 s with no picture change), `FACE` (presenter share), `OPEN` (no hook on frame 0),
`BLANK` (an edgeless blank picture for 0.3 s+). WARN: `DRIFT` (slow uniform zoom over 40% of the runtime), `PUSH`
(over 8 push-ins a minute), `DEAD` (flat unchanging background over 25% of the frame), plus softer levels of VOID,
TEXT, HEAD, STALE and OPEN. On systems without Apple Vision, TEXT, WALL, HEAD, COLLIDE and the hook size are
skipped with a note; VOID, the video rules and the motion rules still run.

Typical fixes: VOID, give the scene more content or a bigger layout (or a `plate`); TEXT or WALL, fewer words,
split the scene; COLLIDE, move the caption (`captions`, `caption_y`) or the text; REPEAT or HOG, rotate layouts;
STALE, split the scene or add a build (`at` cues); DRIFT or PUSH, remove `push` / `zoom` from scenes; OPEN, start on
the presenter or a `kinetic` hook.
