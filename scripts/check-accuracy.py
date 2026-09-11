#!/usr/bin/env python3
"""Check this site's factual claims against scrollmark/social-skills.

Every inaccuracy this site has shipped came from the same place: a change
landed in the skills repo and nobody updated the page. It has happened four
times — a retired product still advertised in the hero, an install command
naming an extra that had been removed, bundled-script counts a release behind,
and a card describing the pipeline as "planning" long after it could render.

Each was caught by a person looking. Nothing checked.

The two repos are separate and the site has no build step, so this reads the
live skills repo over the API and compares. Run it before publishing, and in CI.

  python3 scripts/check-accuracy.py          # human-readable
  python3 scripts/check-accuracy.py --json   # machine-readable

Exit 0 = every checked claim matches. Exit 1 = at least one does not.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "scrollmark/social-skills"
API = f"https://api.github.com/repos/{REPO}"
#: The checkers run against BUILT output. Templates contain Liquid, and a
#: half-rendered `{% if %}` is not what a reader ever sees — so a claim or a
#: class is only real once Eleventy has written it into _site.
SITE = Path(__file__).resolve().parent.parent / "_site"

#: Phrases that were true once and became false. Their reappearance means a
#: revert or a copy-paste from an old draft, so they are checked by name.
RETIRED_PHRASES = [
    ("AI video framework", "showrunner was retired; the video capability is inside social-skills"),
    ("planning a short-form video", "the repo makes videos now, it does not only plan them"),
    ("git+https://github.com/scrollmark/social-skills",
     "pip shells out to git for this form; on a stock Mac that is an xcrun shim"),
    ("video-studio-engine[all]", "[all] was removed; an unknown extra installs the base package silently"),
    ("showrunner", "retired, and deliberately unmentioned here"),
]


#: The API allows 60 unauthenticated calls an hour, per IP — which shared CI
#: runners burn through without any help from us. So: one API call for the
#: whole file tree, and file BODIES over raw.githubusercontent.com, which is
#: not part of that budget. A token is used when one is present (CI passes
#: the workflow's own) and is not required otherwise.
RAW = f"https://raw.githubusercontent.com/{REPO}/master"


def _headers(accept: str) -> dict[str, str]:
    h = {"Accept": accept}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch(path: str) -> str:
    """A file's contents, off raw — no API budget spent."""
    req = urllib.request.Request(f"{RAW}/{path}", headers=_headers("text/plain"))
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()



@functools.lru_cache(maxsize=1)
def tree() -> list[str]:
    """Every path in the repo, in a single request."""
    req = urllib.request.Request(f"{API}/git/trees/master?recursive=1",
                                 headers=_headers("application/vnd.github+json"))
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if data.get("truncated"):
        raise SystemExit("repo tree came back truncated — this check needs a new approach")
    return [e["path"] for e in data["tree"]]


def list_dir(path: str) -> list[str]:
    """Immediate subdirectory names under `path`, from the cached tree."""
    prefix = path.rstrip("/") + "/"
    names = set()
    for entry in tree():
        if entry.startswith(prefix):
            rest = entry[len(prefix):]
            if "/" in rest:
                names.add(rest.split("/", 1)[0])
    return sorted(names)


def list_files(path: str) -> list[str]:
    """Immediate file names under `path`, from the cached tree."""
    prefix = path.rstrip("/") + "/"
    return sorted(e[len(prefix):] for e in tree()
                  if e.startswith(prefix) and "/" not in e[len(prefix):])


