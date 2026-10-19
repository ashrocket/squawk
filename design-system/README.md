# Squawk design system

Squawk is an open-source macOS speech layer. It gives each Codex and Claude Code agent a voice on one shared audio channel. Its job here is the landing page at https://squawk.raiteri.net, which explains the one-channel idea and sends the visitor to Get Squawk, the local voice samples or the public source.

This system formalizes the colours, type and layout that the live site already uses in `site/public/styles.css:3-11`. It makes no new visual choices. The six archived brand directions in `site/archive/brand/` are not this system; the live site does not use them.

## Voice

1. Say what Squawk does in one plain line. Example: "Voices for Codex and Claude Code. One audio channel."
2. Speak to the work, not the tool. Example: "Keep your eyes on the work."
3. State the default and the cost. Example: "Free under MIT. No Squawk account. Your Mac, your keys."
4. Use short pairs of sentences. Example: "Local first. Cloud when you choose."
5. Close with a light line. Example: "Built in public. Over and out."

## Colour

Source: `site/public/styles.css:3-11`. One theme (light). Ratios are WCAG contrast from the hex values, computed by `extract/contrast.py`.

| Token | Value | Role | Contrast |
|---|---|---|---|
| `paper` | #eeede5 | Page ground | Ink on paper 12.76 to 1 |
| `white` | #f7f6ef | Light surface | Ink on white 13.83 to 1 |
| `ink` | #242822 | Body text | Ink on paper 12.76 to 1 |
| `muted` | #656960 | Secondary text | 4.78 to 1 on paper; 5.18 to 1 on white |
| `line` | #d4d5c9 | Rules and borders | Decorative |
| `orange` | #dc492c | Accent: headline span, primary button, wordmark dot | 3.55 to 1 on paper: passes only for text 24px and up |
| `orange-dark` | #ba371e | Primary button hover | White on orange-dark 5.75 to 1 |
| `green` | #d8e7b5 | Text on the dark panel | 11.08 to 1 on dark |
| `dark` | #242b24 | Dark panel ground | |
| `button-label` | #fff | Button label text | 4.17 to 1 on orange at 14px: fails the 4.5 to 1 rule for small text |

Two pairs fail or sit near the limit. Both are real values in the live site, so formalize mode keeps them exact.

- `button-label` on `orange` at 14px is 4.17 to 1. It fails the 4.5 to 1 rule for small text. A darker label or a larger size would pass, but neither is in the code, so this system does not add one.
- `orange` on `paper` is 3.55 to 1. It passes only for text at 24px and up. It is used only for the 88px headline span.

`styles.css` also holds many literal colours outside these eight tokens, such as gradients and section tints. They are not formalized here.

## Type

Families, from code:

- Sans (body, headings, wordmark): `-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif`. Source: `site/public/styles.css:25`. The site loads no webfont.
- Mono (eyebrows, labels, signal layer): `ui-monospace,SFMono-Regular,Menlo,Consolas,monospace`. Source: `site/public/styles.css:12`.

Scale, from code. Where code sets no weight, tracking or line height, the table says "not set" and the browser default applies. The body sets no font size.

| Style | Size | Weight | Tracking | Where |
|---|---|---|---|---|
| wordmark | 31px | 800 | -1.7px | Header and footer wordmark (`styles.css:86`) |
| hero-h1 | clamp(56px, 6.4vw, 88px); token holds 88px | not set (browser default for h1) | -5px, line height 0.99 | Hero headline (`styles.css:141-143`) |
| nav-link | 13px | 600 | not set | Header links (`styles.css:96-97`) |
| lead | 17px | not set | not set | Hero sub-line, max width 430px (`styles.css:150-151`) |
| button | 14px | 650 | not set | Buttons (`styles.css:169-170`) |
| note | 11px | not set | not set | Hero footnote (`styles.css:191`) |
| eyebrow (mono) | 10px | 600 | 1.25px, uppercase, line height 1.6 | Eyebrow labels (`styles.css:121-125`). Recorded exception: tracked all-caps is a generic tell, kept because the live site uses it; do not extend it to new components. |

## Layout and spacing

- Content width: max 1280px, with 56px side gutters (`styles.css:56-57`).
- Header height: 110px (`styles.css:74`). The header has a 1px bottom rule in `line`.
- Hero: two columns, `1fr 1.08fr`, with a 54px gap (`styles.css:113-114`). Top padding 79px and bottom padding 92px (`styles.css:116-117`).
- Radius: 4px for buttons and the nav source link (`styles.css:106`, `167`); 7px for the dark display panel (`styles.css:236`); 18px for the radio case (`styles.css:202`); 100% for the round signal dot (`styles.css:136`).

## Logo and wordmark

- `assets/Logos/radio.svg`: the mark. A 48-unit square with an orange body, an ink antenna, an ink circle dial and a paper display band. It is the favicon (`site/public/index.html:10`) and the header mark at 35px (`site/public/index.html:21`).
- `assets/Logos/icon.png`: a 1024 by 1024 px raster copy of `site/public/icon.png`. No reference to it was found in `site/public/index.html`.
- The wordmark is type, not a file: the word "squawk" in the sans stack at 800 weight, 31px, -1.7px tracking, followed by an orange dot with -9px left margin (`styles.css:86`, `89-90`).
- Clear space and minimum size: not defined in code.
- Do not redraw or recolour the mark. Copy the file. Use the wordmark type only as set out above.

## Landing page anatomy

In order, from `site/public/index.html`:

1. Header (lines 20-25): wordmark, four nav links. Uses the wordmark, the nav links and the bordered `nav-source` link (`styles.css:103-107`).
2. Hero (lines 27-49): eyebrow with signal dot, headline, sub-line, primary button and text link, footnote, and the radio figure. This is `components/Hero`.
3. Principles strip (line 50): three short claims in a rule-bounded grid.
4. How it works (lines 51-59), Listen (60-71), Providers (72-81), Costs (82-116), Install (117-130), Open source (131), footer (133).

Sections 3 to 4 are not formalized in this system. They use literal values beyond the eight colour tokens.

## Status

formalized
