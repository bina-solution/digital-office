"""git.adapters.gitlab — the GitLab adapter (gitlab.com, and self-managed instances).

REST v4, and the differences from GitHub are not cosmetic — each one below is a place where the
obvious GitHub-shaped implementation is WRONG here:

  * a project's identity is its URL-encoded full path (`group%2Fsub%2Fproj`), and groups nest, so the
    namespace is an opaque multi-segment string;
  * an issue's state is changed with `state_event: close|reopen`, not by writing `state`;
  * issues are OPENED (`state=opened`), not `open`;
  * there is no review object (approve/unapprove + notes instead), and no draft or prerelease on a
    release — so those ops report `applied: "approximated"` instead of pretending;
  * creating a project with a README/LICENSE/.gitignore is NOT one call (no `license_template` /
    `gitignore_template`), so the templates are fetched and committed in one `actions[]` commit;
  * `write_repository` authenticates git-over-HTTPS but NOT the API — only `api` does.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from credentials import CredentialError, credential_for
from credentials import normalize_host as credential_host

from .base import GitError, describe, norm_repo, split_repo, unb64

UA = "bina-office-git/0.1 (+digital-office)"


class GitLabAdapter:
    provider = "gitlab"

    def __init__(self, secret: dict, cid: str | None = None):
        self.secret = secret or {}
        self.cid = cid
        # Personal / group / project access tokens, OAuth (with refresh) and deploy tokens all land
        # here as one credential — see credentials.py.
        try:
            self.cred = credential_for("gitlab", self.secret, cid)
        except CredentialError as e:
            raise GitError(e.he_message, status=e.status, detail=e.detail, kind="account")
        self.kind = self.cred.kind
        self.host = credential_host("gitlab", self.secret.get("host") or "")
        self.api = f"https://{self.host}/api/v4"
        self.base_url = f"https://{self.host}"
        if not self.cred.api_usable:
            # A deploy token is a legitimate choice — it clones and pushes — but it cannot call the
            # API at all, so say that in the first sentence instead of letting every op 401.
            raise GitError("חיבור ה-Deploy token מאפשר קוד (clone/push) בלבד ואינו תומך ב-API של "
                           "GitLab. לפעולות API חבר טוקן אישי/קבוצה/פרויקט עם scope api.",
                           status=400, kind="account")
        self.default_namespace = (self.secret.get("namespace") or "").strip().strip("/")
        self._c = httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=False)

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        return dict(self.cred.api_headers)

    def _req(self, method: str, path: str, *, params=None, json=None, allow=(200, 201, 202, 204)):
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
        p = dict(params or {})
        p["per_page"] = max(1, min(100, limit))
        out = self._req("GET", path, params=p)
        return out if isinstance(out, list) else []

    @staticmethod
    def _enc(project: str) -> str:
        """A project's id on the wire is its full path, URL-encoded — slashes included."""
        return quote((project or "").strip().strip("/").removesuffix(".git"), safe="")

    # ── identity ────────────────────────────────────────────────────────────────────────────────
    def whoami(self) -> dict:
        me = self._req("GET", "/user")
        scopes = None
        try:
            if self.kind in ("project_token", "deploy_token"):
                # A project access token IS a bot and cannot introspect itself; asking produces a
                # 403 that reads like a broken credential. Skip the question, keep the answer honest.
                raise GitError("not introspectable", status=403)
            tok = self._req("GET", "/personal_access_tokens/self")
            scopes = tok.get("scopes") or []
        except GitError as e:
            # A project/group access token is a BOT and cannot introspect itself. That is a fact
            # about the account, not a failure of the probe: record "unknown" and let the UI say so.
            if e.status not in (401, 403, 404):
                raise
        caps = {"createRepo": "unknown", "deleteRepo": "unknown", "writeContents": "unknown"}
        if scopes is not None:
            caps = {"createRepo": "api" in scopes, "deleteRepo": "api" in scopes,
                    "writeContents": "api" in scopes}
        return {"login": me.get("username"), "name": me.get("name"), "id": me.get("id"),
                "type": "bot" if me.get("bot") else "user", "scopes": scopes,
                "capabilities": caps,
                "auth_kind": ("bot-token" if me.get("bot")
                              else "pat" if scopes is not None else "unknown"),
                "base_url": self.base_url,
                "note": ("טוקן של פרויקט/קבוצה: אינו יכול ליצור פרויקטים או לראות אחרים."
                         if me.get("bot") else None)}

    # ── namespaces ──────────────────────────────────────────────────────────────────────────────
    def _namespace_id(self, namespace: str) -> int | None:
        """Resolve `group/sub` (or a user) to the numeric id `POST /projects` wants."""
        if not namespace:
            return None
        for ep, key in (("/namespaces", "id"), ("/groups", "id")):
            try:
                found = self._req("GET", ep, params={"search": namespace})
            except GitError:
                continue
            for n in (found if isinstance(found, list) else []):
                full = n.get("full_path") or n.get("path") or n.get("name")
                if full == namespace:
                    return n.get(key)
        raise GitError(f"לא נמצא namespace בשם {namespace} בחשבון הזה.", status=404, kind="input")

    # ── repositories ────────────────────────────────────────────────────────────────────────────
    def list_repos(self, limit: int = 50, search: str = "") -> dict:
        params = {"membership": "true", "order_by": "last_activity_at", "simple": "true"}
        if search:
            params["search"] = search
        raw = self._paged("/projects", params, limit=limit)
        return {"repos": [norm_repo(x, "gitlab", self.host) for x in raw], "total": None}

    def get_repo(self, repo: str) -> dict:
        raw = self._req("GET", f"/projects/{self._enc(repo)}")
        out = norm_repo(raw, "gitlab", self.host)
        out["permissions"] = raw.get("permissions") or {}
        out["empty"] = bool(raw.get("empty_repo"))
        out["fork"] = bool(raw.get("forked_from_project"))
        return out

    def create_repo(self, name: str, *, owner: str = "", private: bool = True,
                    description: str = "", readme: bool = True, license_key: str = "",
                    gitignore: str = "", default_branch: str = "") -> dict:
        ns = (owner or self.default_namespace or "").strip().strip("/")
        body: dict = {"name": name, "path": name, "description": description,
                      "visibility": "private" if private else "public",
                      "initialize_with_readme": bool(readme)}
        if ns:
            body["namespace_id"] = self._namespace_id(ns)
        if default_branch:
            body["default_branch"] = default_branch
        raw = self._req("POST", "/projects", json=body)
        out = norm_repo(raw, "gitlab", self.host)
        out["namespace"] = ns or out.get("owner")
        note_bits = ["הפרויקט נוצר"]
        if readme:
            note_bits.append("עם README")
        # GitLab has no template parameters on project creation. Rather than silently dropping the
        # request, fetch the templates and land them in ONE commit (`actions[]` is the GitLab
        # equivalent of the whole GitHub trees/blobs/commits dance).
        extra = []
        if license_key:
            txt = self._template("/templates/licenses/", license_key)
            if txt:
                extra.append({"action": "create", "file_path": "LICENSE", "content": txt})
        if gitignore:
            txt = self._template("/templates/gitignores/", gitignore)
            if txt:
                extra.append({"action": "create", "file_path": ".gitignore", "content": txt})
        if extra:
            self._req("POST", f"/projects/{self._enc(out['full_name'])}/repository/commits",
                      json={"branch": out.get("default_branch") or default_branch or "main",
                            "commit_message": "Add license and .gitignore",
                            "actions": extra})
            note_bits.append("וכולל " + " ו".join([".gitignore" if a["file_path"] == ".gitignore"
                                                   else "רשיון" for a in extra]))
        out["initialized"] = bool(readme)
        out["applied"] = "native"
        if (license_key or gitignore) and not extra:
            out["applied"] = "approximated"
            note_bits.append("— אך תבניות הרשיון/.gitignore לא נמצאו ב-GitLab ולא צורפו")
        out["note"] = " ".join(note_bits) + "."
        return out

    def _template(self, path: str, key: str) -> str:
        try:
            raw = self._req("GET", f"{path}{quote(key, safe='')}")
        except GitError:
            return ""
        return raw.get("content") or ""

    def delete_repo(self, repo: str) -> dict:
        self._req("DELETE", f"/projects/{self._enc(repo)}", allow=(202, 204))
        return {"deleted": repo, "mode": "scheduled", "permanent_requires_admin": True,
                "note": "ב-GitLab המחיקה מדורגת (30 יום כברירת מחדל) ומחיקה סופית דורשת אדמין."}

    # ── branches, commits, files ────────────────────────────────────────────────────────────────
    def list_branches(self, repo: str, limit: int = 50) -> dict:
        enc = self._enc(repo)
        raw = self._paged(f"/projects/{enc}/repository/branches", None, limit=limit)
        protected = set()
        try:
            for b in self._req("GET", f"/projects/{enc}/protected_branches") or []:
                protected.add(b.get("name"))
        except GitError:
            pass
        out = []
        for b in raw:
            name = b.get("name")
            is_prot = bool(b.get("protected")) or name in protected or \
                any(p and p.endswith("*") and name.startswith(p[:-1]) for p in protected)
            out.append({"name": name, "sha": (b.get("commit") or {}).get("id"),
                        "protected": is_prot, "default": bool(b.get("default"))})
        return {"branches": out}

    def create_branch(self, repo: str, name: str, from_ref: str = "") -> dict:
        base = from_ref or (self.get_repo(repo).get("default_branch") or "main")
        raw = self._req("POST", f"/projects/{self._enc(repo)}/repository/branches",
                        params={"branch": name, "ref": base})
        return {"branch": raw.get("name") or name, "from": base,
                "sha": (raw.get("commit") or {}).get("id")}

    def list_commits(self, repo: str, ref: str = "", path: str = "", limit: int = 20) -> dict:
        params = {}
        if ref:
            params["ref_name"] = ref
        if path:
            params["path"] = path
        raw = self._paged(f"/projects/{self._enc(repo)}/repository/commits", params, limit=limit)
        return {"commits": [{"sha": c.get("id"), "message": (c.get("message") or "").strip(),
                             "author": c.get("author_name"), "date": c.get("authored_date"),
                             "url": c.get("web_url")} for c in raw]}

    def list_dir(self, repo: str, path: str = "", ref: str = "") -> dict:
        """The entries of ONE directory (the app's file browser).

        GitLab has a REAL tree endpoint (`/repository/tree`), not the contents endpoint the other two
        use, and it says `tree`/`blob` where they say `dir`/`file` — normalized here, so a caller never
        learns which provider it is talking to. A full page reports `truncated` rather than quietly
        handing back a short directory.
        """
        p = (path or "").strip("/")
        params: dict = {"per_page": 100}
        if p:
            params["path"] = p
        if ref:
            params["ref"] = ref
        raw = self._req("GET", f"/projects/{self._enc(repo)}/repository/tree", params=params)
        entries = [{"name": x.get("name"), "path": x.get("path"),
                    "type": "dir" if x.get("type") == "tree" else "file",
                    "size": None, "sha": x.get("id")} for x in (raw or [])]
        return {"path": p, "ref": ref or None, "entries": entries,
                "truncated": len(entries) >= 100}

    def get_file(self, repo: str, path: str, ref: str = "") -> dict:
        params = {"ref": ref} if ref else {}
        enc_path = quote((path or "").lstrip("/"), safe="")
        raw = self._req("GET", f"/projects/{self._enc(repo)}/repository/files/{enc_path}",
                        params=params)
        return {"path": raw.get("file_path") or path, "ref": ref or None,
                "sha": raw.get("last_commit_id"), "blob_id": raw.get("blob_id"),
                "size": raw.get("size"), "content": unb64(raw.get("content") or ""),
                "encoding": "utf-8", "truncated": False}

    def put_file(self, repo: str, path: str, content: str, message: str, branch: str = "",
                 sha: str = "") -> dict:
        enc = self._enc(repo)
        enc_path = quote((path or "").lstrip("/"), safe="")
        ref = branch or (self.get_repo(repo).get("default_branch") or "main")
        existing = {}
        try:
            existing = self.get_file(repo, path, ref)
        except GitError as e:
            if e.status != 404:
                raise
        body = {"branch": ref, "content": content,
                "encoding": "text", "commit_message": message or f"Update {path}"}
        if existing:
            body["last_commit_id"] = sha or existing.get("blob_id") or existing.get("sha")
            raw = self._req("PUT", f"/projects/{enc}/repository/files/{enc_path}", json=body)
            created = False
        else:
            raw = self._req("POST", f"/projects/{enc}/repository/files/{enc_path}", json=body)
            created = True
        return {"path": raw.get("file_path") or path, "sha": raw.get("last_commit_id"),
                "commit": raw.get("commit_id"), "created": created, "applied": "native"}

    # ── issues ──────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_issue(i: dict) -> dict:
        return {"id": i.get("iid"), "kind": "issue", "title": i.get("title"),
                "body": i.get("description") or "", "state": i.get("state"),
                "state_reason": None,
                "labels": list(i.get("labels") or []), "author": (i.get("author") or {}).get("username"),
                "comments": i.get("user_notes_count"), "url": i.get("web_url"),
                "confidential": bool(i.get("confidential")),
                "created_at": i.get("created_at"), "updated_at": i.get("updated_at")}

    def list_issues(self, repo: str, state: str = "open", labels: str = "",
                    limit: int = 30) -> dict:
        # `opened`, not `open`: GitLab's own spelling, and `open` is silently ignored.
        params = {"state": {"open": "opened", "closed": "closed", "all": "all"}.get(state, "opened")}
        if labels:
            params["labels"] = labels
        raw = self._paged(f"/projects/{self._enc(repo)}/issues", params, limit=limit)
        return {"issues": [self._norm_issue(i) for i in raw]}

    def create_issue(self, repo: str, title: str, body: str = "", labels=None,
                     assignees=None) -> dict:
        payload: dict = {"title": title, "description": body or ""}
        if labels:
            payload["labels"] = ",".join(labels) if isinstance(labels, list) else str(labels)
        raw = self._req("POST", f"/projects/{self._enc(repo)}/issues", json=payload)
        out = self._norm_issue(raw)
        if assignees:
            out["note"] = ("שיוך משתמשים ב-GitLab מחייב מזהי משתמש (assignee_ids); "
                           "השיוך לא בוצע.")
        return out

    def update_issue(self, repo: str, number: int, *, title: str = "", body: str = "",
                     state: str = "", labels=None) -> dict:
        payload: dict = {}
        if title:
            payload["title"] = title
        if body:
            payload["description"] = body
        if state in ("open", "closed"):
            # `state_event`, NOT `state` — writing `state` here is accepted and does nothing.
            payload["state_event"] = "close" if state == "closed" else "reopen"
        if labels is not None:
            payload["labels"] = ",".join(labels) if isinstance(labels, list) else str(labels)
        if not payload:
            raise GitError("לא צוין מה לשנות ב-issue.", status=400, kind="input")
        raw = self._req("PUT", f"/projects/{self._enc(repo)}/issues/{number}", json=payload)
        return self._norm_issue(raw)

    def comment_issue(self, repo: str, number: int, body: str) -> dict:
        raw = self._req("POST", f"/projects/{self._enc(repo)}/issues/{number}/notes",
                        json={"body": body})
        return {"id": raw.get("id"), "body": raw.get("body"),
                "author": (raw.get("author") or {}).get("username"), "url": None}

    # ── merge requests ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_pr(m: dict) -> dict:
        return {"id": m.get("iid"), "kind": "pr", "title": m.get("title"),
                "body": m.get("description") or "", "state": m.get("state"),
                "draft": bool(m.get("draft")), "merged": m.get("state") == "merged" or
                bool(m.get("merged_at")),
                "source_branch": m.get("source_branch"), "source_sha": m.get("sha"),
                "target_branch": m.get("target_branch"),
                "author": (m.get("author") or {}).get("username"),
                "mergeable": (m.get("detailed_merge_status") in (None, "mergeable")),
                "merge_state": m.get("detailed_merge_status") or m.get("merge_status"),
                "labels": list(m.get("labels") or []), "url": m.get("web_url"),
                "created_at": m.get("created_at"), "updated_at": m.get("updated_at")}

    def list_prs(self, repo: str, state: str = "open", limit: int = 30) -> dict:
        params = {"state": {"open": "opened", "closed": "closed", "merged": "merged",
                            "all": "all"}.get(state, "opened")}
        raw = self._paged(f"/projects/{self._enc(repo)}/merge_requests", params, limit=limit)
        return {"pulls": [self._norm_pr(m) for m in raw], "noun": "MR"}

    def get_pr(self, repo: str, number: int) -> dict:
        return self._norm_pr(self._req("GET", f"/projects/{self._enc(repo)}/merge_requests/{number}"))

    def create_pr(self, repo: str, title: str, head: str, base: str, body: str = "",
                  draft: bool = False) -> dict:
        payload = {"source_branch": head, "target_branch": base, "title": title,
                   "description": body or ""}
        if draft:
            # GitLab derives draft from the TITLE; there is no `draft` field to set.
            payload["title"] = title if title.lower().startswith("draft:") else f"Draft: {title}"
        out = self._norm_pr(self._req("POST", f"/projects/{self._enc(repo)}/merge_requests",
                                      json=payload))
        out["applied"] = "native"
        if draft:
            out["note"] = "הטיוטא ב-GitLab מסומנת בקידומת Draft: בשם ה-MR."
        return out

    def merge_pr(self, repo: str, number: int, method: str = "merge",
                 commit_title: str = "", commit_message: str = "") -> dict:
        enc = self._enc(repo)
        payload: dict = {}
        if commit_message:
            payload["merge_commit_message"] = commit_message
        if method == "squash":
            payload["squash"] = True
        raw = self._req("PUT", f"/projects/{enc}/merge_requests/{number}/merge", json=payload,
                        allow=(200, 201))
        out = {"merged": (raw or {}).get("state") == "merged" or bool((raw or {}).get("merge_commit_sha")),
               "sha": (raw or {}).get("merge_commit_sha") or (raw or {}).get("sha"),
               "message": (raw or {}).get("title")}
        if method in ("merge", "rebase"):
            # The merge METHOD is a project setting on GitLab, not a per-call argument — so say so
            # rather than reporting the requested method as if it had been applied.
            out["method_applied"] = None
            out["applied"] = "approximated"
            out["note"] = ("שיטת המיזוג ב-GitLab היא הגדרה של הפרויקט (merge_method); "
                           "הבקשה לא משנה אותה.")
        else:
            out["method_applied"] = "squash"
            out["applied"] = "native"
        return out

    def comment_pr(self, repo: str, number: int, body: str) -> dict:
        raw = self._req("POST", f"/projects/{self._enc(repo)}/merge_requests/{number}/notes",
                        json={"body": body})
        return {"id": raw.get("id"), "body": raw.get("body"), "url": None}

    def submit_review(self, repo: str, number: int, verdict: str, body: str = "") -> dict:
        """GitLab has no review object. APPROVE maps to the approval endpoint; anything else is a
        note plus (for request_changes) the absence of an approval — which only blocks a merge when
        the project actually requires approvals."""
        enc = self._enc(repo)
        if verdict == "approve":
            try:
                self._req("POST", f"/projects/{enc}/merge_requests/{number}/approve",
                          json={"sha": ""}, allow=(200, 201))
                return {"state": "approved", "applied": "native", "blocks_merge": False,
                        "note": "אישור ה-MR ב-GitLab דורש הרשאת approvals (Premium ב-gitlab.com)."}
            except GitError as e:
                if e.status not in (401, 403, 404):
                    raise
                if body:
                    self.comment_pr(repo, number, body)
                return {"state": "commented", "applied": "approximated", "blocks_merge": False,
                        "note": "לחשבון אין הרשאת approvals — נרשמה תגובה במקום אישור."}
        if body:
            self.comment_pr(repo, number, body)
        return {"state": "commented", "applied": "approximated",
                "blocks_merge": verdict == "request_changes",
                "note": ("אין ב-GitLab בקשת שינויים: נרשמה תגובה, והמיזוג ייחסם רק אם "
                         "הפרויקט דורש אישורים.")}

    # ── releases ────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_release(r: dict) -> dict:
        return {"id": r.get("tag_name"), "tag": r.get("tag_name"), "name": r.get("name"),
                "body": r.get("description") or "",
                "draft": bool(r.get("upcoming_release")),
                "prerelease": False, "published_at": r.get("released_at"),
                "created_at": r.get("created_at"),
                "author": (r.get("author") or {}).get("username"),
                "url": (r.get("_links") or {}).get("self"), "tarball_url": None}

    def list_releases(self, repo: str, limit: int = 20) -> dict:
        raw = self._paged(f"/projects/{self._enc(repo)}/releases", None, limit=limit)
        return {"releases": [self._norm_release(r) for r in raw]}

    def create_release(self, repo: str, tag: str, *, name: str = "", body: str = "",
                       target: str = "", publish: bool = True, prerelease: bool = False) -> dict:
        payload: dict = {"tag_name": tag, "name": name or tag, "description": body or ""}
        if target:
            payload["ref"] = target
        out = self._norm_release(self._req("POST", f"/projects/{self._enc(repo)}/releases",
                                           json=payload))
        if not publish:
            out["applied"] = "approximated"
            out["note"] = "ל-GitLab אין release טיוטא — ה-release נוצר מפורסם."
        else:
            out["applied"] = "native"
        if prerelease:
            out["note"] = (out.get("note", "") + " אין סימון prerelease ב-GitLab.").strip()
        return out

    def delete_release(self, repo: str, tag: str) -> dict:
        self._req("DELETE", f"/projects/{self._enc(repo)}/releases/{quote(tag, safe='')}",
                  allow=(200, 202, 204))
        return {"deleted": tag, "note": "התג נשאר במאגר — מחיקת release אינה מוחקת את התג."}
