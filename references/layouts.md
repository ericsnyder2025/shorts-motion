# Layouts and modes

Every layout meets `references/design.md`: full frame, on the textured field or a plate, text 40 px and up, built on
the spoken word. `scripts/critic.py` enforces the numbers. A scene is `mode` plus, for graphics, `bg.type`;
`scripts/build.py` renders it (the graphics live in `scripts/graphics.py`).

## How timing works

- A scene starts on the first word of its `at` phrase (30 ms early, so the cut lands just before the word) and runs
  until the next scene starts. Scene 0 starts at 0. Matching ignores case and punctuation, so `"at": "first open"`
  matches `First, open`.
- Inside a layout, every `at` is searched for within that scene only. An item with no `at`, or whose phrase is not
  spoken in the scene, is spread evenly and the build prints a `NOTE`.
- Items are laid out from the scene's first frame at 30% opacity (a dim skeleton) and light up on their word, so a
  frame is never half-built and never empty while it waits.
- Captions are cards of up to 3 words, broken at punctuation, pauses and scene changes, the word being said in the
  signal colour. Each layout places them: `off` for kinetic type (the type is the line), `move` to y 1480 under the
  other graphics, the seam for `compare` and `split`.

## Common fields (every graphic)

| Field | What |
|---|---|
| `theme` | `dark` (default) or `light` (paper ground; at most every third scene) |
| `plate` | an image or clip of yours behind the layout, blurred and darkened, drifting sideways (not zooming) |
| `illustration`, `illustration_label` | a small label top-left ("illustration" by default) for anything not real or not a sourced fact |

## kinetic

Big condensed type that builds word by word on the spoken words. For the hook, the lesson line, a reversal.

| Field | What |
|---|---|
| `text` (required) | the line; each word is timed to its spoken word, so write it as it is said |
| `hit` | words in the signal colour with a highlighter bar |
| `strike` | words struck through on their word ("not a guarantee") |
| `sub` / `sub_at` | one support line under the type, and the phrase that brings it in |
| `instant` | every word lit from frame 0 (a cover title that is also the thumbnail) |
| `push` | a slow hold zoom, e.g. 1.04 (off by default; the motion check warns when slow zoom fills the runtime) |
| `height` | override the type block height in px |

```json
{"at": "Most Shorts", "mode": "graphic", "bg": {"type": "kinetic", "text": "Most Shorts lose people in two seconds", "hit": ["two", "seconds"]}}
```

## pages

Kinetic pages: the type is the actor, one page per beat. The key word slams in on its spoken word (a spring
overshoot of about 8%), the sub line rises under it, the next page wipes in behind a colour band, list pages carry a
giant low-contrast numeral that drifts and a 01 / 02 / 03 progress track, and one word can take a highlighter hit.
Pages rotate ink, accent, paper and signal. Adapted from huashu-art-motion's y5 kinetic type (see NOTICE).

| Field | What |
|---|---|
| `pages` (required, 1-6) | `[{text, sub, key, at, label, number}]`; `text` 1-3 words reads best; `key` is a phrase of `sub` shown in the key colour; `label` replaces the 01/02 label; `number` `{value, prefix, suffix, decimals}` makes a count page (the number lands on `at`) |
| `highlight` | `{page, word, at}`: a highlighter hit on one word of one page |
| `start` | the first page colour: 0 ink, 1 accent, 2 paper, 3 signal |
| `plate` | an image behind every page (the page colours turn slightly see-through) |

One page per 2-4 s of speech.

```json
{"at": "Here is the fix", "mode": "graphic", "bg": {"type": "pages", "start": 1, "pages": [
  {"text": "The fix", "sub": "it fits in one breath", "key": "one breath", "at": "fix"},
  {"text": "Three moves", "sub": "in this order", "at": "Three moves"}]}}
```

## stat

One number, big, counting up (or popping) on its word. A number that is not a sourced fact gets `"illustration":
true` (and a label like "rule of thumb" or "example").

