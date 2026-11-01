"""bbox agent — the office agent from the terminal, over agent.v1 (ai/context/agent-contract.md).

Everything the office UI can do with a session is a verb here, with the same words:

  bbox agent list                                 the sessions (running / idle, title, goal)
  bbox agent new  [-t title] [-p preset] [-f file]… [-F] <text|->   a session, first message sent
  bbox agent send [--steer] [-f file]… [-F] <id> <text|->            queue a message (or steer into the running turn)
  bbox agent follow <id> [--history N] [--thinking] [-v]             live: tool calls, results, text as they happen
  bbox agent watch                                every session live, one screen
  bbox agent show <id> · log <id> [-n N] · wait <id> [--timeout S]
  bbox agent cancel <id> · rename <id> <title> · fork <id> [--at-seq N]
  bbox agent cmd <id> "/command …" · commands <id>          the harness's slash commands
  bbox agent goal <id> [get|set <objective> [--rounds N]|pause|resume|clear|complete]
  bbox agent model <id> [--set provider/model[@effort]] · models · presets · preset <id> <name>
  bbox agent upload <id> <file> · subagents <id> · search <query>
  bbox agent login [--force] · whoami · doctor    the connection, and a hop-by-hop trace with timings

A LINKED office's agent, over the link (DGO-32) — the offices are the owner's, and the agent of one
drives the other exactly as the local one does:
  bbox agent --office macbook list                the MacBook's sessions, reached through the tunnel
  bbox agent --office macbook send <id> "…"       …every verb below, with the same semantics
  The office must appear in this office's `remote:`/`serve:` block (`platform.state.yaml`, written by
  dgo-extend on converge) and the credential comes from the vault; `--url`/`--token` still win.

The agent's work items live in the office's project tool (Plane, apps/project-pln) and are his:
  bbox agent tasks [list|show|start|done|comment|take] …   his tasks — `bbox project-pln tasks --as <agent>`, one implementation
  bbox agent do <DGO-12> [more words] [-s <id>] [-F]      hand him a work item: "complete task @project-pln/DGO-12" (a new session, or -s into one)
The agent's name may come first (`bbox agent azaria tasks list`); it selects whose tasks — default: the office agent.

<id> may be a unique prefix (a10c). "-" reads the text from stdin so a long brief keeps its lines:
  bbox agent new -t "vps1" -F - < brief.md
--json on any read verb prints the contract's JSON; piped output is plain lines; Ctrl-C detaches
(the session keeps running) unless --cancel-on-interrupt.

Exit codes: 0 ok · 1 error · 2 usage · 3 unreachable/timeout · 4 not found · 5 auth · 6 ambiguous · 130 interrupted
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .client import CONFIG_PATH, REPO, AgentError, Client, provider
from .render import TTY, Renderer, bold, cyan, dim, fmt_dur, green, one_line, red, yellow


def out(*a) -> None:
    print(*a)
    sys.stdout.flush()


def jout(obj) -> None:
    out(json.dumps(obj, ensure_ascii=False, indent=2))


def text_arg(words: list) -> str:
    t = " ".join(words) if words else ""
    if t == "-" or (not t and not sys.stdin.isatty()):
        t = sys.stdin.read()
    if not t.strip():
        raise AgentError("the message text is empty (pass text, or - to read stdin)", 2)
    return t


def when(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        t = time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        age = time.time() - t
        return f"{fmt_dur(age)} ago" if age < 86400 * 2 else iso[:10]
    except ValueError:
        return iso[:16]


FULL_ID = re.compile(r"^(session-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def sid_of(c: Client, given: str) -> str:
    """The session id to address: a complete id is used as-is (no list call); a prefix is resolved
    by the provider, which is the one place that knows the sessions."""
    return given if FULL_ID.match(given) else c.session(given)["id"]


def state_of(s: dict) -> str:
    if s.get("running"):
        return green("running")
    if s.get("blank"):
        return dim("blank")
    return dim("idle")


# ── verbs ───────────────────────────────────────────────────────────────────────
def cmd_list(c: Client, a) -> int:
    r = c.call("GET", "/v1/sessions" + ("?fresh=1" if a.fresh else ""))
    sessions = r["sessions"]
    partial = bool(r.get("partial"))
    if not a.all:
        sessions = [s for s in sessions if not s.get("blank")]
    if a.json:
        jout(sessions); return 0
    if not sessions:
        out(dim("no sessions yet" + (" — the harness is still listing; retry, or --fresh to wait for it" if partial else ""))); return 0
    # running sessions first, then most recently active — the harness hands the list back in its own
    # (creation) order, which put tonight's live lanes at the bottom of 107 rows, below the idle ones,
    # and read as "every session idle" to anyone who looked at the top
    sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    sessions.sort(key=lambda s: 0 if s.get("running") else 1)
    for s in sessions:
        goal = s.get("goal") or {}
        gtxt = f" ◎ {goal.get('phase')} {goal.get('rounds', 0)}/{goal.get('max_rounds', '?')}" if goal else ""
        q = f" ✉{s['queue']}" if s.get("queue") else ""
        turns = dim(f"  {s.get('turns', 0)} turns")
        out(f"{cyan(s['id'][:20])}  {state_of(s):<18} {when(s.get('updated_at')):>12}  {bold(one_line(s.get('title') or '(untitled)', 60))}"
            f"{turns}{dim(gtxt)}{yellow(q)}{dim(' ?') if s.get('stale') else ''}")
    if partial:
        out(dim("(partial: the harness is still listing its cold sessions — `--fresh` waits for the full list)"))
    return 0


def cmd_show(c: Client, a) -> int:
    s = c.session(a.id, fresh=True)
    if a.json:
        jout(s); return 0
    out(f"{bold(s['id'])}")
    out(f"  title       {s.get('title') or '(untitled)'}")
    out(f"  state       {'running' if s.get('running') else 'idle'}{'  (blank)' if s.get('blank') else ''}   updated {when(s.get('updated_at'))}")
    out(f"  turns       {s.get('turns', 0)}    queued messages {s.get('queue', 0)}")
    if s.get("preset") or s.get("permissions"):
        out(f"  preset      {s.get('preset') or '—'}    permissions {s.get('permissions') or '—'}")
    m = s.get("model") or {}
    if m:
        out(f"  model       {m.get('provider')}/{m.get('model')}{'@' + m['reasoningEffort'] if m.get('reasoningEffort') else ''}")
    g = s.get("goal")
    if g:
        out(f"  goal        [{g.get('phase')}] {one_line(g.get('objective', ''), 120)}  ({g.get('rounds')}/{g.get('max_rounds')} rounds)")
    t = s.get("tokens") or {}
    if t:
        out(f"  tokens      in {t.get('uncachedInputTokens', 0):,} · out {t.get('outputTokens', 0):,} · cache read {t.get('cacheReadTokens', 0):,}")
    todos = s.get("todos") or []
    if todos:
        out("  todos")
        for td in todos[:20]:
            mark = {"completed": green("✓"), "in_progress": yellow("▸")}.get(td.get("status"), dim("·"))
            out(f"    {mark} {one_line(td.get('content', ''), 110)}")
    out(f"  cwd         {s.get('cwd') or '—'}")
    return 0


def _upload_all(c: Client, sid: str, files: list) -> list:
    refs = []
    for f in files or []:
        p = Path(f).expanduser()
        if not p.is_file():
            raise AgentError(f"no such file: {f}", 2)
        r = c.upload(sid, p)
        refs.append({"attachment": r["attachment"], "receipt": r.get("receipt")})
        if not getattr(c, "quiet", False):
            out(dim(f"  ↑ {p.name} ({p.stat().st_size:,} bytes)"))
    return refs


def cmd_new(c: Client, a) -> int:
    text = text_arg(a.text)
    body = {"cwd": a.cwd} if a.cwd else {}
    if a.title:
        body["title"] = a.title
    if a.preset:
        body["preset"] = a.preset
    r = c.call("POST", "/v1/sessions", body)
    sid = r["id"]
    files = _upload_all(c, sid, a.file)
    c.call("POST", f"/v1/sessions/{sid}/messages", {"text": text, "files": files})
    if a.json:
        jout({"id": sid, "preset": r.get("preset")})
    else:
        out(sid)
    return _follow(c, sid, until_idle=True, thinking=a.thinking, verbose=a.verbose) if a.follow else 0


def cmd_send(c: Client, a) -> int:
    text = text_arg(a.text)
    sid = sid_of(c, a.id)
    files = _upload_all(c, sid, a.file)
    c.call("POST", f"/v1/sessions/{sid}/messages", {"text": text, "steer": bool(a.steer), "files": files})
    if not a.follow:
        out(f"{'steered into' if a.steer else 'queued for'} {sid}")
    return _follow(c, sid, until_idle=True, thinking=a.thinking, verbose=a.verbose) if a.follow else 0


def _follow(c: Client, sid: str, until_idle: bool = False, history: int = 0, thinking: bool = False, verbose: bool = False,
            raw: bool = False, since: int = -1, cancel_on_interrupt: bool = False, as_json: bool = False) -> int:
    path = f"/v1/sessions/{sid}/events?history={history}&since={since}" + ("&raw=1" if raw else "")
    r = Renderer(show_thinking=thinking, verbose=verbose)
    saw_turn = False
    try:
        for m in c.events(path):
            if as_json:
                out(json.dumps({"event": m["event"], "id": m["id"], "data": m["data"]}, ensure_ascii=False))
                if until_idle and m["event"] == "turn.end":
                    return 0
                continue
            r.event(m["event"], m["data"])
            if m["event"] == "turn.start":
                saw_turn = True
            if until_idle and m["event"] == "turn.end" and saw_turn:
                r.stop()
                return 0
            if m["event"] in ("end", "error"):
                r.stop()
                return 0 if m["event"] == "end" else 1
    except KeyboardInterrupt:
        r.stop()
        if cancel_on_interrupt:
            c.call("POST", f"/v1/sessions/{sid}/cancel", {})
            out(yellow("cancelled the running turn"))
            return 130
        out(dim("detached — the session keeps running (bbox agent follow to re-attach; --cancel-on-interrupt to stop it)"))
        return 130
    finally:
        r.stop()
    return 0


def cmd_follow(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    return _follow(c, sid, until_idle=a.until_idle, history=a.history, thinking=a.thinking, verbose=a.verbose,
                   raw=a.raw, since=a.since, cancel_on_interrupt=a.cancel_on_interrupt, as_json=a.json)


def cmd_log(c: Client, a) -> int:
    """Recent history = the opening snapshot of the live stream (the harness pages a log only
    against a cursor its follow frame hands out, so the stream is the one source that is always
    consistent); the stream is closed as soon as the snapshot has been rendered."""
    sid = sid_of(c, a.id)
    ren = Renderer(show_thinking=a.thinking, verbose=a.verbose)
    got = []
    for m in c.events(f"/v1/sessions/{sid}/events?history={a.n}"):
        if m["event"] == "snapshot":
            got = (m["data"] or {}).get("events") or (m["data"] or {}).get("records") or []
            break
        if m["event"] in ("error", "end"):
            if m["event"] == "error":
                raise AgentError(str((m["data"] or {}).get("message") or "stream error"), 1)
            break
    if a.json:
        jout({"id": sid, "events": got}); return 0
    for e in got:
        ren.event(e.get("type", ""), e)
    ren.stop()
    return 0


def cmd_wait(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    end = time.time() + a.wait_for
    started = time.time()
    while True:
        s = c.session(sid, fresh=True)
        if not s.get("running"):
            break
        if time.time() > end:
            raise AgentError(f"{sid} still running after {a.wait_for:.0f}s", 3)
        if TTY and not a.quiet:
            sys.stdout.write(f"\r\033[2K{dim(f'running … {fmt_dur(time.time() - started)}')}")
            sys.stdout.flush()
        time.sleep(5)
    if TTY and not a.quiet:
        sys.stdout.write("\r\033[2K")
    r = c.call("GET", f"/v1/sessions/{sid}/messages?limit=6")
    last = next((e for e in reversed(r.get("events") or []) if e.get("type") == "assistant"), None)
    if a.json:
        jout({"id": sid, "running": False, "answer": last.get("text") if last else None})
    else:
        out(last.get("text") if last else dim("(no answer text)"))
    return 0


def cmd_watch(c: Client, a) -> int:
    board = {}

    def draw():
        if not TTY:
            return
        sys.stdout.write("\033[H\033[2J")
        out(bold(f"office agent — {len(board)} sessions   ") + dim(time.strftime("%H:%M:%S")))
        for s in sorted(board.values(), key=lambda x: (not x.get("running"), x.get("updated_at") or ""), reverse=False):
            goal = s.get("goal") or {}
            turns = dim(f"{s.get('turns', 0)} turns")
            queue = yellow(f"  ✉{s['queue']}") if s.get("queue") else ""
            phase = dim(f"  ◎ {goal.get('phase')}") if goal else ""
            out(f"{cyan(s['id'][:20])}  {state_of(s):<18} {bold(one_line(s.get('title') or '(untitled)', 50)):<52} {turns}{queue}{phase}")
        out(dim("\nCtrl-C to leave"))

    try:
        for m in c.events("/v1/watch"):
            ev, d = m["event"], m["data"] or {}
            if a.json:
                out(json.dumps({"event": ev, "data": d}, ensure_ascii=False)); continue
            if ev == "baseline":
                board.clear()
                for s in d.get("sessions") or []:
                    if not s.get("blank"):
                        board[s["id"]] = s
                draw()
            elif ev == "update" and d.get("id") in board:
                s = board[d["id"]]
                key, val = d.get("key"), d.get("value")
                if key == "title":
                    s["title"] = val
                elif key == "goal":
                    g = (val or {}).get("goal") or {}
                    s["goal"] = {"objective": g.get("objective"), "phase": g.get("phase"), "rounds": (val or {}).get("roundsStarted"), "max_rounds": g.get("maxGoalRounds")} if g else None
                elif key == "turnOutline":
                    s["turns"] = len(val or [])
                elif key == "sessionListMetadata":
                    s["blank"] = bool((val or {}).get("blank"))
                s["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                draw()
            elif ev == "queue" and d.get("id") in board:
                board[d["id"]]["queue"] = len(d.get("items") or []); draw()
            elif ev == "jobs" and d.get("id") in board:
                board[d["id"]]["running"] = any(j.get("status") == "running" for j in d.get("jobs") or []) or board[d["id"]].get("running")
                draw()
            elif ev == "error":
                raise AgentError(f"{d.get('code')}: {d.get('message')}", 1)
    except KeyboardInterrupt:
        if TTY:
            out("")
        return 130
    return 0


def cmd_cancel(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    c.call("POST", f"/v1/sessions/{sid}/cancel", {})
    out(f"cancel requested for {sid}"); return 0


def cmd_rename(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    r = c.call("POST", f"/v1/sessions/{sid}/rename", {"title": " ".join(a.title)})
    out(f"{sid}: {r['title']}"); return 0


def cmd_fork(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    r = c.call("POST", f"/v1/sessions/{sid}/fork", {"at_seq": a.at_seq} if a.at_seq is not None else {})
    out(r["id"] if not a.json else json.dumps(r)); return 0


def cmd_cmd(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    line = " ".join(a.line)
    if not line.startswith("/"):
        line = "/" + line
    receipts = [r["receipt"] for r in _upload_all(c, sid, a.file) if r.get("receipt")]
    r = c.call("POST", f"/v1/sessions/{sid}/command", {"line": line, "receipts": receipts})
    if a.json:
        jout(r)
    else:
        res = r.get("result")
        out(dim("ok") if res is None else (res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, indent=2)))
    return 0


def cmd_commands(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    r = c.call("GET", f"/v1/sessions/{sid}/commands")
    if a.json:
        jout(r); return 0
    for x in r.get("commands") or []:
        hint = (x.get("input") or {}).get("hint")
        out(f"  {bold('/' + x['name']):<28} {x.get('description', '')}{dim('  ' + hint) if hint else ''}")
    return 0


def cmd_goal(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    act = a.action or "get"
    if act == "get":
        r = c.call("GET", f"/v1/sessions/{sid}/goal")
    elif act == "set":
        if not a.objective:
            raise AgentError("goal set needs the objective text", 2)
        r = c.call("POST", f"/v1/sessions/{sid}/goal", {"objective": " ".join(a.objective), **({"max_rounds": a.rounds} if a.rounds else {})})
    else:
        r = c.call("POST", f"/v1/sessions/{sid}/goal/{act}", {})
    if a.json:
        jout(r); return 0
    g = r.get("goal")
    if not g:
        out(dim("no goal")); return 0
    out(f"[{g.get('phase')}] {g.get('objective')}  ({g.get('roundsStarted', g.get('rounds', 0))}/{g.get('maxGoalRounds', g.get('max_rounds', '?'))} rounds)")
    if g.get("blockedReason"):
        out(yellow(f"  blocked: {g['blockedReason'].get('message')}"))
    return 0


def cmd_model(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    if a.set:
        spec = a.set
        effort = None
        if "@" in spec:
            spec, effort = spec.rsplit("@", 1)
        if "/" not in spec:
            raise AgentError("--set takes provider/model[@effort]", 2)
        prov, model = spec.split("/", 1)
        r = c.call("POST", f"/v1/sessions/{sid}/model", {"provider": prov, "model": model, **({"effort": effort} if effort else {})})
        out(f"{sid}: {r['provider']}/{r['model']}{'@' + r['effort'] if r.get('effort') else ''}"); return 0
    s = c.session(sid, fresh=True)
    m = s.get("model") or {}
    if a.json:
        jout(m); return 0
    out(f"{m.get('provider')}/{m.get('model')}{'@' + m['reasoningEffort'] if m.get('reasoningEffort') else ''}" if m else dim("default model"))
    return 0


def cmd_models(c: Client, a) -> int:
    r = c.call("GET", "/v1/models")
    if a.json:
        jout(r); return 0
    d = r.get("default") or {}
    out(f"default: {d.get('provider')}/{d.get('model')}")
    for g in r.get("groups") or []:
        out(bold(g.get("name", g.get("id"))))
        for m in g.get("models") or []:
            efforts = ",".join(e["id"] for e in (m.get("reasoning") or {}).get("efforts") or [])
            out(f"  {g.get('id')}/{m['id']:<32} {dim(m.get('name', ''))}{dim('  efforts: ' + efforts) if efforts else ''}")
    for f in r.get("failures") or []:
        out(red(f"  ✗ {f.get('id')}: {f.get('message')}"))
    return 0


def cmd_presets(c: Client, a) -> int:
    r = c.call("GET", "/v1/presets")
    if a.json:
        jout(r); return 0
    for p in r.get("presets") or []:
        out(f"  {bold(p['id']):<24} {p.get('name') or ''}{' (default)' if p.get('isDefault') else ''}{dim('  ' + p['description']) if p.get('description') else ''}{red('  broken: ' + p['broken']) if p.get('broken') else ''}")
    return 0


def cmd_preset(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    r = c.call("POST", f"/v1/sessions/{sid}/preset", {"preset": a.preset})
    out(f"{sid}: preset {r['preset']}"); return 0


def cmd_upload(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    refs = _upload_all(c, sid, [a.file])
    jout(refs[0]) if a.json else out(f"receipt {refs[0].get('receipt')}  ({(refs[0]['attachment'] or {}).get('attachmentId')})")
    return 0


def cmd_subagents(c: Client, a) -> int:
    sid = sid_of(c, a.id)
    r = c.call("GET", f"/v1/sessions/{sid}/subagents")
    jout(r) if a.json else out(json.dumps(r.get("subagents"), ensure_ascii=False, indent=2))
    return 0


def cmd_search(c: Client, a) -> int:
    from urllib.parse import quote
    r = c.call("GET", f"/v1/search?q={quote(' '.join(a.query))}")
    if a.json:
        jout(r); return 0
    for it in r.get("items") or []:
        out(f"{cyan(str(it.get('sessionId', ''))[:20])}  {one_line(it.get('snippet') or it.get('title') or json.dumps(it, ensure_ascii=False), 120)}")
    return 0


# ── the agent's work items (the project tool's verb, one implementation) ────────
AGENT_NAMES = {"azaria": "azaria", "azarya": "azaria", "עזריה": "azaria", "bina": "azaria", "בינה": "azaria"}
DEFAULT_AGENT = "azaria"
TASK_REF = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")


def cmd_tasks(c: Client, a) -> int:
    """`bbox agent tasks …` = `bbox project-pln tasks --as <agent> …`: the project tool owns the
    tasks and the one implementation of listing/moving them; this is the agent's view of it."""
    hook = REPO / "apps/project-pln/hooks/tasks"
    if not hook.exists():
        raise AgentError("the project tool has no `tasks` verb yet (work item DGO-8 — apps/project-pln/hooks/tasks); "
                         "until it lands: bbox project-pln plan dgo-dev, and the items at http://plane.localhost:8080/", 4)
    words = list(a.words or [])
    if not words:
        words = ["list"]
    cmd = [str(REPO / "bbox"), "project-pln", "tasks", *words]
    if "--as" not in words:
        cmd += ["--as", a.agent]
    # the project the agent's work lives in: the office's dev project unless told otherwise
    # (BBOX_AGENT_PROJECT, or --project on the line); `show DGO-12` needs none
    if "--project" not in words and not any(TASK_REF.match(w.upper()) for w in words):
        cmd += ["--project", os.environ.get("BBOX_AGENT_PROJECT", "DGO")]
    if a.json and "--json" not in words:
        cmd.append("--json")
    try:
        return subprocess.run(cmd).returncode
    except FileNotFoundError:
        raise AgentError("bbox is not runnable from here", 3)


