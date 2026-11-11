#!/usr/bin/env python3
"""git/selftest — prove the git service end to end, against the REAL account, on a throwaway repo.

Why this exists: every op this service offers is a promise about someone else's API, and a promise
that is only ever exercised by hand is a promise that breaks silently. This runs the whole ladder —
account → repo → branch → file → issue → PR → merge → release → code push through the proxy → cleanup
— and prints one line per step, so "it works" is an observation rather than a belief.

    python3 apps/git/selftest.py                # full run (CREATES and DELETES a scratch repo)
    python3 apps/git/selftest.py --read-only    # only the ops that cannot change anything
    python3 apps/git/selftest.py --keep         # leave the repo behind for inspection
    python3 apps/git/selftest.py --mirror-offline
                                                # herd-408, NO network and NO account: two bare repos
                                                # on this disk stand in for the source and the forge

The scratch repository is named `bina-git-selftest-<timestamp>` and is DELETED at the end. Deletion
needs a credential that may delete (a classic PAT with `delete_repo`, or a GitHub App with
Administration: write) — without it the run says so and leaves the repo in place rather than
pretending the cleanup happened.

Run it from inside the platform network (the git service is at http://git:8978), e.g.:
    docker exec -it git-<DEPLOYMENT_NAME> python3 /app/selftest.py
or from any container on `traefik-network` that has this file and python3.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

BASE = os.environ.get("GIT_URL", "http://git:8978").rstrip("/")
BRANCH = "selftest"
FILE = "SELFTEST.md"


def call(op: str, **params):
    body = json.dumps({k: v for k, v in params.items() if v is not None}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/{op}", data=body,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8")), e.code
        except ValueError:
            return {}, e.code
    except (urllib.error.URLError, TimeoutError) as e:
        return {}, f"{type(e).__name__}: {e}"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def add(self, step: str, ok: bool, note: str = "") -> bool:
        self.rows.append((step, ok, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {step}" + (f" — {note}" if note else ""))
        return ok

    def summary(self) -> int:
        bad = [r for r in self.rows if not r[1]]
        print("\n" + "─" * 72)
        print(f"{len(self.rows) - len(bad)}/{len(self.rows)} steps passed")
        for step, _ok, note in bad:
            print(f"  FAILED: {step} — {note}")
        return 1 if bad else 0


def mirror_offline(rep: "Report") -> None:
    """herd-408 — prove the two properties that keep a mirror from re-cloning 1.35 GB after a failure.

    Hermetic ON PURPOSE: the app's `accounts` (vault) and `proxy` (credential → URL) are replaced
    BEFORE `mirrors` is imported, so this case needs no vault, no httpx and no network — two bare
    repositories on this disk stand in for the source and the forge, and real `git` does the work.
    What it proves:
      (1) a MISSING scratch is seeded from the TARGET FORGE when the repository is there, and the
          source is only fetched afterwards (no source clone at all);
      (2) a FAILED FETCH keeps the scratch, so the next attempt is incremental;
      (3) a failed CLONE does not — an interrupted copy is not a repository to build on;
      (4) a failure widens the clock (backoff) and a `paused` row is not scheduled at all.
    """
    import shutil
    import tempfile
    import types

    here = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="git-mirror-offline-"))
    origin_p, forge_p = tmp / "source.git", tmp / "forge.git"
    seen: list[list[str]] = []

    g_source = [""]
    g_forge = [str(forge_p)]

    def remote_url(inst_id: str, provider: str, repo: str) -> str:
        return g_forge[0] if provider == "forgejo" else g_source[0]
    # hermetic stubs, installed before the import below
    sys.modules["accounts"] = types.SimpleNamespace(
        resolve=lambda inst_id: ({"id": inst_id}, {"token": "stub"}, None),
        provider_kind=lambda proto: ("forgejo" if proto == "forge_local" else "github", "repo"))
    sys.modules["proxy"] = types.SimpleNamespace(remote_url=remote_url)
    sys.modules.pop("mirrors", None)
    import mirrors                                                # noqa: E402 — after the stubs

    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", HOME=str(tmp), GIT_TERMINAL_PROMPT="0")

    def git(*a: str, cwd=None):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True,
                              env=env, timeout=300)

    def commit_one(path: pathlib.Path, name: str, body: str) -> None:
        git("init", "--bare", "-q", str(path))
        work = pathlib.Path(tempfile.mkdtemp(dir=str(tmp)))
        git("clone", "-q", str(path), str(work))
        (work / "README.md").write_text(body, encoding="utf-8")
        git("-C", str(work), "add", "-A")
        git("-C", str(work), "-c", "user.name=selftest", "-c", "user.email=selftest@local",
            "commit", "-qm", name)
        git("-C", str(work), "push", "-q", "origin", "HEAD:refs/heads/main")

    try:
        # the SOURCE, with its own history
        commit_one(origin_p, "one", "first\n")
        # the FORGE holds what a PREVIOUS successful sync already pushed: the SAME history. An
        # unrelated root here would make the seed's push a non-fast-forward — a different and real
        # refusal that would hide the property this case is about.
        git("init", "--bare", "-q", str(forge_p))
        prev = tmp / "prev-mirror.git"
        git("clone", "--mirror", "-q", str(origin_p), str(prev))
        git("--git-dir", str(prev), "push", "--prune", "-q", str(forge_p),
            "+refs/heads/*:refs/heads/*")
        shutil.rmtree(prev, ignore_errors=True)
        g_source[0] = str(origin_p)

        # the app's own state, redirected to the temp dir
        mirrors.STATE_DIR = tmp / "state"
        mirrors.REGISTRY = mirrors.STATE_DIR / "mirrors.json"
        mirrors.SCRATCH = mirrors.STATE_DIR / "scratch"
        mirrors.MIN_FREE_MB = 0                                      # the check must not depend on the CI disk
        mirrors.MAX_BYTES = 10 ** 12
        mirrors.KEEP_SCRATCH = 1
        mirrors.INTERVAL = 3600
        mirrors._ensure_repo = lambda row: None                  # no forge API in this case
        real_git = mirrors._git

        def recording_git(args, cwd=None, timeout=None):
            seen.append([str(a) for a in args])
            # the module's own default when the caller passed none — a recording wrapper that drops
            # the timeout would disarm the very thing the code sets (found in review)
            return real_git(args, cwd, mirrors.GIT_TIMEOUT if timeout is None else timeout)

        mirrors._git = recording_git
        mid = "stub:github:bina-solution/demo"
        mirrors._save([{ "id": mid, "source_account": "stub", "source_provider": "github",
                         "source_repo": "bina-solution/demo", "target_account": "forge",
                         "target_owner": "office", "target_repo": "demo", "private": True,
                         "interval": 3600, "last_run": None, "last_status": "new",
                         "paused": False, "consecutive_failures": 0, "next_due": None }])
        scratch = mirrors.SCRATCH / mirrors._slug(mid)

        def tip(path: pathlib.Path, ref: str = "refs/heads/main") -> str:
            return (git("--git-dir", str(path), "rev-parse", ref).stdout or "").strip()

        # ── (1) a missing scratch is SEEDED FROM THE FORGE, never re-cloned from the source ──────
        res = mirrors.sync(mid)
        clones = [c for c in seen if c and c[0] == "clone"]
        fetches = [c for c in seen if c and c[0] == "fetch"] or \
                  [c for c in seen if c and "--git-dir" in c and "fetch" in c]
        forged = [c for c in clones if str(forge_p) in c]
        sourced = [c for c in clones if str(origin_p) in c]
        rep.add("1. a missing scratch is seeded from the TARGET FORGE", bool(forged) and not sourced,
                f"clone-forge={len(forged)} clone-source={len(sourced)} "
                f"seeded_from_forge={res.get('seeded_from_forge')}")
        # The seed alone would pass this while the source was never read — the property is
        # "seed, THEN fetch incrementally", so both halves are asserted, and the forge's tip must
        # equal the SOURCE's tip afterwards (a seed that never fetched leaves the older history).
        rep.add("1b. …then the source is FETCHED (not cloned) and the forge ends up at the source",
                bool(fetches) and bool(forged) and tip(forge_p) == tip(origin_p) != "",
                f"fetches={len(fetches)} forge_tip={tip(forge_p)[:8]} source_tip={tip(origin_p)[:8]}")
        rep.add("1c. and the sync itself succeeded", bool(res.get("ok")), res.get("error") or "")

        # ── (2) a FAILED FETCH keeps the scratch, and the NEXT attempt is incremental ─────────────
        seen.clear()
        g_source[0] = str(tmp / "source-is-gone.git")             # the source stops answering
        res2 = mirrors.sync(mid)
        rep.add("2. a failed fetch is reported as a failure", not res2.get("ok"),
                (res2.get("error") or "")[:120])
        rep.add("2b. …and the scratch is KEPT",
                scratch.exists() and mirrors._scratch_usable(scratch),
                f"scratch exists={scratch.exists()}")
        row = mirrors._find(mid) or {}
        rep.add("2c. …and the clock widens (backoff)",
                int(row.get("consecutive_failures") or 0) >= 1
                and int(row.get("next_due") or 0) > time.time(),
                f"failures={row.get('consecutive_failures')} next_due in "
                f"{max(0, int(row.get('next_due') or 0) - int(time.time()))}s")
        rep.add("2d. …and it is not scheduled again immediately",
                mid not in [r.get("id") for r in mirrors.due()])

        # 2e — the recovery is what the failure costs. A new commit upstream, the source back, one run:
        # it must FETCH (never clone) and the new commit must reach the forge.
        work2 = pathlib.Path(tempfile.mkdtemp(dir=str(tmp)))
        git("clone", "-q", str(origin_p), str(work2))
        (work2 / "README.md").write_text("second\n", encoding="utf-8")
        git("-C", str(work2), "add", "-A")
        git("-C", str(work2), "-c", "user.name=selftest", "-c", "user.email=selftest@local",
            "commit", "-qm", "two")
        git("-C", str(work2), "push", "-q", "origin", "HEAD:refs/heads/main")
        g_source[0] = str(origin_p)
        seen.clear()
        res2b = mirrors.sync(mid)
        resumed_clones = [c for c in seen if c and c[0] == "clone"]
        resumed_fetches = [c for c in seen if c and "fetch" in c]
        rep.add("2e. the recovery run FETCHES into the kept scratch and carries the new commit",
                bool(res2b.get("ok")) and not resumed_clones and bool(resumed_fetches)
                and tip(forge_p) == tip(origin_p),
                f"clones={len(resumed_clones)} fetches={len(resumed_fetches)} "
                f"forge_tip={tip(forge_p)[:8]} source_tip={tip(origin_p)[:8]}")

        # ── (3) a failed CLONE is still dropped ───────────────────────────────────────────────────
        # BOTH ends go dark: with a live forge the scratch would be a good seed and the fetch would be
        # the only failure (case 2 again). This is the first-ever-mirror shape — nothing to seed from,
        # the source does not answer — and what it must NOT leave behind is a half-written repository.
        shutil.rmtree(scratch, ignore_errors=True)
        g_forge[0] = g_source[0] = str(tmp / "nothing-here.git")
        res3 = mirrors.sync(mid)
        rep.add("3. a failed CLONE leaves no half-written copy to build on",
                (not res3.get("ok")) and not scratch.exists(),
                f"scratch exists={scratch.exists()}")

        # ── (4) paused is a state, not a number ───────────────────────────────────────────────────
        g_forge[0], g_source[0] = str(forge_p), str(origin_p)
        mirrors.sync(mid)
        mirrors.set_paused(mid, True)
        far = time.time() + 10 ** 6
        paused_ids = [r.get("id") for r in mirrors.due(now=far)]
        mirrors.set_paused(mid, False)
        resumed_ids = [r.get("id") for r in mirrors.due(now=far)]
        rep.add("4. a paused row is not scheduled; a resumed one is",
                (mid not in paused_ids) and (mid in resumed_ids),
                f"paused={mid in paused_ids} resumed={mid in resumed_ids}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--read-only", action="store_true",
                    help="skip every step that writes to the account")
    ap.add_argument("--keep", action="store_true", help="do not delete the scratch repo")
    ap.add_argument("--mirror-offline", action="store_true",
                    help="herd-408: prove the mirror's scratch/seed/backoff rules with fake local "
                         "remotes — no account, no network, nothing created on any real service")
    ap.add_argument("--account", help="connection id (default: the active account)")
    ap.add_argument("--owner", help="namespace to create the repo in (default: the account's own)")
    args = ap.parse_args()
    rep = Report()
    acc = {"account": args.account}

    if args.mirror_offline:
        print("git selftest — mirror scratch rules (offline: two bare repos stand in for the source "
              "and the forge)")
        mirror_offline(rep)
        return rep.summary()

    print(f"git selftest against {BASE}" + ("  [READ ONLY]" if args.read_only else ""))

    # ── 0. the account plane ────────────────────────────────────────────────────────────────────
    req = urllib.request.Request(f"{BASE}/connections")
    with urllib.request.urlopen(req, timeout=30) as r:
        conns = json.loads(r.read().decode("utf-8"))
    rows = [c for c in conns.get("connections", []) if c["id"] == (args.account or conns.get("active"))]
    if not rep.add("an account is active and reachable", bool(rows),
                   f"active={conns.get('active')}"):
        return rep.summary()
    row = rows[0]
    print(f"        account: {row['id']} · {row.get('kind_label')} · {row.get('state')}"
          f" · login={row.get('login')}")

    who, err = call("whoami", **acc)
    rep.add("whoami", bool(who.get("ok")), who.get("error") or "")
    caps = (who.get("data") or {}).get("capabilities") or {}
    print(f"        capabilities: {caps}")

    if args.read_only:
        repo0 = _first_repo(who)
        for op, params in (("listRepos", {"limit": 5}),
                           ("getRepo", {"repo": repo0 or "x/x"})):
            if op == "getRepo" and not repo0:
                rep.add(op, True, "skipped — the account has no repositories")
                continue
            res, code = call(op, **acc, **params)
            rep.add(op, bool(res.get("ok")), res.get("error") or "")
        # The screen the owner actually uses is driven by two READ endpoints and one op that the
        # account-level steps above never touch. They are read-only, so they belong here rather than
        # in the write path: a listDir that works is the difference between a file tree and an empty
        # box, and /api/repo is a page that either answers in one call or does not.
        if repo0:
            d, _ = call("listDir", **acc, repo=repo0, path="")
            entries = ((d.get("data") or {}).get("entries") or []) if d.get("ok") else []
            rep.add("listDir (the file tree)", bool(entries),
                    f"{len(entries)} entries at the root" if entries else (d.get("error") or ""))
        # The origin the app HANDS OUT is a different string from the one traefik routes on, and the
        # two are easy to confuse (measured 2026-09-30: the browser origin lost its port the moment the
        # routing value had to lose its own, and every mirror link and forge.url silently became
        # `http://forge.<host>`). So the service proves it was TOLD a browser origin, and that what it
        # advertises is that one.
        try:
            with urllib.request.urlopen(f"{BASE}/api/mirrors", timeout=30) as r:
                mir = json.loads(r.read().decode("utf-8"))
            want = (os.environ.get("FORGE_ROOT_URL") or "").rstrip("/")
            got = (mir.get("forge") or "").rstrip("/")
            rep.add("the advertised forge origin is the browser one",
                    bool(want) and got == want,
                    f"advertised {got or '—'}, configured {want or 'unset (FORGE_ROOT_URL)'}")
        except urllib.error.HTTPError as e:     # the app answered — what it said is the step's reason
            rep.add("the advertised forge origin is the browser one", False,
                    f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        except Exception as e:  # noqa: BLE001 — a failed read is a failed step, never a crash
            rep.add("the advertised forge origin is the browser one", False, f"{type(e).__name__}: {e}")

        for path, note in (("api/repos?limit=5", "every account's repositories in one list"),
                           # `acc.get('account', '')` returns None — the key EXISTS — and "None"
                           # went into the query string as an account id, so the step asked the app
                           # to resolve an account called None and reported its 409 as if the repo
                           # page were broken. Measured, twice, after a recreate.
                           (f"api/repo?account={acc.get('account') or ''}&repo={quote(repo0 or '')}",
                            "the repository page in one call")):
            try:
                # urllib, like every other call in this file: the selftest runs INSIDE the image, and
                # the app's httpx is a dependency of the service, not of its own proof.
                with urllib.request.urlopen(f"{BASE}/{path}", timeout=60) as r:
                    body = json.loads(r.read().decode("utf-8"))
                ok = body.get("ok") is not False
                extra = ""
                if "api/repo" in path:
                    sec = (body.get("sections") or {})
                    extra = f"branches {len((sec.get('branches') or {}).get('branches') or [])}, " \
                            f"tree {len((sec.get('tree') or {}).get('entries') or [])}"
                elif ok:
                    extra = f"{len(body.get('repos') or [])} repositories"
                rep.add(f"/{path.split('?')[0]} ({note})", ok, body.get("error") or extra)
            except urllib.error.HTTPError as e:
                rep.add(f"/{path.split('?')[0]} ({note})", False,
                        f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
            except Exception as e:                  # noqa: BLE001 — a broken endpoint is a FAILED step
                rep.add(f"/{path.split('?')[0]} ({note})", False, f"{type(e).__name__}: {e}")
        return rep.summary()

    # ── 1. create the scratch repository ────────────────────────────────────────────────────────
    name = f"bina-git-selftest-{int(time.time())}"
    repo_res, code = call("createRepo", name=name, owner=args.owner, private=True,
                          description="Created by apps/git/selftest.py — safe to delete.",
                          readme=True, **acc)
    if not rep.add("createRepo", bool(repo_res.get("ok")), repo_res.get("error") or ""):
        return rep.summary()
    repo = (repo_res.get("data") or {}).get("full_name") or f"{args.owner or ''}/{name}"
    print(f"        repo: {repo}")

    try:
        # ── 2. issues ───────────────────────────────────────────────────────────────────────────
        iss, _ = call("createIssue", repo=repo, title="selftest issue",
                      body="Filed by the selftest; closed and left as evidence.", **acc)
        rep.add("createIssue", bool(iss.get("ok")), iss.get("error") or "")
        number = (iss.get("data") or {}).get("id")
        if number:
            upd, _ = call("updateIssue", repo=repo, issue=number, state="closed", **acc)
            rep.add("updateIssue (close)", bool(upd.get("ok")), upd.get("error") or "")
            com, _ = call("commentIssue", repo=repo, issue=number, body="closed by selftest", **acc)
            rep.add("commentIssue", bool(com.get("ok")), com.get("error") or "")

        # ── 3. branch + file (an API commit, no working copy) ───────────────────────────────────
        br, _ = call("createBranch", repo=repo, branch=BRANCH, **acc)
        rep.add("createBranch", bool(br.get("ok")), br.get("error") or "")
        put, _ = call("putFile", repo=repo, path=FILE, branch=BRANCH,
                      content="# selftest\n\nwritten through the git API.\n",
                      message="selftest: add a file through the API", **acc)
        rep.add("putFile", bool(put.get("ok")), put.get("error") or "")
        getf, _ = call("getFile", repo=repo, path=FILE, ref=BRANCH, **acc)
        rep.add("getFile", bool(getf.get("ok")) and "selftest" in str(
            (getf.get("data") or {}).get("content", "")), getf.get("error") or "")

        # ── 4. pull request + review + merge ────────────────────────────────────────────────────
        default = (repo_res.get("data") or {}).get("default_branch") or "main"
        pr, _ = call("createPR", repo=repo, title="selftest PR", head=BRANCH, base=default,
                     body="Opened by the selftest to prove the PR path.", **acc)
        rep.add("createPR", bool(pr.get("ok")), pr.get("error") or "")
        pr_no = (pr.get("data") or {}).get("id")
        if pr_no:
            rev, _ = call("submitReview", repo=repo, pr=pr_no, verdict="comment",
                          body="reviewed by selftest", **acc)
            rep.add("submitReview", bool(rev.get("ok")), rev.get("error") or "")
            mg, _ = call("mergePR", repo=repo, pr=pr_no, method="merge", **acc)
            applied = (mg.get("data") or {}).get("applied") or "native"
            rep.add("mergePR", bool(mg.get("ok")), mg.get("error") or f"applied={applied}")

        # ── 5. release ──────────────────────────────────────────────────────────────────────────
        rel, _ = call("createRelease", repo=repo, tag="v0.0.1", name="selftest",
                      body="Release created by the selftest.", **acc)
        rep.add("createRelease", bool(rel.get("ok")), rel.get("error") or "")
        lst, _ = call("listReleases", repo=repo, **acc)
        rep.add("listReleases", bool(lst.get("ok")), lst.get("error") or "")

        # ── 6. code: a real clone and a real push through the credential-free proxy ─────────────
        rem, _ = call("remote", repo=repo, **acc)
        remote = rem.get("remote")
        if rep.add("remote (the credential-free URL)", bool(remote), rem.get("error") or ""):
            work = "/tmp/git-selftest-clone"
            subprocess.run(["rm", "-rf", work], check=False)
            env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
            clone = subprocess.run(["git", "clone", "--depth", "1", remote, work],
                                   capture_output=True, text=True, env=env, timeout=300)
            rep.add("git clone through the proxy", clone.returncode == 0,
                    (clone.stderr or "").strip()[:200])
            if clone.returncode == 0:
                with open(os.path.join(work, "PROOF.txt"), "w", encoding="utf-8") as f:
                    f.write("pushed by the office through the git proxy, with no token\n")
                subprocess.run(["git", "-C", work, "add", "PROOF.txt"], check=False, env=env)
                subprocess.run(["git", "-C", work, "-c", "user.email=office@bina.local",
                                "-c", "user.name=office", "commit", "-m",
                                "selftest: push through the proxy"], check=False,
                               capture_output=True, text=True, env=env)
                push = subprocess.run(["git", "-C", work, "push", "origin", default],
                                      capture_output=True, text=True, env=env, timeout=300)
                rep.add("git push through the proxy", push.returncode == 0,
                        (push.stderr or "").strip()[:200])
                back, _ = call("listCommits", repo=repo, ref=default, limit=1, **acc)
                msg = ((back.get("data") or {}).get("commits") or [{}])[0].get("message", "")
                rep.add("the pushed commit is on the remote", "proxy" in msg, msg[:80])
            subprocess.run(["rm", "-rf", work], check=False)

    finally:
        # ── 7. cleanup, and be honest when it is refused ────────────────────────────────────────
        if args.keep:
            print(f"\n  --keep: leaving {repo} in place")
        else:
            dele, _ = call("deleteRepo", repo=repo, **acc)
            if dele.get("ok"):
                rep.add("deleteRepo (cleanup)", True, (dele.get("data") or {}).get("note", ""))
            else:
                rep.add("deleteRepo (cleanup)", False,
                        (dele.get("error") or "") +
                        f" — DELETE {repo} BY HAND, or re-run with a credential that may delete")

    return rep.summary()


def _first_repo(who: dict) -> str | None:
    res, _ = call("listRepos", limit=1)
    repos = (res.get("data") or {}).get("repos") or []
    return repos[0]["full_name"] if repos else None


if __name__ == "__main__":
    sys.exit(main())
