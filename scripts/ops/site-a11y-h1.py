#!/usr/bin/env python3
"""Give every page of the office's public site a top-level heading — one-off, run ON the VPS.

Why it exists. The site (digital-office.co.il, served from the VPS at
/opt/bina-sites/digital-office/site and from the sites-state volume's public/ copy) has four pages
with NO <h1> at all — features.html, business-model.html, vision.html, about.html — which is both a
WCAG failure (a page should carry a top-level heading) and an SEO defect. The pages are hand-written
HTML, so the fix is a one-off script rather than a template change; it is kept here so the next
person (and the next office) can see exactly what was done and repeat it.

It adds a visually hidden h1 (class `sr-only`) carrying the page's lead heading, so the design does not
move a pixel while the document gains its heading. Backs up every file it touches. Idempotent: a page
that already has an h1 is left alone.

The `.sr-only` rule goes INTO the page's own <style>, never into assets/style.css: these pages inline
all their CSS and load no stylesheet. The first run (2026-10-09) appended the rule to style.css only, so
on all four pages the "hidden" h1 showed at full size above the header — the owner's phone, 2026-11-02
(DGO-1132). A rerun repairs such a page: an sr-only element with no rule in the page gets the rule.
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


def with_rule(text: str) -> str:
    """The page with the `.sr-only` rule at the top of its own first <style>, when it uses the class and
    lacks the rule; otherwise the page unchanged. A page with no <style> gets one before </head>."""
    if 'class="sr-only"' not in text or ".sr-only{" in text:
        return text
    style = re.search(r"<style[^>]*>", text)
    if style:
        return text[:style.end()] + SR_ONLY + text[style.end():]
    head = text.find("</head>")
    return text if head < 0 else text[:head] + "<style>" + SR_ONLY + "</style>\n" + text[head:]


def backup(path: str, name: str) -> None:
    """A copy under BACKUP that never overwrites an earlier one: the first backup is the original page."""
    dst, n = os.path.join(BACKUP, name), 1
    while os.path.exists(dst):
        dst, n = os.path.join(BACKUP, f"{name}.{n}"), n + 1
    shutil.copy2(path, dst)


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
        backup(path, name)
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
    # Third pass: the rule that hides the h1, inside the page itself (see the docstring, DGO-1132).
    for name in PAGES:
        path = os.path.join(SITE, name)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        fixed = with_rule(text)
        if fixed == text:
            continue
        backup(path, name)
        open(path, "w", encoding="utf-8").write(fixed)
        print(f"{name}: .sr-only rule added to the page's own <style>")
        changed += 1

    for name in PAGES:
        src, dst = os.path.join(SITE, name), os.path.join(PUBLIC, name)
        if os.path.exists(src) and os.path.isdir(PUBLIC):
            shutil.copy2(src, dst)
    print("pages changed:", changed)
    for n in PAGES:
        t = open(os.path.join(SITE, n), encoding="utf-8").read()
        hidden = ".sr-only{" in t or 'class="sr-only"' not in t
        print(f"{n}: h1={t.count('<h1')} hidden-by-rule={hidden}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