def cmd_do(c: Client, a) -> int:
    """Hand the agent a work item. The message is the convention the plane-tasks skill teaches him:
    `complete task @project-pln/<REF>` — he reads the item, works, and moves it to done himself."""
    ref = a.ref.upper()
    if not TASK_REF.match(ref):
        raise AgentError(f"{a.ref!r} is not a work item reference (like DGO-12)", 2)
    text = f"complete task @project-pln/{ref}"
    if a.text:
        text += "\n" + " ".join(a.text)
    if a.session:
        sid = sid_of(c, a.session)
        c.call("POST", f"/v1/sessions/{sid}/messages", {"text": text, "steer": False, "files": []})
        if not a.json:
            out(f"queued for {sid}: {text.splitlines()[0]}")
    else:
        r = c.call("POST", "/v1/sessions", {"title": ref} | ({"preset": a.preset} if a.preset else {}))
        sid = r["id"]
        c.call("POST", f"/v1/sessions/{sid}/messages", {"text": text, "files": []})
        if not a.json:
            out(f"{sid}  ← {text.splitlines()[0]}")
    if a.json:
        jout({"id": sid, "ref": ref, "text": text})
    return _follow(c, sid, until_idle=True, thinking=a.thinking, verbose=a.verbose) if a.follow else 0


