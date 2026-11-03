#!/usr/bin/env python3
"""build-session-timeline — one self-contained page: what an agent session actually did, round by round.

WHY A BUILDER. The timeline is a MEASUREMENT of a session, so it is read out of the session's own
durable log (`/data/dsh/sessions/<cwd>/<id>/session.v3.jsonl.zstd` — zstd frames appended one per
write, decompressed here with node's zlib, the only zstd in this image), and its money column is
computed by the office's own code: `apps/bina-ds/plugins/cost-meter/lib/pricing.js` and `lib/cost.js`
are inlined into the artifact and loaded by the page as Blob modules, so every figure is produced by
the arithmetic that will produce it in the product — never typed into the page.

WHAT ONE ROUND CARRIES. Its goal (the objective that was active at that moment), its own usage, the
model's own first thought and its closing conclusion, every tool it ran (condensed), the files it
wrote or edited, the gates it ran and their verdicts, the screenshots and deliverables it presented,
and the work-item refs its conclusion closed.

    python3 digital-office/sim/build-session-timeline.py                    # the biggest session
    python3 digital-office/sim/build-session-timeline.py --session 3b0e4897 --hours 24
    python3 digital-office/sim/build-session-timeline.py --json-only        # data, no page

Output (build artifact, gitignored): ci-artifacts/session-timeline/session-timeline.html
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = HERE / "session-timeline.src.html"
PLUGIN = REPO / "apps" / "bina-ds" / "plugins" / "cost-meter"
TOKENS = REPO / "platform-base" / "bina-ui" / "theme-tokens.css"
SESSIONS = pathlib.Path("/data/dsh/sessions")
DEFAULT_OUT = REPO / "ci-artifacts" / "session-timeline"
TZ = dt.timezone(dt.timedelta(hours=3))  # the owner's clock (Asia/Jerusalem)

#: node is the only zstd in this image; the session log is a run of appended zstd frames.
NODE_UNZSTD = r"""
const zlib=require('zlib'),fs=require('fs');
const file=process.argv[2]||process.argv[1];
const buf=fs.readFileSync(file);const M=[0x28,0xb5,0x2f,0xfd];const st=[];
for(let i=0;i<=buf.length-4;i++) if(buf[i]===M[0]&&buf[i+1]===M[1]&&buf[i+2]===M[2]&&buf[i+3]===M[3]){const f=buf[i+4];if((f&0x08)===0)st.push(i);}
const out=[];for(let k=0;k<st.length;k++){const a=st[k],b=(k+1<st.length)?st[k+1]:buf.length;try{out.push(zlib.zstdDecompressSync(buf.subarray(a,b)));}catch(e){}}
process.stdout.write(Buffer.concat(out));
"""

REF = re.compile(r"\b(?:ui2|agt|lnk|web|qa|eng|n8n|app|idx|own|pln|sec|doc|core|rap|flt|cap|req|ui)-?\d{2,3}\b")
GATE = re.compile(r"\b(G\d{1,2})\b[^\n]{0,40}?\b(PASS|FAIL)\b")


def sessions() -> list[pathlib.Path]:
    return sorted(SESSIONS.glob("*/session-*/session.v3.jsonl.zstd"))


def decompress(path: pathlib.Path) -> str:
    done = subprocess.run(["node", "-e", NODE_UNZSTD, str(path)], capture_output=True, check=True)
    return done.stdout.decode("utf8", "replace")


def biggest(paths: list[pathlib.Path]) -> pathlib.Path:
    """The session that cost the most is the one with the most recorded output in its log."""
    return max(paths, key=lambda p: p.stat().st_size)


def clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def condense(command: str) -> str:
    """One bash call as a reader can hold it — what KIND of thing ran, not the whole line."""
    c = re.sub(r"\s+", " ", (command or "").strip())
    c = re.sub(r"^cd \S+ ?&& ?", "", c)
    gate = re.search(r"scripts/refactor/([a-z0-9-]+)\.py", c)
    if gate:
        return "שער · " + gate.group(1)
    if "flow-qa.py" in c:
        return "סים · flow-qa"
    if "ui-map" in c or "live-ui-map" in c:
        return "מפה · ui-map"
    if "build.mjs" in c:
        return "סים · build"
    if "docker run" in c or "docker exec" in c:
        image = re.search(r"--entrypoint \S+ (\S+)", c) or re.search(r"docker (?:run|exec)[^|]{0,60}? (\S+)", c)
        return "docker · " + (image.group(1) if image else "?")
    if c.startswith("curl") or " curl " in c:
        host = re.search(r"https?://([^/\s\"']+)", c)
        return "קריאה · " + (host.group(1) if host else "http")
    if c.startswith("git ") or " git " in c:
        return "git · " + " ".join(c.split()[1:3])
    if "pulse" in c:
        return "דופק · " + clip(c, 40)
    if "pytest" in c or "--self-test" in c:
        return "בדיקה · self-test"
    return clip(c, 74)


def build_rounds(records: list[dict], since: dt.datetime) -> dict:
    """Fold the durable log into one entry per round, in the owner's clock, inside the window."""
    rounds: list[dict] = []
    meta = {"id": "", "title": "", "created": None}
    goal = ""
    goal_ops: list[dict] = []
    cur: dict | None = None
    total_steps = 0

    def st(ms: int) -> dt.datetime:
        return dt.datetime.fromtimestamp(ms / 1000, TZ)

    for rec in records:
        kind = rec.get("type")
        when = rec.get("time")
        data = rec.get("data") or {}
        if kind == "session":
            meta["id"] = rec.get("id", "")
            meta["created"] = rec.get("createdAt")
            continue
        if kind == "session/title" and not meta["title"]:
            meta["title"] = clip(str(data.get("title") or ""), 120)
            continue
        if when is None or st(when) < since:
            if kind == "turn/end":
                cur = None
            continue
        if kind == "goal/change":
            g = data.get("goal") or {}
            op = data.get("operation") or ""
            objective = clip(g.get("objective") or "", 200)
            if op in ("create", "edit") and objective:
                goal = objective
            goal_ops.append({"t": when, "op": op, "phase": g.get("phase") or "", "objective": objective,
                             "rounds": g.get("maxGoalRounds")})
            if cur is not None:
                cur["events"].append({"kind": "goal", "op": op, "text": clip(objective, 90)})
            continue
        if kind == "turn/start":
            cur = {"n": data.get("turn"), "t0": when, "t1": when, "goal": goal, "source": "", "usage":
                   {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheWriteTokens": 0},
                   "steps": 0, "thought": "", "conclusion": "", "tools": {}, "cmds": [], "changes": [],
                   "gates": [], "images": [], "delivered": [], "refs": [], "closed": [], "events": [],
                   "errors": 0}
            rounds.append(cur)
            continue
        if cur is None:
            continue
        cur["t1"] = when
        if kind == "user/message":
            src = (data.get("source") or {}).get("kind")
            cur["source"] = src or ""
            text = " ".join(x.get("text", "") for x in (data.get("content") or []) if isinstance(x, dict))
            if src != "goal":
                cur["events"].append({"kind": "owner", "text": clip(text, 160)})
            continue
        if kind == "step/start":
            cur["steps"] += 1
            total_steps += 1
            continue
        if kind == "assistant/message":
            usage = data.get("usage") or {}
            for key in cur["usage"]:
                cur["usage"][key] += usage.get(key) or 0
            for block in (data.get("message") or {}).get("content") or []:
                if block.get("type") == "reasoning" and not cur["thought"]:
                    cur["thought"] = clip(block.get("text") or "", 320)
                if block.get("type") == "text" and (block.get("text") or "").strip():
                    cur["conclusion"] = clip(block.get("text"), 1400)
            continue
        if kind == "tool/call":
            name = data.get("name") or "?"
            cur["tools"][name] = cur["tools"].get(name, 0) + 1
            try:
                args = json.loads(data.get("arguments") or "{}")
            except Exception:
                args = {}
            if name == "bash":
                cur["cmds"].append(condense(args.get("command", "")))
            elif name in ("write", "edit"):
                path = str(args.get("file_path") or "")
                if path and path not in cur["changes"]:
                    cur["changes"].append(path.replace(str(REPO) + "/", ""))
            elif name == "read_image":
                cur["images"].append(str(args.get("file_path") or ""))
            elif name == "present":
                for item in args.get("files") or []:
                    cur["delivered"].append(str(item.get("path") or ""))
            elif name == "todo_write":
                cur["events"].append({"kind": "todo", "text": clip(", ".join(
                    ("✔ " if t.get("status") == "completed" else "") + str(t.get("content", ""))
                    for t in (args.get("todos") or [])[:6]), 220)})
            continue
        if kind == "tool/result":
            blob = json.dumps(data, ensure_ascii=False)
            for gate, verdict in GATE.findall(blob):
                entry = f"{gate} {verdict}"
                if entry not in cur["gates"]:
                    cur["gates"].append(entry)
            if "regression(s)" in blob:
                line = re.search(r"\d+ gate\(s\) run[^\"\\]{0,60}", blob)
                if line:
                    cur["events"].append({"kind": "gates", "text": line.group(0)})
            if '"code":' in blob and re.search(r'"code":\s*[1-9]', blob):
                cur["errors"] += 1
            continue
        if kind == "deliverables/presented":
            for item in data.get("files") or []:
                cur["delivered"].append(str(item.get("path") or ""))
            continue
        if kind in ("compaction/start", "compaction/end"):
            cur["events"].append({"kind": "compaction", "text": kind.split("/")[1]})
            continue

    for rnd in rounds:
        conclusion = rnd["conclusion"]
        refs = []
        for ref in REF.findall(conclusion):
            if ref not in refs:
                refs.append(ref)
        rnd["refs"] = refs
        for ref in refs:
            if re.search(re.escape(ref) + r"[^.]{0,24}?נסגר", conclusion):
                rnd["closed"].append(ref)
        rnd["cmds"] = list(dict.fromkeys(rnd["cmds"]))[:8]
        rnd["changes"] = rnd["changes"][:14]
        rnd["images"] = list(dict.fromkeys(rnd["images"]))[:6]
        rnd["delivered"] = list(dict.fromkeys(rnd["delivered"]))[:8]
        rnd["gates"] = rnd["gates"][:8]
    return {"meta": meta, "rounds": rounds, "steps": total_steps, "goalOps": goal_ops}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="", help="session id (or a unique prefix), or a path to the log")
    parser.add_argument("--hours", type=float, default=24.0, help="how far back the window reaches")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    found = sessions()
    if not found:
        sys.exit(f"no session logs under {SESSIONS}")
    if args.session and pathlib.Path(args.session).exists():
        log = pathlib.Path(args.session)
    elif args.session:
        matches = [p for p in found if args.session in p.parent.name]
        if len(matches) != 1:
            sys.exit(f"--session {args.session} matched {len(matches)} logs")
        log = matches[0]
    else:
        log = biggest(found)

    now = dt.datetime.now(TZ)
    since = now - dt.timedelta(hours=args.hours)
    text = decompress(log)
    records = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    data = build_rounds(records, since)
    data["meta"]["log"] = str(log)
    data["meta"]["window"] = {"from": since.isoformat(timespec="seconds"), "to": now.isoformat(timespec="seconds")}
    data["meta"]["title"] = data["meta"]["title"] or log.parent.name

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "session-timeline.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
    if args.json_only:
        print(args.out / "session-timeline.json", len(data["rounds"]), "rounds")
        return

    html = SRC.read_text(encoding="utf8")
    html = html.replace("__PRICING_SRC__", (PLUGIN / "lib" / "pricing.js").read_text(encoding="utf8"))
    html = html.replace("__COST_SRC__", (PLUGIN / "lib" / "cost.js").read_text(encoding="utf8"))
    html = html.replace("__TIMELINE_JSON__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    html = html.replace(
        '<link rel="stylesheet" href="../../platform-base/bina-ui/theme-tokens.css" />',
        "<style>\n" + TOKENS.read_text(encoding="utf8") + "\n</style>",
    )
    target = args.out / "session-timeline.html"
    target.write_text(html, encoding="utf8")
    print(f"{target}  ({target.stat().st_size // 1024} KiB · {len(data['rounds'])} rounds · {data['steps']} steps)")


if __name__ == "__main__":
    main()
