"""Build the landing page's text pages: personvern, kontakt and the rest.

    python3 scripts/build_site_pages.py

Each page's text is a fragment in `site-pages/<slug>.html`. This wraps it in
the landing page's own nav and footer, taken from `site/index.html`, so a
change to either is made once, there, and every page follows the next time
this runs. The output goes to `site/<slug>/index.html` and is committed:
Render serves `site/` as it is, with nothing to build.

A fragment starts with a comment holding its title, description and status:

    <!--
    title: Personvern
    description: Hvilke personopplysninger Arvaka behandler, og hvorfor.
    status: utkast
    -->

`status: utkast` puts a banner at the top and keeps search engines away, so a
draft can be read on the real site before anyone has approved it. Remove the
line, or write `status: ferdig`, when it is.
"""
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "site-pages"
SITE = ROOT / "site"
ORIGIN = "https://arvaka.no"


def _part(page: str, tag: str) -> str:
    found = re.findall(rf"<{tag}\b.*?</{tag}>", page, flags=re.S)
    if len(found) != 1:
        sys.exit(f"Fant {len(found)} <{tag}> i site/index.html, ventet én.")
    # The landing page links to its own sections; from another page they are
    # sections of the front page.
    return re.sub(r'href="#([\w-]+)"', r'href="/#\1"', found[0])


def _meta(fragment: str, source: Path) -> tuple[dict, str]:
    m = re.match(r"\s*<!--(.*?)-->\s*", fragment, flags=re.S)
    if not m:
        sys.exit(f"{source.name}: mangler kommentaren med title og description øverst.")
    meta = {}
    for line in m.group(1).strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    for key in ("title", "description"):
        if not meta.get(key):
            sys.exit(f"{source.name}: mangler «{key}».")
    return meta, fragment[m.end():].strip()


DRAFT_BANNER = """<div class="draft-banner" role="note">
  <strong>Utkast.</strong> Denne siden er ikke godkjent ennå. Tekst i
  <span class="todo">gult</span> må fylles inn eller sjekkes før den publiseres.
</div>"""


def build(source: Path, nav: str, footer: str) -> Path:
    meta, body = _meta(source.read_text(encoding="utf-8"), source)
    slug = source.stem
    draft = meta.get("status", "").lower() == "utkast"
    title = html.escape(f"{meta['title']} — Arvaka")
    description = html.escape(meta["description"])
    page = f"""<!doctype html>
<html lang="no">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta name="description" content="{description}" />
    <link rel="canonical" href="{ORIGIN}/{slug}/" />{'''
    <meta name="robots" content="noindex" />''' if draft else ''}
    <meta name="theme-color" content="#FAFAF9" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="preload" href="/assets/fonts/geist.woff2" as="font" type="font/woff2" crossorigin />
    <link rel="preload" href="/assets/fonts/newsreader.woff2" as="font" type="font/woff2" crossorigin />
    <link rel="stylesheet" href="/assets/site.css" />
    <link rel="stylesheet" href="/assets/pages.css" />
  </head>
  <body>
    <!-- Built by scripts/build_site_pages.py from site-pages/{slug}.html. Edit that, not this. -->
    {nav}
    {DRAFT_BANNER if draft else ''}
    <main class="doc">
{body}
    </main>
    {footer}
  </body>
</html>
"""
    out = SITE / slug / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    front = (SITE / "index.html").read_text(encoding="utf-8")
    nav, footer = _part(front, "nav"), _part(front, "footer")
    sources = sorted(SOURCES.glob("*.html"))
    if not sources:
        sys.exit(f"Ingen sider i {SOURCES}.")
    for source in sources:
        print(f"  {build(source, nav, footer).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