def cmd_login(c: Client, a) -> int:
    r = c.login(force=a.force)
    jout(r) if a.json else out(f"logged in to {r['provider']} at {r['url']}  (token cached in {r['config']})")
    return 0


def cmd_whoami(c: Client, a) -> int:
    prov = c.provider_cache or provider(c.office)
    info = {"url": c.url, "provider": prov["app"], "token": "present" if c.token else "none", "token_source": c.token_source, "config": str(CONFIG_PATH)}
    if c.office:
        info["office"] = c.office
    if prov.get("served_by"):
        info["served_by"] = prov["served_by"]
    jout(info) if a.json else out("\n".join(f"{k:<13} {v}" for k, v in info.items()))
    return 0


def cmd_doctor(c: Client, a) -> int:
    """Every hop from this terminal to the harness, with a number on it."""
    rows = []

    def row(name, ok, ms, note=""):
        rows.append((name, ok, ms, note))
        if not a.json:
            mark = green("ok ") if ok else red("BAD")
            out(f"  {mark} {name:<34} {dim(f'{ms:>7.0f} ms') if ms is not None else '':>12}  {note}")

    if not a.json:
        out(bold("bbox agent — connection trace"))
    t = time.time()
    try:
        prov = c.provider_cache or provider(c.office)
        row("provider manifest", True, (time.time() - t) * 1000, f"{prov['app']} → {prov['service']}:{prov['port']}"
            + (f" (office {c.office})" if c.office else ""))
    except AgentError as e:
        row("provider manifest", False, None, e.message); prov = None
    row("token", bool(c.token), 0, f"source: {c.token_source}" + ("" if c.token else " — run: bbox agent login"))
    host, port = c.url.split("://", 1)[1].split("/")[0].rsplit(":", 1) if ":" in c.url.split("://", 1)[1] else (c.url.split("://", 1)[1], "80")
    t = time.time()
    try:
        with socket.create_connection((host, int(port)), timeout=5):
            row(f"tcp {host}:{port}", True, (time.time() - t) * 1000)
        tcp_ok = True
    except OSError as e:
        row(f"tcp {host}:{port}", False, (time.time() - t) * 1000, f"{e} — the provider is not published on this host's loopback")
        tcp_ok = False
    h = {}
    if tcp_ok:
        t = time.time()
        try:
            h = c.health()
            row("GET /v1/health (adapter)", bool(h.get("ok")), (time.time() - t) * 1000,
                f"adapter up {fmt_dur(h.get('uptime_s', 0))}, harness {h.get('harness')} in {h.get('harness_ms')} ms, stream {'yes' if h.get('stream') else 'NO'}" if h.get("harness") else h.get("error", ""))
        except AgentError as e:
            row("GET /v1/health (adapter)", False, (time.time() - t) * 1000, e.message)
        if c.token:
            t = time.time()
            try:
                hd = c.call("GET", "/v1/health?deep=1", timeout=a.timeout or 240)
                row("session list (harness, deep)", bool(hd.get("ok")), (time.time() - t) * 1000, f"{hd.get('sessions', '?')} sessions, list {hd.get('list_ms', '?')} ms" if hd.get("sessions") is not None else hd.get("list_error", ""))
            except AgentError as e:
                row("session list (harness, deep)", False, (time.time() - t) * 1000, e.message)
            t = time.time()
            try:
                c.call("GET", "/v1/sessions", timeout=a.timeout or 240)
                row("GET /v1/sessions (cached)", True, (time.time() - t) * 1000)
            except AgentError as e:
                row("GET /v1/sessions (cached)", False, (time.time() - t) * 1000, e.message)
    if not tcp_ok and prov:
        if sys.platform == "darwin" and not os.environ.get("BBOX_IN_GUEST"):
            t = time.time()
            try:
                st = subprocess.run(["bash", str(REPO / "packaging/macos/engine.sh"), "status"], capture_output=True, text=True, timeout=60).stdout.strip()
                row("macOS engine", st == "Running", (time.time() - t) * 1000, st or "not created")
            except (OSError, subprocess.TimeoutExpired) as e:
                row("macOS engine", False, None, str(e))
        out(yellow(f"  → the {prov['app']} container must publish {port} on the docker host's loopback (docker-compose.yml `ports`);"
                   f" a container created before that line needs one recreate: bbox run {prov['app']}"))
    if a.json:
        jout([{"hop": n, "ok": o, "ms": m, "note": x} for n, o, m, x in rows])
    return 0 if all(o for _, o, _, _ in rows) else 1


