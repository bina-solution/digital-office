#!/usr/bin/env python3
"""topics.py — the topics log (topics.yaml, DGO-818): what is still to become a work item, and the log's rules.

    python3 apps/digital-assets/content/topics.py            # the open entries: words still waiting for an item
    python3 apps/digital-assets/content/topics.py --check    # exit 1, naming each entry that breaks a rule
    python3 apps/digital-assets/content/topics.py --json     # every entry, and the counts, as JSON

The rules (topics.yaml's header says why): ids tNNN, unique; a real date; a known source; the words are there;
`state: item` names its item (DGO-NNN), `state: open` names none yet, `state: declined` says why.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:                                      # the Mac host has none; the engine guest does
    sys.exit("topics.py needs PyYAML: pip install pyyaml")

LOG = Path(__file__).resolve().with_name("topics.yaml")
SOURCES = ("owner", "user", "search", "field")
STATES = ("open", "item", "declined")
ID = re.compile(r"^t\d{3,}$", re.ASCII)                 # «t٠٠١» (Arabic-Indic digits) is not an id
REF = re.compile(r"^[A-Z][A-Z0-9]*-\d+$", re.ASCII)


def load(path: Path = LOG) -> list[dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    topics = doc.get("topics") if isinstance(doc, dict) else None
    if not isinstance(topics, list):
        raise ValueError(f"{path.name}: no `topics:` list")
    return topics


def problems(topics: list, today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    out, seen = [], set()
    for n, t in enumerate(topics, 1):
        if not isinstance(t, dict):
            out.append(f"entry {n}: not a mapping")
            continue
        tid = str(t.get("id") or f"entry {n}")
        if not ID.fullmatch(str(t.get("id") or "")):
            out.append(f"{tid}: id is tNNN")
        elif int(tid[1:]) in seen:                         # t001 and t0001 are one id
            out.append(f"{tid}: id used twice (an id is never reused)")
        else:
            seen.add(int(tid[1:]))
        when = t.get("date")
        if isinstance(when, dt.datetime) or not isinstance(when, dt.date):
            out.append(f"{tid}: date is a day, written YYYY-MM-DD without quotes")
        elif when > today:
            out.append(f"{tid}: date {when} is in the future")
        if t.get("source") not in SOURCES:
            out.append(f"{tid}: source is one of {', '.join(SOURCES)}")
        if not isinstance(t.get("words"), str) or not t["words"].strip():
            out.append(f"{tid}: the words are kept, verbatim, as one text")
        state, item = t.get("state"), t.get("item")
        if state not in STATES:
            out.append(f"{tid}: state is one of {', '.join(STATES)}")
        elif state == "item" and not REF.fullmatch(str(item or "")):
            out.append(f"{tid}: state item names its item (DGO-NNN)")
        elif state == "open" and item:
            out.append(f"{tid}: an open entry has no item yet — it is `state: item`")
        elif state == "declined":
            if item:
                out.append(f"{tid}: a declined entry has no item — the item was the subject taken")
            if not str(t.get("why") or "").strip():
                out.append(f"{tid}: a declined entry says why")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--file", default=str(LOG))
    a = ap.parse_args(argv)
    try:
        topics = load(Path(a.file))
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"topics: {e}", file=sys.stderr)
        return 1
    bad = problems(topics)
    counts = {s: sum(1 for t in topics if isinstance(t, dict) and t.get("state") == s) for s in STATES}
    if a.json:
        print(json.dumps({"counts": counts, "problems": bad, "topics": topics}, ensure_ascii=False, default=str))
        return 1 if (a.check and bad) else 0
    if a.check:
        for p in bad:
            print(f"  - {p}")
        print(f"topics: {len(topics)} entries — {counts['item']} items, {counts['open']} open, "
              f"{counts['declined']} declined; {len(bad)} problem(s)")
        return 1 if bad else 0
    open_ = [t for t in topics if isinstance(t, dict) and t.get("state") == "open"]
    for t in open_:
        print(f"{t.get('id')}  {t.get('date')}  {t.get('source')}  ({t.get('where') or '—'})  «{t.get('words')}»")
    print(f"topics: {len(open_)} open of {len(topics)} — each becomes an item: "
          "./bbox project-pln tasks new DGO \"<name>\" --comment \"<the words>\"")
    if bad:
        print(f"topics: {len(bad)} problem(s) in the log — run with --check", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
