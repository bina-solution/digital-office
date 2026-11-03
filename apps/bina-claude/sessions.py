"""Every Claude session this office keeps, as data: `./bbox bina-claude sessions|show` (DGO-1074).

Runs INSIDE the bina-claude container (hooks/sessions pipes it in), where the app's volume is /data:
  /data/home      the CLI's home (the terminal, the agent.v1 adapter)
  /data/desktop   the Claude Desktop app's home
Claude Code — the CLI and the desktop app's Code tab alike — writes one JSONL file per session under
<home>/.claude/projects/<encoded cwd>/<session id>.jsonl. Those files ARE the sessions; this reads them,
it keeps no index of its own that could drift.

  sessions [--json] [--home cli|desktop] [-n N]   newest first: id, home, project, title, turns, updated
  show <id-or-prefix> [--json] [-n N]             the conversation: who said what, tool calls in one line
"""
import argparse
import glob
import json
import os
import sys

HOMES = {"cli": "/data/home", "desktop": "/data/desktop"}


def records(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for c in content or []:
        if isinstance(c, dict):
            if c.get("type") == "text":
                out.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                out.append(f"⏺ {c.get('name')}({json.dumps(c.get('input'), ensure_ascii=False)[:120]})")
            elif c.get("type") == "tool_result":
                body = c.get("content")
                first = text_of(body) if isinstance(body, list) else str(body or "")
                out.append(f"  ⎿ {first.strip().splitlines()[0][:120] if first.strip() else '(no output)'}")
    return "\n".join(o for o in out if o)


def summarize(path, home):
    sid = os.path.basename(path)[:-len(".jsonl")]
    title = summary = cwd = first = last = None
    turns = 0
    for r in records(path):
        t = r.get("type")
        ts = r.get("timestamp")
        if ts:
            first = first or ts
            last = ts
        cwd = cwd or r.get("cwd")
        if t == "summary" and r.get("summary"):
            summary = r["summary"]
        if t in ("custom-title", "ai-title") and (r.get("customTitle") or r.get("aiTitle")):
            title = r.get("customTitle") or r.get("aiTitle")
        if t == "user" and not r.get("isMeta"):
            content = (r.get("message") or {}).get("content")
            if isinstance(content, str) or any(isinstance(c, dict) and c.get("type") == "text" for c in content or []):
                turns += 1
                if not title and not summary:
                    words = " ".join(text_of(content).split())
                    if words and not words.startswith("<"):
                        title = words[:80]
    return {"id": sid, "home": home, "project": cwd or os.path.basename(os.path.dirname(path)),
            "title": title or summary or "(untitled)", "turns": turns, "started": first, "updated": last,
            "file": path, "bytes": os.path.getsize(path)}


def all_sessions(only=None):
    out = []
    for home, root in HOMES.items():
        if only and home != only:
            continue
        for path in glob.glob(os.path.join(root, ".claude", "projects", "*", "*.jsonl")):
            try:
                out.append(summarize(path, home))
            except OSError:
                continue
    out.sort(key=lambda s: s["updated"] or "", reverse=True)
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog="bbox bina-claude")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sessions"); p.add_argument("--json", action="store_true")
    p.add_argument("--home", choices=sorted(HOMES)); p.add_argument("-n", type=int, default=50)
    p = sub.add_parser("show"); p.add_argument("id"); p.add_argument("--json", action="store_true")
    p.add_argument("-n", type=int, default=40)
    a = ap.parse_args(argv)

    if a.cmd == "sessions":
        rows = all_sessions(a.home)
        if a.json:
            print(json.dumps({"sessions": rows[:a.n], "total": len(rows)}, ensure_ascii=False))
            return 0
        if not rows:
            print("no sessions on this office yet")
            return 0
        for s in rows[:a.n]:
            print(f"{s['id'][:8]}  {s['home']:<7} {(s['updated'] or '')[:16]:<16}  {s['turns']:>3} turns  "
                  f"{s['project'][-28:]:<28}  {s['title'][:70]}")
        if len(rows) > a.n:
            print(f"… {len(rows) - a.n} more (-n {len(rows)})")
        return 0

    hits = [s for s in all_sessions() if s["id"].startswith(a.id)]
    if not hits:
        print(f"no session {a.id}", file=sys.stderr); return 4
    if len(hits) > 1:
        print(f"{len(hits)} sessions start with {a.id}", file=sys.stderr); return 6
    s = hits[0]
    msgs = []
    for r in records(s["file"]):
        if r.get("type") in ("user", "assistant") and not r.get("isMeta"):
            body = text_of((r.get("message") or {}).get("content"))
            if body.strip():
                msgs.append({"role": r["type"], "at": r.get("timestamp"), "text": body})
    if a.json:
        print(json.dumps({**s, "messages": msgs[-a.n:]}, ensure_ascii=False)); return 0
    print(f"{s['id']}  ({s['home']}, {s['project']})  {s['title']}")
    for m in msgs[-a.n:]:
        who = "you" if m["role"] == "user" else "claude"
        print(f"\n› {who} {(m['at'] or '')[:16]}\n{m['text'][:2000]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
