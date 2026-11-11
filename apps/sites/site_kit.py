# Lifted from apps/digital-assets/site_kit.py — the slot rules are digital-assets'; this copy stays that file (G110)
"""digital-assets.site_kit — every text and picture on the website is a slot.

The contract with a website is HTML attributes, and nothing else (no script on the page, no runtime
fetch, nothing that search engines cannot read):

    <h1 data-da="content.website.home-hero">…</h1>              the element's TEXT is the slot
    <img data-da-src="identity.logo.primary" src="…">            the image's SRC is the slot's file
    <a data-da-href="content.docs.home" href="…">…</a>           the link's HREF
    <meta name="description" data-da-content="identity.description.short" content="…">
    <img data-da-alt="identity.name.brand-he" alt="…">           an ALT text
    <input data-da-placeholder="content.website.form-name" placeholder="…">   a field's PLACEHOLDER
    <a data-da-title="content.website.reset" title="…">                    a TITLE (the tooltip)
    <button data-da-aria-label="content.website.menu" aria-label="…">      what a screen reader says

    <span data-da-attr-data-to-value="content.website.units" data-to-value="…">   ANY other attribute

The last four are texts a visitor reads (or hears) as much as a heading: a contact form's «שם» and
«אימייל», a menu button's «תפריט», the number a counter widget counts up to (it lives in
`data-to-value`; the element's own text is only where the animation starts). A text that lives only
in an attribute was otherwise the one text on a page that could not come from digital assets.

`scan(html)` lists what a page already maps (key, attribute, current value) and — just as useful —
what it does NOT map yet: every heading, paragraph, button, image and meta description, so the owner
can see which texts on the site are still hand-written. `apply(html, bundle)` rewrites the mapped
values from the bundle (`GET /api/bundle`), and reports what it changed, what the page uses that the
bundle lacks, and what the bundle has that the page never shows.

Pure stdlib, so the same file runs inside `sites` (managed sites), in a static-site build step, or as
a command on a folder:

    python3 site_kit.py scan  page.html
    python3 site_kit.py apply --bundle http://digital-assets:8985/api/bundle --dir ./site [--files _da]
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ATTRS = {"data-da": "text", "data-da-src": "src", "data-da-href": "href",
         "data-da-content": "content", "data-da-alt": "alt", "data-da-placeholder": "placeholder",
         "data-da-title": "title", "data-da-aria-label": "aria-label"}
ATTR_PREFIX = "data-da-attr-"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr"}
CANDIDATES = {"h1", "h2", "h3", "p", "button", "title", "img", "a", "li", "figcaption", "blockquote"}


class _Finder(HTMLParser):
    """Records, for every element, where its start tag and its content begin and end (offsets into
    the original text), so a value can be spliced in without re-serialising the whole page."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.text = text
        self._lines = [0]
        for m in re.finditer("\n", text):
            self._lines.append(m.end())
        self.stack: list[dict] = []
        self.elements: list[dict] = []

    def _off(self) -> int:
        line, col = self.getpos()
        return self._lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self._off()
        raw = self.get_starttag_text() or ""
        el = {"tag": tag, "attrs": dict(attrs), "start": start, "inner_start": start + len(raw),
              "raw": raw, "inner_end": None, "text": ""}
        self.elements.append(el)
        if tag not in VOID and not raw.rstrip().endswith("/>"):
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        start = self._off()
        raw = self.get_starttag_text() or ""
        self.elements.append({"tag": tag, "attrs": dict(attrs), "start": start,
                              "inner_start": start + len(raw), "raw": raw, "inner_end": None, "text": ""})

    def handle_endtag(self, tag):
        off = self._off()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                el = self.stack[i]
                el["inner_end"] = off
                el["text"] = self.text[el["inner_start"]:off]
                del self.stack[i:]
                return


def _elements(text: str) -> list[dict]:
    f = _Finder(text)
    f.feed(text)
    f.close()
    return f.elements


