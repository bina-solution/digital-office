#!/usr/bin/env python3
"""test_push_behind — an n8n push from a checkout that lacks what is live, or is behind its office's branch, is
refused before anything is imported, at every door; every import names its commit; a pull takes it out (DGO-1603).

    python3 apps/n8n/test_push_behind.py            (git; no office, no docker)

Real repositories made here: an origin with two office lines, the office's checkout, and commits that land after
it pulled — the 17:24 case: the commits that closed vps1's webhooks were on another line (hp-dgo), not on
vps1-dgo, and live rows came from them.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
GUARD = HERE / "tooling" / "push-guard.py"
spec = importlib.util.spec_from_file_location("push_guard", GUARD)
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)
FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def sh(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=vps1-dgo",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, name):
    (pathlib.Path(cwd) / name).write_text(name, encoding="utf-8")
    sh(cwd, "add", name)
    sh(cwd, "commit", "-q", "-m", f"add {name}")
    return sh(cwd, "rev-parse", "HEAD")


QUIET = {}                                               # a pushing shell that is not a CI runner
ENV = {"DGO_BRANCH": "vps1-dgo"}
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    origin, office, hp = d / "origin.git", d / "office", d / "hp"
    sh(d, "init", "-q", "--bare", str(origin))
    sh(d, "clone", "-q", str(origin), str(hp))
    base = commit(hp, "a")
    sh(hp, "push", "-q", "origin", "HEAD:vps1-dgo", "HEAD:hp-dgo")
    sh(d, "clone", "-q", "-b", "vps1-dgo", str(origin), str(office))

    code, said = pg.check(office, env=ENV, environ=QUIET, stamps=[(base, "vps1-dgo", 30, "x")])
    check(code == 0 and "nothing newer is lost" in said, "a checkout at its branch's tip, live rows from its own past: pushes")

    # ── LIVE: the 17:24 case — the rows that closed the webhooks came from a commit on ANOTHER line ──
    closed = commit(hp, "b-closes-the-webhooks")
    sh(hp, "push", "-q", "origin", "HEAD:hp-dgo")
    check(sh(office, "cat-file", "-t", "HEAD") == "commit" and
          subprocess.run(["git", "-C", str(office), "cat-file", "-e", closed], capture_output=True).returncode != 0,
          "(the office has never seen the commit that closed them)")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[(closed, "", 12, "meet-recordings, …")])
    check(code == pg.REFUSED and "(on origin/hp-dgo)" in said and closed[:8] in said and "12 live workflow(s)" in said
          and "Nothing was imported" in said and "DGO-1603" in said and "dgo-stable" in said,
          "live rows from a commit this checkout has never seen, published on another line: refused (origin's lines "
          "fetched and asked), naming them and the way in — though HEAD has every commit of its own branch")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[(closed, "", 12, "x")])
    check(code == pg.REFUSED and "(on origin/hp-dgo)" in said, "…and the same answer the next time it is asked")
    sh(office, "fetch", "-q", "origin", "hp-dgo")            # …the commit is now known here, but not in HEAD
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[(closed, "", 12, "x")])
    check(code == pg.REFUSED and "origin/hp-dgo" in said and "HEAD lacks" in said,
          "live rows from a published commit HEAD lacks: refused, naming the branch it is on")
    probe = d / "probe"
    sh(office, "worktree", "add", "-q", "-b", "probe-x", str(probe), "HEAD")
    local = commit(probe, "p-local-only")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[(local, "vps1-dgo", 2, "x")])
    check(code == 0 and "no origin branch holds" in said,
          "live rows from a probe's unpublished commit on this office's own line: said, not refused")
    gone = d / "gone"                                    # a commit from a history this office never had (pruned)
    sh(d, "init", "-q", str(gone))
    stray = commit(gone, "z-elsewhere")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[(stray, "vps1-dgo", 4, "x")])
    check(code == 0 and "no origin branch holds" in said,
          "live rows from a commit neither here nor on origin, origin asked (a pruned probe, another history): said, "
          "not refused — no pull could bring it")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[("unknown", "", 5, "x")])
    check(code == 0, "a row stamped `unknown` (a push from no git checkout) is not a commit to compare")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=None, pg=None)
    check(code == 0 and "could not be asked" in said, "no reachable database: the live question is said, not answered")

    # ── BEHIND its own branch ──
    other = d / "other"
    sh(d, "clone", "-q", "-b", "vps1-dgo", str(origin), str(other))
    newer = commit(other, "c-on-vps1-dgo")
    sh(other, "push", "-q", "origin", "HEAD:vps1-dgo")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[])
    check(code == 0, "without asking origin, the office's stale ref cannot see it — which is why origin is asked")
    code, said = pg.check(office, env=ENV, environ=QUIET, stamps=[])
    check(code == pg.REFUSED and "BEHIND" in said and "vps1-dgo has 1 commit(s) HEAD lacks" in said
          and "c-on-vps1-dgo" in said, "a checkout its branch moved past: refused after asking origin, naming what it lacks")
    code, said = pg.check(office, env=ENV, environ={"N8N_PUSH_BEHIND_OK": "restoring yesterday on purpose"}, stamps=[])
    check(code == 0 and "OVERRIDDEN" in said and "restoring yesterday" in said, "the override pushes, and says why")
    for environ, ok in (({"GITHUB_ACTIONS": "true"}, True), ({"CI": "1"}, True), ({"CI": "false"}, False),
                        ({"CI": "0"}, False)):
        code, _ = pg.check(office, env=ENV, environ=environ, stamps=[])
        check((code == 0) == ok, f"CI {environ}: {'not asked' if ok else 'asked (not a CI runner)'}")
    code, said = pg.check(office, env={}, environ=QUIET, stamps=[])
    check(code == 0 and "DGO_BRANCH is not declared" in said, "no DGO_BRANCH: behind not asked, and said")
    code, said = pg.check(office, env={}, environ={"DGO_BRANCH": "vps1-dgo"}, stamps=[])
    check(code == pg.REFUSED, "DGO_BRANCH from the environment counts, as the branch hook reads it")

    sh(office, "pull", "-q", "--ff-only", "origin", "vps1-dgo")
    commit(office, "d-local")                              # an office ahead of origin with its own commits
    code, said = pg.check(office, env=ENV, environ=QUIET, stamps=[(newer, "vps1-dgo", 3, "x")])
    check(code == 0, "an office AHEAD of origin (its own unpushed commits) pushes")

    # ── a worktree has no .env: its main checkout's is read ──
    (office / ".env").write_text("export DGO_BRANCH=vps1-dgo   # the office's line\nCI=false\n", encoding="utf-8")
    wt = d / "old"
    sh(office, "worktree", "add", "-q", "--detach", str(wt), "HEAD~2")
    check(pg.office_env(wt).get("DGO_BRANCH") == "vps1-dgo", "a worktree reads its main checkout's .env "
          "(`export`, an inline comment)")
    code, said = pg.check(wt, environ=QUIET, stamps=[])
    check(code == pg.REFUSED and "vps1-dgo has" in said, "a worktree left at an older commit is behind its branch")
    sh(office, "remote", "set-url", "origin", str(d / "nowhere.git"))
    code, said = pg.check(wt, environ=QUIET, stamps=[])
    check(code == pg.REFUSED and "origin was not reachable" in said,
          "origin unreachable: said, and the refs already known still refuse a checkout behind them")

    # ── origin CANNOT be asked (vps1's containers hold no git credential): live work is still guarded ──
    later = commit(hp, "e-later-on-hp")                    # lands on hp-dgo after this office lost its origin
    sh(hp, "push", "-q", "origin", "HEAD:hp-dgo")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[(later, "hp-dgo", 7, "x")])
    check(code == pg.REFUSED and "another office's line" in said and "hp-dgo" in said,
          "offline: a live row from ANOTHER office's line that HEAD lacks is refused by the stamp's line alone")
    code, said = pg.check(office, env=ENV, environ=QUIET, fetch=False, stamps=[(later, "", 7, "x")])
    check(code == pg.REFUSED and "could not be asked" in said,
          "offline: an unknown commit with no line named is refused — an unanswered question is not a yes")

    # ── the CLI's exit codes, as the hooks read them ──
    r = subprocess.run([sys.executable, str(GUARD), "check", str(wt)], capture_output=True, text=True,
                       # a bare environment, as a hook's — but what the interpreter itself needs to START stays: the
                       # CI's python (setup-python's toolcache build) loads libpython through LD_LIBRARY_PATH, and
                       # without it this subprocess died before the guard could answer (the Dell, 2026-11-10)
                       env={"PATH": "/usr/bin:/bin:/usr/local/bin",
                            **{k: os.environ[k] for k in ("LD_LIBRARY_PATH",) if k in os.environ}})
    check(r.returncode == pg.REFUSED and "BEHIND" in r.stderr, "the CLI refuses with 3, on stderr"
          + ("" if r.returncode == pg.REFUSED and "BEHIND" in r.stderr
             else f" — it exited {r.returncode}: {' '.join((r.stderr or r.stdout or '').split())[-300:]}"))
    check(pg.main(["check", str(wt), "--pg"]) == pg.NO_ANSWER, "a guard that cannot answer exits 4, never 0")

    # ── STAMP and UNSTAMP: meta comes back exactly as it was ──
    stage = d / "stage"
    stage.mkdir()
    shapes = {"null": {"id": "w1", "nodes": [], "meta": None}, "empty": {"id": "w2", "nodes": [], "meta": {}},
              "filled": {"id": "w3", "nodes": [], "meta": {"templateCredsSetupCompleted": True}},
              "absent": {"id": "w4", "nodes": []}, "hebrew": {"id": "w5", "name": "סיכום \ud800", "meta": None}}
    for name, wf in shapes.items():
        (stage / f"{name}.json").write_text(json.dumps(wf), encoding="utf-8")
    n = pg.stamp(stage, "0123456789abcdef")
    got = {name: json.loads((stage / f"{name}.json").read_text(encoding="utf-8")) for name in shapes}
    check(n == 5 and all(w["meta"]["dgoCommit"] == "0123456789abcdef" for w in got.values())
          and got["filled"]["meta"]["templateCredsSetupCompleted"] is True,
          "every staged workflow names its commit in meta, keeps what meta held, and a lone surrogate is no crash")
    n = pg.unstamp(stage)
    back = {name: json.loads((stage / f"{name}.json").read_text(encoding="utf-8")) for name in shapes}
    check(n == 5 and back == shapes, "a pull takes the stamp out: meta exactly as it was — null, {}, filled, absent")
    check(pg.unstamp(stage) == 0, "…and a workflow no push stamped is left as it is")
    (stage / "edited.json").write_text(json.dumps({"id": "w6", "meta": {"dgoCommit": "ab", "dgoMetaWas": "null",
                                                                         "templateId": "the editor's"}}), encoding="utf-8")
    pg.unstamp(stage)
    check(json.loads((stage / "edited.json").read_text(encoding="utf-8"))["meta"] == {"templateId": "the editor's"},
          "keys n8n's editor wrote into a stamped meta since stay")
    (stage / "lined.json").write_text(json.dumps({"id": "w7", "meta": None}), encoding="utf-8")
    pg.stamp(stage, "fedcba9876543210", "vps1-dgo")
    lined = json.loads((stage / "lined.json").read_text(encoding="utf-8"))["meta"]
    pg.unstamp(stage)
    check(lined.get("dgoBranch") == "vps1-dgo"
          and json.loads((stage / "lined.json").read_text(encoding="utf-8"))["meta"] is None,
          "the stamp names the office's line, and a pull takes that out too")
    commit_, line_ = pg.provenance(wt)
    check(len(commit_) == 40 and line_ == "vps1-dgo", "a checkout's provenance: its HEAD and its office's line")

# ── REOPEN: G97's rule on both sides — a push that opens what live has closed is refused ──
STAND_IN_97 = '''
import ipaddress
PUBLIC = {}
def findings(wfs):          # the shape of G97's rule, for a checkout that carries it (dgo-stable, hp-dgo, vps1-dgo)
    out = []
    for wid, wf in wfs.items():
        if not wf.get("active"):
            continue
        for n in wf.get("nodes") or []:
            p = n.get("parameters") or {}
            if not str(n.get("type", "")).endswith("webhook") or (p.get("authentication") or "none") != "none":
                continue
            wl = (p.get("options") or {}).get("ipWhitelist") or ""
            ok = bool(wl.strip()) and all(ipaddress.ip_network(x.strip(), strict=False).is_private
                                          for x in wl.split(",") if x.strip())
            if not ok and p.get("path") not in PUBLIC:
                out.append((wid, p.get("path") or "?", "no ipWhitelist" if not wl.strip() else "public entry"))
    return out
'''
REAL_97 = HERE.parents[1] / "scripts" / "refactor" / "webhook-auth-lint.py"
hook = lambda path, **o: {"type": "n8n-nodes-base.webhook", "parameters": {"path": path, **o}}  # noqa: E731
closed_node = hook("meet-recordings", options={"ipWhitelist": "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"})
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    stage, repo = d / "stage", d / "checkout"
    stage.mkdir()
    (repo / "scripts" / "refactor").mkdir(parents=True)
    code, said = pg.reopen(stage, repo, live={}, environ=QUIET)
    check(code == 0 and "does not carry G97" in said, "a checkout without G97 and nothing staged: nothing to ask")
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [hook("meet-recordings")]}), encoding="utf-8")
    code, said = pg.reopen(stage, repo, live={}, environ=QUIET)
    check(code == 0 and "new to this office" in said,
          "a checkout without G97, a staged webhook live does not have: nothing to re-open")
    there = {"meetRecordings01": {"active": True, "nodes": [closed_node]}}
    code, said = pg.reopen(stage, repo, live=there, environ=QUIET)
    check(code == pg.NO_ANSWER and "does not carry G97" in said and "meetRecordings01" in said,
          "a checkout without G97, a staged webhook live also has: the question is not answered (4), not a yes")
    code, said = pg.reopen(stage, repo, live=None, pg=None, env={}, environ=QUIET)
    check(code == pg.NO_ANSWER, "…and when live cannot be asked either: not answered (4)")
    code, said = pg.reopen(stage, repo, live=there, environ={"N8N_PUSH_REOPEN_OK": "G97 arrives with the merge"})
    check(code == 0 and "OVERRIDDEN" in said, "…and the override is the way past it, named")
    gate = repo / "scripts" / "refactor" / "webhook-auth-lint.py"
    gate.write_text(REAL_97.read_text(encoding="utf-8") if REAL_97.exists() else STAND_IN_97, encoding="utf-8")
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [hook("meet-recordings")]}), encoding="utf-8")
    for live, want, what in (
            ({"meetRecordings01": {"active": True, "nodes": [closed_node]}}, pg.REFUSED,
             "closed live (a private allow-list), open in the tree: the push is REFUSED — the 17:24 case"),
            ({"meetRecordings01": {"active": False, "nodes": [hook("meet-recordings")]}}, pg.REFUSED,
             "inactive live, active and open in the tree: refused"),
            ({"meetRecordings01": {"active": True, "nodes": [hook("meet-recordings")]}}, 0,
             "already open live: the tree's debt, said, not refused"),
            ({}, 0, "new to this office: the tree's debt, said, not refused")):
        code, said = pg.reopen(stage, repo, live=live, environ=QUIET)
        check(code == want and ("RE-OPEN" in said) == (want == pg.REFUSED) and "meet-recordings" in said, what)
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": {"active": True, "nodes": [closed_node]}},
                           environ={"N8N_PUSH_REOPEN_OK": "the caller moved to the private network"})
    check(code == 0 and "OVERRIDDEN" in said, "the re-open override pushes, and says why")
    code, said = pg.reopen(stage, repo, live=None, pg=None, env={}, environ=QUIET)
    check(code == pg.NO_ANSWER, "the staged set opens a webhook and live cannot be asked: unanswered, not a yes")
    code, said = pg.reopen(stage, repo, live=None, pg=None, env={},
                           environ={"N8N_PUSH_REOPEN_OK": "the database is being restored"})
    check(code == 0 and "OVERRIDDEN" in said, "…and the override is the way past an unanswered question too")
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": {"active": True, "nodes": [hook("other-path")]}},
                           environ=QUIET)
    check(code == 0 and "does not carry" in said, "a path the live workflow does not carry (new or renamed): said, "
                                                  "not a re-open")
    # one workflow, two webhooks (INDOX's incoming_document: create and read) — decided per path: the one open live
    # never excuses the other, closed live
    two_live = {"active": True, "nodes": [hook("doc-create"), hook("doc-read", options={"ipWhitelist": "10.0.0.0/8"})]}
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [hook("doc-create"), hook("doc-read")]}), encoding="utf-8")
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": two_live}, environ=QUIET)
    check(code == pg.REFUSED and "doc-read" in said.split("RE-OPEN", 1)[-1] and "already open live" in said,
          "two webhooks, one open live and one closed live, both open in the tree: REFUSED for the closed one")
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [hook("doc-create"), closed_node]}), encoding="utf-8")
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": two_live}, environ=QUIET)
    check(code == 0 and "doc-create" in said, "…and the tree that keeps the closed one closed goes, saying the other")
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [hook("meet-recordings")]}), encoding="utf-8")
    # a deactivation in the editor is the quickest close in an incident; an import that stopped before its
    # activation looks the same, and the guard cannot tell them apart — both refused, the retry names itself
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": {"active": False, "nodes": [hook("meet-recordings")]}},
                           environ=QUIET)
    check(code == pg.REFUSED and "inactive live" in said and "stopped before it activated" in said,
          "deactivated live with the same open body: refused, and the words name the retry's way past")
    disabled = dict(hook("meet-recordings"), disabled=True)
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": {"active": True, "nodes": [disabled]}},
                           environ=QUIET)
    check(code == pg.REFUSED and "disabled live" in said,
          "a webhook node DISABLED live (n8n registers nothing for it), enabled and open in the tree: refused")
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [disabled]}), encoding="utf-8")
    code, said = pg.reopen(stage, repo, live=None, pg=None, env={}, environ=QUIET)
    check(code == 0 and "no staged workflow opens" in said, "a webhook disabled in the tree opens nothing")
    get_post = [hook("doc", httpMethod="GET"),
                hook("doc", httpMethod="POST", options={"ipWhitelist": "10.0.0.0/8"})]
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True,
         "nodes": [hook("doc", httpMethod="GET"), hook("doc", httpMethod="POST")]}), encoding="utf-8")
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": {"active": True, "nodes": get_post}}, environ=QUIET)
    check(code == pg.REFUSED and "POST /webhook/doc is closed live" in said and "GET /webhook/doc — already open" in said,
          "one path, two methods — GET open live, POST closed live: the POST is refused, not excused by the GET")
    both = hook("doc", httpMethod=["GET", "POST"], options={"ipWhitelist": "10.0.0.0/8"})
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": {"active": True, "nodes": [both]}}, environ=QUIET)
    check(code == pg.REFUSED and "GET /webhook/doc is closed live" in said and "POST /webhook/doc is closed live" in said,
          "one closed live node of two methods, split in the tree into two open ones: both refused")
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [hook("meet-recordings")]}), encoding="utf-8")
    slash = hook("/meet-recordings", options={"ipWhitelist": "10.0.0.0/8"})
    code, said = pg.reopen(stage, repo, live={"meetRecordings01": {"active": True, "nodes": [slash]}}, environ=QUIET)
    check(code == pg.REFUSED, "closed live as `/meet-recordings` (n8n strips the slash), open in the tree: refused")
    (stage / "meetRecordings01.json").write_text(json.dumps(
        {"id": "meetRecordings01", "active": True, "nodes": [closed_node]}), encoding="utf-8")
    code, said = pg.reopen(stage, repo, live=None, pg=None, env={}, environ=QUIET)
    check(code == 0 and "no staged workflow opens" in said, "a staged set that opens nothing never needs the database")
    check(pg.staged_ids(stage) == ["meetRecordings01"], "the ids a staged set would import")

# ── .env as lib.sh and the branch hook read it; the overrides past a guard that cannot answer ──
e = pg.parse_env("POSTGRES_USER=first\nPOSTGRES_USER=second\nDGO_BRANCH=old\nDGO_BRANCH=new\n")
check(e["POSTGRES_USER"] == "first" and e["DGO_BRANCH"] == "new",
      "a duplicated key: the first wins (lib.sh), DGO_BRANCH the last (the branch hook)")
import os  # noqa: E402
saved_env = dict(os.environ)
try:
    os.environ.pop("N8N_PUSH_BEHIND_OK", None)
    check(pg.main(["live", ".", "--pg"]) == pg.NO_ANSWER, "a guard that cannot answer: 4")
    os.environ["N8N_PUSH_BEHIND_OK"] = "the guard is being repaired"
    check(pg.main(["live", ".", "--pg"]) == 0, "…and its override is the way past that too, named")
finally:
    os.environ.clear()
    os.environ.update(saved_env)

# ── EVERY DOOR asks before it imports; clean-recreate before it wipes; the pull doors unstamp before render ──
src = {door: (HERE / "hooks" / door).read_text(encoding="utf-8")
       for door in ("push", "push-app", "clean-recreate", "pull", "pull-app")}
# The compile and the render run through `wrap_run` since beee2181 (on the host's node, or inside n8n's own container
# when the host has none, DGO-1746); a call written the old way, "${WRAP}" directly, still counts — the EARLIEST of
# either spelling is the anchor.


def earliest(s, *needles):
    found = [i for i in (s.find(n) for n in needles) if i >= 0]
    return min(found) if found else -1


COMPILE, RENDER = ("wrap_run compile", '"${WRAP}" compile'), ("wrap_run render", '"${WRAP}" render')
for door, early, before in (("push", "behind", ("── Mutual exclusion",)), ("push-app", "behind", COMPILE),
                            ("clean-recreate", "check", ("TRUNCATE TABLE",))):
    s = src[door]
    asked = s.find(f'push-guard.py" {early}')
    check(0 < asked < earliest(s, *before), f"hooks/{door} asks `{early}` before {before[0]!r}")
    check("|| _gc=$?" in s[asked:asked + 200], f"hooks/{door} keeps the guard's exit (3 refused, else unanswered)")
for door, first in (("push", "n8n import:workflow"), ("push-app", 'req("PUT"')):
    s = src[door]
    for q in ("live", "reopen", "stamp"):
        check(0 < s.find(f'push-guard.py" {q}') < s.find(first), f"hooks/{door} asks `{q}` before {first!r}")
    check("--ids-from" in s[s.find('push-guard.py" live'):s.find('push-guard.py" live') + 220],
          f"hooks/{door} asks the live question about the rows it would overwrite only")
cr = src["clean-recreate"]
check(cr.find("TRUNCATE TABLE") < cr.find('N8N_PUSH_BEHIND_OK="clean-recreate') < cr.find('"${SCRIPT_DIR}/push"')
      and 'N8N_PUSH_REOPEN_OK="clean-recreate' in cr,
      "clean-recreate's restore carries the answer it got before the wipe — never refused after it")
pa = src["push-app"]
dry = pa[pa.find('if [ "${DRY}" = "1" ]; then\n  log "${APP}: would push'):]
check('push-guard.py" reopen' in dry[:900] and 'push-guard.py" live' in dry[:900],
      "push-app's dry run says what the push guard would answer")
for door in ("pull", "pull-app"):
    check(0 < src[door].find('push-guard.py" unstamp') < earliest(src[door], *RENDER),
          f"hooks/{door} takes the push's stamp out before it renders into git")

print(f"test_push_behind: {'all passed' if not FAILS else f'{len(FAILS)} FAILED'}")
sys.exit(1 if FAILS else 0)
