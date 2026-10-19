"""sites.checks.visits — who came, when, to which page, and how they got there.

Read from the site's OWN access log, never from a script in the page:

  * a log line is written by the server for every request, including the ones that run no
    JavaScript — a JS beacon counts only browsers that execute it, which undercounts the people who
    matter least and overcounts the crawlers that do;
  * a third-party analytics script is a dependency, a cookie banner and a privacy question the
    office would then have to answer. This is one file on a machine the owner already owns;
  * the SAME mechanism works for a site the office renders (its own JSON log under `<root>/logs`)
    and for a site it adopted (the container's stdout), so day one of adoption already has numbers.

The aggregation is hourly and happens at ingest: a busy site writes millions of lines, and the
question being asked ("how many visits this week, to what") is answered completely by hourly counts
plus the top paths and referrers. Individual lines are never stored.

Bots are counted SEPARATELY and never folded into the human number. A site whose traffic is 80%
crawlers looks healthy on a merged chart and is, in fact, a site nobody visits — and that is the one
number the owner can act on.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

BOT_UA = re.compile(
    r"(bot|crawl|spider|slurp|baidu|yandex|semrush|ahrefs|mj12|dotbot|petal|python-requests|"
    r"curl/|wget/|headlesschrome|facebookexternalhit|whatsapp|telegrambot|uptimerobot|"
    r"monitoring|pingdom|lighthouse|google-inspectiontool|gptbot|claudebot|ccbot|bytespider)",
    re.I)

#: The office's own log format, written by the nginx conf the pattern renders (runtime.render_nginx).
_JSON_KEYS = ("t", "ip", "m", "u", "s", "b", "r", "a", "h", "rt")
_COMBINED = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<t>[^\]]+)\] "(?P<m>\S+)(?: (?P<u>[^"]*?))?(?: [^"]*)?" '
    r'(?P<s>\d{3}) (?P<b>\d+|-)(?: "(?P<r>[^"]*)" "(?P<a>[^"]*)")?')


def parse_line(line: str) -> dict | None:
    """One log line → one hit, or None. Both formats, because both exist in the fleet: the JSON the
    pattern writes, and the combined format every nginx that predates the pattern writes."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            d = json.loads(line)
        except ValueError:
            return None
        if not isinstance(d, dict) or "u" not in d:
            return None
        return {"ts": _ts(d.get("t")), "ip": d.get("ip") or "", "u": d.get("u") or "/",
                "s": _int(d.get("s")), "b": _int(d.get("b")), "r": d.get("r") or "",
                "a": d.get("a") or "", "h": d.get("h") or ""}
    # docker logs prefixes a timestamp when --timestamps is used; drop it before matching
    m = _COMBINED.match(line.split(" ", 1)[1] if re.match(r"^\d{4}-\d\d-\d\dT", line) else line)
    if not m:
        return None
    u = m.group("u") or "/"
    return {"ts": _ts(m.group("t")), "ip": m.group("ip"), "u": u, "s": _int(m.group("s")),
            "b": _int(m.group("b")) if m.group("b") not in (None, "-") else 0,
            "r": m.group("r") or "", "a": m.group("a") or "", "h": ""}


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _ts(raw) -> int:
    """nginx's own time (iso8601 with an offset in the JSON format, `%d/%b/%Y:%H:%M:%S %z` in the
    combined one) → epoch seconds. It is the SERVER's clock, not the office's, and that is the right
    answer: a site on a VPS in another timezone must not have its visits shifted by our own."""
    if not raw:
        return 0
    text = str(raw).strip()
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        pass
    try:
        return int(datetime.strptime(text, "%d/%b/%Y:%H:%M:%S %z").timestamp())
    except ValueError:
        return 0


def classify(hit: dict) -> tuple[bool, str]:
    """(is_bot, path) — the path with its query stripped and its slug normalised, so `/about?x=1`
    and `/about/` are one page in the report and not three."""
    path = (hit.get("u") or "/").split("?")[0].split("#")[0]
    if len(path) > 120:
        path = path[:120]
    # a numeric-looking segment (an id, a date, a hash) is a distinct page for a human and 4,000
    # distinct rows for the report — collapse them.
    path = re.sub(r"/\d{3,}", "/<n>", path)
    path = re.sub(r"/[0-9a-f]{16,}", "/<hash>", path)
    return bool(BOT_UA.search(hit.get("a") or "")), path


def aggregate(lines: list[str], host: str = "") -> dict:
    """Lines → hourly buckets. Pure, so it is testable without a machine and without a database."""
    hours: dict[int, dict] = {}
    for raw in lines:
        hit = parse_line(raw)
        if not hit:
            continue
        ts = hit["ts"]
        if not ts:
            continue
        hour = ts - (ts % 3600)
        bot, path = classify(hit)
        h = hours.setdefault(hour, {"hits": 0, "bots": 0, "errors": 0, "bytes": 0,
                                    "ips": set(), "paths": {}, "refs": {}})
        h["hits"] += 1
        h["bytes"] += hit.get("b") or 0
        if bot:
            h["bots"] += 1
        else:
            h["ips"].add(hit.get("ip") or "")
        if (hit.get("s") or 0) >= 400:
            h["errors"] += 1
        if not bot:
            h["paths"][path] = h["paths"].get(path, 0) + 1
            ref = (hit.get("r") or "").strip()
            if ref and not ref.startswith("-"):
                try:
                    refhost = urlparse(ref).netloc
                except ValueError:
                    refhost = ""
                if refhost and host and host not in refhost:
                    h["refs"][refhost[:80]] = h["refs"].get(refhost[:80], 0) + 1
                elif refhost and not host:
                    h["refs"][refhost[:80]] = h["refs"].get(refhost[:80], 0) + 1
    out = {}
    for hour, h in hours.items():
        out[hour] = {"hits": h["hits"], "bots": h["bots"], "errors": h["errors"],
                     "bytes": h["bytes"], "uniques": len([i for i in h["ips"] if i]),
                     "paths": h["paths"], "refs": h["refs"]}
    return {"hours": out, "lines": len(lines),
            "hits": sum(h["hits"] for h in out.values()),
            "bots": sum(h["bots"] for h in out.values()),
            "uniques": sum(h["uniques"] for h in out.values())}
