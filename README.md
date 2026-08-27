# scrollmark.github.io

Landing site for Scrollmark's open-source work, intended for GitHub Pages at
[scrollmark.github.io](https://scrollmark.github.io).

Four static pages — `index.html`, `skills.html`, `mcp.html` and `404.html` —
plus `styles.css`. The output is plain static HTML with no framework runtime;
styling follows the **Sticker Energy** design system (tokens mirrored from the
SocialGPT design system; light paper default with the ink-canvas dark theme).
Interactivity (theme toggle, install-snippet tabs, copy buttons) is Datastar
via CDN.

```
src/index.html          front matter + the page's <main>, nothing else
src/_includes/base.html <head>, nav and footer — the parts every page shares
src/src.11tydata.json   flat .html permalinks, so URLs never change
eleventy.config.js      passthrough copy for css and images
_site/                  build output; this is what deploys
```

`<head>`, the nav and the footer used to be copied into every page — about 460
of 2080 lines — and the README's own warning about keeping the copies in step
had itself gone stale. [Eleventy](https://www.11ty.dev) builds them from one
layout now.

The pages are not identical, so the layout takes what differs as front matter:
`title`, `description`, `ogTitle`, `ogDesc`, `canonical`, `active` (which nav
link gets `aria-current`), `home` and `about` (the brand and About targets,
which differ on the home page and again on the 404), `prefix` (the 404 is
served from arbitrary paths and needs absolute asset URLs), `footer` and
`noindex`. A naive include would have quietly dropped the `aria-current` and
broken the 404's assets.

Every `<code>` inside a `.codebox` needs an `id` that is unique within its page —
the copy buttons share one `$copied` signal keyed by that id, so a duplicate id
silently copies the wrong command.

## Develop

```bash
npm install
npm run dev      # eleventy --serve on :4321, watches src/ and rebuilds
```

Editing `src/_includes/base.html` updates every page at once — that is the
point of the build. `npm run build` writes `_site/` without serving, and
`npm run check` runs both guards against that output.

The watcher covers `src/` — pages, `_includes/` and `_data/`. Editing a JSON
file in `_data/` rebuilds and reloads like any template edit.

**`eleventy.config.js` is the exception, and it fails quietly.** A change there
does trigger a rebuild, but the config module is already loaded, so anything
newly *registered* — a filter, a shortcode, a passthrough — is not picked up.
The build then fails with `undefined filter: …` and writes zero files, while
the dev server carries on serving the last good output. The browser looks
completely normal and nothing you edit is taking effect. Restart after touching
the config.

`scripts/dev-server.py` serves an already-built `_site/` without Node, for when
that is easier. It sends `no-store`, because a browser holding a stale
`styles.css` reads exactly like a CSS fix that did not work.

## Deploy

**GitHub Pages is not enabled on this repository yet.** Turn it on at
*Settings → Pages → Build and deployment* and set the source to **GitHub
Actions** — not "Deploy from a branch". The branch holds templates now, so
serving it directly would publish Liquid tags instead of pages.

`.github/workflows/pages.yml` then builds and deploys on every push to `main`.
`.github/workflows/accuracy.yml` builds first too, and checks the output rather
than the templates: a claim is only real once Eleventy has written it.

## License

MIT — see [LICENSE](LICENSE).
