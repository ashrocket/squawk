# Sources

Project root: the squawk project folder, which is the parent of this `design-system/` folder. Every `path:line` in this system is relative to it.

## Read

- `site/public/styles.css`: lines 1-30 (`:root` tokens at 3-12, body at 21-27), 55-140 (wrap, header, wordmark, nav, hero, eyebrow, signal dot, h1), 150-300 (hero copy, buttons, text link, radio case and display, frequency scale), 412-430 (principles strip), plus single cited lines. Read by line range; the whole file (2008 lines) was not loaded.
- `site/public/index.html`: lines 1-60 (head, header, hero copy and figure, principles strip, first section) and lines 117-133 (install, open source, footer) for the section map.
- `site/public/radio.svg`: read in full (429 bytes) to describe the mark.
- `site/public/icon.png`: pixel size checked with `sips` (1024 by 1024). Copied, not viewed.

## Copied

- `site/public/radio.svg` to `assets/Logos/radio.svg`.
- `site/public/icon.png` to `assets/Logos/icon.png`.

## Inputs from ashcode

- The shared spec `SPEC.md` in the workspace `design-systems/` folder (outside this project), the profile `profiles/squawk.json` and the evidence digest. They set the scope and the classification `formalize_from_code`.

## Not read

- The project `README.md`, `app/` sources, `site/public/docs/*`, `site/archive/brand/*` and the other site pages. The brief limits the system to the live landing page and its tokens. The six archived brand directions were not read and are not the system.

## Generated

- `tokens.css` from `tokens.json` by `extract/gen_tokens_css.py`.
