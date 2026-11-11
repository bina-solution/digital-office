#!/usr/bin/env python3
"""from_newsflow.py — newsflow's approved stories into the site's news desk (DGO-1383).

    ./bbox remote hp-laptop newsflow "/api/site?limit=1000" | python3 apps/digital-assets/content/newsdesk/from_newsflow.py

newsflow 0.2.0 (on the HP) keeps the review step: a story leaves the office only after a reviewer approved it with a
summary in our own words. `GET /api/site` is that feed and nothing else is. This writes it to newsdesk/newsflow.json,
which export_site.py reads beside approved.json (one story, one URL: approved.json wins). A feed that is empty, an
error page or not JSON changes nothing — the file is replaced only by a feed that parsed and holds stories.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "newsflow.json"


def main() -> int:
    raw = sys.stdin.read()
    start = raw.find("{")                     # `bbox remote` prints an «HTTP 200 GET …» line before the body
    if start < 0:
        print("from_newsflow: no JSON in the answer — newsflow.json left as it was", file=sys.stderr)
        return 1
    try:
        feed = json.loads(raw[start:])
    except ValueError as e:
        print(f"from_newsflow: the answer is not JSON ({e}) — newsflow.json left as it was", file=sys.stderr)
        return 1
    items = [i for i in feed.get("items") or [] if i.get("url") and i.get("title") and i.get("summary_he")]
    if not items:
        print("from_newsflow: no approved stories in the feed — newsflow.json left as it was", file=sys.stderr)
        return 1
    for i in items:
        i["status"] = "approved"
    OUT.write_text(json.dumps({"about": "newsflow GET /api/site — the stories its review step approved (DGO-1383)",
                               "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"from_newsflow: {len(items)} approved stories → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
