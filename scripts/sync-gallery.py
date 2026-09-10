#!/usr/bin/env python3
"""Build the gallery's data from scrollmark/social-skills.

A template on this site is two halves that already exist in that repo: a
*format* (the shape — how many scenes, what frame, whether it speaks) and a
*style* preset (the look — caption colour, card colours, type). Ten formats and
fourteen styles is a hundred and forty pairings, and a page listing all of them
would be a page nobody reads. So the pairings are curated, by hand, below —
this file is where the gallery grows.

Everything else is read rather than written: the format frontmatter and the
style JSON come out of the skills repo, so a colour on this site is the colour
that repo would actually render. Nothing here invents a value; a pairing that
names a format or a style the repo does not have is an error, not a blank card.

  python3 scripts/sync-gallery.py                       # read the live repo
  python3 scripts/sync-gallery.py --skills ../social-skills   # read a checkout

Writes src/_data/gallery.json. Commit the result: GitHub Pages builds this site
with no network and no checkout of the skills repo, so the data has to be in
the tree. `check-accuracy.py` is what notices when it drifts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = "scrollmark/social-skills"
RAW = f"https://raw.githubusercontent.com/{REPO}/master"
FORMATS_DIR = "skills/video-formats/references/formats"
STYLES_DIR = "src/video_studio/styles"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "_data" / "gallery.json"

#: The gallery, as a list. Each entry is a format, a style, and one line saying
#: why the two belong together — the only sentence on the card that is written
#: here rather than read from the repo.
PAIRINGS = [
    ("explainer", "clean-corporate",
     "A concept walked through end to end, in the flat palette a deck already uses."),
    ("cinematic", "documentary",
     "Cut to the track, captions off, colour left alone. The look is the footage."),
    ("timeline-explainer", "3b1b-dark",
     "Numbered beats on a dark ground, the way a maths lecture counts."),
    ("product-launch", "tech-startup",
     "Three capabilities and a name to land, in a palette built to look shipped."),
    ("brand-origin", "warm-minimal",
     "One from-here-to-there story, told quietly enough to be believed."),
    ("talking-head", "loud-social",
     "One person to camera, captions loud enough to work on mute."),
]


def read_live(path: str) -> str:
    with urllib.request.urlopen(f"{RAW}/{path}", timeout=30) as r:
        return r.read().decode()


def read_local(root: Path, path: str) -> str:
    return (root / path).read_text()


def frontmatter(text: str) -> dict[str, str]:
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not fm:
        return {}
    out = {}
    for line in fm.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def json_block(text: str) -> dict:
    block = re.search(r"```json\n(.*?)```", text, re.S)
    return json.loads(block.group(1)) if block else {}


def swatch(style_values: dict) -> tuple[dict, list[str]]:
    """The colours a card previews with, taken from the preset itself.

    A preview whose colours were picked here would be a drawing of a style
    rather than the style, and would stay pretty while the preset changed
    underneath it. So nothing is invented: a preset that does not say what
    colour its captions are produces a problem, not a default.

    Two things this got wrong before, both of which published a colour the
    preset does not have. `captions.color` defaulted to white -- `loud-social`
    has no `color` at all, it has a four-colour `palette`, and the card claimed
    white. And `stroke` stood in for `highlight` when there was none, which
    paints an OUTLINE as a FILL: `loud-social`'s black 14px stroke became a
    black caption word on a navy card.
    """
    captions = style_values.get("captions", {})
    title = style_values.get("cards", {}).get("title", {})
    problems = []
    if not ("bg" in title and "fg" in title):
        problems.append("cards.title has no bg/fg — nothing to paint a card with")
    palette = captions.get("palette") or []
    caption = captions.get("color") or (palette[0] if palette else None)
    if caption is None:
        problems.append("captions has neither a color nor a palette")
    # The emphasised word: the preset's own highlight, or the second colour of
    # a palette that cycles per word, which is what that word would be.
    accent = captions.get("highlight") or (palette[1] if len(palette) > 1 else caption)
    out = {"bg": title.get("bg"), "fg": title.get("fg"),
           "caption": caption, "accent": accent}
    # The outline is a real caption property and the reason these colours are
    # legible over footage at all, so the preview draws it rather than leaving
    # the type to fend for itself against a card background it never sits on.
    if captions.get("stroke"):
        out["stroke"] = captions["stroke"]
    return ({k: v for k, v in out.items() if v is not None}, problems)


def build(read) -> tuple[list[dict], list[str]]:
    """Every pairing, resolved through *read*, plus whatever went wrong.

    Split out from main() so `check-accuracy.py` compares the committed file
    against THIS code rather than against a second implementation of it. A
    second implementation agreeing with the first is not evidence: the first
    version of that check re-derived the swatch and duly certified a colour
    the preset does not define, because both copies invented the same default.
    """
    entries: list[dict] = []
    problems: list[str] = []
    for fmt_name, style_name, why in PAIRINGS:
        try:
            fmt = frontmatter(read(f"{FORMATS_DIR}/{fmt_name}.md"))
        except Exception as e:  # noqa: BLE001 — the reason belongs in the report
            problems.append(f"format {fmt_name}: {e}")
            continue
        if not fmt:
            problems.append(f"format {fmt_name}: no frontmatter to read")
            continue
        try:
            style_text = read(f"{STYLES_DIR}/{style_name}.md")
        except Exception as e:  # noqa: BLE001
            problems.append(f"style {style_name}: {e}")
            continue
        style_meta, style_values = frontmatter(style_text), json_block(style_text)
        if not style_values:
            problems.append(f"style {style_name}: no json block")
            continue
        colours, colour_problems = swatch(style_values)
        if colour_problems:
            problems += [f"style {style_name}: {c}" for c in colour_problems]
            continue
        captions = style_values.get("captions", {})
        # Empty strings are dropped rather than carried: Liquid treats "" as
        # truthy, so a key present-but-empty renders its label and no value —
        # a spec row reading "Music" with nothing after it. Absent is absent.
        entry = {
            "format": fmt_name,
            "style": style_name,
            "why": why,
            "title": fmt.get("title", fmt_name),
            "description": fmt.get("description", ""),
            "styleDescription": style_meta.get("description", ""),
            "aspect": fmt.get("aspect", ""),
            "alsoWorks": fmt.get("alsoWorks", ""),
            "scenes": fmt.get("scenes", ""),
            "sceneSeconds": fmt.get("sceneSeconds", ""),
            "captions": fmt.get("captions", ""),
            "narration": fmt.get("narration", ""),
            "music": fmt.get("music", ""),
            "needs": fmt.get("needs", ""),
            "swatch": colours,
            "fontFamily": captions.get("fontFamily", ""),
            "uppercase": captions.get("uppercase", False),
        }
        entries.append({k: v for k, v in entry.items() if v != "" and v is not False})
    return entries, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills", type=Path,
                    help="a local social-skills checkout to read instead of the live repo")
    ap.add_argument("--check", action="store_true",
                    help="report drift and change nothing")
    args = ap.parse_args()

    read = (lambda p: read_local(args.skills, p)) if args.skills else read_live
    # Deliberately not the checkout path: it names somebody's laptop, and what
    # the file is claiming is which repo the values came from.
    source = f"{REPO}@master" if not args.skills else f"{REPO}@local checkout"
    entries, problems = build(read)

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    rendered = json.dumps({"source": source, "entries": entries}, indent=2) + "\n"

    if args.check:
        current = json.loads(OUT.read_text()) if OUT.is_file() else {}
        # `source` records where the data was last read from and is expected to
        # differ between a checkout and the live repo, so it is not drift.
        same = current.get("entries") == entries
        print("gallery.json matches the repo" if same
              else "gallery.json is stale — re-run without --check")
        return 0 if same else 1

    OUT.write_text(rendered)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(entries)} pairings from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
