#!/usr/bin/env python3
"""Build the flamedisk documentation site into _site/.

Converts README.md and docs/api.md to HTML using the Markdown library,
wraps each page in a shared template, and copies docs/img/ into _site/.

Run from the repo root:
    python .github/scripts/build_docs.py
"""
import re
import shutil
from pathlib import Path

import markdown

ROOT   = Path(__file__).parent.parent.parent
SITE   = ROOT / "_site"
DOCS   = ROOT / "docs"

EXTENSIONS = [
    "tables",
    "fenced_code",
    "codehilite",
    "toc",
    "pymdownx.superfences",
]

NAV = [
    ("Home",          "index.html"),
    ("API reference", "api.html"),
    ("Changelog",     "changelog.html"),
]

CSS = """
:root {
  --bg: #1e1e2e; --sf: #252535; --sf2: #2d2d42; --bd: #3a3a52;
  --tx: #cdd6f4; --mt: #7f849c; --ac: #89b4fa;
  --gn: #a6e3a1; --rd: #f38ba8; --yw: #f9e2af;
  --mono: "Cascadia Code","JetBrains Mono","Fira Mono",monospace;
  --ui: "Segoe UI",system-ui,sans-serif;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  background: var(--bg); color: var(--tx);
  font-family: var(--ui); font-size: 15px; line-height: 1.7;
  display: flex; flex-direction: column; min-height: 100vh;
}

/* ── header ── */
header {
  background: var(--sf); border-bottom: 1px solid var(--bd);
  padding: 0 2rem; height: 52px;
  display: flex; align-items: center; gap: 2rem;
  position: sticky; top: 0; z-index: 100;
}
.logo { font-family: var(--mono); font-size: 16px; font-weight: 700; text-decoration: none; }
.logo .fl {
  background: linear-gradient(to top, #e85d04, #f48c06, #ffd166);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.logo em { color: var(--tx); font-style: normal; }
nav { display: flex; gap: 0.25rem; }
nav a {
  color: var(--mt); text-decoration: none; font-size: 13px;
  padding: 4px 12px; border-radius: 4px; transition: background .15s, color .15s;
}
nav a:hover, nav a.active { background: var(--sf2); color: var(--tx); }
.version { margin-left: auto; font-family: var(--mono); font-size: 11px; color: var(--mt); }

/* ── layout ── */
.page { display: flex; flex: 1; }
.sidebar {
  width: 220px; flex-shrink: 0; padding: 2rem 1rem 2rem 1.5rem;
  border-right: 1px solid var(--bd); position: sticky; top: 52px;
  height: calc(100vh - 52px); overflow-y: auto;
}
.sidebar h4 { font-size: 10px; text-transform: uppercase; letter-spacing: .6px;
  color: var(--mt); margin-bottom: .5rem; margin-top: 1.25rem; }
.sidebar h4:first-child { margin-top: 0; }
.sidebar a { display: block; color: var(--mt); text-decoration: none;
  font-size: 13px; padding: 2px 0; transition: color .1s; }
.sidebar a:hover { color: var(--tx); }
main { flex: 1; padding: 2.5rem 3rem; max-width: 860px; overflow-x: hidden; }

/* ── typography ── */
h1 { font-size: 2rem; font-weight: 700; color: var(--tx); margin-bottom: 1rem; line-height: 1.2; }
h2 { font-size: 1.25rem; font-weight: 600; color: var(--tx);
  margin-top: 2.5rem; margin-bottom: .75rem;
  padding-bottom: .35rem; border-bottom: 1px solid var(--bd); }
h3 { font-size: 1rem; font-weight: 600; color: var(--ac);
  margin-top: 1.75rem; margin-bottom: .5rem; }
p { margin-bottom: 1rem; color: var(--tx); }
a { color: var(--ac); text-decoration: none; }
a:hover { text-decoration: underline; }
strong { color: var(--tx); }
hr { border: none; border-top: 1px solid var(--bd); margin: 2rem 0; }

/* ── code ── */
code {
  font-family: var(--mono); font-size: .85em;
  background: var(--sf2); color: var(--yw);
  padding: 1px 5px; border-radius: 3px;
}
pre {
  background: var(--sf); border: 1px solid var(--bd); border-radius: 6px;
  padding: 1rem 1.25rem; overflow-x: auto; margin-bottom: 1.25rem;
}
pre code { background: none; padding: 0; color: var(--tx); font-size: .84em; }

/* ── tables ── */
table { width: 100%; border-collapse: collapse; margin-bottom: 1.25rem; font-size: 13.5px; }
th { background: var(--sf2); color: var(--mt); font-weight: 600;
  text-align: left; padding: 6px 10px;
  text-transform: uppercase; font-size: 11px; letter-spacing: .4px; }
td { padding: 6px 10px; border-bottom: 1px solid var(--bd); vertical-align: top; }
tr:last-child td { border-bottom: none; }
td code { font-size: .82em; }

/* ── screenshots ── */
img { max-width: 100%; border-radius: 6px; border: 1px solid var(--bd);
  margin: .75rem 0 1.25rem; display: block; }

/* ── codehilite ── */
.codehilite { background: var(--sf); border: 1px solid var(--bd);
  border-radius: 6px; padding: 1rem 1.25rem; overflow-x: auto; margin-bottom: 1.25rem; }
.codehilite pre { background: none; border: none; padding: 0; margin: 0; }

/* ── footer ── */
footer {
  text-align: center; font-size: 12px; color: var(--mt);
  padding: 1.5rem; border-top: 1px solid var(--bd);
}
"""

TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} — flamedisk</title>
<style>{css}</style>
</head>
<body>
<header>
  <a class="logo" href="index.html"><span class="fl">flame</span><em>disk</em></a>
  <nav>{nav_links}</nav>
  <span class="version">{version}</span>
</header>
<div class="page">
  <aside class="sidebar">{toc}</aside>
  <main>{body}</main>
</div>
<footer>flamedisk {version} · MIT licence</footer>
</body>
</html>
"""


def read_version() -> str:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore[no-reuse-of-unused-import]
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def convert(md_text: str, img_prefix: str = "") -> tuple[str, str]:
    """Return (html_body, toc_html)."""
    # Rewrite image paths to be relative to _site root
    if img_prefix:
        md_text = md_text.replace("](docs/img/", f"]({img_prefix}")

    md = markdown.Markdown(extensions=EXTENSIONS, extension_configs={
        "codehilite": {"css_class": "codehilite", "guess_lang": False},
        "toc": {"title": "On this page", "toc_depth": "2-3"},
    })
    body = md.convert(md_text)
    toc  = md.toc  # type: ignore[attr-defined]
    return body, toc


def nav_links(active: str) -> str:
    parts = []
    for label, href in NAV:
        cls = ' class="active"' if href == active else ""
        parts.append(f'<a href="{href}"{cls}>{label}</a>')
    return "".join(parts)


def render(title: str, body: str, toc: str, active: str, version: str) -> str:
    return TEMPLATE.format(
        title=title, css=CSS,
        nav_links=nav_links(active),
        toc=toc or "",
        body=body,
        version=version,
    )


def build() -> None:
    version = read_version()
    SITE.mkdir(exist_ok=True)

    # Copy screenshots
    dest_img = SITE / "img"
    if dest_img.exists():
        shutil.rmtree(dest_img)
    shutil.copytree(DOCS / "img", dest_img)

    pages = [
        ("index.html",     "Home",          ROOT / "README.md",      "img/"),
        ("api.html",       "API reference", DOCS / "api.md",         ""),
        ("changelog.html", "Changelog",     ROOT / "CHANGELOG.md",   ""),
    ]

    for filename, title, src, img_prefix in pages:
        md_text = src.read_text(encoding="utf-8")
        body, toc = convert(md_text, img_prefix)
        html = render(title, body, toc, filename, version)
        (SITE / filename).write_text(html, encoding="utf-8")
        print(f"  {filename}")

    print(f"Built {len(pages)} pages → {SITE}/")


if __name__ == "__main__":
    build()
