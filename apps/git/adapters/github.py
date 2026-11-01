"""git.adapters.github — the GitHub adapter (github.com, and GitHub Enterprise Server).

REST v3. `host` absent means github.com (`https://api.github.com`); any other host is treated as a
GitHub Enterprise Server appliance, whose API root is `https://<host>/api/v3` — and which is locked
to its appliance release, so the `X-GitHub-Api-Version` header is sent only for github.com.

Two GitHub facts shape this file:

  * a pull request IS an issue (`/issues` returns PRs too, and they must be filtered out), while
    comments on a PR go to the ISSUE comment endpoint — so `kind` is always explicit;
  * creating a repository is ONE call with `auto_init` + `gitignore_template` + `license_template`,
    which is the opposite of GitLab and the reason the canonical op takes those as flags.
"""
from __future__ import annotations

import httpx

from credentials import CredentialError, credential_for
from credentials import normalize_host as credential_host

from .base import GitError, b64, describe, norm_repo, split_repo, unb64

API_VERSION = "2022-11-28"          # pinned; the default drifts, and the drift is silent
UA = "bina-office-git/0.1 (+digital-office)"


class GitHubAdapter:
    provider = "github"

    def __init__(self, secret: dict, cid: str | None = None):
        self.secret = secret or {}
        self.cid = cid
        # Every auth kind in the catalogue (classic PAT, fine-grained PAT, App installation token,
        # OAuth with refresh) is resolved HERE, once, into headers — including minting an App token
        # or refreshing an expired OAuth one. The rest of the adapter never sees a token.
        try:
            self.cred = credential_for("github", self.secret, cid)
        except CredentialError as e:
            raise GitError(e.he_message, status=e.status, detail=e.detail, kind="account")
        self.kind = self.cred.kind
        self.host = credential_host("github", self.secret.get("host") or "")
        official = self.host.lower() in ("github.com", "www.github.com", "api.github.com")
        self.api = "https://api.github.com" if official else f"https://{self.host}/api/v3"
        self.base_url = f"https://{self.host}"
        self.official = official
        if not self.cred.api_usable:
            raise GitError("החיבור הזה אינו תומך ב-API (קוד בלבד).", status=400, kind="account")
        self.default_namespace = (self.secret.get("namespace") or "").strip().strip("/")
        self._c = httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=False)

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        h = dict(self.cred.api_headers)
        if self.official:
            h["X-GitHub-Api-Version"] = API_VERSION
        return h

    def _req(self, method: str, path: str, *, params=None, json=None, allow=(200, 201, 204)):
        try:
            r = self._c.request(method, f"{self.api}{path}", headers=self._headers(),
                                params=params, json=json)
        except httpx.HTTPError as e:
            raise GitError(f"לא ניתן להגיע ל-{self.host}.",
                           status=502, detail=str(e), kind="network")
        if r.status_code not in allow:
            try:
                payload = r.json()
            except ValueError:
                payload = r.text
            raise describe(r.status_code, payload)
        if r.status_code == 204 or not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            raise GitError("הספק החזיר תשובה שאינה JSON.", status=502, kind="provider")

    def _paged(self, path: str, params: dict | None = None, limit: int = 50) -> list[dict]:
        """One page, sized to the caller's need. GitHub's Link header is the only paging signal that
        exists on every endpoint, and the office asks for "the first N", never for a full crawl."""
        per = max(1, min(100, limit))
        p = dict(params or {})
        p["per_page"] = per
        out = self._req("GET", path, params=p)
        if isinstance(out, list):
            return out
        return []

    # ── identity ────────────────────────────────────────────────────────────────────────────────
    def whoami(self) -> dict:
        if self.kind == "app":
            return self._whoami_app()
        r = self._c.request("GET", f"{self.api}/user", headers=self._headers())
        if r.status_code != 200:
            try:
                payload = r.json()
            except ValueError:
                payload = r.text
            raise describe(r.status_code, payload)
        me = r.json()
        scopes = r.headers.get("x-oauth-scopes")
        # A fine-grained token sends NO scope header. Empty is therefore "unknown", never "no
        # permissions" — the difference decides whether the UI promises repo creation.
        scopes_list = [s.strip() for s in scopes.split(",") if s.strip()] if scopes else None
        caps = {"createRepo": "unknown", "deleteRepo": "unknown", "writeContents": "unknown"}
        if scopes_list is not None:
            caps = {
                "createRepo": True,
                "deleteRepo": "delete_repo" in scopes_list,
                "writeContents": "repo" in scopes_list or "public_repo" in scopes_list,
                "webhooks": "admin:repo_hook" in scopes_list or "write:repo_hook" in scopes_list,
            }
        return {"login": me.get("login"), "name": me.get("name"), "id": me.get("id"),
                "type": me.get("type"), "scopes": scopes_list, "capabilities": caps,
                "auth_kind": "classic-pat" if scopes_list is not None else "fine-grained-or-app",
                "base_url": self.base_url}

    def _whoami_app(self) -> dict:
        """A GitHub App installation token has no /user — it identifies an APP and an INSTALLATION.

        Asking /user here returns 403 "Resource not accessible by integration", which would read as
        "your token is broken" for a credential that is working perfectly. So the probe asks the
        question this credential can actually answer.
        """
        app = self._req("GET", "/app")
        login = self.cred.login_hint
        instal = {}
        try:
            items = self._req("GET", "/app/installations")
            instal = (items or [{}])[0] if isinstance(items, list) and items else {}
            login = login or (instal.get("account") or {}).get("login")
        except GitError:
            pass
        return {"login": f"{app.get('slug') or app.get('name')} → {login}" if login
                else (app.get("slug") or app.get("name")),
                "name": app.get("name"), "id": app.get("id"), "type": "app",
                "scopes": None,
                "capabilities": {"createRepo": "unknown", "deleteRepo": "unknown",
                                 "writeContents": "unknown"},
                "auth_kind": "github-app",
                "expires_in": self.cred.expires_in,
                "base_url": self.base_url,
                "note": "GitHub App: ההרשאות נקבעות בהתקנה, וטוקן ההתקנה מונפק מחדש בכל שעה."}

    # ── repositories ────────────────────────────────────────────────────────────────────────────
    def list_repos(self, limit: int = 50, search: str = "") -> dict:
        if self.kind == "app":
            # An installation token cannot use /user/repos; the App's own endpoint is the answer.
            raw = self._req("GET", "/installation/repositories", params={"per_page": min(100, limit)})
            return {"repos": [norm_repo(x, "github", self.host)
                              for x in ((raw or {}).get("repositories") or [])][:limit], "total": None}
        if search:
            raw = self._paged("/search/repositories", {"q": search}, limit=limit)
            items = [norm_repo(x, "github", self.host)
                     for x in ((raw if isinstance(raw, list) else raw.get("items")) or [])]
            return {"repos": items[:limit], "total": None, "paging": "search"}
        raw = self._paged("/user/repos",
                          {"affiliation": "owner,collaborator,organization_member",
                           "sort": "pushed"}, limit=limit)
        return {"repos": [norm_repo(x, "github", self.host) for x in raw], "total": None}

    def get_repo(self, repo: str) -> dict:
        raw = self._req("GET", f"/repos/{repo}")
        out = norm_repo(raw, "github", self.host)
        out["permissions"] = raw.get("permissions") or {}
        out["fork"] = bool(raw.get("fork"))
        out["has_issues"] = bool(raw.get("has_issues", True))
        return out

    def create_repo(self, name: str, *, owner: str = "", private: bool = True,
                    description: str = "", readme: bool = True, license_key: str = "",
                    gitignore: str = "", default_branch: str = "") -> dict:
        owner = (owner or self.default_namespace or "").strip().strip("/")
        body: dict = {"name": name, "description": description, "private": bool(private),
                      "auto_init": bool(readme)}
        if license_key:
            body["license_template"] = license_key
        if gitignore:
            body["gitignore_template"] = gitignore
        if default_branch and readme:
            body["default_branch"] = default_branch
        path = f"/orgs/{owner}/repos" if owner and owner != self._login() else "/user/repos"
        raw = self._req("POST", path, json=body)
        out = norm_repo(raw, "github", self.host)
        out["initialized"] = bool(readme)
        out["namespace"] = owner or (raw.get("owner") or {}).get("login")
        out["applied"] = "native"
        out["note"] = ("המאגר נוצר עם README" if readme else "המאגר נוצר ריק") + \
                      (" וכולל .gitignore" if gitignore else "") + \
                      (" ורשיון" if license_key else "") + "."
        return out

    def delete_repo(self, repo: str) -> dict:
        self._req("DELETE", f"/repos/{repo}", allow=(204, 202))
        return {"deleted": repo, "mode": "immediate",
                "note": "המחיקה ב-GitHub מיידית ובלתי הפיכה."}

    # ── branches, commits, files ────────────────────────────────────────────────────────────────
    def list_branches(self, repo: str, limit: int = 50) -> dict:
        raw = self._paged(f"/repos/{repo}/branches", None, limit=limit)
        return {"branches": [{"name": b.get("name"),
                              "sha": (b.get("commit") or {}).get("sha"),
                              "protected": bool(b.get("protected"))} for b in raw]}

    def _ref_sha(self, repo: str, ref: str) -> str:
        raw = self._req("GET", f"/repos/{repo}/git/ref/heads/{ref}")
        return ((raw.get("object") or {}).get("sha")) or ""

    def create_branch(self, repo: str, name: str, from_ref: str = "") -> dict:
        base = from_ref or (self.get_repo(repo).get("default_branch") or "main")
        sha = self._ref_sha(repo, base)
        if not sha:
            raise GitError(f"לא נמצא הענף {base} במאגר.", status=404, kind="input")
        self._req("POST", f"/repos/{repo}/git/refs",
                  json={"ref": f"refs/heads/{name}", "sha": sha})
        return {"branch": name, "from": base, "sha": sha}

    def list_commits(self, repo: str, ref: str = "", path: str = "", limit: int = 20) -> dict:
        params = {"path": path} if path else {}
        if ref:
            params["sha"] = ref
        raw = self._paged(f"/repos/{repo}/commits", params, limit=limit)
        return {"commits": [{"sha": c.get("sha"),
                             "message": ((c.get("commit") or {}).get("message") or "").strip(),
                             "author": (((c.get("commit") or {}).get("author") or {}).get("name")
                                        or (c.get("author") or {}).get("login")),
                             "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
                             "url": c.get("html_url")} for c in raw]}

    def list_dir(self, repo: str, path: str = "", ref: str = "") -> dict:
        """The entries of ONE directory, for the app's own file browser.

        `get_file` refuses a directory on purpose (a caller that asked for a file must not receive an
        array), so the listing gets its own op. The SAME endpoint answers both — GitHub returns a list
        for a directory and an object for a file — and a file path therefore comes back as a
        one-entry listing rather than an error: the caller asked "what is here", and answering
        "this" is truthful.
        """
        p = (path or "").strip("/")
        params = {"ref": ref} if ref else {}
        raw = self._req("GET", f"/repos/{repo}/contents" + (f"/{p}" if p else ""), params=params)
        if isinstance(raw, dict):
            raw = [raw]
        return {"path": p, "ref": ref or None,
                "entries": [self._entry(x) for x in raw if isinstance(x, dict)]}

    @staticmethod
    def _entry(x: dict) -> dict:
        return {"name": x.get("name"), "path": x.get("path"),
                "type": "dir" if x.get("type") == "dir" else "file",
                "size": x.get("size"), "sha": x.get("sha")}

    def get_file(self, repo: str, path: str, ref: str = "") -> dict:
        params = {"ref": ref} if ref else {}
        raw = self._req("GET", f"/repos/{repo}/contents/{path}", params=params)
        if isinstance(raw, list):
            raise GitError(f"{path} הוא תיקייה, לא קובץ.", status=400, kind="input")
        content = unb64(raw.get("content") or "") if raw.get("encoding") != "none" else ""
        return {"path": path, "ref": ref or None, "sha": raw.get("sha"),
                "size": raw.get("size"), "content": content,
                "encoding": "utf-8", "truncated": raw.get("encoding") == "none",
                "url": raw.get("html_url")}

    def put_file(self, repo: str, path: str, content: str, message: str, branch: str = "",
                 sha: str = "") -> dict:
        cur: dict = {}
        try:
            cur = self.get_file(repo, path, branch)
        except GitError as e:
            if e.status != 404:
                raise
        body = {"message": message or f"Update {path}", "content": b64(content)}
        if branch:
            body["branch"] = branch
        existing = sha or cur.get("sha")
        if existing:
            body["sha"] = existing
        raw = self._req("PUT", f"/repos/{repo}/contents/{path}", json=body, allow=(200, 201))
        commit = raw.get("commit") or {}
        return {"path": path, "sha": (raw.get("content") or {}).get("sha"),
                "commit": commit.get("sha"), "commit_url": commit.get("html_url"),
                "created": not existing, "applied": "native"}

    # ── issues ──────────────────────────────────────────────────────────────────────────────────
    def list_issues(self, repo: str, state: str = "open", labels: str = "",
                    limit: int = 30) -> dict:
        params = {"state": state or "open"}
        if labels:
            params["labels"] = labels
        raw = self._paged(f"/repos/{repo}/issues", params, limit=limit)
        # GitHub returns PULL REQUESTS from /issues too. Dropping them here rather than in the caller
        # is the whole point of a canonical layer: a "issue list" that silently contains PRs is a bug
        # every consumer would otherwise have to know about.
        items = [self._norm_issue(i) for i in raw if "pull_request" not in i]
        return {"issues": items}

    @staticmethod
    def _norm_issue(i: dict) -> dict:
        return {"id": i.get("number"), "kind": "issue", "title": i.get("title"),
                "body": i.get("body") or "", "state": i.get("state"),
                "state_reason": i.get("state_reason"),
                "labels": [l.get("name") for l in (i.get("labels") or [])],
                "author": (i.get("user") or {}).get("login"),
                "comments": i.get("comments"), "url": i.get("html_url"),
                "created_at": i.get("created_at"), "updated_at": i.get("updated_at")}

    def create_issue(self, repo: str, title: str, body: str = "", labels=None,
                     assignees=None) -> dict:
        payload: dict = {"title": title, "body": body or ""}
        if labels:
            payload["labels"] = labels if isinstance(labels, list) else \
                [s.strip() for s in str(labels).split(",") if s.strip()]
        if assignees:
            payload["assignees"] = assignees if isinstance(assignees, list) else \
                [s.strip() for s in str(assignees).split(",") if s.strip()]
        raw = self._req("POST", f"/repos/{repo}/issues", json=payload)
        return self._norm_issue(raw)

    def update_issue(self, repo: str, number: int, *, title: str = "", body: str = "",
                     state: str = "", labels=None) -> dict:
        payload: dict = {}
        if title:
            payload["title"] = title
        if body:
            payload["body"] = body
        if state in ("open", "closed"):
            payload["state"] = state
            if state == "closed":
                payload["state_reason"] = "completed"
        if labels is not None:
            payload["labels"] = labels if isinstance(labels, list) else \
                [s.strip() for s in str(labels).split(",") if s.strip()]
        if not payload:
            raise GitError("לא צוין מה לשנות ב-issue.", status=400, kind="input")
        raw = self._req("PATCH", f"/repos/{repo}/issues/{number}", json=payload)
        return self._norm_issue(raw)

    def comment_issue(self, repo: str, number: int, body: str) -> dict:
        raw = self._req("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body})
        return {"id": raw.get("id"), "body": raw.get("body"),
                "author": (raw.get("user") or {}).get("login"), "url": raw.get("html_url")}

    # ── pull requests ───────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_pr(p: dict) -> dict:
        head = p.get("head") or {}
        return {"id": p.get("number"), "kind": "pr", "title": p.get("title"),
                "body": p.get("body") or "", "state": p.get("state"),
                "draft": bool(p.get("draft")), "merged": bool(p.get("merged")),
                "source_branch": head.get("ref"), "source_sha": head.get("sha"),
                "target_branch": (p.get("base") or {}).get("ref"),
                "author": (p.get("user") or {}).get("login"),
                "mergeable": p.get("mergeable"),
                "merge_state": p.get("mergeable_state"),
                "labels": [l.get("name") for l in (p.get("labels") or [])],
                "url": p.get("html_url"), "created_at": p.get("created_at"),
                "updated_at": p.get("updated_at")}

    def list_prs(self, repo: str, state: str = "open", limit: int = 30) -> dict:
        raw = self._paged(f"/repos/{repo}/pulls", {"state": state or "open"}, limit=limit)
        return {"pulls": [self._norm_pr(p) for p in raw], "noun": "PR"}

    def get_pr(self, repo: str, number: int) -> dict:
        return self._norm_pr(self._req("GET", f"/repos/{repo}/pulls/{number}"))

    def create_pr(self, repo: str, title: str, head: str, base: str, body: str = "",
                  draft: bool = False) -> dict:
        payload = {"title": title, "head": head, "base": base, "body": body or ""}
        if draft:
            payload["draft"] = True
        out = self._norm_pr(self._req("POST", f"/repos/{repo}/pulls", json=payload))
        out["applied"] = "native"
        return out

    def merge_pr(self, repo: str, number: int, method: str = "merge",
                 commit_title: str = "", commit_message: str = "") -> dict:
        payload: dict = {"merge_method": method if method in ("merge", "squash", "rebase")
                         else "merge"}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        raw = self._req("PUT", f"/repos/{repo}/pulls/{number}/merge", json=payload)
        return {"merged": bool(raw.get("merged")), "sha": raw.get("sha"),
                "message": raw.get("message"), "method_applied": method, "applied": "native"}

    def comment_pr(self, repo: str, number: int, body: str) -> dict:
        raw = self._req("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body})
        return {"id": raw.get("id"), "body": raw.get("body"), "url": raw.get("html_url")}

    def submit_review(self, repo: str, number: int, verdict: str, body: str = "") -> dict:
        event = {"approve": "APPROVE", "request_changes": "REQUEST_CHANGES",
                 "comment": "COMMENT"}.get(verdict)
        if not event:
            raise GitError("verdict חייב להיות approve | request_changes | comment.",
                           status=400, kind="input")
        raw = self._req("POST", f"/repos/{repo}/pulls/{number}/reviews",
                        json={"event": event, "body": body or ""})
        return {"review_id": raw.get("id"), "state": (raw.get("state") or "").lower(),
                "author": (raw.get("user") or {}).get("login"),
                "applied": "native", "blocks_merge": event == "REQUEST_CHANGES"}

    # ── releases ────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_release(r: dict) -> dict:
        return {"id": r.get("id"), "tag": r.get("tag_name"), "name": r.get("name"),
                "body": r.get("body") or "", "draft": bool(r.get("draft")),
                "prerelease": bool(r.get("prerelease")),
                "published_at": r.get("published_at"), "created_at": r.get("created_at"),
                "author": (r.get("author") or {}).get("login"), "url": r.get("html_url"),
                "tarball_url": r.get("tarball_url")}

    def list_releases(self, repo: str, limit: int = 20) -> dict:
        raw = self._paged(f"/repos/{repo}/releases", None, limit=limit)
        return {"releases": [self._norm_release(r) for r in raw]}

    def create_release(self, repo: str, tag: str, *, name: str = "", body: str = "",
                       target: str = "", publish: bool = True, prerelease: bool = False) -> dict:
        payload: dict = {"tag_name": tag, "name": name or tag, "body": body or "",
                         "draft": not publish, "prerelease": bool(prerelease)}
        if target:
            payload["target_commitish"] = target
        out = self._norm_release(self._req("POST", f"/repos/{repo}/releases", json=payload))
        out["applied"] = "native"
        return out

    def delete_release(self, repo: str, tag: str) -> dict:
        rel = self._req("GET", f"/repos/{repo}/releases/tags/{tag}")
        self._req("DELETE", f"/repos/{repo}/releases/{rel.get('id')}", allow=(204,))
        return {"deleted": tag, "note": "התג נשאר במאגר — מחיקת release אינה מוחקת את התג."}

    # ── helpers ─────────────────────────────────────────────────────────────────────────────────
    def _login(self) -> str:
        me = getattr(self, "_me", None)
        if not me:
            me = self.whoami().get("login") or ""
            self._me = me
        return me
