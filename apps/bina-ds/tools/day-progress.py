#!/usr/bin/env python3
"""day-progress.py — the day's bar: how much of the work is closed, and what the day has cost.

THE OWNER, 2026-10-14: «אני מצפה בעצם לכל סיכום יום להכיל גם פרוגרס באר progress bar מ1 ל 100% כמה
אחוז מהמשימות בוצעו ואמור לעלות כל הזמן». So every day summary carries ONE line, always the same
shape:

    יום 2026-10-14 · ▓▓▓▓░░░░░░ 43% · נסגרו היום 28 · בתהליך 37 · מחזורים 2/3 · עלות: …

WHAT THE PERCENT IS — a measurement, never a guess: the office's own Plane, asked live —
`bbox project-pln tasks list --json` → items closed TODAY over (closed today + still in progress).
The two raw counts are printed beside the bar, so the number can be checked by hand.

THE CYCLES: today's seder sessions (`data/bina-ds/sedarim/<day>/sessions.json`); a cycle counts as
finished when its own page carries a balance — the תיעוד step wrote one, and its placeholder is gone.

THE COST: the seder ledger (`skills/seder/ledger.mjs --line`) echoed verbatim, so this line and the
day page can never disagree about the money.

NOTHING IS CACHED. Every run asks Plane and the day's folder again; a bar that lags is worse than no
bar. `--json` prints the numbers alone, for a caller that wants to compute with them.

Usage:  python3 apps/bina-ds/tools/day-progress.py [--day YYYY-MM-DD] [--width 10] [--json]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DAY_DIR = REPO / "data/bina-ds/sedarim"
TZ = "Asia/Jerusalem"


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        p = subprocess.run(cmd, cwd=str(cwd or REPO), capture_output=True, text=True, timeout=180)
        return p.stdout or ""
    except Exception:
        return ""


def plane_counts(day: str) -> tuple[int, int]:
    """(closed today, in progress now) — straight from Plane through the office's own CLI."""
    raw = _run([str(REPO / "bbox"), "project-pln", "tasks", "list", "--json"])
    i = raw.find("{")
    if i < 0:
        return (-1, -1)
    try:
        tasks = json.loads(raw[i:]).get("tasks", [])
    except ValueError:
        return (-1, -1)
    closed = sum(1 for t in tasks if t.get("group") == "completed"
                 and str(t.get("updated_at") or "").startswith(day))
    started = sum(1 for t in tasks if t.get("group") == "started")
    return (closed, started)


def cycles(day: str) -> tuple[int, int]:
    """(finished, 3) — a full day cycle is שחרית · מנחה · ערבית, each judged by its LATEST session of
    the day: finished means that session's page carries a balance (the תיעוד step wrote one)."""
    folder = DAY_DIR / day
    try:
        rows = json.loads((folder / "sessions.json").read_text(encoding="utf-8"))
    except Exception:
        rows = []
    latest: dict[str, dict] = {}
    for r in rows:
        name = str(r.get("cycle") or "")
        if name and (name not in latest or str(r.get("at", "")) > str(latest[name].get("at", ""))):
            latest[name] = r
    done = 0
    for name in ("shacharit", "mincha", "arvit"):
        r = latest.get(name)
        if not r:
            continue
        page = folder / f"{str(r.get('at', '')).replace(':', '-')}-{name}.md"
        try:
            text = page.read_text(encoding="utf-8")
        except OSError:
            continue
        body = text.split("## מאזן הסדר", 1)[-1] if "## מאזן הסדר" in text else ""
        if body.strip() and "(נכתב בשלב תיעוד)" not in body:
            done += 1
    return (done, 3)


def ledger_line() -> str:
    home = os.environ.get("DSH_HOME", "/data/dsh")
    for p in (Path(home) / "profiles/bina/agent-presets/azaria/skills/seder/ledger.mjs",
              REPO / "apps/bina-ds/harness/profile/agent-presets/azaria/skills/seder/ledger.mjs"):
        if p.exists():
            out = _run(["node", str(p), "--line"])
            m = re.search(r"תקציב:.*", out)
            if m:
                return m.group(0).strip()
    return "עלות: לא נקראה (ledger.mjs לא נמצא)"


def bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "▓" * filled + "░" * (width - filled)


def main() -> int:
    args = sys.argv[1:]
    day = date.today().strftime("%Y-%m-%d")
    width = 10
    as_json = "--json" in args
    for i, a in enumerate(args):
        if a == "--day" and i + 1 < len(args):
            day = args[i + 1]
        if a == "--width" and i + 1 < len(args):
            width = int(args[i + 1])

    closed, started = plane_counts(day)
    done, opened = cycles(day)
    denom = closed + started if closed >= 0 else 0
    pct = (closed / denom * 100) if denom else 0.0
    cost = ledger_line()

    if as_json:
        print(json.dumps({"day": day, "percent": round(pct, 1), "closed_today": closed,
                          "in_progress": started, "cycles_done": done, "cycles_opened": opened,
                          "cost": cost}, ensure_ascii=False))
        return 0

    print(f"יום {day} · {bar(pct, width)} {pct:.0f}% · נסגרו היום {closed} · בתהליך {started}"
          f" · מחזורים {done}/{opened} · {cost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