# ── argument parsing ────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bbox agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--url", help="provider URL (default: cached, else http://127.0.0.1:3081)")
    ap.add_argument("--token", help="action token (default: cached; obtained through the engine on first use)")
    ap.add_argument("--office", help="a LINKED office: talk to ITS agent over the link "
                                     "(e.g. --office macbook list) — resolves through this office's "
                                     "`remote:`/`serve:` block, token from the vault")
    ap.add_argument("--timeout", type=float, default=None, help="seconds per call (default 240)")
    ap.add_argument("-q", "--quiet", action="store_true")
    # the global flags are accepted after the verb too (`bbox agent list --json`): each subparser
    # carries copies whose default is SUPPRESS, so an unset copy never overwrites the global value
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--office", default=argparse.SUPPRESS)
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", parser_class=lambda **kw: argparse.ArgumentParser(parents=[common], **kw))

    def sid(p):
        p.add_argument("id", help="session id or unique prefix")

    p = sub.add_parser("list", aliases=["ls"], help="the sessions"); p.add_argument("--all", action="store_true", help="include blank sessions"); p.add_argument("--fresh", action="store_true"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("show", help="one session's summary"); sid(p); p.set_defaults(fn=cmd_show)
    for name, aliases in (("new", ["ask", "create"]),):
        p = sub.add_parser(name, aliases=aliases, help="a new session, first message sent")
        p.add_argument("-t", "--title"); p.add_argument("-p", "--preset"); p.add_argument("--cwd")
        p.add_argument("-f", "--file", action="append", default=[], help="attach a file (repeatable)")
        p.add_argument("-F", "--follow", action="store_true", help="stay attached until the turn ends")
        p.add_argument("--thinking", action="store_true"); p.add_argument("-v", "--verbose", action="store_true")
        p.add_argument("text", nargs="*"); p.set_defaults(fn=cmd_new)
    p = sub.add_parser("send", help="queue a message into a session (or --steer into the running turn)"); sid(p)
    p.add_argument("--steer", action="store_true"); p.add_argument("-f", "--file", action="append", default=[])
    p.add_argument("-F", "--follow", action="store_true"); p.add_argument("--thinking", action="store_true"); p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("text", nargs="*"); p.set_defaults(fn=cmd_send)
    p = sub.add_parser("follow", aliases=["attach", "tail"], help="live view of a session"); sid(p)
    p.add_argument("--history", type=int, default=0, help="replay the last N messages first")
    p.add_argument("--since", type=int, default=-1, help="only events after this seq")
    p.add_argument("--until-idle", action="store_true", help="exit when the running turn ends")
    p.add_argument("--thinking", action="store_true", help="show the model's reasoning"); p.add_argument("-v", "--verbose", action="store_true", help="show tool output, not just its first line")
    p.add_argument("--raw", action="store_true", help="the harness's own events, untranslated"); p.add_argument("--cancel-on-interrupt", action="store_true")
    p.set_defaults(fn=cmd_follow)
    p = sub.add_parser("watch", help="every session live, one screen"); p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("log", aliases=["history"], help="recent turns of a session"); sid(p); p.add_argument("-n", type=int, default=20); p.add_argument("--thinking", action="store_true"); p.add_argument("-v", "--verbose", action="store_true"); p.set_defaults(fn=cmd_log)
    p = sub.add_parser("wait", help="block until the running turn ends, print the answer"); sid(p); p.add_argument("--for", dest="wait_for", type=float, default=3600, help="give up after S seconds (default 3600)"); p.set_defaults(fn=cmd_wait)
    p = sub.add_parser("cancel", aliases=["stop"], help="interrupt the running turn"); sid(p); p.set_defaults(fn=cmd_cancel)
    p = sub.add_parser("rename", help="set the title"); sid(p); p.add_argument("title", nargs="+"); p.set_defaults(fn=cmd_rename)
    p = sub.add_parser("fork", help="fork a session"); sid(p); p.add_argument("--at-seq", type=int, default=None); p.set_defaults(fn=cmd_fork)
    p = sub.add_parser("cmd", aliases=["slash"], help="run a slash command in a session"); sid(p); p.add_argument("-f", "--file", action="append", default=[]); p.add_argument("line", nargs="+"); p.set_defaults(fn=cmd_cmd)
    p = sub.add_parser("commands", help="the slash commands a session offers"); sid(p); p.set_defaults(fn=cmd_commands)
    p = sub.add_parser("goal", help="a session's goal"); sid(p); p.add_argument("action", nargs="?", choices=["get", "set", "pause", "resume", "clear", "complete"]); p.add_argument("--rounds", type=int); p.add_argument("objective", nargs="*"); p.set_defaults(fn=cmd_goal)
    p = sub.add_parser("model", help="a session's model (--set provider/model[@effort])"); sid(p); p.add_argument("--set"); p.set_defaults(fn=cmd_model)
    p = sub.add_parser("models", help="the model catalog"); p.set_defaults(fn=cmd_models)
    p = sub.add_parser("presets", help="the agent presets"); p.set_defaults(fn=cmd_presets)
    p = sub.add_parser("preset", help="switch a session's agent preset"); sid(p); p.add_argument("preset"); p.set_defaults(fn=cmd_preset)
    p = sub.add_parser("upload", help="upload a file into a session (returns a receipt)"); sid(p); p.add_argument("file"); p.set_defaults(fn=cmd_upload)
    p = sub.add_parser("subagents", help="a session's subagents"); sid(p); p.set_defaults(fn=cmd_subagents)
    p = sub.add_parser("search", help="search sessions"); p.add_argument("query", nargs="+"); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("tasks", help="the agent's work items in the project tool (list|show|start|done|comment|take …)")
    p.add_argument("--agent", default=DEFAULT_AGENT, help=argparse.SUPPRESS); p.add_argument("words", nargs=argparse.REMAINDER); p.set_defaults(fn=cmd_tasks)
    p = sub.add_parser("do", help="hand the agent a work item: complete task @project-pln/<REF>")
    p.add_argument("ref", help="the work item, like DGO-12"); p.add_argument("-s", "--session", help="into this session instead of a new one")
    p.add_argument("-p", "--preset"); p.add_argument("-F", "--follow", action="store_true"); p.add_argument("--thinking", action="store_true"); p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("text", nargs="*", help="more words for him"); p.set_defaults(fn=cmd_do)
    p = sub.add_parser("login", help="obtain and cache the action token"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_login)
    p = sub.add_parser("whoami", help="where this CLI points"); p.set_defaults(fn=cmd_whoami)
    p = sub.add_parser("doctor", help="trace every hop with timings"); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("health", help="the provider's health"); p.set_defaults(fn=lambda c, a: (jout(c.health(deep=True)), 0)[1])
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # `bbox agent azaria tasks list`: the agent's name first selects whose tasks these are
    agent = DEFAULT_AGENT
    if argv and argv[0].lower() in AGENT_NAMES:
        agent = AGENT_NAMES[argv.pop(0).lower()]
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help(); return 2
    if getattr(a, "agent", None) in (None, DEFAULT_AGENT):
        a.agent = agent
    try:
        c = Client(url=a.url, token=a.token, timeout=a.timeout or 240.0, office=a.office or "")
        c.quiet = a.quiet
        return a.fn(c, a)
    except AgentError as e:
        sys.stderr.write(red("agent: ") + e.message + "\n" if TTY else f"agent: {e.message}\n")
        return e.code
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
