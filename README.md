# scrollmark.github.io

Landing page for Scrollmark's open-source work, served by GitHub Pages at
[scrollmark.github.io](https://scrollmark.github.io).

A single static page — no build step, no framework runtime. Styling follows the
**Sticker Energy** design system (tokens mirrored from
`platform/socialgpt/frontend/app/globals.css`; light paper default with the
ink-canvas dark theme). Interactivity (theme toggle, install-snippet tabs, copy
buttons) is [Datastar](https://data-star.dev) via CDN.

## Develop

Open `index.html` in a browser, or:

```bash
npx serve
```

## Deploy

Push to `main` — GitHub Pages serves the repo root.
