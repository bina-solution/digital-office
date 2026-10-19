#!/usr/bin/env python3
"""Give every page of the office's public site a top-level heading — one-off, run ON the VPS.

Why it exists. The site (digital-office.co.il, served from the VPS at
/opt/bina-sites/digital-office/site and from the sites-state volume's public/ copy) has four pages
with NO <h1> at all — features.html, business-model.html, vision.html, about.html — which is both a
WCAG failure (a page should carry a top-level heading) and an SEO defect. The pages are hand-written
HTML, so the fix is a one-off script rather than a template change; it is kept here so the next
person (and the next office) can see exactly what was done and repeat it.

It adds a visually hidden h1 (class `sr-only`, plus the rule in assets/style.css) carrying the page's
own <title>, so the design does not move a pixel while the document gains its heading. Backs up every
file it touches. Idempotent: a page that already has an h1 is left alone.
"""
import os
import re
import shutil
import sys

SITE = os.environ.get("SITE_DIR", "/opt/bina-sites/digital-office/site")
PUBLIC = os.environ.get("SITE_PUBLIC", "/var/lib/docker/volumes/deployment-hacohen_sites_state/_data/public/digital-office")
BACKUP = os.environ.get("SITE_BACKUP", "/root/site-a11y-backup")
PAGES = ("features.html", "business-model.html", "vision.html", "about.html")
SR_ONLY = ".sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}\n"


def main() -> int:
    os.makedirs(BACKUP, exist_ok=True)
    changed = 0
    for name in PAGES:
        path = os.path.join(SITE, name)
        if not os.path.exists(path):
            print(f"{name}: missing")
            continue
        text = open(path, encoding="utf-8").read()
        if "<h1" in text:
            print(f"{name}: already has an h1")
            continue
        shutil.copy2(path, os.path.join(BACKUP, name))
        # The page's own lead heading is its real title; the <title> element is not reliable here
        # (the pages carry their copy in data-da attributes, and a first run fell back to the file
        # name — a hidden heading that says "features.html" is worse than none).
        lead = re.search(r"<h2[^>]*>(.*?)</h2>", text, re.S)
        title = ""
        if lead:
            title = re.sub(r"<[^>]+>", "", lead.group(1)).strip()
        if not title:
            match = re.search(r"<title>(.*?)</title>", text, re.S)
            title = re.split(r"[|·—]", (match.group(1).strip() if match else name))[0].strip()
        body = text.find("<body")
        if body < 0:
            print(f"{name}: no <body>")
            continue
        end = text.find(">", body) + 1
        text = text[:end] + "\n<h1 class=\"sr-only\">" + title + "</h1>" + text[end:]
        open(path, "w", encoding="utf-8").write(text)
        print(f"{name}: h1 added — {title[:60]}")
        changed += 1
    # Second pass: an h1 added by an earlier run whose text is a file name gets its real text back.
    for name in PAGES:
        path = os.path.join(SITE, name)
        text = open(path, encoding="utf-8").read()
        m = re.search(r'<h1 class="sr-only">([^<]*)</h1>', text)
        if not m or m.group(1).strip() != name:
            continue
        lead = re.search(r"<h2[^>]*>(.*?)</h2>", text, re.S)
        if not lead:
            continue
        real = re.sub(r"<[^>]+>", "", lead.group(1)).strip()
        if not real:
            continue
        open(path, "w", encoding="utf-8").write(text.replace(m.group(0), '<h1 class="sr-only">' + real + "</h1>"))
        print(f"{name}: h1 text fixed — {real[:60]}")
        changed += 1

    css = os.path.join(SITE, "assets", "style.css")
    if os.path.exists(css):
        current = open(css, encoding="utf-8").read()
        if ".sr-only" not in current:
            shutil.copy2(css, os.path.join(BACKUP, "style.css"))
            open(css, "a", encoding="utf-8").write("\n" + SR_ONLY)
            print("style.css: .sr-only added")
    for name in PAGES:
        src, dst = os.path.join(SITE, name), os.path.join(PUBLIC, name)
        if os.path.exists(src) and os.path.isdir(PUBLIC):
            shutil.copy2(src, dst)
    if os.path.isdir(PUBLIC):
        shutil.copy2(css, os.path.join(PUBLIC, "assets", "style.css"))
    print("pages changed:", changed)
    print("h1 per page:", {n: open(os.path.join(SITE, n), encoding="utf-8").read().count("<h1") for n in PAGES})
    return 0


if __name__ == "__main__":
    sys.exit(main())
