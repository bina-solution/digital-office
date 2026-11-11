#!/usr/bin/env python3
"""push-guard — what an n8n push asks before it imports a workflow, at its doors (hooks/push, the whole
instance; hooks/push-app, one app through the API; hooks/clean-recreate, before it wipes). DGO-1603.

    python3 apps/n8n/tooling/push-guard.py behind <checkout>                       before anything is staged
    python3 apps/n8n/tooling/push-guard.py live <checkout> --pg <container> --ids-from <stage dir>
    python3 apps/n8n/tooling/push-guard.py reopen <stage dir> <checkout> --pg <container>   G97 on both sides
    python3 apps/n8n/tooling/push-guard.py check <checkout> --pg <container>        behind + every live row
    python3 apps/n8n/tooling/push-guard.py stamp <stage dir> <checkout>  every staged workflow names its commit and line
    python3 apps/n8n/tooling/push-guard.py unstamp <export dir>     a pull takes the stamp out again

Exit: 0 push · 3 refused, and why · 4 the guard could not answer (and an unanswered question is not a yes).

WHY. On 2026-11-09 at 17:24 a push to vps1 re-activated twelve webhooks that answered the internet with no
password. The commits that had closed them were on other lines (hp-dgo, then batch 31 on dgo-stable), not yet on
vps1-dgo, and the push ran from vps1's checkout: it put back what that checkout said. A push imports what its
checkout says, so a checkout that lacks what is LIVE undoes it.

TWO QUESTIONS, both asked before anything is imported:
  1. LIVE: every workflow a push imports carries `meta.dgoCommit` and `meta.dgoBranch` (STAMP below), so n8n says
     which commit and which office's line its rows came from. A push is refused when a live row came from a commit
     HEAD lacks and it is another office's line's (no origin needed: an office whose containers hold no git
     credential is guarded too), or published on an origin branch, or unknown here while origin cannot be asked.
     That is the 17:24 case on any line. A commit only this machine has, or one no origin branch holds (a probe's,
     another history's), is said and not refused (live_question).
  2. BEHIND: the office's branch is `DGO_BRANCH` (the environment's, else .env's, as .claude/hooks/
     office-branch.py reads it). The push is refused when HEAD lacks commits that `origin/<branch>` (asked of
     origin first, best effort, never prompting) or the local `<branch>` has: a worktree left at an older commit
     is behind its branch as much as a checkout that was never pulled.
Neither is asked on a CI runner (GITHUB_ACTIONS=true, or CI=1/true/yes: it pushes the commit it was given), and
`N8N_PUSH_BEHIND_OK=<why>` in the pushing shell overrides both, named in the log. Where there is nothing to
compare with (no git, no DGO_BRANCH, no reachable database) the question is not asked, and that is SAID. A
worktree has no .env of its own: its main checkout's is read.

STAMP. Every staged workflow carries `meta.dgoCommit`, the commit it was rendered from. n8n keeps a workflow's
`meta` when it is imported (the whole-instance push, and a brand-new workflow in the per-app one). The per-app
door's API update sends name, nodes, connections and settings only, so a row updated that way keeps the commit
of its last import. A pull writes a live workflow's `meta` into its blueprint (tooling/wrap.mjs render), so the
pull doors run `unstamp` first: the stamp is the push's record, never source, and `meta` comes back exactly as
it was (null, {}, filled or absent).
"""
import json
import os
import pathlib
import re
import subprocess
import sys

REFUSED, NO_ANSWER = 3, 4
WHY = ("on 2026-11-09 a push from a checkout that lacked newer work put twelve webhooks on vps1 back open to "
       "the internet (DGO-1603): a push imports what its checkout says, and an older checkout undoes what is live")
TRUE = ("1", "true", "yes")


LAST_WINS = ("DGO_BRANCH",)    # read as .claude/hooks/office-branch.py reads it; every other key as lib.sh does


