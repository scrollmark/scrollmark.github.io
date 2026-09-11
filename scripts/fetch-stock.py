#!/usr/bin/env python3
"""Fetch the gallery's stock frames, and record where each one came from.

The preview cards were flat colour before this: the style's colours on an
empty panel, which is a swatch rather than a template. A template is type over
a picture, and until a picture is behind it the card cannot show the thing it
is selling.

Photographs come from Openverse, filtered to CC0 — public domain, no licence
notice required — and every one is recorded in `src/_data/stock.json` with its
creator, its source page and its licence anyway. Free of obligation is not the
same as free of provenance, and a page that claims its colours are read from a
repository should be able to say where its photographs are from too.

  python3 scripts/fetch-stock.py            # fetch anything missing
  python3 scripts/fetch-stock.py --refetch  # fetch everything again

Crops to the frame its pairing is composed for, because that is what the card
draws: a 9:16 format gets a 9:16 still. Uses `sips`, which ships with macOS.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STOCK_DIR = ROOT / "stock"
OUT = ROOT / "src" / "_data" / "stock.json"
API = "https://api.openverse.org/v1/images/"

#: pairing -> what the picture should show. One line each, and the whole table
#: is the knob: a new pairing needs a query here and nothing else.
SUBJECTS = {
    "explainer+clean-corporate": "desk laptop notebook workspace",
    "cinematic+documentary": "mountain fog landscape moody",
    "timeline-explainer+3b1b-dark": "night sky stars long exposure",
    "product-launch+tech-startup": "smartphone desk minimal dark",
    "brand-origin+warm-minimal": "hands pottery workshop craft",
    "talking-head+loud-social": "microphone studio recording",
    "daily-recap+vhs-90s": "skateboard street night city",
    "titled-video+analog-editorial": "coffee cup wooden table morning",
    "brand-origin+magazine-cover": "textile fabric fashion detail",
    "daily-recap+summer-scrapbook": "friends summer beach sun",
    "cinematic+weekend-gothic": "neon sign night rain street",
    "timeline-explainer+lookbook-sage": "green plant leaves wall",
    "titled-video+postcard-serif": "city street autumn buildings",
    "talking-head+pov-quiet": "window light quiet room",
}

#: The frame each pairing is composed for. Kept here rather than read from
#: gallery.json so this script can run before that file exists.
ASPECTS = {"9:16": (450, 800), "16:9": (800, 450), "source": (600, 400)}


def search(query: str) -> dict | None:
    url = API + "?" + urllib.parse.urlencode(
        {"q": query, "license": "cc0", "page_size": 8, "mature": "false"})
    request = urllib.request.Request(url, headers={"User-Agent": "scrollmark-gallery/1.0"})
    with urllib.request.urlopen(request, timeout=40) as response:
        results = json.load(response).get("results", [])
    for result in results:
        if result.get("url") and (result.get("width") or 0) >= 800:
            return result
    return results[0] if results else None


def download(url: str, target: Path) -> None:
    """With a User-Agent. Several hosts that Openverse indexes -- Flickr among
    them -- answer Python's default agent with a 403."""
    request = urllib.request.Request(url, headers={"User-Agent": "scrollmark-gallery/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())


def crop(source: Path, width: int, height: int) -> None:
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "62",
                    "-Z", str(max(width, height) * 2), str(source)],
                   check=True, capture_output=True)
    subprocess.run(["sips", "-c", str(height), str(width), str(source)],
                   check=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--aspects", type=Path, help="gallery.json, for each pairing's frame")
    args = ap.parse_args()

    aspects = {}
    if args.aspects and args.aspects.is_file():
        for entry in json.loads(args.aspects.read_text())["entries"]:
            aspects[f"{entry['format']}+{entry['style']}"] = entry.get("aspect", "9:16")

    STOCK_DIR.mkdir(exist_ok=True)
    credits = json.loads(OUT.read_text()) if OUT.is_file() else {}
    for pairing, query in SUBJECTS.items():
        name = pairing.replace("+", "--") + ".jpg"
        target = STOCK_DIR / name
        if target.is_file() and not args.refetch and pairing in credits:
            continue
        found = search(query)
        if not found:
            # One retry on the first two words. A narrow query returning
            # nothing is a bad query, not a reason to leave a card blank.
            found = search(" ".join(query.split()[:2]))
        if not found:
            print(f"{pairing}: nothing found for {query!r}", file=sys.stderr)
            return 1
        download(found["url"], target)
        width, height = ASPECTS.get(aspects.get(pairing, "9:16"), ASPECTS["9:16"])
        crop(target, width, height)
        credits[pairing] = {
            "file": f"stock/{name}",
            "title": found.get("title") or "",
            "creator": found.get("creator") or "unknown",
            "source": found.get("foreign_landing_url") or found.get("url"),
            "license": (found.get("license") or "cc0").upper(),
            "query": query,
        }
        print(f"{pairing}: {credits[pairing]['creator']} — {target.stat().st_size // 1024}KB")
    OUT.write_text(json.dumps(credits, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(credits)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