| Field | What |
|---|---|
| `value` (required) | the number |
| `prefix`, `suffix`, `decimals` | "$", " s", "%"; decimal places |
| `label`, `sub`, `note` | what it counts (big), one support line, a small footnote |
| `at` | the phrase that starts the count |
| `count` | `false` pops the final number instead of counting |

## steps

A numbered list told one item at a time: the current item fills the hero zone, a numbered rail shows progress.

| Field | What |
|---|---|
| `items` (required) | `[{title, sub, at}]` |
| `title` | a small heading over the rail |
| `first`, `of` | the number of item 0 and the total on the rail: put another layout between items by splitting the list over scenes (`first: 1, of: 3` ... `first: 3, of: 3`) |

## flow

A vertical chain that builds node by node, arrows drawing between them.

| Field | What |
|---|---|
| `nodes` (required) | `[{title, sub, at, highlight}]`; 3-5 nodes; `sub` lines are dropped (with a NOTE) when the nodes get too short |
| `title` | a heading |
| `direction` | `down` (default) or `up` (reads bottom to top: working backward) |

## checklist

Items that appear and tick on their words.

| Field | What |
|---|---|
| `items` (required) | `[{text, at}]`; 2-4 short items |
| `title` | a heading |

## compare

Two states, top and bottom halves; the bottom one lights up on its word. Captions sit on the seam (y 960).

| Field | What |
|---|---|
| `top`, `bottom` (required) | `{label, text, plate}`; `bottom.at` is the phrase that lights it |

## quote

A pull line with a marker sweep across the phrase that matters. Stops the build if it is too long to fit.

| Field | What |
|---|---|
| `text` (required) | the line (about 12 words at most) |
| `mark`, `mark_at` | the phrase that gets the sweep, and when (default: when `mark` is spoken) |
| `by`, `at` | attribution line; when the quote enters |

## phone

A phone showing a screen (image or clip). Label anything that is not a real screen ("demo").

| Field | What |
|---|---|
| `src` (required) | the screen image or clip, next to the spec |
| `label` | a line under the phone |
| `scroll` | px to scroll an image screen over the scene |
| `push` | a hold zoom (off by default) |

## Modes with footage

| Mode | Fields | Notes |
|---|---|---|
| `cutaway` | `bg`: `image`, `video` (`src`, `push`, `media_start`) or `code` (`file`, `lines`, `title`, `speed`, `wrap`, `font_px`) | a full-frame picture, clip or code file; clips shorter than the scene hold their last frame (NOTE) |
| `avatar` | `zoom` 1.0-1.4 | `presenter.video` full frame; two avatar scenes in a row read as a camera change only with different zooms, and REPEAT still fails them unless `--profile speaker` |
| `split` | `bg` (a panel graphic or image/video/code), `presenter` top/bottom, `seam`, `headline`, `zoom` | the presenter stays on screen while a graphic reads; a split counts as presenter time |
| `stack` | `bg` image/video/code, `dim` | `presenter.alpha` in front of the background (the code wall); HyperFrames reports the text under the cut-out as occluded, and build.py accepts exactly that |

The presenter take must be in sync with the voice from 0 s: the scenes play it at the scene's own time. Use footage
of yourself or of people who agreed to it, and follow the platforms' rules for labelling AI-generated presenters.

## Choosing

1. Read the script's beats. One idea per scene; a scene runs 1.5-5 s.
2. Pick the layout that shows the beat: a list is `steps`, a chain is `flow`, a reversal is `kinetic` with
   `strike`, a number is `stat`, a contrast is `compare`, a run of short beats is `pages`, a screen is `phone`.
3. No layout twice in a row; at least min(5, scenes / 2 + 1) layouts; keep each non-presenter layout under 40% of
   the runtime.
4. Open on the hook: the presenter saying it, or a `kinetic` hook (the critic's OPEN check).
5. Review the rendered frames (the critic sheet), not only the HTML.
