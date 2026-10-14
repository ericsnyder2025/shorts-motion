# Design rules

What a scene must look like. `references/layouts.md` lists the layouts that meet it; `scripts/critic.py` measures it.
The rules came out of reviewing real posted cuts: the failures were always the same few things (a small head in a
corner over an empty frame, the same two graphic types in rotation, text too small to read on a phone, everything
slowly zooming like a slideshow).

## The frame (1080 x 1920)

| Zone | y (px) | What goes there |
|---|---|---|
| Top margin | 0-140 | Nothing readable (status bar, platform tabs) |
| Hero | 140-1140 | Headlines, numbers, the graphic's content, the presenter's face in split layouts |
| Caption band | 1160-1400 | Burned-in captions (default y 1280). Graphic text never enters it while a caption is up |
| Base | 1400-1920 | The presenter's body, B-roll, texture. Nothing critical: platform UI covers the bottom ~300 px and the right ~150 px |

Side margins 72 px. Full-frame graphics fill y 170-1380 and move their captions to 1480, below the content and above
the platform UI; kinetic type turns captions off and uses 180-1540.

## Fill

- No empty region over 22% of the frame (critic VOID). A background is never a flat colour: every graphic scene sits
  on the shared field (glows that drift, a dot grid, film grain, a vignette) or on a plate of your own. The dot grid
  is the texture that keeps a dark field from reading as empty space; if you change it in `theme.json`, re-run the
  critic.
- The presenter is big or absent: full frame, a full-width half (split), or a cut-out near full scale (stack). No
  corner picture-in-picture: it puts a 20%-high head in a corner and leaves most of the frame empty.
- One idea per scene. Seven boxes are seven beats, not one grid with a moving highlight.

## Type

| Role | Font (default theme) | Size | Notes |
|---|---|---|---|
| Headline | Barlow Condensed 700, uppercase | 120-220 px | 1-3 lines, tight leading |
| Big number | Barlow Condensed 700 | 220-420 px | counts up or pops |
| Page word | Montserrat 900 | 200-300 px | one line while it stays big |
| Label / item | Montserrat 800-900 | 48-72 px | sentence case |
| Support line | Montserrat 700-800 | 48-66 px | at most one per scene |
| Disclosure ("demo", "illustration") | Montserrat 700 | 30-34 px | required where the screen is not real |

Nothing under 40 px tall as measured on the frame (critic TEXT; labels may be 26), at most 9 lines besides the
caption (critic WALL). If it needs more words, it needs more scenes.

## Colour

`theme.json` tokens: `ink` (dark scenes' base), `ink_deep` (the field's floor, vignette), `ink_lift` (cards on dark),
`accent` (fills, bars), `accent_light` (secondary text on dark), `paper` (light scenes), `signal` (the one warm hit
per scene: the number, the key word), `text`. One highlight colour per scene. Light (paper) scenes at most every
third scene, so the cut has rhythm; on paper the layouts use `accent` for highlighted text because `signal` is too
pale to read there.

## Motion

- Everything enters (0.2-0.4 s, power3 or back ease) on the word that names it.
- The picture changes at least every 4.5 s (critic STALE warns at 4.5, fails at 6): the next item, the next page,
  the next scene.
- Hold still rather than zoom. Slow uniform zoom on every scene is what made our cuts read as slideshows next to the
  viral ones (critic DRIFT, PUSH; `scripts/motion/README.md`). The layouts ship with no hold push; the field's glows
  drift sideways and the grain moves, which keeps a hold alive. Save a push for a reveal and pull back after it.
- Scene changes are hard cuts.

## Captions

Word cards of up to 3 words, the word being said in the signal colour. A scene can ask for `default` (y 1280),
`move` (with `caption_y`), `seam`, `top` (y 300, for layouts whose content is low) or `off` (only when the screen
text is the spoken line). The critic fails graphic text that touches the caption (COLLIDE).

## Variety (per video; the critic enforces the numbers)

- No layout twice in a row (REPEAT), and no two consecutive scenes that look the same.
- At least min(5, scenes / 2 + 1) distinct layouts (VARIETY).
- No non-presenter layout over 40% of the runtime (HOG).
- With a presenter: on screen 10-20% of the runtime by default (FACE). Put them on camera where a face earns it: the
  hook, the turn, the ask. For talking-head-led videos use `--profile speaker` (75%+, zoom changes instead of layout
  rotation).
- Open on the hook (OPEN): the presenter saying it from frame 0, or the hook in big type on frame 0. A graphic
  opening with a presenter in the video only warns: check that it is a visual hook, not a plain screen.

## Honesty

- Anything not real on screen is labelled ("demo", "illustration", "example"). A number that is not a sourced fact
  takes `"illustration": true`.
- No credentials, customer data or anyone's personal details on screen.
- Presenter footage only of yourself or of people who agreed to it; label AI-generated presenters the way each
  platform asks.

## Review

Look at the rendered frames (the critic sheet is built from the final MP4), never only the HTML or a preview: a
layout can look right in the page and still clip, overlap or drift in the render.
