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
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "scrollmark/social-skills"
API = f"https://api.github.com/repos/{REPO}"
SITE = Path(__file__).resolve().parent.parent

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
    p = len(programs)
    expect("program count", re.search(rf"\b{p} programs\b", joined) is not None,
           f"site states {p} programs (repo has {p})")

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

    # 8. The MCP tool catalog.
    mcp_html = pages.get("mcp.html", "")
    tools = re.findall(r'<li[^>]*>([a-z_]+)</li>', mcp_html)
    stated = re.search(r"All (\d+) tools", mcp_html)
    expect("tool catalog", stated is not None and len(tools) == int(stated.group(1)),
           f"catalog lists {len(tools)} tools and says so")

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
