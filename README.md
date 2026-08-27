# scrollmark.github.io

Landing site for Scrollmark's open-source work, intended for GitHub Pages at
[scrollmark.github.io](https://scrollmark.github.io).

Four static pages — `index.html`, `skills.html`, `mcp.html` and `404.html` —
plus `styles.css`.
No build step, no framework runtime. Styling follows the **Sticker Energy** design
system (tokens mirrored from the SocialGPT design system; light
paper default with the ink-canvas dark theme). Interactivity (theme toggle,
install-snippet tabs, copy buttons) is Datastar via CDN.

The `<nav>`, the `<footer>` and the pre-paint theme `<script>` are duplicated
verbatim in all three pages. Edit all three copies or they drift apart.

Every `<code>` inside a `.codebox` needs an `id` that is unique within its page —
the copy buttons share one `$copied` signal keyed by that id, so a duplicate id
silently copies the wrong command.

## Develop

Open `index.html` in a browser, or:

```bash
npx serve
```

## Deploy

**GitHub Pages is not enabled on this repository yet.** Pushing to `main` publishes
nothing until someone turns it on: repository *Settings → Pages → Build and
deployment*, source **Deploy from a branch**, branch `main`, folder `/ (root)`.
`.nojekyll` is already committed, so Pages serves the files as-is.

Once Pages is enabled, pushes to `main` deploy the repo root.

## License

MIT — see [LICENSE](LICENSE).
