#!/usr/bin/env python3
"""Build the static mobile/web site into _site/.

Mirrors the same html/ folder the desktop launcher reads, plus the
hand-authored shell in web/ (index.html, style.css, app.js, manifest,
service worker, icons). Also generates guides-index.json, which the
front end (web/app.js) fetches to build its sidebar -- titles, ordering,
and "is this an interactive tool" detection all replicate the exact
same logic launcher.py uses (read_title / display_name_from_filename /
is_interactive_program / extract_plain_text), so the mobile site and
the desktop app always agree on what a guide is called and how it's
ordered.

Run this locally with `python3 scripts/build_site.py`, or let the
"Build and deploy mobile site" GitHub Actions workflow run it
automatically on every push to main that touches html/, web/, or the
logo.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_DIR = REPO_ROOT / "html"
WEB_DIR = REPO_ROOT / "web"
OUT_DIR = REPO_ROOT / "_site"

# Same regexes as launcher.py -- kept in sync deliberately so the mobile
# site's titles/ordering/tool-detection never drift from the desktop app.
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
ORDER_PREFIX_RE = re.compile(r"^\d+[\s_.\-]+")
SCRIPT_TAG_RE = re.compile(r"<script\b", re.IGNORECASE)
SCRIPT_STYLE_BLOCK_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

SIDEBAR_HIDDEN_FILES = {"01_welcome.html"}
SEARCH_TEXT_MAX_CHARS = 4000


def display_name_from_filename(filename: str) -> str:
    name = Path(filename).stem
    name = ORDER_PREFIX_RE.sub("", name)
    name = name.replace("_", " ").replace("-", " ")
    return name.strip().title() or filename


def read_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return display_name_from_filename(path.name)
    match = TITLE_TAG_RE.search(text)
    if match:
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        if title:
            return title
    return display_name_from_filename(path.name)


def is_interactive_program(text: str) -> bool:
    return bool(SCRIPT_TAG_RE.search(text))


def extract_plain_text(text: str) -> str:
    text = SCRIPT_STYLE_BLOCK_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return WHITESPACE_RE.sub(" ", text).strip()[:SEARCH_TEXT_MAX_CHARS]


def build_guides_index() -> dict:
    docs = []
    home_file = None
    if HTML_DIR.exists():
        for path in sorted(HTML_DIR.glob("*.htm*"), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hidden = path.name in SIDEBAR_HIDDEN_FILES
            if hidden and home_file is None:
                home_file = path.name
            docs.append({
                "file": path.name,
                "title": read_title(path),
                "isProgram": is_interactive_program(raw),
                "hidden": hidden,
                "text": extract_plain_text(raw),
            })
    return {
        "docs": docs,
        "homeFile": home_file,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> int:
    if not HTML_DIR.exists():
        print(f"error: {HTML_DIR} does not exist", file=sys.stderr)
        return 1
    if not WEB_DIR.exists():
        print(f"error: {WEB_DIR} does not exist", file=sys.stderr)
        return 1

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    shutil.copytree(WEB_DIR, OUT_DIR)

    # Stamp the service worker with a fresh build id so every deploy
    # gets its own cache name (see web/sw.js's comment).
    sw_path = OUT_DIR / "sw.js"
    if sw_path.exists():
        sw_text = sw_path.read_text(encoding="utf-8")
        sw_text = sw_text.replace("__BUILD_ID__", str(int(time.time())))
        sw_path.write_text(sw_text, encoding="utf-8")

    # Mirror the actual guide content so the front end can fetch it
    # same-origin (no CORS, no external cache staleness, no rate limits).
    out_html_dir = OUT_DIR / "html"
    out_html_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in HTML_DIR.glob("*.htm*"):
        if path.is_file():
            shutil.copy2(path, out_html_dir / path.name)
            copied += 1

    index = build_guides_index()
    (OUT_DIR / "guides-index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

    print(f"Built {OUT_DIR} — {copied} guide file(s), homeFile={index['homeFile']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
