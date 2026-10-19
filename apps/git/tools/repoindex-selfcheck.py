#!/usr/bin/env python3
"""repoindex-selfcheck — the repository fan-out, proven without the engine.

WHY THIS ONE. The list screen is the feature ("every repository, from every account"), and its failure
modes are the interesting part: one expired token, one rate-limited provider, one code-only
credential with no API at all. None of those may empty the screen, and the cache is the only thing
standing between a refreshing browser and a shared GitHub quota. All of that is plain Python logic in
`repoindex.py`, and none of it needs Docker, a provider or a browser to be checked.

`accounts` and `mirrors` are replaced by recording stubs BEFORE `repoindex` is imported, so the module
is exercised exactly as it is, with its collaborators scripted.

    python3 apps/git/tools/repoindex-selfcheck.py     # non-zero exit on the first failed assertion
"""
from __future__ import annotations

import pathlib
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # so `import repoindex` finds apps/git/repoindex.py

# ── the two collaborators, scripted ──────────────────────────────────────────────────────────────
ACCOUNT_ROWS: list[dict] = []
REPOS: dict[str, list[dict]] = {}
FAIL: dict[str, str] = {}
PUBLIC_BASE = "http://forge.localhost:8080"
MIRRORS: list[dict] = []
CALLS: dict[str, int] = {}


class _Adapter:
    def __init__(self, cid: str):
        self.cid = cid

    def list_repos(self, limit: int = 50) -> dict:
        CALLS[self.cid] = CALLS.get(self.cid, 0) + 1
        if self.cid in FAIL:
            raise RuntimeError(FAIL[self.cid])
        return {"repos": list(REPOS.get(self.cid, []))}


accounts = types.ModuleType("accounts")
accounts.vault_list = lambda: (list(ACCOUNT_ROWS), None)
accounts.vault_secret = lambda cid: {"token": "x"}
accounts.provider_kind = lambda protocol: {
    "git_github_pat": ("github", "pat"),
    "git_forge_local": ("forgejo", "pat"),
    "git_gitlab_pat": ("gitlab", "pat"),
    "git_gitlab_deploy_token": ("gitlab", "deploy_token"),
}.get(protocol or "", ("", ""))
accounts.adapter_for_instance = lambda inst, sec: _Adapter(inst["id"])

mirrors = types.ModuleType("mirrors")
mirrors.load = lambda: list(MIRRORS)
mirrors.public_base = lambda: PUBLIC_BASE

sys.modules["accounts"] = accounts
sys.modules["mirrors"] = mirrors
import repoindex  # noqa: E402  (must come after the stubs are installed)

# ── assertions ───────────────────────────────────────────────────────────────────────────────────
passed = failed = 0


def check(name: str, got, want) -> None:
    global passed, failed
    if got == want:
        passed += 1
        return
    failed += 1
    print(f"FAIL  {name}\n      got  {got!r}\n      want {want!r}")


def truthy(name: str, got) -> None:
    global passed, failed
    if got:
        passed += 1
        return
    failed += 1
    print(f"FAIL  {name} — got {got!r}")


def reset() -> None:
    # `vault_list` is RESTORED here, not only replaced: a test that scripts a dead vault and does not
    # put it back leaves every later test reading an empty world — which is how this very helper was
    # found to be incomplete (the contract test below failed with a KeyError, not a wrong value).
    accounts.vault_list = lambda: (list(ACCOUNT_ROWS), None)
    ACCOUNT_ROWS.clear(); REPOS.clear(); FAIL.clear(); MIRRORS.clear(); CALLS.clear()
    repoindex.forget()


# 1. every account contributes, and a LOCAL repository sorts first
reset()
ACCOUNT_ROWS[:] = [
    {"id": "gh1", "label": "GitHub — solomon", "protocol": "git_github_pat", "account_hint": "solomonBoltin@github.com"},
    {"id": "lc1", "label": "פורג' מקומי", "protocol": "git_forge_local", "account_hint": "office@forge"},
]
REPOS["gh1"] = [{"full_name": "solomonBoltin/b", "description": "", "default_branch": "main"},
                {"full_name": "solomonBoltin/a", "description": "alpha", "default_branch": "main"}]
REPOS["lc1"] = [{"full_name": "office/repo", "description": "", "default_branch": "main"}]
out = repoindex.index()
check("lists every account's repositories", len(out["repos"]), 3)
check("a local repository sorts first", out["repos"][0]["full_name"], "office/repo")
check("a local row is marked local", out["repos"][0]["local"], True)
check("rows carry the account they came from", {r["account"] for r in out["repos"]}, {"gh1", "lc1"})
check("no errors when nothing failed", out["errors"], [])

# 2. ONE failing account is reported BESIDE the others, never instead of them
reset()
ACCOUNT_ROWS[:] = [
    {"id": "gh1", "label": "GitHub — solomon", "protocol": "git_github_pat"},
    {"id": "gl1", "label": "GitLab", "protocol": "git_gitlab_pat"},
]
REPOS["gh1"] = [{"full_name": "solomonBoltin/a", "description": ""}]
FAIL["gl1"] = "timeout"
out = repoindex.index()
check("the healthy account still answers", len(out["repos"]), 1)
check("the failing account is reported", len(out["errors"]), 1)
truthy("…with its own message", "timeout" in (out["errors"][0]["error"] or ""))

