#!/usr/bin/env python3
"""Render the approved voice pool reading one poem and build gallery/index.html.

Hover a card to hear that voice. Rerun after changing the pool in speak.py.
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import speak  # noqa: E402

POEM_TITLE = 'Langston Hughes — "Dreams" (1922)'
POEM_LINES = [
    "Hold fast to dreams",
    "For if dreams die",
    "Life is a broken-winged bird",
    "That cannot fly.",
    "Hold fast to dreams",
    "For when dreams go",
    "Life is a barren field",
    "Frozen with snow.",
]
POEM_SPOKEN = ("Hold fast to dreams, for if dreams die, life is a broken-winged "
               "bird that cannot fly. Hold fast to dreams, for when dreams go, "
               "life is a barren field, frozen with snow.")

AUDIO = HERE / "audio"
AUDIO.mkdir(exist_ok=True)


def slug(voice):
    return re.sub(r"[^a-z0-9]+", "_", voice.lower()).strip("_")


def tier(voice):
    if voice == "default":
        return "System default"
    if voice.startswith("kokoro:"):
        return "Kokoro neural"
    return "Apple Premium"


def label(voice):
    if voice == "default":
        return "Default"
    if voice.startswith("kokoro:"):
        return voice.split("_", 1)[1].capitalize()
    return voice.split(" (")[0]


def render(voice, text, out_m4a):
    if voice.startswith("kokoro:"):
        src = speak.synthesize_kokoro(text, voice.split(":", 1)[1])
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False)
        cmd = ["say", "-o", tmp.name] if voice == "default" else ["say", "-v", voice, "-o", tmp.name]
        subprocess.run(cmd + [text], check=True)
        src = tmp.name
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", src, str(out_m4a)],
                   check=True, capture_output=True)
    pathlib.Path(src).unlink(missing_ok=True)


def main():
    text = speak.apply_lexicon(POEM_SPOKEN)
    cards = []
    for voice in speak.build_pool():
        out = AUDIO / f"{slug(voice)}.m4a"
        if not out.exists():
            print(f"rendering {voice} -> {out.name}", flush=True)
            render(voice, text, out)
        cards.append({"voice": voice, "label": label(voice), "tier": tier(voice),
                      "audio": f"audio/{out.name}"})

    poem_html = "<br>".join(POEM_LINES)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>squawk voice gallery</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #14161a; color: #e8e6e3;
         margin: 0; padding: 2rem; }}
  h1 {{ font-weight: 600; }} h1 span {{ color: #7fb069; }}
  .poem {{ color: #9aa0a6; font-style: italic; margin: 0 0 1.5rem; line-height: 1.5; }}
  .poem b {{ color: #c9cdd2; font-style: normal; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
           gap: 0.8rem; }}
  .card {{ background: #1f232a; border: 1px solid #2c313a; border-radius: 10px;
           padding: 1rem; cursor: pointer; transition: all .15s; }}
  .card:hover {{ border-color: #7fb069; transform: translateY(-2px); }}
  .card.playing {{ background: #243524; border-color: #7fb069; }}
  .card .name {{ font-size: 1.15rem; font-weight: 600; }}
  .card .tier {{ font-size: 0.75rem; color: #9aa0a6; margin-top: 0.25rem; }}
  .tier-badge-Kokoro {{ color: #7fb069 !important; }}
  #arm {{ position: fixed; inset: 0; background: #14161acc; backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          font-size: 1.4rem; cursor: pointer; }}
</style>
</head>
<body>
<h1>squawk <span>voice gallery</span></h1>
<p class="poem"><b>{POEM_TITLE}</b><br>{poem_html}<br><br>
Hover a voice and it picks up the poem where the last one left off. Click to pin/unpin.</p>
<div class="grid" id="grid"></div>
<div id="arm">🔊 Click anywhere to arm the speakers</div>
<script>
const VOICES = {json.dumps(cards, indent=2)};
const grid = document.getElementById('grid');
let armed = false, pinned = null, ratio = 0;  // shared spot in the poem, 0..1
const players = VOICES.map(v => {{
  const audio = new Audio(v.audio);
  audio.preload = 'auto';
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `<div class="name">${{v.label}}</div>` +
    `<div class="tier ${{v.tier.startsWith('Kokoro') ? 'tier-badge-Kokoro' : ''}}">${{v.tier}}</div>`;
  const stop = () => {{ audio.pause(); card.classList.remove('playing'); }};
  const play = () => {{
    if (audio.duration > 0) audio.currentTime = ratio >= 0.99 ? 0 : ratio * audio.duration;
    audio.play().then(() => card.classList.add('playing')).catch(() => {{}});
  }};
  audio.ontimeupdate = () => {{
    if (!audio.paused && audio.duration > 0) ratio = audio.currentTime / audio.duration;
  }};
  audio.onended = () => {{ card.classList.remove('playing'); ratio = 0;
    if (pinned === audio) pinned = null; }};
  card.onmouseenter = () => {{ if (armed && !pinned) play(); }};
  card.onmouseleave = () => {{ if (pinned !== audio) stop(); }};
  card.onclick = () => {{
    if (pinned === audio) {{ pinned = null; stop(); return; }}
    if (pinned) {{ pinned.pause(); }}
    document.querySelectorAll('.card').forEach(c => c.classList.remove('playing'));
    pinned = audio; play();
  }};
  grid.appendChild(card);
  return audio;
}});
document.getElementById('arm').onclick = async (e) => {{
  for (const a of players) {{  // unlock every element inside the user gesture
    a.muted = true;
    try {{ await a.play(); }} catch (err) {{}}
    a.pause(); a.currentTime = 0; a.muted = false;
  }}
  armed = true;
  e.target.remove();
}};
</script>
</body>
</html>
"""
    (HERE / "index.html").write_text(page)
    print(f"built {HERE / 'index.html'} with {len(cards)} voices")


if __name__ == "__main__":
    main()