def parse_env(text):
    """A .env as the readers it must agree with read it: the FIRST assignment of a key wins (lib.sh's `_env_raw`, so
    the database this guard asks is the one the hooks' own psql asks), except DGO_BRANCH, whose LAST wins (the
    branch hook's). `export`, quotes and an inline comment are understood."""
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if v[:1] in ("'", '"') and v[:1] in v[1:]:
            v = v[1:v.index(v[0], 1)]
        else:
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        if k in LAST_WINS or k not in env:
            env[k] = v
    return env


def git(repo, *args, timeout=60):
    """-> (code, stdout, stderr); a git that does not answer in time is code 124, never an exception."""
    e = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if "fetch" in args and "GIT_SSH_COMMAND" not in e:
        # never a prompt over ssh either — unless the checkout names its own ssh command (a deploy key)
        try:
            own = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), "config", "--get",
                                  "core.sshCommand"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                 timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            own = False
        if not own:
            e["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=10"
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=e)
    except subprocess.TimeoutExpired:
        return 124, "", f"git {args[0]} did not answer in {timeout} s"
    except OSError:                                     # no git on this machine (app-management's image)
        return 127, "", "git not found"
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def office_env(repo):
    """The checkout's .env, or — a worktree has none — its main checkout's."""
    p = pathlib.Path(repo) / ".env"
    if not p.exists():
        rc, common, _ = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if rc != 0:                                     # git before 2.31: the same, relative to the checkout
            rc, common, _ = git(repo, "rev-parse", "--git-common-dir")
            common = str((pathlib.Path(repo) / common).resolve()) if rc == 0 and common else ""
        if rc == 0 and common:
            p = pathlib.Path(common).parent / ".env"
    try:
        return parse_env(p.read_text(encoding="utf-8", errors="replace")) if p.exists() else {}
    except OSError:
        return {}


def ci(environ):
    return (environ.get("GITHUB_ACTIONS") or "").strip().lower() == "true" or \
        (environ.get("CI") or "").strip().lower() in TRUE