def _plain(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _mapping(attrs: dict) -> list[tuple[str, str]]:
    """(the data-da attribute, what it sets) for one element: the named ones in ATTRS, then every
    `data-da-attr-<name>` — any other attribute whose value is a text (a counter's `data-to-value`)."""
    out = [(a, w) for a, w in ATTRS.items() if attrs.get(a)]
    out += [(a, a[len(ATTR_PREFIX):]) for a in attrs
            if a.startswith(ATTR_PREFIX) and len(a) > len(ATTR_PREFIX) and attrs.get(a)]
    return out


def scan(text: str) -> dict:
    mapped, candidates = [], []
    for el in _elements(text):
        pairs = _mapping(el["attrs"])
        keys = [(a, el["attrs"][a]) for a, _ in pairs]
        for (attr, key), (_, what) in zip(keys, pairs):
            cur = _plain(el["text"]) if what == "text" else el["attrs"].get(what, "")
            mapped.append({"key": key, "what": what, "tag": el["tag"], "current": (cur or "")[:200]})
        if keys or el["tag"] not in CANDIDATES:
            continue
        if el["tag"] == "img":
            candidates.append({"tag": "img", "what": "src", "current": el["attrs"].get("src", "")})
        elif el["tag"] == "a":
            continue                                   # links are mapped on purpose, not listed
        else:
            t = _plain(el["text"])
            if t and not re.fullmatch(r"[\W\d_]+", t):
                candidates.append({"tag": el["tag"], "what": "text", "current": t[:160]})
    for el in _elements(text):                          # the meta description, if unmapped
        a = el["attrs"]
        if el["tag"] == "meta" and (a.get("name") == "description" or a.get("property") in
                                    ("og:title", "og:description", "og:image")) and not a.get("data-da-content"):
            candidates.append({"tag": "meta", "what": "content", "name": a.get("name") or a.get("property"),
                               "current": (a.get("content") or "")[:160]})
    return {"mapped": mapped, "unmapped": candidates,
            "keys": sorted({m["key"] for m in mapped})}


try:
    # The tag's attributes are walked with the SAME expressions HTMLParser uses to read them into
    # `el["attrs"]`, so the attribute replaced here is by construction the one the parser saw: a quoted
    # value is consumed whole (`onclick="… title='x'"` is not a title), and an unquoted one with `=` in it
    # (`href=?p=2`) does not end the walk — which, when it did, appended a SECOND attribute: the browser
    # shows the first (old) value, the parser keeps the last, and the slot silently never appeared.
    from html.parser import attrfind_tolerant as _ATTRFIND, tagfind_tolerant as _TAGFIND
except ImportError:                                    # pragma: no cover — the stdlib's own, as of 3.9–3.12
    _ATTRFIND = re.compile(r'((?<=[\'"\s/])[^\s/>][^\s/=>]*)(\s*=+\s*(\'[^\']*\'|"[^"]*"|(?![\'"])[^>\s]*))?'
                           r'(?:\s|/(?!>))*')
    _TAGFIND = re.compile(r'([a-zA-Z][^\t\n\r\f />\x00]*)(?:\s|/(?!>))*')


def _set_attr(raw: str, name: str, value: str) -> str:
    esc = htmllib.escape(value, quote=True)
    tag = _TAGFIND.match(raw, 1)
    k = tag.end() if tag else len(raw)
    while k < len(raw):
        m = _ATTRFIND.match(raw, k)
        if not m or m.end() == k:
            break
        if m.group(1).lower() == name.lower():
            end = m.end(2) if m.group(2) else m.end(1)
            return f'{raw[:m.start(1)]}{m.group(1)}="{esc}"{raw[end:]}'
        k = m.end()
    close = raw.rstrip()
    tail = "/>" if close.endswith("/>") else ">"
    body = close[: -len(tail)].rstrip()
    return f'{body} {name}="{esc}"{tail}'


def _text_html(entry: dict) -> str:
    t = entry.get("text") or ""
    out = htmllib.escape(t)
    if entry.get("kind") in ("richtext", "list", "price-list", "hours", "address"):
        out = out.replace("\n", "<br>\n")
    return out


def apply(text: str, bundle: dict, file_url=None) -> tuple[str, dict]:
    """Rewrite every mapped value. `file_url(entry)` decides the URL a file gets on the site (a
    copied local path, or the bundle's own URL). Returns (new_html, report)."""
    slots = (bundle or {}).get("slots") or {}
    edits = []                                           # (start, end, replacement)
    changed, missing = [], set()
    used = set()
    for el in _elements(text):
        raw = el["raw"]
        new_raw = raw
        for attr, what in _mapping(el["attrs"]):
            key = el["attrs"].get(attr)
            used.add(key)
            entry = slots.get(key)
            if not entry:
                missing.add(key)
                continue
            if what == "text":
                if el["inner_end"] is None:
                    continue
                new_inner = _text_html(entry)
                if el["text"] != new_inner:
                    edits.append((el["inner_start"], el["inner_end"], new_inner))
                    changed.append({"key": key, "what": what})
            else:
                # A FILE goes through `file_url` into whichever attribute names it (a lazy loader's
                # `data-src` as much as `src`): the bundle's own URL is the asset service's internal
                # address, which a page must never show. A TEXT goes in as it is — except into `src`,
                # where a text slot has nothing to point at and the attribute is left as it was.
                url = entry.get("url")
                as_file = (file_url(entry) if file_url else url) if url else None
                if what == "src":
                    value = as_file
                else:
                    value = entry.get("text") or as_file or ""
                if value is None:
                    continue
                if el["attrs"].get(what) != value:
                    new_raw = _set_attr(new_raw, what, value)
                    changed.append({"key": key, "what": what})
        if new_raw != raw:
            edits.append((el["start"], el["start"] + len(raw), new_raw))
    for start, end, rep in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + rep + text[end:]
    return text, {"changed": changed, "missing": sorted(missing),
                  "unused": sorted(set(slots) - used)}


# ── command line: scan a page, or apply a bundle to a folder of pages ────────────────────────────
def _fetch_bundle(src: str) -> dict:
    if re.match(r"https?://", src):
        import urllib.request
        with urllib.request.urlopen(src, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    return json.loads(Path(src).read_text(encoding="utf-8"))


def _main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "scan":
        print(json.dumps(scan(Path(argv[1]).read_text(encoding="utf-8")), ensure_ascii=False, indent=2))
        return 0
    if argv and argv[0] == "apply":
        args = dict(zip(argv[1::2], argv[2::2]))
        bundle = _fetch_bundle(args["--bundle"])
        root = Path(args.get("--dir", "."))
        sub = args.get("--files")                      # copy files next to the pages when given
        total = {"pages": 0, "changed": 0, "missing": set()}

        def local(entry):
            if not sub:
                return entry["url"]
            import urllib.request
            name = f"{entry['sha']}.{entry['url'].rsplit('.', 1)[-1].split('?')[0]}"
            dest = root / sub / name
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(entry["url"], timeout=60) as r:
                    dest.write_bytes(r.read())
            return f"/{sub}/{name}"
        for page in sorted(root.rglob("*.html")):
            src = page.read_text(encoding="utf-8")
            out, rep = apply(src, bundle, local)
            if out != src:
                page.write_text(out, encoding="utf-8")
            total["pages"] += 1
            total["changed"] += len(rep["changed"])
            total["missing"] |= set(rep["missing"])
        print(json.dumps({**total, "missing": sorted(total["missing"])}, ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
