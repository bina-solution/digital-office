#!/usr/bin/env python3
"""recheck.py — the quarterly check that every written piece is still true (DGO-817, seo-1009).

    python3 apps/digital-assets/content/recheck.py [--today 2026-11-10] [--no-net] [--write] [--strict]

For every piece in the library (content/<type>/<slug>.he.md), the same fixed list, over its body AND the public
lines of its front matter (title, seo_title, meta_description, summary, the FAQ):
  1. LINKS     every external link (Markdown, <autolinks>, a placeholder's `url:`, `sources:`, `project:`) still
               answers to a GET: a 4xx/5xx, a redirect loop or no answer is broken; a redirect that lands on the
               site's error page is broken; 401/403/429 is «not for a robot» (opened by hand); a move says where
               it goes now
  2. FACTS     FACTS.md changed after the piece's `updated` date → its DGO lines are read again against FACTS.md
  3. DUE       a piece is due 91 days after its `updated` (or `published`) date. It is flagged in the run BEFORE that
               day (the run that comes before it), never a quarter late
  4. SOURCES   a source last `accessed` more than 91 days ago, or with no date, is opened again
  5. DATED     a price (₪, $, €, ש״ח, אירו, דולר …) in a paragraph — or a table and the paragraph above it — that
               carries no year
  6. WORDS     a line that says «משרד»: an installation is a «לשכה», and «משרד» is a physical office only (BRIEF.md) —
               a person reads each one and keeps it only when it means a physical office
`updated` moves only when the content really changed (seo-1009), so this check never touches a piece: it reports.
--write keeps the report as rechecks/<year>-Q<n>.md; everything from the MANUAL marker line on (the reading by
hand) is kept as it was. --strict exits 1 when a link is broken or a piece is due.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import http.client
import ipaddress
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:                                      # the Mac host has none; the engine guest does
    sys.exit("recheck.py needs PyYAML: pip install pyyaml")

HERE = Path(__file__).resolve().parent
TYPES = ("article", "project", "tutorial", "comparison", "directory", "news", "report", "post", "glossary")
QUARTER = dt.timedelta(days=91)
MANUAL = "<!-- manual: the reading by hand, from here on; recheck.py --write keeps it as it is -->"
#: a Markdown link (one level of parentheses inside, a "title" after it), an autolink, a placeholder's url:
LINKS = (re.compile(r"\]\((https?://(?:[^()\s]|\([^()\s]*\))+)"), re.compile(r"<(https?://[^>\s]+)>"),
         re.compile(r"\|\s*url:\s*(https?://[^\s\]|]+)"))
PRICE = re.compile(r"(?:[₪$€]\s?\d)|(?:\d[\d,.]*\s?(?:אלף\s?)?(?:[₪$€]|ש״ח|ש\"ח|ש''ח|שקל|דולר|יורו|אירו|USD|EUR|NIS))")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)          # `$1` in code is not a price: code is left out, not `$N`
YEAR = re.compile(r"(?<!\d)20[23]\d(?!\d)")              # 2020–2039, also «ב2026»; never «2000 מילים» or port 2049
AGENT = "dgo-content-recheck/1 (+https://digital-office.co.il)"
#: answers that say «not for a robot», not «gone»: such a link is reported as not checked, never as broken
BLOCKED = (401, 403, 429)
#: where a redirect lands when the page is gone (boi.org.il/PublicApi → /404 to a HEAD), whatever the extension
ERROR_PAGE = re.compile(r"(?:^|/)(?:404|error|not-?found|page-not-found)(?:\.\w+)?/?$", re.I)
http.client._MAXHEADERS = 1000          # a CDN that sends 100+ headers is an answer, not a failure (measured)


def _date(v) -> dt.date | None:
    if isinstance(v, dt.datetime):                       # «2026-10-19 10:00:00» parses as a datetime
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _around(line: str, word: str, before: int = 30, after: int = 50) -> str:
    """The words around `word` in a line, so the excerpt shows what the reader has to judge."""
    text = " ".join(line.split())
    at = text.find(word)
    return text[max(at - before, 0):at + len(word) + after]


def split_piece(text: str) -> tuple[dict, str, int]:
    """(front matter, body, the body's first line in the file). A file with no closed front matter is all body."""
    text = text.lstrip("﻿")
    if text.startswith("---"):
        m = re.search(r"^---[ \t]*$", text[3:], re.M)
        if m:
            raw, rest = text[3:3 + m.start()], text[3 + m.end():]
            try:
                front = yaml.safe_load(raw)
            except (yaml.YAMLError, ValueError, TypeError):  # «updated: 2026-02-30» raises ValueError, not YAMLError
                front = None
            if isinstance(front, dict):
                body = rest[1:] if rest.startswith("\n") else rest
                return front, body, text[:len(text) - len(body)].count("\n") + 1
    return {}, text, 1                                    # no front matter it can read: all of it is body


def pieces(root: Path) -> list[dict]:
    out = []
    for t in TYPES:
        for f in sorted((root / t).glob("*.he.md")) if (root / t).is_dir() else []:
            front, body, first = split_piece(f.read_text(encoding="utf-8-sig"))
            out.append({"path": f"{t}/{f.name}", "front": front, "body": body, "first_line": first})
    return out


def _list(v) -> list:
    return v if isinstance(v, list) else []               # `faq: 5` or `sources: x` is no list, not a crash


def public_lines(front: dict) -> list[str]:
    """The front matter a reader sees: the title lines, the description, the summary, the FAQ."""
    out = [str(front.get(k) or "") for k in ("title", "seo_title", "meta_description", "summary")]
    for qa in _list(front.get("faq")):
        if isinstance(qa, dict):
            out += [str(qa.get("q") or ""), str(qa.get("a") or "")]
    return [s for s in out if s]


def links_of(p: dict) -> list[str]:
    text = p["body"] + "\n" + "\n".join(public_lines(p["front"]))
    found = {u.rstrip(".,;") for rx in LINKS for u in rx.findall(text)}
    for s in _list(p["front"].get("sources")):
        if isinstance(s, dict) and str(s.get("url", "")).startswith("http"):
            found.add(str(s["url"]))
    proj = p["front"].get("project")
    if isinstance(proj, dict):
        found |= {str(proj[k]) for k in ("website", "repo") if str(proj.get(k, "")).startswith("http")}
    return sorted(found)


def _private(host: str) -> bool:
    try:
        return any(not ipaddress.ip_address(a[4][0]).is_global      # private, loopback, CGNAT/Tailscale 100.64/10
                   for a in socket.getaddrinfo(host, None))
    except (OSError, ValueError):
        return False


class _NoInward(urllib.request.HTTPRedirectHandler):
    """A public page may not send this check to an address inside the office's own network."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        src, dst = urllib.parse.urlsplit(req.full_url).hostname or "", urllib.parse.urlsplit(newurl).hostname or ""
        if dst != src and _private(dst) and not _private(src):
            raise urllib.error.HTTPError(newurl, 310, "a redirect into a private address, not followed", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl() -> ssl.SSLContext:
    """The system's CA store: a Python built by uv or pyenv has none of its own (every https said «verify failed»)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for cafile in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if Path(cafile).exists():
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


_CTX = _ssl()
_OPENER = urllib.request.build_opener(_NoInward(), urllib.request.HTTPSHandler(context=_CTX))


def _as_sent(url: str) -> str:
    """The address as a browser sends it: a Hebrew host in IDNA, a Hebrew path, query or fragment %-encoded."""
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").encode("idna").decode("ascii") if p.hostname else ""
    netloc = host + (f":{p.port}" if p.port else "")
    q = lambda s: urllib.parse.quote(s, safe="/?#[]@!$&'()*+,;=%~:")      # noqa: E731
    return urllib.parse.urlunsplit((p.scheme, netloc, q(p.path), q(p.query), q(p.fragment)))


def check_url(url: str, timeout: float = 15) -> tuple[int | None, str]:
    """(status, the address it ends at) — or (None, why) when nothing answered, after a second try.

    A GET, never a HEAD: gov.il answers HEAD with 404 and the Bank of Israel redirects a HEAD to its /404 page,
    while both answer the reader's GET with 200 (measured 2026-11-10). The body is not read."""
    why = "no answer"
    for _attempt in (1, 2):
        try:
            req = urllib.request.Request(_as_sent(url), method="GET", headers={"User-Agent": AGENT, "Accept": "*/*"})
            with _OPENER.open(req, timeout=timeout) as r:
                return r.status, r.geturl()
        except urllib.error.HTTPError as e:                # a 3xx here is a loop or a redirect with no Location
            return e.code, e.geturl() or url
        except Exception as e:                            # noqa: BLE001 — any failure to answer is «no answer»
            why = str(getattr(e, "reason", e))[:120]      # a reset or a timeout: once more, then it is said
    return None, why


def facts_changed(root: Path) -> dt.date | None:
    """The last day FACTS.md changed: its last commit — or its file date when it has edits not yet committed."""
    f = root / "FACTS.md"
    if not f.exists():
        return None
    mtime = dt.date.fromtimestamp(f.stat().st_mtime)
    try:
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", f.name], cwd=root, capture_output=True,
                               timeout=30)                # staged or not: any edit since the last commit
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", f.name], cwd=root, capture_output=True,
                             text=True, timeout=30).stdout.strip()
        if out and dirty.returncode == 0:
            return dt.date.fromisoformat(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return mtime


def _undated(paragraphs: list[str]) -> list[str]:
    out = []
    for i, par in enumerate(paragraphs):
        if not PRICE.search(par) or YEAR.search(par):
            continue
        if par.lstrip().startswith("|") and i and YEAR.search(paragraphs[i - 1]):
            continue                                      # a table carries the date of the line above it
        out.append(" ".join(par.split())[:90])
    return out


def next_run(today: dt.date) -> dt.date:
    q = (today.month - 1) // 3 + 1
    return dt.date(today.year + (q == 4), 1 if q == 4 else 3 * q + 1, 1)


def recheck(root: Path, today: dt.date, facts_date: dt.date | None, net: bool = True) -> list[dict]:
    found = pieces(root)
    links: dict = {}
    for p in found:
        p["links"] = links_of(p)
        links.update({u: None for u in p["links"]})
    if net and links:
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            for u, res in zip(links, pool.map(check_url, links)):
                links[u] = res
    upcoming = next_run(today)
    out = []
    for p in found:
        fr = p["front"]
        anchor = _date(fr.get("updated")) or _date(fr.get("published"))
        due_on = anchor + QUARTER if anchor else None
        broken, moved, blocked = [], [], []
        for u in p["links"]:
            res = links.get(u)
            if res is None:
                continue
            status, where = res
            unq = urllib.parse.unquote                    # a Hebrew path comes back %-encoded: the same address
            redirected = unq(where).rstrip("/") != unq(u).rstrip("/")
            if status in BLOCKED:
                blocked.append(f"{u} → {status}")
            elif status is None or status >= 300 or (redirected and ERROR_PAGE.search(urllib.parse.urlsplit(where).path)):
                broken.append(f"{u} → {status or where}" + (f" ({where})" if status and redirected else ""))
            elif redirected:
                moved.append(f"{u} → {where}")
        stale = [str(s.get("url")) + ("" if _date(s.get("accessed")) else " (בלי תאריך פתיחה)")
                 for s in _list(fr.get("sources")) if isinstance(s, dict)
                 and (not _date(s.get("accessed")) or _date(s.get("accessed")) + QUARTER < today)]
        undated = _undated(public_lines(fr)) + _undated(re.split(r"\n\s*\n", CODE.sub("", p["body"])))
        office = [f"מטא: …{_around(s, 'משרד')}…" for s in public_lines(fr) if "משרד" in s]
        office += [f"{n}: …{_around(ln, 'משרד')}…" for n, ln in enumerate(p["body"].split("\n"), p["first_line"])
                   if "משרד" in ln]                         # n is the line in the FILE, where an editor opens it
        out.append({"path": p["path"], "updated": anchor.isoformat() if anchor else None,
                    "due_on": due_on.isoformat() if due_on else None, "due": bool(due_on and due_on < upcoming),
                    "facts_newer": bool(facts_date and anchor and facts_date > anchor),
                    "links": len(p["links"]), "broken": broken, "moved": moved, "blocked": blocked,
                    "stale_sources": stale, "undated_prices": undated, "office_word": office, "checked_links": net})
    return out


def report(rows: list[dict], today: dt.date, facts_date: dt.date | None) -> str:
    q = (today.month - 1) // 3 + 1
    lines = [f"# הבדיקה הרבעונית של הספרייה — {today.year} Q{q}", "",
             f"- רצה: {today.isoformat()} · FACTS.md השתנה לאחרונה: {facts_date or '—'} · הריצה הבאה: "
             f"{next_run(today).isoformat()}",
             f"- {len(rows)} פיסות · {sum(r['links'] for r in rows)} קישורים"
             + ("" if all(r["checked_links"] for r in rows) else " (הקישורים לא נבדקו בריצה הזו)"),
             f"- שבורים: {sum(len(r['broken']) for r in rows)} · הופנו: {sum(len(r['moved']) for r in rows)} · "
             f"חסומים לבדיקה אוטומטית (401/403/429, לפתוח ביד): {sum(len(r['blocked']) for r in rows)} · "
             f"מגיע זמנן עד הריצה הבאה: {sum(r['due'] for r in rows)} · FACTS חדש מהן: "
             f"{sum(r['facts_newer'] for r in rows)} · מקורות לפתוח שוב: {sum(len(r['stale_sources']) for r in rows)} · "
             f"מחירים בלי שנה: {sum(len(r['undated_prices']) for r in rows)} · «משרד» לבדיקה: "
             f"{sum(len(r['office_word']) for r in rows)}", ""]
    for r in rows:
        lines += [f"## {r['path']}", "",
                  f"- עודכן {r['updated'] or '—'}; הבדיקה שלו ב-{r['due_on'] or '—'}"
                  + (" — **בריצה הזו**" if r["due"] else ""),
                  f"- FACTS.md השתנה אחריו: {'כן — לקרוא שוב כל שורה על DGO מול FACTS.md' if r['facts_newer'] else 'לא'}",
                  f"- קישורים: {r['links']}"]
        lines += [f"  - שבור: {b}" for b in r["broken"]] + [f"  - הופנה: {m}" for m in r["moved"]]
        lines += [f"  - חסום לרובוט, לפתוח ביד: {b}" for b in r["blocked"]]
        lines += [f"- מקור לפתוח שוב: {s}" for s in r["stale_sources"]]
        lines += [f"- מחיר בלי שנה: «{u}…»" for u in r["undated_prices"]]
        lines += [f"- «משרד» (שורה {o}) — לשכה, אלא אם זה משרד פיזי" for o in r["office_word"]]
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--root", default=str(HERE))
    ap.add_argument("--no-net", action="store_true", help="skip the link check (offline)")
    ap.add_argument("--write", action="store_true", help="keep the report as rechecks/<year>-Q<n>.md")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    root, today = Path(a.root), dt.date.fromisoformat(a.today)
    facts = facts_changed(root)
    rows = recheck(root, today, facts, net=not a.no_net)
    text = report(rows, today, facts)
    if a.write:
        out = root / "rechecks" / f"{today.year}-Q{(today.month - 1) // 3 + 1}.md"
        out.parent.mkdir(exist_ok=True)
        old = out.read_text(encoding="utf-8") if out.exists() else ""
        kept = old[old.index(MANUAL):] if MANUAL in old else ""     # the reading by hand is never overwritten
        out.write_text(text + "\n" + (kept if kept.endswith("\n") or not kept else kept + "\n"), encoding="utf-8")
        print(f"recheck: {out.relative_to(root)}" + (" (the reading by hand kept)" if kept else ""))
    elif not a.strict:
        print(text)
    bad = any(r["broken"] or r["due"] for r in rows)
    return 1 if (a.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
