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
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

#: Contrast a title must clear against the still behind it.
#:
#: 3:1 rather than 4.5:1 because these titles are large text, which is the
#: threshold WCAG sets for it -- and because some are unreachable otherwise: a
#: mid-tone title like weekend-gothic's vermilion cannot clear 4.5 against ANY
#: photograph, light or dark, since it sits in the middle of the range itself.
#: Where a still can do better than 3 it is taken; this is the floor, not the aim.
TITLE_CONTRAST_FLOOR = 3.0

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
    "cinematic+neon-sign": "neon bar sign night",
    "daily-recap+wet-paint": "graffiti wall paint colourful",
    "titled-video+chrome-y2k": "computer keyboard dark tech",
    "brand-origin+zine-glitch": "concrete wall texture grey",
    "timeline-explainer+arcade-crt": "arcade machine screen retro",
}

#: The frame each pairing is composed for. Kept here rather than read from
#: gallery.json so this script can run before that file exists.
ASPECTS = {"9:16": (450, 800), "16:9": (800, 450), "source": (600, 400)}


def luminance(rgb: tuple[float, float, float]) -> float:
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def hex_luminance(value: str) -> float:
    h = value.lstrip("#")
    return luminance(tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def contrast(a: float, b: float) -> float:
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def band_luminance(path: Path) -> float | None:
    """The mean tone of the strip a title sits in, not of the whole picture.

    A photograph that averages mid-grey can still be black where the type goes.
    Only the band matters, so only the band is measured.
    """
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", "crop=iw:ih/5:0:ih*0.28,scale=1:1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    if len(result.stdout) < 3:
        return None
    return luminance(tuple(b / 255 for b in result.stdout[:3]))


def search_many(query: str, limit: int = 8) -> list[dict]:
    url = API + "?" + urllib.parse.urlencode(
        {"q": query, "license": "cc0", "page_size": limit, "mature": "false"})
    request = urllib.request.Request(url, headers={"User-Agent": "scrollmark-gallery/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.load(response).get("results", [])
    except Exception:  # noqa: BLE001 -- a dead query is not a dead run
        return []


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


#: Words that push a search toward the tone a title needs. A light title wants
#: a dark band under it and vice versa, and the surest way to get one from a
#: stock search is to ask for it.
DARKER = ("night", "dark", "shadow", "low light", "silhouette")
LIGHTER = ("bright", "white", "minimal", "daylight", "pale")


def rebalance(pairing: str, query: str, title_hex: str, size: tuple[int, int],
              target: Path) -> tuple[dict, float] | None:
    """Find a still the title can be read against, and say what it measured.

    Tries the plain query first: a photograph that already works is better than
    one bent toward a tone. Only when that fails does it ask for the tone, and
    each candidate is downloaded and MEASURED rather than assumed -- "night" in
    a search returns plenty of brightly lit pictures of nights.
    """
    title = hex_luminance(title_hex)
    want_dark = title > 0.35
    words = DARKER if want_dark else LIGHTER
    best: tuple[dict, float] | None = None
    keep = target.with_name(target.stem + ".best.jpg")
    # The incumbent counts as a candidate: a swap that makes a card worse is
    # not a fix, and the floor is not always reachable.
    if target.is_file():
        band = band_luminance(target)
        if band is not None:
            best = ({"incumbent": True}, contrast(title, band))
            shutil.copy2(target, keep)
    for extra in ("",) + words:
        for found in search_many(f"{query} {extra}".strip()):
            if not found.get("url"):
                continue
            try:
                download(found["url"], target)
                crop(target, *size)
            except Exception:  # noqa: BLE001 -- a dead image is not a dead run
                continue
            band = band_luminance(target)
            if band is None:
                continue
            ratio = contrast(title, band)
            if best is None or ratio > best[1]:
                best = (found, ratio)
                shutil.copy2(target, keep)   # the file, not just the number
            if ratio >= TITLE_CONTRAST_FLOOR:
                shutil.copy2(keep, target)
                keep.unlink(missing_ok=True)
                return best
    if keep.is_file():
        shutil.copy2(keep, target)
        keep.unlink(missing_ok=True)
    return best


def measure_into(credits: dict, gallery: dict) -> int:
    """Record what each still measures, and which bytes it measured.

    The measurement needs ffmpeg; CI does not have it and a site that checks
    its own copy should not need a media toolchain to do it. So the number is
    recorded here, next to a hash of the exact file it came from -- change the
    picture without re-running this and the hash stops matching, which is the
    failure that matters. A number with no bytes attached would rot silently.
    """
    written = 0
    for entry in gallery["entries"]:
        pairing = f"{entry['format']}+{entry['style']}"
        shot = credits.get(pairing)
        if not shot:
            continue
        path = ROOT / shot["file"]
        if not path.is_file():
            continue
        shot["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        band = band_luminance(path)
        if band is None:
            continue
        shot["bandLuminance"] = round(band, 6)
        if entry["swatch"].get("bg") == "transparent":
            shot["titleContrast"] = round(
                contrast(hex_luminance(entry["swatch"]["fg"]), band), 2)
        else:
            shot.pop("titleContrast", None)
        written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--measure", action="store_true",
                    help="record each still's hash and what it measures")
    ap.add_argument("--rebalance", action="store_true",
                    help="replace stills whose title cannot be read against them")
    ap.add_argument("--aspects", type=Path, help="gallery.json, for each pairing's frame")
    args = ap.parse_args()

    aspects = {}
    if args.aspects and args.aspects.is_file():
        for entry in json.loads(args.aspects.read_text())["entries"]:
            aspects[f"{entry['format']}+{entry['style']}"] = entry.get("aspect", "9:16")

    STOCK_DIR.mkdir(exist_ok=True)
    credits = json.loads(OUT.read_text()) if OUT.is_file() else {}

    # Stills we made ourselves. They are not fetched, so `--rebalance` leaves
    # them alone and `--measure` records them like any other -- but their
    # provenance is "ours", not a licence somebody else granted.
    OURS = {
        "daily-recap+summer-scrapbook",
        "daily-recap+pov-serif",
        "cinematic+weekend-gothic",
        "brand-origin+editorial-sage",
        "titled-video+postcard-serif",
    }
    for pairing in OURS:
        name = pairing.replace("+", "--") + ".jpg"
        if (STOCK_DIR / name).is_file():
            clip = STOCK_DIR / (pairing.replace("+", "--") + ".mp4")
            credits[pairing] = {
                **credits.get(pairing, {}),
                "file": f"stock/{name}",
                "title": "Scrollmark template still",
                "creator": "Scrollmark",
                "source": "in-house",
                "license": "OWN",
                # A card with a clip plays it on hover; the still is its poster,
                # so a card with no clip, or a visitor who never hovers, is
                # exactly what it was.
                **({"clip": f"stock/{clip.name}", "clipBytes": clip.stat().st_size}
                   if clip.is_file() else {}),
            }

    if args.measure:
        if not args.aspects or not args.aspects.is_file():
            raise SystemExit("--measure needs --aspects gallery.json for the swatches")
        n = measure_into(credits, json.loads(args.aspects.read_text()))
        OUT.write_text(json.dumps(credits, indent=2, sort_keys=True) + "\n")
        print(f"measured {n} still(s)")
        return 0

    if args.rebalance:
        if not args.aspects or not args.aspects.is_file():
            raise SystemExit("--rebalance needs --aspects gallery.json for the swatches")
        gallery = json.loads(args.aspects.read_text())
        changed = 0
        for entry in gallery["entries"]:
            pairing = f"{entry['format']}+{entry['style']}"
            swatch = entry["swatch"]
            if swatch.get("bg") != "transparent":
                continue  # the title has its own panel; the picture cannot hurt it
            name = pairing.replace("+", "--") + ".jpg"
            target = STOCK_DIR / name
            title = hex_luminance(swatch["fg"])
            band = band_luminance(target) if target.is_file() else None
            if band is not None and contrast(title, band) >= TITLE_CONTRAST_FLOOR:
                continue
            query = SUBJECTS.get(pairing, pairing.replace("+", " "))
            width, height = ASPECTS.get(aspects.get(pairing, "9:16"), ASPECTS["9:16"])
            found = rebalance(pairing, query, swatch["fg"], (width, height), target)
            if not found:
                print(f"{pairing}: nothing usable found", file=sys.stderr)
                continue
            result, ratio = found
            if result.get("incumbent"):
                print(f"keep {pairing}: {ratio:.2f}:1 — nothing found beat the one it has",
                      file=sys.stderr)
                credits.setdefault(pairing, {})["titleContrast"] = round(ratio, 2)
                continue
            credits[pairing] = {
                "file": f"stock/{name}", "title": result.get("title") or "",
                "creator": result.get("creator") or "unknown",
                "source": result.get("foreign_landing_url") or result.get("url"),
                "license": (result.get("license") or "cc0").upper(),
                "query": query, "titleContrast": round(ratio, 2),
            }
            changed += 1
            mark = "ok " if ratio >= TITLE_CONTRAST_FLOOR else "BEST"
            print(f"{mark} {pairing}: {ratio:.2f}:1  {credits[pairing]['creator']}")
        OUT.write_text(json.dumps(credits, indent=2, sort_keys=True) + "\n")
        print(f"rebalanced {changed} still(s)")
        return 0
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