def _load_sibling(name: str, filename: str):
    """Import a script next to this one. Named with a hyphen, so `import` alone
    cannot reach it — and renaming it would break every documented command."""
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def site_text() -> dict[str, str]:
    return {p.name: p.read_text() for p in SITE.glob("*.html")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    problems: list[str] = []
    checked: list[str] = []

    try:
        skills = sorted(list_dir("skills"))
        cli = fetch("src/video_studio/cli.py")
    except urllib.error.URLError as e:
        print(f"cannot reach {REPO}: {e}", file=sys.stderr)
        return 2

    block = re.search(r"COMMANDS: dict\[str, str\] = \{(.*?)\n\}", cli, re.S).group(1)
    programs = re.findall(r'^\s+"([a-z_]+)"', block, re.M)
    pages = site_text()
    joined = "\n".join(pages.values())

    def expect(label: str, condition: bool, detail: str) -> None:
        (checked if condition else problems).append(f"{label}: {detail}")

    # 1. Skill count. Asking "does 16 appear somewhere" is too weak — one page
    #    can say 15 while another still says 16 and the check passes. So take
    #    EVERY "N skills" on the site, remove the per-group counts (which are
    #    legitimately smaller and must sum to the total), and require that what
    #    remains is only ever the true number.
    n = len(skills)
    group_counts = [int(g) for g in re.findall(r"Group \w+ · (\d+) skills", joined)]
    expect("group counts", sum(group_counts) == n if group_counts else True,
           f"groups sum to {sum(group_counts)} (repo has {n})")

    # Layer counts are a second, different partition (prose / prose+script /
    # engine-dependent) and are legitimately smaller too, so they come out of
    # the pool as well before the remainder is judged.
    # Sticker counts (layers, and the headline total itself) are a different
    # partition with no single invariant to assert — 8 prose + 4 bundled leaves
    # 4 engine-dependent. They are removed from the pool rather than checked,
    # so the remainder test stays about headline counts only.
    layer_counts = [int(m) for m in re.findall(r"corner-sticker[^>]*>(\d+) skills", joined)]

    all_counts = [int(m) for m in re.findall(r"\b(\d+) skills\b", joined)]
    remainder = list(all_counts)
    for g in group_counts + layer_counts:
        if g in remainder:
            remainder.remove(g)
    wrong = sorted({c for c in remainder if c != n})
    expect("skill count", not wrong,
           f"every headline count is {n}" + (f" — WRONG: {wrong}" if wrong else ""))

    # 2. Every skill the site offers must exist.
    offered = set(re.findall(r"-s ([a-z-]+)", joined))
    unknown = sorted(offered - set(skills))
    expect("skill names", not unknown, f"install commands name only real skills"
           + (f" — UNKNOWN: {unknown}" if unknown else ""))
    missing = sorted(set(skills) - offered)
    expect("skill coverage", not missing, "every skill has an install command"
           + (f" — MISSING: {missing}" if missing else ""))

    # 3. Program count.
    #
    # Reported as "the site says X, the repo has Y" rather than interpolating the
    # repo's count into both halves. It used to do the latter, so a genuine
    # failure printed "site states 35 programs (repo has 35)" -- which reads as a
    # bug in the checker, and a checker that looks broken when it is right is one
    # people learn to skip.
    p = len(programs)
    said = re.search(r"\b(\d+) programs\b", joined)
    expect("program count", said is not None and int(said.group(1)) == p,
           f"the site says {said.group(1) if said else 'no'} programs, the repo has {p}")

    # 4. Retired phrases must not come back.
    for phrase, why in RETIRED_PHRASES:
        hits = [f for f, t in pages.items() if phrase.lower() in t.lower()]
        expect("retired phrase", not hits,
               f"{phrase!r} absent — {why}" + (f" — FOUND IN {hits}" if hits else ""))

    # 5. Page furniture that only fails silently.
    #
    # Everything below is invisible when it breaks. A missing canonical, an
    # og:image pointing at a 404, a fallback that stopped covering one page —
    # none of them change how the site looks to the person editing it, which
    # is exactly why they need a machine to notice.
    CANONICAL = {
        "index.html": "https://scrollmark.github.io/",
        "skills.html": "https://scrollmark.github.io/skills.html",
        "mcp.html": "https://scrollmark.github.io/mcp.html",
        "gallery.html": "https://scrollmark.github.io/gallery.html",
    }
    for page, url in CANONICAL.items():
        text = pages.get(page, "")
        expect("canonical", f'<link rel="canonical" href="{url}" />' in text,
               f"{page} declares canonical {url}")
        expect("og:url matches canonical",
               f'<meta property="og:url" content="{url}" />' in text,
               f"{page} og:url agrees with its canonical")

    card = SITE / "og-card.png"
    expect("og:image exists", card.is_file(),
           "og-card.png is present, so the social preview is not a 404")

    for name in ("404.html", "sitemap.xml", "robots.txt"):
        expect("page furniture", (SITE / name).is_file(), f"{name} exists")

    # 6. The Datastar fallback, on every page that hides anything.
    #
    # Thirteen of the sixteen `data-show` blocks start at display:none and are
    # revealed by Datastar — including install commands. If it never runs they
    # are unreachable, so all three escape hatches have to stay in place.
    for page, text in pages.items():
        if "data-show" not in text:
            continue
        for marker, what in (("no-ds", "onerror/nomodule hook"),
                             ("<noscript>", "noscript override")):
            expect("js fallback", marker in text,
                   f"{page} keeps its {what}")

    # 7. The dependency matrix must agree with the skills themselves.
    skills_html = pages.get("skills.html", "")
    rows = re.findall(r"<tr>\s*<td><code>([a-z-]+)</code></td>(.*?)</tr>",
                      skills_html, re.S)
    expect("matrix rows", len(rows) == n,
           f"matrix has one row per skill ({len(rows)} of {n})")
    named = {r[0] for r in rows}
    expect("matrix names", named <= set(skills),
           "matrix names only real skills"
           + (f" — UNKNOWN {sorted(named - set(skills))}" if named - set(skills) else ""))
    free = sum(1 for _, cells in rows if ">nothing<" in cells)
    repo_free = sum(
        1 for sk in skills
        if not list_files(f"skills/{sk}/scripts")
        and "video-studio" not in fetch(f"skills/{sk}/SKILL.md")
    )
    expect("matrix install-free", free == repo_free,
           f"matrix marks {free} skills install-free (repo agrees)")

    # 8. The MCP tool catalog, against what the server actually exposes.
    #
    # The page's heading now derives its count from the same data the list comes
    # from, so comparing those two would pass no matter what either said — the
    # shape of check this repo has been burned by before. The comparison that
    # means something is against the server, and CI cannot reach it (the MCP
    # endpoint needs OAuth). So the server's answer is recorded here, dated, and
    # the catalog is checked against the record. Refresh it by calling
    # server_info and the tools/list on mcp.gpt.social, not by editing to match.
    SERVER_TOOLS = {  # read from mcp.gpt.social on 26 August 2026
        "whoami", "list_accounts", "get_account", "get_account_metrics",
        "list_videos", "get_video", "list_uploads", "get_follower_history",
        "get_growth_summary", "get_post_metrics_history", "get_content_profile",
        "get_creator", "list_creator_videos", "list_similar_videos", "search",
        "search_videos", "fetch", "analyze_creator", "analyze_post",
        "get_analysis_status", "get_video_analysis", "get_publish_options",
        "get_upload_link", "get_publish_status", "publish_post", "server_info",
    }
    WRITE_TOOLS = {"publish_post"}   # the only one that posts to a platform

    mcp_html = pages.get("mcp.html", "")
    listed = set(re.findall(r'<li[^>]*>([a-z_]+)</li>', mcp_html))
    expect("tool catalog", listed == SERVER_TOOLS,
           f"catalog lists exactly the {len(SERVER_TOOLS)} tools the server exposes"
           + (f" — MISSING {sorted(SERVER_TOOLS - listed)}" if SERVER_TOOLS - listed else "")
           + (f" — EXTRA {sorted(listed - SERVER_TOOLS)}" if listed - SERVER_TOOLS else ""))

    marked = set(re.findall(r'<li class="tool--write">([a-z_]+)</li>', mcp_html))
    expect("write-capable tools", marked == WRITE_TOOLS,
           "exactly the write-capable tools are marked as such"
           + (f" — marked {sorted(marked)}, expected {sorted(WRITE_TOOLS)}" if marked != WRITE_TOOLS else ""))

    stated = re.search(r"All (\d+) tools", mcp_html)
    expect("stated tool count", stated and int(stated.group(1)) == len(SERVER_TOOLS),
           f"the page says {len(SERVER_TOOLS)}")

    # 9. The template gallery, against the two halves it was generated from.
    #
    # gallery.json is committed, because Pages builds this site with no network
    # and no checkout of the skills repo. So it is a copy, and a copy is a
    # claim: these are the colours that preset has and this is the frame that
    # format is composed for.
    #
    # The comparison regenerates with sync-gallery.py's own functions rather
    # than re-deriving the values here. Re-deriving is what this check did
    # first, and it certified a colour the preset does not define -- the two
    # copies of the fallback agreed with each other, which is not evidence of
    # anything. Regenerating also covers the fields a hand-written comparison
    # kept forgetting: the description rendered as the card's heading, the
    # title, the typeface, and whether a pairing is in the file at all.
    sync_gallery = _load_sibling("sync_gallery", "sync-gallery.py")

    committed = json.loads((SITE.parent / "src" / "_data" / "gallery.json").read_text())
    live, gallery_problems = sync_gallery.build(sync_gallery.read_live)
    for gp in gallery_problems:
        problems.append(f"gallery source: {gp}")
    # A source that could not be read says nothing about the committed file, so
    # the comparison is skipped rather than reporting every pairing as orphaned
    # — a cascade of wrong diagnoses hides the one true line above it.
    if gallery_problems:
        live = []

    by_pair = ({(e["format"], e["style"]): e for e in committed["entries"]}
               if live else {})

    # The two numbers the page quotes about the repo, checked against it. The
    # page renders them from this file rather than stating them, so this is the
    # only place they can go stale.
    if live:
        fresh = sync_gallery.counts(None)
        expect("gallery counts", committed.get("counts") == fresh,
               f"the data says {committed.get('counts')} formats/presets, the repo has {fresh}")

    # Every template the pack publishes reaches the page.
    #
    # `build()` orders by ORDER and then falls through to pack order, so a
    # newly published template appears on its own -- but only if this site is
    # regenerated. Without this check a template released upstream is invisible
    # here and nothing says so, which is the failure mode the whole migration
    # introduced: curation moved to a repo whose releases this site does not
    # watch.
    #
    # Read from the pack directly rather than from `build()`'s output, so a
    # template dropped ANYWHERE in that function -- an unresolvable ref, a bad
    # swatch, a silent `continue` -- is counted as missing rather than agreeing
    # with itself.
    if live:
        pack, pack_problems = sync_gallery.load_pack(sync_gallery.read_live)
        for pp in pack_problems:
            problems.append(f"pack: {pp}")
        published = {a["id"] for a in (pack or {}).get("assets", [])
                     if a.get("kind") == "template"}
        shown = {f"template/{e['format']}-{e['style']}" for e in committed["entries"]}
        absent = sorted(published - shown)
        expect("every published template is on the page",
               bool(published) and not absent,
               f"all {len(published)} templates in the pack have a card"
               + (f" — MISSING: {absent}" if absent else ""))
    for entry in live:
        key = (entry["format"], entry["style"])
        have = by_pair.pop(key, None)
        stale = sorted(k for k in set(entry) | set(have or {})
                       if entry.get(k) != (have or {}).get(k))
        expect("gallery entry", have is not None and not stale,
               f"{key[0]} + {key[1]} matches the repo"
               + (" — MISSING from gallery.json" if have is None
                  else f" — STALE {stale}: {[(k, (have or {}).get(k), entry.get(k)) for k in stale]}"
                  if stale else "")
               + (" — regenerate with scripts/sync-gallery.py" if have is None or stale else ""))
    # Only meaningful when the source could be read. Reporting `ok` for a
    # comparison that ran against nothing is the failure this file exists to
    # prevent, one level up: a check that looks like it passed.
    if live:
        expect("gallery extras", not by_pair,
               "gallery.json holds no pairing sync-gallery.py does not make"
               + (f" — ORPHANED: {sorted(by_pair)}" if by_pair else ""))

    # 9b. Caption legibility, measured rather than asserted in a comment.
    #
    # The band under a caption is the preset's own stroke, which is what makes
    # an arbitrary palette readable. The stylesheet states the floor that
    # produces, and a stated floor is a claim like any other here: it said
    # 14:1 until a preset measured 13.45. So the claim is parsed out of the CSS
    # and checked against the data it describes.
    def _luminance_of(value: str) -> float:
        h = value.lstrip("#")
        ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def _contrast(a: str, b: str) -> float:
        def lum(h):
            h = h.lstrip("#")
            ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
            return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
        la, lb = lum(a), lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    captions = {}
    for e in committed["entries"]:
        sw = e["swatch"]
        captions[f"{e['format']} + {e['style']}"] = _contrast(
            sw["caption"], sw.get("stroke", sw["bg"]))
    below_aa = sorted(k for k, v in captions.items() if v < 4.5)
    expect("caption legibility", not below_aa,
           f"every caption clears AA on its own band (worst {min(captions.values()):.2f}:1)"
           + (f" — BELOW 4.5: {below_aa}" if below_aa else ""))

    css = (SITE / "styles.css").read_text()
    stated = re.search(r"caption is (\d+(?:\.\d+)?):1 or better", css)
    measured = min(captions.values())
    expect("stated contrast floor", stated is not None and float(stated.group(1)) <= measured,
           f"the stylesheet says {stated.group(1) if stated else 'no'}:1, "
           f"the worst measured is {measured:.2f}:1")

    # 9c. The photographs behind the previews.
    #
    # They are CC0, so no notice is legally required -- which is exactly why a
    # check is worth having: nothing external forces the credit to stay correct
    # or the file to stay present. A missing file is an invisible failure, too;
    # the card still draws, in flat colour, looking like a design decision.
    stock = json.loads((SITE.parent / "src" / "_data" / "stock.json").read_text())
    for entry in committed["entries"]:
        pairing = f"{entry['format']}+{entry['style']}"
        shot = stock.get(pairing)
        expect("gallery still", shot is not None,
               f"{pairing} has a photograph"
               + ("" if shot else " — run scripts/fetch-stock.py"))
        if not shot:
            continue
        expect("gallery still shipped", (SITE / shot["file"]).is_file(),
               f"{shot['file']} is in the built site")
        if shot.get("clip"):
            clip = SITE / shot["clip"]
            expect("gallery clip shipped", clip.is_file(),
                   f"{shot['clip']} is in the built site")
            # A card's clip has to stay small enough to serve on hover. The
            # band is the one it was encoded into; a re-encode that drifts out
            # of it is a page that got heavier without anyone deciding to.
            size = clip.stat().st_size if clip.is_file() else 0
            expect("gallery clip weight", 200 * 1024 <= size <= 400 * 1024,
                   f"{shot['clip']} is {size // 1024}KB, inside 200-400KB")
            # A moving card is marked as one. The tint is what a reader
            # notices; without it a clip is a surprise that only rewards the
            # visitor who happened to hover.
            marked = pages.get("gallery.html", "").count("tpl-card--moves")
            expect("moving cards are marked", marked == sum(
                1 for s in stock.values() if s.get("clip")),
                f"{marked} cards carry the motion tint, one per clip")
            expect("gallery clip is posted by its still",
                   f'poster="{shot["file"]}"' in pages.get("gallery.html", ""),
                   f"{shot['clip']} shows its own still until it plays")
        missing = [k for k in ("creator", "source", "license") if not shot.get(k)]
        expect("gallery still credited", not missing,
               f"{pairing} names its photographer and licence"
               + (f" — MISSING {missing}" if missing else ""))
        # Either somebody else's, in the public domain, or ours. What is not
        # allowed is a third thing: a still with a licence nobody can name.
        licence = shot.get("license", "").upper()
        expect("gallery still provenance", licence in {"CC0", "OWN"},
               f"{pairing} is public domain or ours (it says {shot.get('license')})")
        if licence == "OWN":
            expect("our stills say so", shot.get("creator") == "Scrollmark"
                   and shot.get("source") == "in-house",
                   f"{pairing} names itself as ours rather than borrowing a credit")

    # Every credited photographer must actually appear on the page.
    # Ours are credited on the page by the line that says which are ours, not
    # by a photographer's name, so they are not in this sweep.
    uncredited = [s["creator"] for s in stock.values()
                  if s.get("license", "").upper() != "OWN"
                  and s["creator"] not in pages.get("gallery.html", "")]
    expect("gallery credits rendered", not uncredited,
           "every photographer is named on the page"
           + (f" — MISSING: {sorted(set(uncredited))}" if uncredited else ""))

    # 9d. The webfont request the gallery makes.
    #
    # One system face in a css2 request 400s the whole thing, and then none of
    # the real faces load -- the page falls back to its own typeface and looks
    # deliberate. So the URL is fetched, and every face a preset names must be
    # in it.
    font_link = re.search(r"https://fonts\.googleapis\.com/css2\?display=swap[^\"]*",
                          pages.get("gallery.html", ""))
    expect("gallery font request", font_link is not None,
           "the gallery asks for the faces its presets name")
    if font_link:
        try:
            request = urllib.request.Request(
                font_link.group(0).replace("&amp;", "&"),
                headers={"User-Agent": "Mozilla/5.0 (scrollmark-accuracy)"})
            with urllib.request.urlopen(request, timeout=30) as response:
                served = response.status == 200
        except urllib.error.HTTPError as error:
            served = False
            print(f"  font request said {error.code}", file=sys.stderr)
        expect("gallery fonts load", served,
               "Google Fonts serves every face the page asks for")
        asked = font_link.group(0)
        missing = sorted({
            face for entry in committed["entries"]
            for face in (entry.get("titleFace"), entry.get("captionFace"))
            if face and face.replace(" ", "+") not in asked
        })
        expect("gallery faces requested", not missing,
               "every face a preset names is in the request"
               + (f" — MISSING: {missing}" if missing else ""))

    # 9e. A title has to be readable against the picture chosen for it.
    #
    # Where a preset's title card is transparent, the type sits straight on the
    # photograph, so the photograph is part of whether it can be read. Seven of
    # the ten such pairings failed when the stills were picked for subject
    # alone -- one at 1.24:1, which is a title you cannot see.
    #
    # Measuring needs a decoder, and this runner has no ffmpeg -- a site that
    # checks its own copy should not need a media toolchain to do it. So
    # `fetch-stock.py --measure` records the number beside a hash of the exact
    # bytes it measured, and this checks BOTH: the hash still matches the file
    # (so the number belongs to the picture that is shipping) and the number
    # clears the floor. A recorded number with no bytes attached would rot in
    # silence, which is the failure this file exists to prevent.
    #
    # 3:1 because these are large text, which is the threshold WCAG sets for
    # it, and because some titles cannot do better against ANY photograph:
    # weekend-gothic's vermilion sits mid-range, so it needs a near-black band.
    stale, unreadable, unmeasured = [], [], []
    for entry in committed["entries"]:
        pairing = f"{entry['format']}+{entry['style']}"
        shot = stock.get(pairing)
        if not shot:
            continue
        path = SITE.parent / shot["file"]
        if path.is_file() and shot.get("sha256"):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != shot["sha256"]:
                stale.append(pairing)
        if entry["swatch"].get("bg") != "transparent":
            continue
        measured = shot.get("titleContrast")
        band = shot.get("bandLuminance")
        if measured is None or band is None:
            unmeasured.append(pairing)
            continue
        # Recomputed from the recorded band and the preset's own colour, so a
        # contrast edited by hand fails even though the picture is untouched.
        # What is NOT verifiable here is the band itself: checking that would
        # mean decoding the JPEG, which is the toolchain this avoids. The hash
        # ties it to bytes nobody has changed; that is the guarantee on offer.
        title = _luminance_of(entry["swatch"]["fg"])
        recomputed = round((max(title, band) + 0.05) / (min(title, band) + 0.05), 2)
        if abs(recomputed - measured) > 0.02:
            stale.append(f"{pairing} records {measured}:1, its band gives {recomputed}:1")
        elif measured < 3.0:
            unreadable.append(f"{pairing} at {measured}:1")

    expect("still measurements are current", not stale,
           "every recorded measurement matches the file it describes"
           + (f" — CHANGED SINCE MEASURING: {stale} (scripts/fetch-stock.py --measure)"
              if stale else ""))
    expect("titles are measured", not unmeasured,
           "every transparent title has a recorded contrast"
           + (f" — MISSING: {unmeasured}" if unmeasured else ""))
    expect("title on its still", not unreadable,
           "every transparent title clears 3:1 against its photograph"
           + (f" — UNREADABLE: {unreadable} (scripts/fetch-stock.py --rebalance)"
              if unreadable else ""))

    # The moving cards lead. They are the ones somebody arriving is looking
    # for, and an order that drifts is the kind of thing nobody notices until
    # the showcase is buried on row four.
    leading = [f"{e['format']}+{e['style']}" for e in committed["entries"][:5]]
    with_clips = {p for p, s in stock.items() if s.get("clip")}
    expect("moving cards lead", set(leading) == with_clips,
           "the five templates with clips are the first five cards"
           + (f" — LEADING: {leading}" if set(leading) != with_clips else ""))

    # Every pairing must reach the built page, or the data is a file nobody sees.
    gallery_html = pages.get("gallery.html", "")
    # This one still means something with no source: it compares the committed
    # data against the built page, and both are in the tree.
    shown = live or committed["entries"]
    unshown = [e["format"] for e in shown
               if f">{e['format']} · {e['style']}<" not in gallery_html]
    expect("gallery rendered", not unshown,
           f"all {len(shown)} pairings in {'the repo' if live else 'gallery.json'}"
           f" appear on the page"
           + (f" — MISSING: {unshown}" if unshown else ""))

    # The title goes where the PRESET says, on both axes. The preview used to
    # pin every title to the top left corner whatever the preset's `rect` said,
    # which is a look the engine never draws and was visibly wrong against the
    # five reference recreations -- four centre the title in the frame and
    # `postcard-serif` sits it near the top, and all five drew identically.
    # Checked against the rect rather than against a remembered list of which
    # ones are centred: the preset is the only thing that knows.
    placed = [e for e in shown if e.get("titleTop")]
    misplaced = []
    for e in placed:
        key = f"{e['format']} · {e['style']}"
        want = f"--tpl-title-top: {e['titleTop']}"
        if want not in gallery_html:
            misplaced.append(f"{key} wants {want}")
    expect("title placement rendered", not misplaced,
           f"every placed title carries its preset's own vertical centre"
           + (f" — MISSING: {misplaced}" if misplaced else ""))

    # And that centre is the rect's MIDDLE, not its top edge: a card is a box
    # its type sits in the middle of, so a rect running 0.38 to 0.56 places
    # type at 0.47.
    #
    # The arithmetic is repeated here on purpose. The obvious version calls
    # `sync_gallery.title_placement` and compares its answer to the number
    # that function produced, which certifies anything at all: changing the
    # centre to the rect's top edge moved all seventeen titles and the check
    # still reported ok, because both sides moved together. Reading the rect
    # and halving it here is the only version that can disagree.
    if live:
        drifted = []
        for e in placed:
            rect = (sync_gallery.json_block(
                sync_gallery.read_live(f"{sync_gallery.STYLES_DIR}/{e['style']}.md")
            ).get("cards", {}).get("title", {}).get("rect") or [0, 0, 0, 0])
            want = round(rect[1] + rect[3] / 2, 4)
            if want != e.get("titleTop"):
                drifted.append(
                    f"{e['style']}: page {e.get('titleTop')}, preset {want}")
        expect("title placement matches the preset", not drifted,
               f"all {len(placed)} placed titles sit at their rect's centre"
               + (f" — DRIFT: {drifted}" if drifted else ""))

    # The caption goes where the preset says too, measured up from the bottom
    # edge. Same independent recomputation as the title: read `bottom` from the
    # preset rather than asking the code that emitted it.
    if live:
        cap_drift = []
        overlaps = []
        for e in shown:
            values = sync_gallery.json_block(
                sync_gallery.read_live(f"{sync_gallery.STYLES_DIR}/{e['style']}.md"))
            captions = values.get("captions", {})
            want = captions.get("bottom")
            if not isinstance(want, (int, float)):
                continue
            if round(want, 4) != e.get("captionBottom"):
                cap_drift.append(
                    f"{e['style']}: page {e.get('captionBottom')}, preset {want}")
            # And the two placements must not collide. They did: `pov-serif`
            # and `pov-quiet` each put their caption band inside their own
            # title box, which nothing noticed until the preview drew both
            # where the preset asks. Fixed upstream; checked here because this
            # page is where it became visible.
            rect = values.get("cards", {}).get("title", {}).get("rect")
            if isinstance(rect, list) and len(rect) == 4:
                band_bottom = 1 - want
                band_top = band_bottom - captions.get("fontSize", 56) / 1920
                if band_top < rect[1] + rect[3] and band_bottom > rect[1]:
                    overlaps.append(e["style"])
        expect("caption placement matches the preset", not cap_drift,
               "every caption sits where its preset puts it"
               + (f" — DRIFT: {cap_drift}" if cap_drift else ""))
        expect("title and caption do not collide", not overlaps,
               "no preset puts its caption band inside its own title box"
               + (f" — COLLIDING: {overlaps}" if overlaps else ""))

    if args.json:
        print(json.dumps({"ok": not problems, "checked": checked, "problems": problems}, indent=2))
    else:
        for c in checked:
            print(f"  ok    {c}")
        for pr in problems:
            print(f"  FAIL  {pr}", file=sys.stderr)
        print(f"\n{len(checked)} claim(s) verified, {len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
