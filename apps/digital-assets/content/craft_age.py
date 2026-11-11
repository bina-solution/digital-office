#!/usr/bin/env python3
"""craft_age.py — which rules of CRAFT.md are due for a re-check, and which stand on a weak source.

    python3 apps/digital-assets/content/craft_age.py [--today 2026-11-05] [--months 6] [--strict]

Reads every table row of CRAFT.md that has a rule id (V1, Y3, W6, A4, H2 …) and prints:
  DUE        the `checked` date is older than --months (default 6)
  WEAK       the row marks itself (secondary) or (unverified)
Exit 0, or 1 with --strict when anything is DUE — the content skills run it before they cite a rule
(DGO-1395: a platform rule followed without its source is a rumour; one never re-checked is last year's).
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROW = re.compile(r"^\|\s*([VYWAH]\d+)\s*\|(.+)\|\s*$")
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
CRAFT = Path(__file__).with_name("CRAFT.md")


def rules(path: Path = CRAFT) -> list:
    """[(rule id, rule text, the `checked` cell)] — every table row of CRAFT.md that has a rule id."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            cells = [c.strip() for c in m.group(2).split("|")]
            out.append((m.group(1), cells[0] if cells else "", cells[-1] if cells else ""))
    return out


def is_due(checked: str, today: dt.date, months: int = 6) -> bool:
    """A rule is due when its `checked` cell holds no date, or one older than `months`."""
    d = DATE.search(checked)
    return not d or dt.date.fromisoformat(d.group(1)) < today - dt.timedelta(days=round(months * 30.44))


def due_ids(today: dt.date, months: int = 6, path: Path = CRAFT) -> set:
    """The ids of the rules due for a re-check — what a content skill's check reads before it cites one."""
    return {rid for rid, _rule, checked in rules(path) if is_due(checked, today, months)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(CRAFT))
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today)
    due = weak = total = 0
    for rid, rule, checked in rules(Path(a.file)):
        total += 1
        if is_due(checked, today, a.months):
            due += 1
            print(f"DUE   {rid:<4} checked {checked or '—'} · {rule[:80]}")
        if re.search(r"\((secondary|unverified)\)", checked):
            weak += 1
            print(f"WEAK  {rid:<4} {checked} · {rule[:80]}")
    print(f"{total} rules · {due} due for a re-check (older than {a.months} months) · {weak} on a weak source")
    return 1 if (a.strict and due) else 0


if __name__ == "__main__":
    sys.exit(main())
