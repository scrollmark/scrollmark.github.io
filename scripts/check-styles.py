#!/usr/bin/env python3
"""Every class and custom property the markup uses must exist in the CSS.

This site had `.sticker--tangerine` on two elements in skills.html and no such
rule in styles.css. `.chip` carries no background of its own — the colour comes
entirely from a `.sticker--*` variant — so those two chips rendered as bare
text on no background. Nothing errored. Nothing logged. The palette had grown a
sixth colour, the card variants and text tokens were written for it, and the
sticker variant simply never was.

That is this project's recurring failure in a new place: something correct for
whoever wrote it, silently wrong for the next reader, with no signal either
way. A human noticed it in a browser. This is the machine noticing instead.

  python3 scripts/check-styles.py
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections import defaultdict

#: The checkers run against BUILT output. Templates contain Liquid, and a
#: half-rendered `{% if %}` is not what a reader ever sees — so a claim or a
#: class is only real once Eleventy has written it into _site.
SITE = pathlib.Path(__file__).resolve().parent.parent / "_site"


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


def main() -> int:
    css = strip_comments((SITE / "styles.css").read_text())  # passthrough-copied
    defined_classes = set(re.findall(r"\.([A-Za-z_][\w-]*)", css))
    defined_vars = set(re.findall(r"(--[\w-]+)\s*:", css))

    used_classes: dict[str, set[str]] = defaultdict(set)
    used_vars: dict[str, set[str]] = defaultdict(set)

    for name in re.findall(r"var\(\s*(--[\w-]+)", css):
        used_vars[name].add("styles.css")

    for f in sorted(SITE.glob("*.html")):
        text = f.read_text()
        for attr in re.findall(r'class="([^"]*)"', text):
            for c in attr.split():
                used_classes[c].add(f.name)
        for name in re.findall(r"var\(\s*(--[\w-]+)", text):
            used_vars[name].add(f.name)
        # An inline `style="--tilt: 3deg"` defines that property for its element.
        for name in re.findall(r'style="[^"]*?(--[\w-]+)\s*:', text):
            defined_vars.add(name)

    problems: list[str] = []
    for c, files in sorted(used_classes.items()):
        if c not in defined_classes:
            problems.append(f'class .{c} used in {", ".join(sorted(files))} — no rule in styles.css')
    for v, files in sorted(used_vars.items()):
        if v not in defined_vars:
            problems.append(f'var({v}) used in {", ".join(sorted(files))} — never defined')

    # Colour families should be complete. A palette colour with a card variant
    # but no sticker variant is exactly how tangerine went missing.
    families = {m for m in re.findall(r"--se-([a-z]+):", css)}
    for fam in sorted(families):
        for kind in ("sticker", "card"):
            if f".{kind}--{fam}" not in css and any(
                f"{kind}--{fam}" in f.read_text() for f in SITE.glob("*.html")
            ):
                problems.append(f".{kind}--{fam} is used but not defined")

    # `.marker` is `white-space: nowrap`, so a trailing space inside a marked
    # phrase is not a break opportunity — and the template puts no whitespace
    # between </span> and what follows. A headline written that way cannot wrap
    # after the marker and runs off its column. It happened on the home page:
    # "social media " + "agents." rendered 147px past its own box, with the
    # last word clipped by the graphic beside it. Invisible in the source, and
    # only at some widths.
    hero = SITE.parent / "src" / "_data" / "hero.json"
    if hero.is_file():
        import json
        for page, block in json.loads(hero.read_text()).items():
            head = block.get("headline", {})
            marked, after = head.get("marked", ""), head.get("after", "")
            if marked != marked.rstrip():
                problems.append(
                    f'hero.{page}: marked phrase {marked!r} ends with a space. '
                    "`.marker` is nowrap, so that space cannot break — move it "
                    "to the front of `after`.")
            elif after and not after[0] in " ,.;:!?" and not marked.endswith(("-", "—")):
                problems.append(
                    f'hero.{page}: {marked!r} runs straight into {after!r} with no '
                    "separator; the template adds none after the marker.")

    print(f"  {len(used_classes)} classes and {len(used_vars)} custom properties checked")
    for p in problems:
        print(f"  FAIL  {p}", file=sys.stderr)
    if not problems:
        print("  every class and property the markup uses is defined")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
