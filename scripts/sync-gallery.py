#!/usr/bin/env python3
"""Build the gallery's data from the pack scrollmark/social-skills publishes.

A template on this site is two halves: a *format* (the shape — how many
scenes, what frame, whether it speaks) and a *style* preset (the look —
caption colour, card colours, type). Which pairs are worth showing is
curation, and it used to live HERE, as two hand-kept Python literals. It does
not any more: the pairings are `template` assets in the published pack, and
this file enumerates them.

That is the whole point of the move. The editor cannot see a commit to this
site, so a pairing curated here could never reach the product. Now both are
consumers of one published index, and this script is a renderer.

One file is read instead of thirty-two: the pack carries every style's JSON
and every format's frontmatter verbatim, so a colour on this site is still the
colour that repo would actually render. Nothing here invents a value; a
template naming a format or style the pack does not have is an error there,
before it ever reaches this script.

What stays site-owned is presentation: the ORDER the cards appear in, and the
lossy projection below — `titleScale`, `captionBottom`, the five-colour swatch
— which are instructions for drawing a thumbnail in CSS and have no business
in the source of truth.

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
PACK_INDEX = "packs/index.json"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "_data" / "gallery.json"

#: The order the cards are read in, by template id. Presentation, and the one
#: piece of curation that stays on this site: which cards a visitor reads first
#: says nothing about what the templates ARE, and the editor has its own idea
#: of what to show first.
#:
#: The five recreations of the reference templates lead, because they are the
#: ones with a moving preview and the ones somebody arriving is most likely to
#: be looking for. The rest is a hand-made sequence that alternates formats so
#: no two neighbours are the same shape, which pack order -- alphabetical by
#: filename -- would quietly undo.
#:
#: Anything not named here follows, in pack order, so a newly published
#: template appears rather than vanishing. An id here that no longer exists is
#: an error: losing a card is exactly what a migration does quietly.
ORDER = [
    "template/daily-recap-summer-scrapbook",
    "template/cinematic-weekend-gothic",
    "template/brand-origin-editorial-sage",
    "template/titled-video-postcard-serif",
    "template/daily-recap-pov-serif",
    "template/explainer-clean-corporate",
    "template/cinematic-documentary",
    "template/timeline-explainer-3b1b-dark",
    "template/product-launch-tech-startup",
    "template/brand-origin-warm-minimal",
    "template/talking-head-loud-social",
    "template/daily-recap-vhs-90s",
    "template/titled-video-analog-editorial",
    "template/brand-origin-magazine-cover",
    "template/timeline-explainer-lookbook-sage",
    "template/talking-head-pov-quiet",
    "template/cinematic-neon-sign",
    "template/daily-recap-wet-paint",
    "template/titled-video-chrome-y2k",
    "template/brand-origin-zine-glitch",
    "template/timeline-explainer-arcade-crt",
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


#: How tall each frame is, in the pixels a composer fontSize is stated in.
#: `source` keeps the footage's own frame, and 1280 is the 3:2 the gallery
#: stands in for it with.
FRAME_HEIGHTS = {"9:16": 1920, "16:9": 1080, "1:1": 1080, "4:5": 1350, "source": 1280}


def frame_height(aspect: str) -> int:
    return FRAME_HEIGHTS.get(aspect, 1920)


def named_face(stack: str) -> str:
    """The first family the preset actually names, system faces included.

    Different from `face` on purpose. `face` answers "which webfont should the
    page load", and a system family is not one -- but it IS what a render uses,
    so a card that prints `face`'s answer says EB Garamond about a preset whose
    first choice is Georgia.
    """
    for name in stack.split(","):
        cleaned = name.strip().strip("\"'")
        if cleaned and cleaned.lower() not in GENERIC_FAMILIES:
            return cleaned
    return ""


def face(stack: str) -> str:
    """The first real family in a CSS stack.

    The preset names a stack so it degrades well in a render. A web page
    loading a webfont needs the family on its own, and only the first one is
    the face the preset means -- the rest are what to do when it is missing.
    """
    for name in stack.split(","):
        cleaned = name.strip().strip("\"'")
        lowered = cleaned.lower()
        if cleaned and lowered not in GENERIC_FAMILIES and lowered not in SYSTEM_FACES:
            return cleaned
    return ""


#: CSS keywords, which are not faces anyone can load.
GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy",
                    "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace",
                    "ui-rounded", "math", "emoji", "fangsong"}

#: Faces that exist on a device rather than on Google Fonts. Naming one in the
#: stylesheet request is not a harmless miss: the whole css2 request 400s, so
#: ONE system face means NONE of the real ones load.
SYSTEM_FACES = {"courier new", "georgia", "impact", "helvetica", "arial",
                "didot", "menlo", "sfmono-regular", "times new roman",
                "palatino", "verdana", "tahoma", "inter"}


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


def counts(skills: Path | None) -> dict[str, int]:
    """How many formats and presets exist, not how many are paired here.

    Read rather than written down. The page quotes both numbers, and a number
    a person maintains on a page about a repository is the drift this site has
    already shipped six times.

    From the pack index, which states them, rather than from the GitHub
    contents API. That API is a 60-an-hour-per-IP budget CI shares with every
    other runner, and the accuracy job duly started failing with "rate limit
    exceeded" on a change that touched no counts at all. The index is a few KB
    on raw.githubusercontent.com with no such budget, and it is the same file
    the rest of this script already reads.
    """
    read = (lambda path: read_local(skills, path)) if skills else read_live
    index = json.loads(read(PACK_INDEX))
    packs = index.get("packs") or []
    available = (packs[0].get("assetCounts") if packs else {}) or {}
    return {"formats": available.get("format", 0), "styles": available.get("style", 0)}


def title_placement(title: dict) -> dict:
    """Where the preset puts its title, as fractions of the frame.

    The preset has always said this -- `rect` is `[x, y, w, h]` and `align`
    names the horizontal one -- and the preview threw all of it away, pinning
    every title to the top left corner. That is wrong for most of the
    collection and conspicuously wrong for the five recreations: four of them
    centre the title on both axes and one (`postcard-serif`) sits it near the
    top, and the preview drew all five identically.

    Reported as the rect's CENTRE rather than its top edge, because a card is
    a box its type is centred in: a rect from 0.38 to 0.56 puts type at 0.47,
    not at 0.38. A preset that states no rect gets nothing back and keeps the
    flow position -- the rect comes from its storyboard in that case, and
    inventing one here would be the preview claiming to know a number the
    preset does not state.
    """
    rect = title.get("rect")
    if not (isinstance(rect, list) and len(rect) == 4):
        return {}
    x, y, w, h = rect
    return {
        "titleLeft": round(x, 4),
        "titleWidth": round(w, 4),
        "titleTop": round(y + h / 2, 4),
        "titleAlign": title.get("align", "left"),
    }


def load_pack(read) -> tuple[dict | None, list[str]]:
    """The index, then the one pack it names.

    Two reads rather than a hardcoded filename: the index is the thing that
    knows the current version, and pinning a version here would leave this site
    rendering an old pack for as long as nobody noticed.
    """
    try:
        index = json.loads(read(PACK_INDEX))
    except Exception as e:  # noqa: BLE001 — the reason belongs in the report
        return None, [f"{PACK_INDEX}: {e}"]
    packs = index.get("packs") or []
    if not packs:
        return None, [f"{PACK_INDEX}: no packs listed"]
    entry = packs[0]
    try:
        return json.loads(read(f"packs/{entry['url']}")), []
    except Exception as e:  # noqa: BLE001
        return None, [f"packs/{entry.get('url')}: {e}"]


def in_order(templates: list[dict]) -> tuple[list[dict], list[str]]:
    """ORDER first, then everything else in pack order.

    Ordering is the one piece of curation that stays on this site, because it
    is presentation: which cards a visitor reads first says nothing about what
    the templates are.
    """
    by_id = {template["id"]: template for template in templates}
    problems = [f"ORDER names {i}, which is not in the pack"
                for i in ORDER if i not in by_id]
    first = [by_id[i] for i in ORDER if i in by_id]
    rest = [t for t in templates if t["id"] not in set(ORDER)]
    return first + rest, problems


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

    pack, pack_problems = load_pack(read)
    problems += pack_problems
    if pack is None:
        return entries, problems

    by_id = {asset["id"]: asset for asset in pack.get("assets", [])}
    templates = [a for a in pack.get("assets", []) if a.get("kind") == "template"]
    ordered, order_problems = in_order(templates)
    problems += order_problems

    for template in ordered:
        values = template.get("values", {})
        why = values.get("why", "")
        format_ref, style_ref = values.get("formatRef"), values.get("styleRef")
        fmt_asset, style_asset = by_id.get(format_ref), by_id.get(style_ref)
        # Named rather than skipped. The pack refuses an unresolvable ref at
        # build time, so reaching here means the pack and this script disagree
        # about what a ref is -- which is worth a failure, not a shorter page.
        if fmt_asset is None or fmt_asset.get("kind") != "format":
            problems.append(f"{template['id']}: {format_ref} is not a format in the pack")
            continue
        if style_asset is None or style_asset.get("kind") != "style":
            problems.append(f"{template['id']}: {style_ref} is not a style in the pack")
            continue

        fmt_name = format_ref.split("/", 1)[1]
        style_name = style_ref.split("/", 1)[1]
        # The format's frontmatter and the style's JSON block, carried through
        # the pack unchanged. Reading them here rather than from markdown is
        # what makes this a renderer: one fetch, and the same bytes the editor
        # applies.
        fmt = fmt_asset.get("values", {})
        style_values = style_asset.get("values", {})
        style_meta = {"description": style_asset.get("description", "")}
        preview = values.get("previewCopy") or {}

        colours, colour_problems = swatch(style_values)
        if colour_problems:
            problems += [f"style {style_name}: {c}" for c in colour_problems]
            continue
        captions = style_values.get("captions", {})
        title_card = style_values.get("cards", {}).get("title", {})
        placement = title_placement(title_card)
        # Empty strings are dropped rather than carried: Liquid treats "" as
        # truthy, so a key present-but-empty renders its label and no value —
        # a spec row reading "Music" with nothing after it. Absent is absent.
        entry = {
            "format": fmt_name,
            "style": style_name,
            "why": why,
            "title": fmt.get("title", fmt_name),
            "previewTitle": preview.get("title", ""),
            "previewCaption": preview.get("caption", ""),
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
            # The preset's own size as a fraction of the frame it is drawn in,
            # so a preview shows the proportion the preset asks for rather than
            # one size for every card.
            #
            # Divided by the frame's OWN height, not always 1920: a composer
            # fontSize is pixels, and the same 196px is a tenth of a portrait
            # frame and a sixth of a landscape one. Dividing everything by 1920
            # drew every landscape card a third too small.
            "titleScale": round(
                title_card.get("fontSize", 84)
                / frame_height(fmt.get("aspect", "9:16")), 4),
            # The outline, relative to the type it outlines -- the same ratio
            # the editor stores, so it survives a change of frame the way the
            # size does.
            "captionStrokeEm": round(
                captions.get("strokeWidth", 0) / max(1, captions.get("fontSize", 56)), 4),
            "captionScale": round(
                captions.get("fontSize", 56) / frame_height(fmt.get("aspect", "9:16")), 4),
            # What to load, and what to say. They differ whenever a preset
            # names a system face first.
            "titleFace": face(title_card.get("fontFamily", "")),
            "captionFace": face(captions.get("fontFamily", "")),
            "titleFaceNamed": named_face(title_card.get("fontFamily", "")),
            "captionFaceNamed": named_face(captions.get("fontFamily", "")),
            "uppercase": captions.get("uppercase", False),
            # How far up from the bottom edge the caption sits, as a fraction
            # of the frame. Every preset states one and the preview honoured
            # none of them, holding all 21 against the bottom -- which is
            # roughly right for the eighteen that ask for 0.10-0.16 and wrong
            # by a third of a frame for the two `pov` presets, whose captions
            # sit near the middle.
            "captionBottom": round(captions["bottom"], 4)
            if isinstance(captions.get("bottom"), (int, float)) else "",
            **placement,
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

    available = counts(args.skills)
    rendered = json.dumps(
        {"source": source, "counts": available, "entries": entries}, indent=2) + "\n"

    if args.check:
        current = json.loads(OUT.read_text()) if OUT.is_file() else {}
        # `source` records where the data was last read from and is expected to
        # differ between a checkout and the live repo, so it is not drift.
        same = (current.get("entries") == entries
                and current.get("counts") == counts(args.skills))
        print("gallery.json matches the repo" if same
              else "gallery.json is stale — re-run without --check")
        return 0 if same else 1

    OUT.write_text(rendered)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(entries)} pairings from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
