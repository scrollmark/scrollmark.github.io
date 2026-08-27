import markdownIt from "markdown-it";

// Copy in _data/ is written as Markdown so a sentence can carry emphasis, a
// link or a code span without becoming HTML-inside-JSON. `renderInline` emits
// no wrapping <p>, so the string drops straight into whatever element holds it.
const md = markdownIt({ html: false, typographer: false, linkify: false });

// Four pages that shared ~460 lines of head, nav and footer. Eleventy exists
// here only to stop that boilerplate being copied by hand — the output is the
// same flat static HTML this site has always served, and both checkers run
// against that output rather than against templates.
export default function (eleventyConfig) {
  eleventyConfig.addFilter("md", (value) => (value ? md.renderInline(String(value)) : ""));

  // Everything that is not a page ships byte-for-byte.
  for (const file of [
    "styles.css",
    "brand-scrollmark.png",
    "brand-socialgpt.svg",
    "og-card.png",
    "robots.txt",
    "sitemap.xml",
  ]) {
    eleventyConfig.addPassthroughCopy(file);
  }

  return {
    dir: { input: "src", includes: "_includes", output: "_site" },
    // `.html` pages are Liquid templates. Verified safe: the source pages
    // contain no `{{` or `{%` of their own, so nothing in the content is
    // reinterpreted — the Datastar expressions use single braces.
    htmlTemplateEngine: "liquid",
  };
}