# 3. a CODE-ONLY credential says so instead of looking empty
reset()
ACCOUNT_ROWS[:] = [{"id": "gl1", "label": "GitLab deploy", "protocol": "git_gitlab_deploy_token"}]
out = repoindex.index()
check("a code-only account returns no repositories", out["repos"], [])
truthy("…and says why", "קוד בלבד" in (out["errors"][0]["error"] or ""))

# 4. a mirror is attached to the repository it copies, and is not a row of its own
reset()
ACCOUNT_ROWS[:] = [{"id": "gh1", "label": "GitHub", "protocol": "git_github_pat"}]
REPOS["gh1"] = [{"full_name": "solomonBoltin/deployment-hacohen", "description": ""}]
MIRRORS[:] = [{"id": "m1", "source_account": "gh1", "source_repo": "solomonBoltin/deployment-hacohen",
               "target_owner": "office", "target_repo": "deployment-hacohen", "last_status": "ok"}]
out = repoindex.index()
check("the list is still one repository", len(out["repos"]), 1)
check("the mirror is attached", (out["repos"][0]["mirror"] or {}).get("id"), "m1")
check("…and browses into the forge",
      (out["repos"][0]["mirror"] or {}).get("browse_url"), PUBLIC_BASE + "/office/deployment-hacohen")

# 5. searching filters on the name AND the description
reset()
ACCOUNT_ROWS[:] = [{"id": "gh1", "label": "GitHub", "protocol": "git_github_pat"}]
REPOS["gh1"] = [{"full_name": "solomonBoltin/alpha", "description": ""},
                {"full_name": "solomonBoltin/beta", "description": "הצעת מחיר"}]
check("search by name", len(repoindex.index(q="alpha")["repos"]), 1)
check("search by description", len(repoindex.index(q="מחיר")["repos"]), 1)
check("a query that matches nothing", repoindex.index(q="zzz")["repos"], [])

# 6. THE CACHE — the reason a refreshing screen does not spend the GitHub quota
reset()
ACCOUNT_ROWS[:] = [{"id": "gh1", "label": "GitHub", "protocol": "git_github_pat"}]
REPOS["gh1"] = [{"full_name": "solomonBoltin/a", "description": ""}]
repoindex.index()
repoindex.index()
check("a second read is served from the cache", CALLS.get("gh1"), 1)
repoindex.index(refresh=True)
check("refresh really asks again", CALLS.get("gh1"), 2)
repoindex.forget("gh1")
repoindex.index()
check("forget() drops it", CALLS.get("gh1"), 3)

# 7. the vault being down is not "no repositories"
reset()
accounts.vault_list = lambda: ([], "שירות החיבורים אינו זמין")
out = repoindex.index()
check("a dead vault returns no rows", out["repos"], [])
truthy("…and the reason is the vault", "החיבורים" in (out["errors"][0]["error"] or ""))

# 8. THE CONTRACT WITH THE BROWSER. The screen reads a fixed set of keys off each row, and a key the
#    producer stops emitting is invisible until somebody opens the page — the canned render tests
#    cannot catch it, because their fixtures are written by hand. So the producer is asked directly.
#    (The key list is the one `repoRow` in static/app.js actually reads; see the comment there.)
reset()
ACCOUNT_ROWS[:] = [
    {"id": "gh1", "label": "GitHub — solomon", "protocol": "git_github_pat"},
    {"id": "lc1", "label": "פורג' מקומי", "protocol": "git_forge_local"},
]
REPOS["gh1"] = [{"full_name": "solomonBoltin/apitools", "description": "d", "private": True,
                 "default_branch": "main", "archived": False, "provider": "github",
                 "web_url": "https://github.com/solomonBoltin/apitools"}]
REPOS["lc1"] = [{"full_name": "office/repo", "description": "", "private": True,
                 "default_branch": "main", "archived": False, "provider": "forgejo",
                 "web_url": "https://forge.localhost/office/repo"}]
MIRRORS[:] = [{"id": "m1", "source_account": "gh1", "source_repo": "solomonBoltin/apitools",
               "target_owner": "office", "target_repo": "apitools", "last_status": "ok"}]
rows = {r["full_name"]: r for r in repoindex.index()["repos"]}
NEEDED = ["account", "account_label", "full_name", "private", "default_branch", "description",
          "provider", "local", "mirror", "archived", "web_url"]
for name in ("solomonBoltin/apitools", "office/repo"):
    missing = [k for k in NEEDED if k not in rows[name]]
    check(f"contract: every key the screen reads is emitted for {name}", missing, [])
check("contract: the mirror row carries the fields the chip reads",
      sorted(k for k in ("id", "status", "error", "last_run", "bytes", "browse_url", "target")
             if k not in rows["solomonBoltin/apitools"]["mirror"]), [])
check("contract: a local row is flagged local", rows["office/repo"]["local"], True)

print(f"\nrepoindex-selfcheck — {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
