"""Build the landing page's text pages: personvern, kontakt and the rest.

    python3 scripts/build_site_pages.py

Each page's text is a fragment in `site-pages/<slug>.html`. This wraps it in
the landing page's own nav and footer, taken from `site/index.html`, so a
change to either is made once, there, and every page follows the next time
this runs. The output goes to `site/<slug>/index.html` and is committed:
Render serves `site/` as it is, with nothing to build.

The English pages are fragments in `site-pages/en/<slug>.html`, under the
English slugs in `ENGLISH`, wrapped in the nav and footer of `site/en/index.html`
and written to `site/en/<slug>/index.html`. Each page's language switch, and
its `hreflang` links, go to the same page in the other language.

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


# Norwegian slug → English slug. A page needs both fragments.
ENGLISH = {
    "databehandleravtale": "data-processing",
    "kontakt": "contact",
    "om-oss": "about",
    "personvern": "privacy",
    "regnskapsforer": "accountants",
}


def _part(page: str, tag: str, front: str = "/") -> str:
    found = re.findall(rf"<{tag}\b.*?</{tag}>", page, flags=re.S)
    if len(found) != 1:
        sys.exit(f"Fant {len(found)} <{tag}> på forsiden, ventet én.")
    # The landing page links to its own sections; from another page they are
    # sections of the front page.
    return re.sub(r'href="#([\w-]+)"', rf'href="{front}#\1"', found[0])


def _switch(nav: str, no: str, en: str) -> str:
    """Point the nav's NO/EN links at this page in each language."""
    for lang, path in (("no", no), ("en", en)):
        nav, n = re.subn(rf'href="[^"]*"(\s+)hreflang="{lang}"',
                         rf'href="{path}"\1hreflang="{lang}"', nav)
        if n != 1:
            sys.exit(f"Fant {n} språklenker for «{lang}» i navigasjonen, ventet én.")
    return nav


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


DRAFT_BANNER = {
    "no": """<div class="draft-banner" role="note">
  <strong>Utkast.</strong> Denne siden er ikke godkjent ennå. Tekst i
  <span class="todo">gult</span> må fylles inn eller sjekkes før den publiseres.
</div>""",
    "en": """<div class="draft-banner" role="note">
  <strong>Draft.</strong> This page is not approved yet. Text in
  <span class="todo">yellow</span> must be filled in or checked before it is published.
</div>""",
}


def build(source: Path, lang: str, nav: str, footer: str) -> Path:
    meta, body = _meta(source.read_text(encoding="utf-8"), source)
    if lang == "en":
        no = next((k for k, v in ENGLISH.items() if v == source.stem), None)
        if no is None:
            sys.exit(f"{source.name}: ingen norsk side i ENGLISH har denne engelske sluggen.")
        en = source.stem
    else:
        no, en = source.stem, ENGLISH.get(source.stem)
        if en is None:
            sys.exit(f"{source.name}: mangler engelsk slug i ENGLISH.")
    paths = {"no": f"/{no}/", "en": f"/en/{en}/"}
    path = paths[lang]
    nav = _switch(nav, paths["no"], paths["en"])
    draft = meta.get("status", "").lower() in ("utkast", "draft")
    title = html.escape(f"{meta['title']} — Arvaka")
    description = html.escape(meta["description"])
    page = f"""<!doctype html>
<html lang="{lang}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta name="description" content="{description}" />
    <link rel="canonical" href="{ORIGIN}{path}" />
    <link rel="alternate" hreflang="no" href="{ORIGIN}{paths['no']}" />
    <link rel="alternate" hreflang="en" href="{ORIGIN}{paths['en']}" />
    <link rel="alternate" hreflang="x-default" href="{ORIGIN}{paths['no']}" />{'''
    <meta name="robots" content="noindex" />''' if draft else ''}
    <meta name="theme-color" content="#FAFAF9" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="preload" href="/assets/fonts/geist.woff2" as="font" type="font/woff2" crossorigin />
    <link rel="preload" href="/assets/fonts/newsreader.woff2" as="font" type="font/woff2" crossorigin />
    <link rel="stylesheet" href="/assets/site.css" />
    <link rel="stylesheet" href="/assets/pages.css" />
  </head>
  <body>
    <!-- Built by scripts/build_site_pages.py from {source.relative_to(ROOT)}. Edit that, not this. -->
    {nav}
    {DRAFT_BANNER[lang] if draft else ''}
    <main class="doc">
{body}
    </main>
    {footer}
  </body>
</html>
"""
    out = SITE / path.strip("/") / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    for lang, sources, front_page, front in (
            ("no", SOURCES, SITE / "index.html", "/"),
            ("en", SOURCES / "en", SITE / "en" / "index.html", "/en/")):
        page = front_page.read_text(encoding="utf-8")
        nav, footer = _part(page, "nav", front), _part(page, "footer", front)
        found = sorted(sources.glob("*.html"))
        if not found:
            sys.exit(f"Ingen sider i {sources}.")
        for source in found:
            print(f"  {build(source, lang, nav, footer).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