def live_stamps(env, pg, ids=None):
    """[(commit, line, rows, some names)] of the live n8n — of these workflow ids only, when given — or None when
    it cannot be asked."""
    if not pg:
        return None
    if ids is not None and not ids:
        return []
    only = ("and id in (" + ",".join("'" + i.replace("'", "''") + "'" for i in ids) + ") ") if ids else ""
    sql = ("select meta->>'dgoCommit', coalesce(meta->>'dgoBranch', ''), count(*), "
           "left(string_agg(translate(name, E'\\t\\n\\r', '   '), ', ' order by name), 160) "
           f"from workflow_entity where meta->>'dgoCommit' is not null {only}group by 1, 2")
    try:
        # the password travels in the environment (`-e PGPASSWORD` with no value), never on a command line
        r = subprocess.run(["docker", "exec", "-e", "PGPASSWORD", pg, "psql",
                            "-U", env.get("POSTGRES_USER", "postgres"), "-d", env.get("POSTGRES_DB", "postgres"),
                            "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, PGPASSWORD=env.get("POSTGRES_PASSWORD", "")))
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = []
    for line in r.stdout.split("\n"):             # not splitlines(): jsonb leaves U+2028 and \x85 unescaped
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[2].isdigit():
            out.append((parts[0].strip(), parts[1].strip(), int(parts[2]), parts[3]))
    return out


def live_question(repo, stamps, branch):
    """-> ([refusal lines], [said lines]) for the live rows' commits against this checkout's HEAD.

    A stamp is (commit, the line it was pushed from, rows, names). A live commit HEAD lacks is refused when:
      * it was pushed from ANOTHER office's line — work this checkout can only get through dgo-stable; that needs
        no origin at all, so an office whose containers hold no git credential (vps1) is guarded too;
      * it is published on an origin branch (known here, or after one fetch of origin per run);
      * origin could not be asked and the commit is not even known here — an unanswered question is not a yes.
    It is said, not refused, when it is this machine's own (known here, on no origin branch: a probe's) or origin
    answered and has it nowhere (pruned, another history): no pull could bring it, and refusing it would refuse
    every push after."""
    refuse, said = [], []
    origin = {}                                          # one fetch of origin per run, whatever the stamps
    for commit, line, rows, names in stamps:
        if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            continue                                    # "unknown": a push from no git checkout
        known = git(repo, "cat-file", "-e", commit + "^{commit}")[0] == 0
        if known and git(repo, "merge-base", "--is-ancestor", commit, "HEAD")[0] == 0:
            continue
        if line and branch and line != branch:
            refuse.append(f"  {rows} live workflow(s) came from {commit[:8]} on {line} — another office's line, "
                          f"which this checkout's HEAD lacks ({names})")
            continue
        where, asked = published(repo, commit, origin)
        if where:
            refuse.append(f"  {rows} live workflow(s) came from {commit[:8]} (on {where}), which this checkout's "
                          f"HEAD lacks ({names})")
        elif not asked and not known:
            refuse.append(f"  {rows} live workflow(s) came from {commit[:8]}, a commit this checkout has never seen, "
                          f"and origin could not be asked whether it is published ({names})")
        else:
            said.append(f"{rows} live workflow(s) came from {commit[:8]}, which HEAD lacks and no origin branch holds "
                        f"— a probe's, or another history's: not refused")
    return refuse, said


def published(repo, commit, origin):
    """-> (the remote branch that holds the commit or None, whether origin was asked). The refs known here are asked
    first; when none holds it, origin's branches are fetched — once per run (`origin` remembers it) — and asked
    again: the same answer every time, which a fetch by sha cannot give (git answers it from what it already has)."""
    def holder():
        rc, where, _ = git(repo, "for-each-ref", "--contains", commit, "--format=%(refname:short)", "refs/remotes")
        return where.splitlines()[0] if rc == 0 and where else None
    found = holder()
    if found is not None:
        return found, True
    if "asked" not in origin:
        origin["asked"] = git(repo, "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=15", "fetch",
                              "--quiet", "origin", timeout=90)[0] == 0
    return (holder() if origin["asked"] else None), origin["asked"]


def behind_question(repo, branch, fetch=True):
    """-> ([refusal lines], [said lines]) for HEAD against the office's branch."""
    said = []
    if fetch:
        rc, _, err = git(repo, "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=15", "fetch", "--quiet",
                         "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", timeout=60)
        if rc != 0:
            said.append(f"origin was not reachable ({(err.splitlines() or ['?'])[-1][:120]}); the refs already "
                        "known are used")
    refuse = []
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        if git(repo, "rev-parse", "--verify", "--quiet", ref)[0] != 0:
            continue
        rc, n, _ = git(repo, "rev-list", "--count", f"HEAD..{ref}")
        if rc == 0 and n.isdigit() and int(n) > 0:
            newest = git(repo, "log", "-1", "--format=%h %s", ref)[1][:100]
            refuse.append(f"  {ref.split('/', 2)[-1]} has {n} commit(s) HEAD lacks, the newest: {newest}")
    return refuse, said


def check(repo, pg=None, env=None, environ=None, fetch=True, stamps=None, live="all", behind=True):
    """-> (exit code, words), before anything is imported.

    `live`: which live rows the LIVE question asks about — "all" (clean-recreate: it wipes every row), a list of
    workflow ids (a push: only the rows it would overwrite, so a row only another office's blueprint holds never
    refuses a push that cannot touch it), or None (not asked: the early call, before anything is staged).
    `behind`: whether the BEHIND question is asked."""
    environ = os.environ if environ is None else environ
    if ci(environ):
        return 0, "push-guard: a CI runner pushes the commit it was given — not asked"
    rc, head, err = git(repo, "rev-parse", "HEAD")
    if rc != 0:
        why = "no git here" if rc == 127 or "not found" in err else f"not a git checkout git can read ({err[:120]})"
        return 0, f"push-guard: {why} — nothing to compare with, not asked"
    env = office_env(repo) if env is None else env
    branch = office_branch(env, environ)
    refuse, said, lived = [], [], False
    if live is not None:
        stamps = live_stamps(env, pg, None if live == "all" else list(live)) if stamps is None else stamps
        if stamps is None:
            said.append("the live n8n could not be asked which commits its rows came from")
        else:
            r, s = live_question(repo, stamps, branch)
            refuse += ["LIVE n8n has work this checkout lacks:"] + r if r else []
            said += s
            lived = bool(r)
    if behind:
        if not branch:
            said.append("DGO_BRANCH is not declared — behind-its-branch not asked")
        else:
            r, s = behind_question(repo, branch, fetch)
            refuse += [f"this checkout (HEAD {head[:8]}) is BEHIND its office's branch:"] + r if r else []
            said += s
    if not refuse:
        return 0, "; ".join([f"push-guard: HEAD {head[:8]} — nothing newer is lost"] + said)
    override = (environ.get("N8N_PUSH_BEHIND_OK") or "").strip()
    if override:
        return 0, "push-guard OVERRIDDEN (N8N_PUSH_BEHIND_OK: " + override + "): " + " ".join(refuse + said)
    return REFUSED, "\n".join(refuse + [f"  ({s})" for s in said] + [
        f"Nothing was imported. Why this is refused: {WHY}.",
        f"Work on {branch or 'this office’s branch'} comes in with `git pull --ff-only` (or `bbox update`)."] + (
        ["Work from another office's line reaches this one through dgo-stable as a batch commit, never as that "
         "commit, so these rows never become this checkout's history: once the same work is on this line, push "
         "once with N8N_PUSH_BEHIND_OK naming why — the import stamps those rows with this line."] if lived else []) +
        ["To push anyway, say why in N8N_PUSH_BEHIND_OK."])


def staged_ids(stage):
    """The workflow ids a staged set would import (each file's `id`, else its name)."""
    out = []
    for f in sorted(pathlib.Path(stage).glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append(str(wf.get("id") or f.stem) if isinstance(wf, dict) else f.stem)
    return out


def office_branch(env, environ=None):
    """The office's line: DGO_BRANCH from the environment, else from .env (as the branch hook reads it)."""
    environ = os.environ if environ is None else environ
    return (environ.get("DGO_BRANCH") or env.get("DGO_BRANCH") or "").strip()


def provenance(repo):
    """(commit, line) of a checkout: its HEAD ('unknown' with no git) and its office's line ('' undeclared)."""
    rc, head, _ = git(repo, "rev-parse", "HEAD")
    return (head if rc == 0 and head else "unknown"), office_branch(office_env(repo))


def gate97(repo):
    """G97's own rule (scripts/refactor/webhook-auth-lint.py: `findings`, its PUBLIC declarations) from the checkout
    that pushes, or None where that checkout does not carry it yet — the rule is never written twice."""
    import importlib.util
    path = pathlib.Path(repo) / "scripts" / "refactor" / "webhook-auth-lint.py"
    if not path.exists():
        return None
    saved = list(sys.path)                          # G97 puts its own directory first; nothing here asked for it
    try:
        spec = importlib.util.spec_from_file_location("webhook_auth_lint", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod


def live_workflows(env, pg, ids):
    """{id: {"active", "nodes"}} of these workflows as n8n RUNS them (the published body an active workflow runs,
    else the draft), or None when the database cannot be asked."""
    if not ids:
        return {}
    if not pg:
        return None
    quoted = ",".join("'" + i.replace("'", "''") + "'" for i in ids)
    sql = ("select w.id, w.active, coalesce(h.nodes, w.nodes)::jsonb::text from workflow_entity w "
           "left join workflow_history h on h.\"versionId\" = w.\"activeVersionId\" "
           f"where w.id in ({quoted})")
    try:
        r = subprocess.run(["docker", "exec", "-e", "PGPASSWORD", pg, "psql", "-U", env.get("POSTGRES_USER", "postgres"),
                            "-d", env.get("POSTGRES_DB", "postgres"), "-tA", "-F", "\t", "-c", sql],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, PGPASSWORD=env.get("POSTGRES_PASSWORD", "")))
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = {}
    for line in r.stdout.split("\n"):             # not splitlines(): jsonb leaves U+2028 and \x85 unescaped
        parts = line.split("\t", 2)
        if len(parts) == 3:
            try:
                out[parts[0]] = {"active": parts[1] == "t", "nodes": json.loads(parts[2])}
            except ValueError:
                return None
    return out


def webhooks(wf, g97):
    """{(path, method): (state, why)} for every webhook node of one workflow, as n8n would register it.

    One key per webhook n8n registers — its path (n8n strips a leading `/`) and its HTTP method(s) — so one webhook
    open never excuses another closed in the same workflow (INDOX's incoming_document carries two; n8n allows a GET
    and a POST on one path). state: "open" (G97's rule finds it open and n8n registers it), "closed" (an
    authentication, or a private allow-list), "disabled" (the node is disabled: n8n registers nothing for it) or
    "inactive" (the workflow is: nothing of it is registered)."""
    out = {}
    for n in wf.get("nodes") or []:
        if not str(n.get("type", "")).endswith("webhook"):
            continue
        p = n.get("parameters") or {}
        path = str(p.get("path") or n.get("webhookId") or n.get("name") or "?").strip("/")
        m = p.get("httpMethod") or "GET"
        method = ",".join(sorted(str(x).upper() for x in m)) if isinstance(m, list) else str(m).upper()
        hit = g97.findings({"_": {"active": True, "nodes": [n]}})
        if n.get("disabled"):
            state = "disabled"
        elif not wf.get("active"):
            state = "inactive"
        else:
            state = "open" if hit else "closed"
        why = hit[0][2] if hit else ""
        was = out.get((path, method))
        if was is None or state == "open":        # one key twice (n8n refuses that live): open wins
            out[(path, method)] = (state, why)
    return out


def reopen(stage, repo, live=None, pg=None, env=None, environ=None):
    """-> (exit code, words): does this push RE-OPEN a webhook that live has closed? (G97's rule, both sides.)

    A tree can declare webhooks open that an office has closed live: on 2026-11-09 a push put twelve back on vps1
    from a checkout that did not have the change that closed them (fd5aca13 on hp-dgo, carried by batch 31 as
    dc253fc2). So the question is not only "is anything open in the staged set" — an office that has not taken the
    closing batch yet would refuse every push — but "does this push open what live has closed". Per webhook (see
    `webhooks`), for each one the staged set opens:
      * live closed it — an authentication, a private allow-list, the node disabled, or the workflow deactivated —
        REFUSED. A deactivation is the quickest close in an incident, and the guard cannot tell it from an import
        that stopped before its activation, so both are refused; the retry of a stopped push names itself in
        N8N_PUSH_REOPEN_OK;
      * live has it open, or does not carry it at all (a webhook new here, or a workflow new here): SAID — the
        tree's own debt, which G97 names in CI and the closing batch pays.
    A checkout without G97 cannot ask the rule: when the staged set carries a webhook, that is a question not
    answered (exit 4), not a yes. N8N_PUSH_REOPEN_OK=<why> pushes anyway, past both, named in the log."""
    environ = os.environ if environ is None else environ
    if ci(environ):
        return 0, "reopen-check: a CI runner — not asked"
    override = (environ.get("N8N_PUSH_REOPEN_OK") or "").strip()
    staged = {}
    for f in sorted(pathlib.Path(stage).glob("*.json")):
        wf = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(wf, dict):
            staged[str(wf.get("id") or f.stem)] = wf
    g97 = gate97(repo)
    if g97 is None:
        carries = [w for w, wf in staged.items() if wf.get("active") and any(
            str(n.get("type", "")).endswith("webhook") and not n.get("disabled")
            and ((n.get("parameters") or {}).get("authentication") or "none") == "none" for n in wf.get("nodes") or [])]
        if not carries:
            return 0, "reopen-check: this checkout does not carry G97, and no staged active workflow has an " \
                      "unauthenticated webhook"
        if live is None:
            env = office_env(repo) if env is None else env
            live = live_workflows(env, pg, sorted(carries))
        there = carries if live is None else [w for w in carries if w in live]
        if not there:
            return 0, ("reopen-check: this checkout does not carry G97; the staged workflow(s) with an unauthenticated "
                       "webhook are new to this office — nothing live to re-open")
        words = (f"reopen-check: {len(there)} staged workflow(s) carry an unauthenticated webhook that live also has "
                 f"({', '.join(there[:5])}{'…' if len(there) > 5 else ''}), and this checkout does not carry G97 "
                 "(scripts/refactor/webhook-auth-lint.py), so whether this push re-opens what live closed cannot be "
                 "asked — take dgo-stable (it brings G97)")
        return (0, "reopen-check OVERRIDDEN (N8N_PUSH_REOPEN_OK: " + override + "): " + words) if override \
            else (NO_ANSWER, words)
    opens = {(wid, key): why for wid, wf in staged.items()
             for key, (state, why) in webhooks(wf, g97).items() if state == "open"}
    if not opens:
        return 0, f"reopen-check: no staged workflow opens a webhook ({len(staged)} staged, G97's rule)"
    if live is None:
        env = office_env(repo) if env is None else env
        live = live_workflows(env, pg, sorted({w for w, _ in opens}))
    if live is None:
        words = ("reopen-check: the staged set opens webhook(s), and the live n8n could not be asked whether they "
                 "are closed there — an unanswered question is not a yes")
        return (0, "reopen-check OVERRIDDEN (N8N_PUSH_REOPEN_OK: " + override + "): " + words) if override \
            else (NO_ANSWER, words)
    reopened, said = [], []
    for (wid, (path, method)), why in sorted(opens.items()):
        hook = f"{wid} {method} /webhook/{path}"
        if wid not in live:
            said.append(f"{hook} — new here, open in the tree ({why}): G97's debt, not refused")
            continue
        have = webhooks(live[wid], g97)
        state, _ = have.get((path, method), ("absent", ""))
        if state == "absent":                     # one live node of several methods, split in the tree (or merged)
            mine = set(method.split(","))
            near = [s for (p, m), (s, _w) in have.items() if p == path and mine & set(m.split(","))]
            if near:
                state = next((s for s in near if s != "open"), "open")
        if state == "absent":
            said.append(f"{hook} — a webhook the live workflow does not carry (new or renamed), open in the tree "
                        f"({why}): G97's debt, not refused")
        elif state == "open":
            said.append(f"{hook} — already open live ({why}): G97's debt, not refused")
        else:
            reopened.append(f"  {hook} is {state} live, and this push would open it ({why})")
    if not reopened:
        return 0, "reopen-check: nothing live is re-opened; " + "; ".join(said)
    if override:
        return 0, "reopen-check OVERRIDDEN (N8N_PUSH_REOPEN_OK: " + override + "): " + " ".join(reopened)
    return REFUSED, "\n".join(
        ["This push would RE-OPEN webhook(s) that the live n8n has closed to the internet:"] + reopened +
        [f"  ({s})" for s in said] +
        ["No workflow was imported. The blueprint here still declares them open (G97); the change that closed them "
         "reaches this office through dgo-stable (batch 31, DGO-1603). If an earlier push stopped before it "
         "activated them, or to push anyway, say why in N8N_PUSH_REOPEN_OK."])


def stamp(stage, commit, line=""):
    """Write `meta.dgoCommit` (and `meta.dgoBranch`, the office's line it was pushed from) into every staged
    workflow, keeping what `meta` was (see unstamp). -> how many."""
    mark = {"dgoCommit": commit, **({"dgoBranch": line} if line else {})}
    n = 0
    for f in sorted(pathlib.Path(stage).glob("*.json")):
        wf = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(wf, dict):
            continue
        if isinstance(wf.get("meta"), dict):
            wf["meta"] = {**wf["meta"], **mark}
        elif "meta" not in wf:
            wf["meta"] = {**mark, "dgoMetaWas": "absent"}
        elif wf["meta"] is None:
            wf["meta"] = {**mark, "dgoMetaWas": "null"}
        else:
            continue                       # a meta of another shape is not n8n's; it is left alone
        f.write_text(json.dumps(wf, indent=2) + "\n", encoding="utf-8")
        n += 1
    return n


def unstamp(folder):
    """A pull's exported workflows, the push's stamp taken out and `meta` as it was before it. -> how many."""
    n = 0
    for f in sorted(pathlib.Path(folder).glob("*.json")):
        wf = json.loads(f.read_text(encoding="utf-8"))
        meta = wf.get("meta") if isinstance(wf, dict) else None
        if not isinstance(meta, dict) or "dgoCommit" not in meta:
            continue
        meta = dict(meta)
        was = meta.pop("dgoMetaWas", None)
        meta.pop("dgoCommit")
        meta.pop("dgoBranch", None)
        if meta:                                       # n8n's editor wrote keys of its own since: they stay
            wf["meta"] = meta
        elif was == "absent":
            wf.pop("meta")
        else:
            wf["meta"] = None if was == "null" else meta
        f.write_text(json.dumps(wf, indent=2) + "\n", encoding="utf-8")
        n += 1
    return n


def main(argv):
    try:
        if len(argv) >= 2 and argv[0] in ("check", "behind", "live"):
            # check: behind + every live row (clean-recreate) · behind: the early call, before anything is staged ·
            # live <checkout> --ids-from <stage dir>: the rows this push would overwrite
            pg = argv[argv.index("--pg") + 1] if "--pg" in argv[2:] else None
            scope = staged_ids(argv[argv.index("--ids-from") + 1]) if "--ids-from" in argv[2:] else "all"
            code, words = check(argv[1], pg=pg, live=None if argv[0] == "behind" else scope,
                                behind=argv[0] != "live")
            print(words, file=sys.stderr if code else sys.stdout)
            return code
        if len(argv) >= 3 and argv[0] == "reopen":
            pg = argv[argv.index("--pg") + 1] if "--pg" in argv[3:] else None
            code, words = reopen(argv[1], argv[2], pg=pg)
            print(words, file=sys.stderr if code else sys.stdout)
            return code
        if len(argv) >= 3 and argv[0] == "stamp":
            commit, line = provenance(argv[2])
            print(f"stamp: {stamp(argv[1], commit, line)} staged workflow(s) carry meta.dgoCommit {commit[:8]}"
                  f"{' from ' + line if line else ''}")
            return 0
        if len(argv) >= 2 and argv[0] == "unstamp":
            print(f"unstamp: {unstamp(argv[1])} pulled workflow(s) without the push's stamp")
            return 0
    except Exception as e:                              # noqa: BLE001 — said, and never a silent yes
        words = f"push-guard could not answer: {type(e).__name__}: {e}"
        # …unless the override for THIS question names why the push goes anyway — the documented way past a guard
        # must exist when the guard itself cannot answer too
        name = "N8N_PUSH_REOPEN_OK" if argv[:1] == ["reopen"] else "N8N_PUSH_BEHIND_OK"
        why = (os.environ.get(name) or "").strip() if argv[:1] != ["stamp"] and argv[:1] != ["unstamp"] else ""
        if why:
            print(f"{words} — OVERRIDDEN ({name}: {why})")
            return 0
        print(words, file=sys.stderr)
        return NO_ANSWER
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
