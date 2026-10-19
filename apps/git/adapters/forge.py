"""git.adapters.forgejo — the office's OWN forge (Forgejo / Gitea, REST v1).

A third adapter is not a copy of the other two: the calls below are the ones that fail SILENTLY when
written the GitHub- or GitLab-shaped way.

  * the credential is `Authorization: token <token>` — a bare value, not `Bearer`, not
    `PRIVATE-TOKEN` — and the base URL is a plain in-network origin (`http://forge:3000`), not an
    `api.*` hostname: there is no TLS here, no api-version header, and the API root is `/api/v1`;
  * the payloads are GitHub-SHAPED (`full_name`, `html_url`, `clone_url`, `owner.login`, `private`,
    `default_branch`, `archived`), which is exactly why the office's normalized repo shape is reused
    verbatim — but `visibility` does not exist on this API at all (`private` and `internal` do);
  * an issue's state IS `state` (`open`/`closed`) — the GitLab `state_event` dance does not exist —
    while LABELS are label IDs, not names, and are not part of the issue-edit payload at all;
  * `GET /repos/{o}/{r}/issues` also returns PULL REQUESTS, marked by a non-null `pull_request`;
  * a PR comment IS an issue comment: it is posted to `/issues/{index}/comments`;
  * `POST /pulls` has NO `draft` field — a draft is a prefix on the title;
  * the merge POST answers with an EMPTY 200: the status IS the confirmation, so reading a `merged`
    field off the body would report every successful merge as a failure;
  * reviews are REAL here (`POST /pulls/{index}/reviews`, APPROVE / REQUEST_CHANGES) — this is the
    one place the provider is natively richer than GitLab, which had to approximate;
  * `PUT /contents/{path}` WITHOUT `sha` creates a NEW file and is refused on an existing one, so a
    stale sha is the classic 409; and `delete_repo` is IMMEDIATE (GitLab's is deferred ~30 days),
    while `delete_release` leaves the git tag behind — the same trap as every other provider.

The credential plumbing for this provider is intentionally LOCAL to this adapter: a Forgejo
credential is a plain access token — nothing to mint, nothing to refresh, no OAuth round trip and no
App installation — so the token is read straight from the secret. (credentials.py resolves the same
secret for git-over-HTTPS through the proxy; the API needs exactly the one header built below, so
this module deliberately does not depend on that entry.)
"""
from __future__ import annotations

import os
from urllib.parse import quote

import httpx

from .base import GitError, b64, describe, split_repo, unb64

UA = "bina-office-git/0.1 (+digital-office)"
DEFAULT_BASE = "http://forge:3000"
_MAX_PAGES = 10                     # a listing is "the first N", never a full crawl
_LABEL_COLOR = "#ededed"            # the colour a label gets when this office creates it

# The office's merge vocabulary → Forgejo's `Do`. The provider also knows `rebase-merge` (a rebase
# that always leaves a merge commit), `fast-forward-only` and `manually-merged`; the office's three
# names are what GitHub's merge_method calls, and those three are what map 1:1.
_MERGE_DO = {"merge": "merge", "squash": "squash", "rebase": "rebase"}


class ForgejoAdapter:
    provider = "forgejo"

    def __init__(self, secret: dict, cid: str | None = None):
        self.secret = secret or {}
        self.cid = cid
        # One plain access token — see the module docstring for why this is not a `credential_for`
        # call. The token itself never leaves this attribute and is never put in a returned payload.
        self._token = (self.secret.get("token") or "").strip()
        if not self._token:
            raise GitError("בחשבון הפורג' המקומי אין טוקן שמור — יש להריץ שוב את "
                           "apps/git/hooks/prepare כדי להנפיק טוקן, או להדביק טוקן של המשתמש "
                           "במסך „גיט”.",
                           status=400, kind="account")
        # The forge is reached IN-NETWORK as an origin (`http://forge:3000`), so the caller-supplied
        # `base_url` (or FORGE_URL) IS the API root's parent — there is nothing to derive.
        self.base_url = (self.secret.get("base_url") or os.environ.get("FORGE_URL")
                         or DEFAULT_BASE).strip().rstrip("/")
        # Every normalized payload carries a `host`. This forge has no TLS hostname, so the authority
        # of the base URL is the honest label (`forge:3000`) rather than an empty string.
        self.host = self.base_url.split("://", 1)[-1].strip("/")
        self.api = f"{self.base_url}/api/v1"
        self._c = httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=False)

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        return {"Authorization": f"token {self._token}", "Accept": "application/json",
                "User-Agent": UA}

    def _req(self, method: str, path: str, *, params=None, json=None, allow=(200, 201, 202, 204)):
        try:
            r = self._c.request(method, f"{self.api}{path}", headers=self._headers(),
                                params=params, json=json)
        except httpx.HTTPError as e:
            raise GitError(f"לא ניתן להגיע לפורג' בכתובת {self.base_url}.",
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
            raise GitError("הפורג' החזיר תשובה שאינה JSON.", status=502, kind="provider")

    def _paged(self, path: str, params: dict | None = None, limit: int = 50) -> list[dict]:
        """`page`/`limit` are the only paging controls here (not `per_page`), and the answer is a
        bare JSON array.

        A page that comes back SHORT is the end of the list — but a page that comes back FULL means
        more exist, so this walks pages until the caller's `limit` is satisfied instead of handing
        back one page and calling it the whole answer (the failure mode gate G36 was written for).
        """
        out: list[dict] = []
        want = max(1, int(limit))
        page = 1
        while len(out) < want and page <= _MAX_PAGES:
            per = min(50, want - len(out))
            chunk = self._req("GET", path, params={**(params or {}), "page": page, "limit": per})
            if not isinstance(chunk, list) or not chunk:
                break
            out.extend(chunk)
            if len(chunk) < per:
                break
            page += 1
        return out[:want]

    @staticmethod
    def _repo_path(repo: str) -> str:
        """`owner/name` → `/repos/{owner}/{name}`.

        Unlike GitLab, the namespace is NOT one opaque path segment: this API addresses a repository
        as two path parameters, so the two halves are quoted separately.
        """
        owner, name = split_repo(repo)
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    @staticmethod
    def _file_path(path: str) -> str:
        """A file path IS one opaque segment sequence: slashes are kept, everything else is quoted."""
        return quote((path or "").lstrip("/"), safe="/")

    # ── identity ────────────────────────────────────────────────────────────────────────────────
    def whoami(self) -> dict:
        raw = self._req("GET", "/user")
        admin = bool(raw.get("is_admin"))
        return {"login": raw.get("login"), "name": raw.get("full_name") or raw.get("login"),
                "email": raw.get("email"), "id": raw.get("id"), "type": "user", "admin": admin,
                # A Forgejo token cannot introspect its own scopes (there is no self-token endpoint,
                # and /user does not report them), so "unknown" is the honest answer — the same
                # answer a fine-grained GitHub token gets. Do not turn it into "none".
                "scopes": None,
                "capabilities": {"createRepo": "unknown", "deleteRepo": "unknown",
                                 "writeContents": "unknown"},
                "auth_kind": "pat", "base_url": self.base_url,
                "note": ("חשבון admin בפורג' המקומי — יכול ליצור משתמשים, ארגונים וטוקנים."
                         if admin else None)}

    def _login(self) -> str:
        me = getattr(self, "_me", None)
        if not me:
            me = self.whoami().get("login") or ""
            self._me = me
        return me

    # ── repositories ────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_repo(raw: dict, host: str) -> dict:
        """Forgejo's repo payload is GitHub-shaped, so the office's repo shape is reused verbatim —
        with one derivation: this API has no `visibility` field, it has `private` AND `internal`
        (an instance-wide repository that is not private), so visibility is computed from the two."""
        private = bool(raw.get("private"))
        return {
            "id": raw.get("id"), "name": raw.get("name"), "full_name": raw.get("full_name"),
            "owner": (raw.get("owner") or {}).get("login"),
            "description": raw.get("description") or "",
            "private": private,
            "visibility": "private" if private
                          else ("internal" if raw.get("internal") else "public"),
            "default_branch": raw.get("default_branch"),
            "clone_url": raw.get("clone_url"), "web_url": raw.get("html_url"),
            "archived": bool(raw.get("archived")), "provider": "forgejo", "host": host,
        }

    def list_repos(self, limit: int = 50, search: str = "") -> dict:
        """The account's own repositories.

        `GET /user/repos` does not document a `q` filter (the instance-wide `/repos/search` does, and
        that one is deliberately not used: it answers with OTHER people's repositories). `q` is sent
        anyway — it costs nothing where it is ignored — and the result is filtered here as well, so
        the search is never a silent no-op whichever way the instance behaves.
        """
        params: dict = {}
        if search:
            params["q"] = search
        raw = self._paged("/user/repos", params, limit=limit)
        repos = [self._norm_repo(r, self.host) for r in raw]
        if search:
            needle = search.lower()
            repos = [r for r in repos if needle in (r.get("full_name") or "").lower()
                     or needle in (r.get("description") or "").lower()]
        return {"repos": repos, "count": len(repos), "total": None}

    def get_repo(self, repo: str) -> dict:
        raw = self._req("GET", self._repo_path(repo))
        out = self._norm_repo(raw, self.host)
        out["permissions"] = raw.get("permissions") or {}
        out["empty"] = bool(raw.get("empty"))
        out["fork"] = bool(raw.get("fork"))
        # Mirror-ness is part of the record here (a Forgejo repository can BE the mirror), so it is
        # reported rather than left for the caller to guess from a separate endpoint.
        out["mirror"] = bool(raw.get("mirror"))
        out["original_url"] = raw.get("original_url") or None
        out["has_issues"] = bool(raw.get("has_issues", True))
        return out

    def create_repo(self, name: str, *, owner: str = "", private: bool = True,
                    description: str = "", readme: bool = False, gitignore: str = "",
                    license: str = "", default_branch: str = "", license_key: str = "") -> dict:
        """Create a repository — with its README, .gitignore and license — in ONE call (unlike
        GitLab, which needs a follow-up commit; the templates are Forgejo's own parameters).

        Two details that are not obvious from the parameter names:

          * `auto_init` is what makes the templates apply at all. Asking for a `.gitignore` or a
            license without initializing the repository is accepted and then silently ignored, so
            `auto_init` is raised to true whenever a template was asked for — and the note says so.
          * `readme` is a TEMPLATE NAME on this API (`"Default"`), not a boolean.

        `license_key` is accepted as an alias for `license` because the office's own `createRepo`
        dispatcher passes that spelling; `license` is the canonical name of the canonical op.
        """
        template_key = (license or license_key or "").strip()
        auto_init = bool(readme or gitignore or template_key)
        body: dict = {"name": name, "private": bool(private), "description": description,
                      "auto_init": auto_init,
                      "default_branch": default_branch,
                      "gitignores": gitignore or "",
                      "license": template_key,
                      "readme": "Default" if readme else ""}
        ns = (owner or "").strip().strip("/")
        # A personal namespace cannot be addressed as an organisation: `POST /orgs/{user}/repos`
        # 404s. So `owner` is routed by what it names, not by whether it was given.
        if ns and ns != self._login():
            path = f"/orgs/{quote(ns, safe='')}/repos"
        else:
            path = "/user/repos"
        raw = self._req("POST", path, json=body)
        out = self._norm_repo(raw, self.host)
        out["initialized"] = auto_init
        out["namespace"] = ns or out.get("owner")
        out["applied"] = "native"
        bits = ["המאגר נוצר" + (" עם README" if readme else "")]
        if gitignore:
            bits.append("וכולל .gitignore")
        if template_key:
            bits.append("ורשיון")
        if auto_init and not readme:
            bits.append("— הוא אותחל כדי שתבניות ה-.gitignore/הרשיון יחולו, "
                        "כי בלעדי אתחול הפורג' מתעלם מהן")
        out["note"] = " ".join(bits) + "."
        return out

    def delete_repo(self, repo: str) -> dict:
        """Delete a repository.

        This is IMMEDIATE and irreversible — the GitLab adapter's `mode: "scheduled"` (a 30-day
        recovery window, permanent removal by an admin) has no equivalent here. The record says so,
        because the difference decides whether a caller dares ask twice.
        """
        self._req("DELETE", self._repo_path(repo), allow=(200, 202, 204))
        return {"deleted": repo, "mode": "immediate",
                "note": "מחיקת מאגר בפורג' היא מיידית ובלתי הפיכה."}

    # ── branches, commits, files ────────────────────────────────────────────────────────────────
    def list_branches(self, repo: str, limit: int = 50) -> dict:
        rp = self._repo_path(repo)
        raw = self._paged(f"{rp}/branches", None, limit=limit)
        # A Forgejo branch carries no "this is the default" flag; the repository does. Comparing
        # against it keeps the normalized shape the callers already read.
        try:
            default = self._req("GET", rp).get("default_branch")
        except GitError:
            default = None
        return {"branches": [{"name": b.get("name"), "sha": (b.get("commit") or {}).get("id"),
                              "protected": bool(b.get("protected")),
                              "default": b.get("name") == default} for b in raw]}

    def create_branch(self, repo: str, name: str, from_ref: str = "") -> dict:
        base = from_ref or (self.get_repo(repo).get("default_branch") or "main")
        raw = self._req("POST", f"{self._repo_path(repo)}/branches",
                        json={"new_branch_name": name, "old_branch_name": base})
        return {"branch": (raw or {}).get("name") or name, "from": base,
                "sha": ((raw or {}).get("commit") or {}).get("id")}

    def list_commits(self, repo: str, ref: str = "", path: str = "", limit: int = 20) -> dict:
        params: dict = {}
        if ref:
            params["sha"] = ref
        if path:
            params["path"] = path
        raw = self._paged(f"{self._repo_path(repo)}/commits", params, limit=limit)
        return {"commits": [{"sha": c.get("sha"),
                             "message": (((c.get("commit") or {}).get("message")) or "").strip(),
                             "author": (((c.get("commit") or {}).get("author") or {}).get("name")
                                        or (c.get("author") or {}).get("login")),
                             "date": ((c.get("commit") or {}).get("author") or {}).get("date")
                                     or c.get("created"),
                             "url": c.get("html_url")} for c in raw]}

    def list_dir(self, repo: str, path: str = "", ref: str = "") -> dict:
        """The entries of ONE directory — and the one place Forgejo is RICHER than the others: every
        entry carries its last commit (sha + date), which is what a GitHub-shaped file list shows in
        its right-hand column. The path segment is OMITTED for the root: `…/contents/` with a trailing
        slash is not the same request as `…/contents`, and only the latter lists the root.
        """
        p = (path or "").strip("/")
        params = {"ref": ref} if ref else {}
        url = f"{self._repo_path(repo)}/contents" + (f"/{self._file_path(p)}" if p else "")
        raw = self._req("GET", url, params=params)
        if isinstance(raw, dict):
            raw = [raw]
        return {"path": p, "ref": ref or None,
                "entries": [{"name": x.get("name"), "path": x.get("path"),
                             "type": "dir" if x.get("type") == "dir" else "file",
                             "size": x.get("size"), "sha": x.get("sha"),
                             "last_commit": x.get("last_commit_sha"),
                             "updated": x.get("last_commit_when")}
                            for x in raw if isinstance(x, dict)]}

    def get_file(self, repo: str, path: str, ref: str = "") -> dict:
        params = {"ref": ref} if ref else {}
        raw = self._req("GET", f"{self._repo_path(repo)}/contents/{self._file_path(path)}",
                        params=params)
        # A DIRECTORY answers 200 with an ARRAY of entries — decoding that as a file would produce a
        # bytes object printed at the caller, so it is refused here with the reason.
        if isinstance(raw, list):
            raise GitError(f"{path} הוא תיקייה, לא קובץ.", status=400, kind="input")
        content = raw.get("content") or ""
        size = raw.get("size")
        return {"path": raw.get("path") or path, "ref": ref or None, "sha": raw.get("sha"),
                "size": size, "content": unb64(content), "encoding": "utf-8",
                # No content alongside a real size = the instance withheld the blob (its own size
                # limit), NOT an empty file. Saying "truncated" is the difference between "the file
                # is empty" and "ask the git side for it".
                "truncated": not content and bool(size),
                "type": raw.get("type"), "url": raw.get("html_url")}

    def put_file(self, repo: str, path: str, content: str, message: str, branch: str = "",
                 sha: str = "") -> dict:
        """Write ONE file through the API.

        CREATE and UPDATE are two different ENDPOINTS here (POST vs PUT), not one verb with an
        optional sha the way GitHub does it. Measured against forgejo 16.0.5, because the difference
        is invisible until it fails:

            POST …/contents/<path>            → 201, creates the file. No sha.
            PUT  …/contents/<path> without sha → 422 "[SHA]: Required"
            PUT  …/contents/<path> with sha    → 200, updates the file.

        So the sha picks the verb: a caller updating a file passes the sha it read from `getFile`,
        and a caller creating one passes nothing. A create that hits an existing file therefore gets
        Forgejo's own 409/422, which is translated here into the sentence that says what to do
        instead of leaving "Required" in front of a person.
        """
        body: dict = {"content": b64(content), "message": message or f"Update {path}"}
        if branch:
            body["branch"] = branch
        if sha:
            body["sha"] = sha
        verb = "PUT" if sha else "POST"
        try:
            raw = self._req(verb, f"{self._repo_path(repo)}/contents/{self._file_path(path)}",
                            json=body)
        except GitError as e:
            if not sha and e.status in (409, 422):
                raise GitError(
                    f"הקובץ {path} כבר קיים במאגר — כדי לעדכן אותו צריך לקרוא אותו קודם "
                    f"(getFile) ולשלוח את ה-sha שקיבלת.", status=409, kind="input",
                    provider_error=e.provider_error) from e
            raise
        raw = raw if isinstance(raw, dict) else {}
        commit = raw.get("commit") or {}
        blob = raw.get("content") or {}
        return {"path": blob.get("path") or path, "sha": blob.get("sha") or sha or None,
                "commit": commit.get("sha"), "commit_url": commit.get("html_url"),
                "created": not sha, "applied": "native"}

    # ── labels ──────────────────────────────────────────────────────────────────────────────────
    def _label_ids(self, repo: str, labels) -> tuple[list[int], list[str]]:
        """Label names → label IDs, plus the names that could not be resolved.

        This is the sharpest difference from GitHub in the whole issue surface: GitHub takes label
        NAMES and invents a missing one on the spot, Forgejo takes label IDs and has no such
        behaviour. A name that does not exist yet is therefore created here — silently DROPPING it
        would post an issue that looks labelled in the request and is unlabelled in the forge — and
        a name that could not even be created is returned to the caller to be reported, never
        swallowed.
        """
        names = (labels if isinstance(labels, list)
                 else [s.strip() for s in str(labels or "").split(",") if s.strip()])
        ids: list[int] = []
        want: list[str] = []
        for n in names:
            if isinstance(n, int) or (isinstance(n, str) and n.strip().isdigit()):
                ids.append(int(n))
            elif str(n).strip():
                want.append(str(n).strip())
        if not want:
            return ids, []
        rp = self._repo_path(repo)
        known: dict[str, int] = {}
        try:
            for lb in self._paged(f"{rp}/labels", None, limit=50):
                known[lb.get("name")] = lb.get("id")
        except GitError:
            # Labels are an ADDITION to the issue, not the issue: a repo whose label list cannot be
            # read still gets a correctly created issue, with the unresolved names reported.
            return ids, want
        unresolved: list[str] = []
        for name in want:
            lid = known.get(name)
            if lid is None:
                try:
                    created = self._req("POST", f"{rp}/labels",
                                        json={"name": name, "color": _LABEL_COLOR,
                                              "description": ""}, allow=(200, 201))
                    lid = (created or {}).get("id")
                except GitError:
                    lid = None
            if lid is None:
                unresolved.append(name)
            else:
                ids.append(lid)
        return ids, unresolved

    # ── issues ──────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_issue(i: dict) -> dict:
        return {"id": i.get("number"), "number": i.get("number"), "kind": "issue",
                "title": i.get("title"), "body": i.get("body") or "", "state": i.get("state"),
                # Forgejo has no close REASON (GitHub's `state_reason`); null, not a guess.
                "state_reason": None,
                "labels": [l.get("name") for l in (i.get("labels") or [])],
                "author": (i.get("user") or {}).get("login"),
                "comments": i.get("comments"), "url": i.get("html_url"),
                "created_at": i.get("created_at"), "updated_at": i.get("updated_at"),
                "provider": "forgejo"}

    def list_issues(self, repo: str, state: str = "open", labels: str = "",
                    limit: int = 30) -> dict:
        """Issues — with `type=issues`, and filtered again on the way out.

        `GET /repos/{o}/{r}/issues` is the same endpoint that serves PULL REQUESTS: without `type`
        a PR shows up in an issue list, marked only by a non-null `pull_request`. Both belts are
        worn because an instance that ignores the parameter must not turn a PR into an issue.
        """
        params: dict = {"state": state or "open", "type": "issues"}
        if labels:
            params["labels"] = labels
        raw = self._paged(f"{self._repo_path(repo)}/issues", params, limit=limit)
        return {"issues": [self._norm_issue(i) for i in raw if not i.get("pull_request")]}

    def create_issue(self, repo: str, title: str, body: str = "", labels=None,
                     assignees=None) -> dict:
        payload: dict = {"title": title, "body": body or ""}
        ids: list[int] = []
        unresolved: list[str] = []
        if labels:
            ids, unresolved = self._label_ids(repo, labels)
            if ids:
                payload["labels"] = ids
        if assignees:
            # The one place Forgejo is friendlier than GitLab: usernames are accepted directly.
            payload["assignees"] = (assignees if isinstance(assignees, list)
                                    else [s.strip() for s in str(assignees).split(",") if s.strip()])
        out = self._norm_issue(self._req("POST", f"{self._repo_path(repo)}/issues", json=payload))
        out["applied"] = "native"
        if unresolved:
            out["applied"] = "approximated"
            out["note"] = ("התוויות שלא נמצאו ולא נוצרו: " + ", ".join(unresolved) +
                           " — ה-issue נוצר בלעדיהן.")
        return out

    def update_issue(self, repo: str, number: int, *, title: str = "", body: str = "",
                     state: str = "", labels=None) -> dict:
        """Edit an issue.

        `state` is written DIRECTLY here (`open`/`closed`) — the GitLab adapter's `state_event` is
        accepted by this API as an unknown field and would do nothing. Labels are the other half:
        they are not a field of the issue-edit payload at all, so they are replaced by their own
        call (`PUT /issues/{index}/labels`) instead of being quietly left behind.
        """
        rp = self._repo_path(repo)
        payload: dict = {}
        if title:
            payload["title"] = title
        if body:
            payload["body"] = body
        if state in ("open", "closed"):
            payload["state"] = state
        if not payload and labels is None:
            raise GitError("לא צוין מה לשנות ב-issue.", status=400, kind="input")
        if payload:
            raw = self._req("PATCH", f"{rp}/issues/{number}", json=payload)
        else:
            raw = self._req("GET", f"{rp}/issues/{number}")
        out = self._norm_issue(raw if isinstance(raw, dict) else {})
        if labels is not None:
            ids, unresolved = self._label_ids(repo, labels)
            fresh = self._req("PUT", f"{rp}/issues/{number}/labels", json={"labels": ids})
            if isinstance(fresh, list):
                out["labels"] = [l.get("name") for l in fresh]
            out["applied"] = "native"
            if unresolved:
                out["applied"] = "approximated"
                out["note"] = ("התוויות שלא נמצאו ולא נוצרו: " + ", ".join(unresolved) + ".")
        return out

    def comment_issue(self, repo: str, number: int, body: str) -> dict:
        raw = self._req("POST", f"{self._repo_path(repo)}/issues/{number}/comments",
                        json={"body": body})
        return {"id": raw.get("id"), "body": raw.get("body"),
                "author": (raw.get("user") or {}).get("login"), "url": raw.get("html_url"),
                "provider": "forgejo"}

    # ── pull requests ───────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_pr(p: dict) -> dict:
        head = p.get("head") or {}
        base = p.get("base") or {}
        return {"id": p.get("number"), "number": p.get("number"), "kind": "pr",
                "title": p.get("title"), "body": p.get("body") or "", "state": p.get("state"),
                "draft": bool(p.get("draft")), "merged": bool(p.get("merged")),
                "mergeable": p.get("mergeable"),
                # Forgejo reports mergeability as one boolean and has no GitHub-style
                # `mergeable_state` string; null is the honest value for that key.
                "merge_state": None,
                # `head`/`base` are the branch NAMES in the office's shape; the provider's
                # PRBranchInfo objects are flattened into the canonical source/target keys below.
                "head": head.get("ref"), "base": base.get("ref"),
                "source_branch": head.get("ref"), "source_sha": head.get("sha"),
                "target_branch": base.get("ref"),
                "author": (p.get("user") or {}).get("login"),
                "labels": [l.get("name") for l in (p.get("labels") or [])],
                "comments": p.get("comments"), "url": p.get("html_url"),
                "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
                "provider": "forgejo"}

    def list_prs(self, repo: str, state: str = "open", limit: int = 30) -> dict:
        # `open`/`closed`/`all` are this API's own spellings (gitlab.py's `opened` and `merged`
        # are not) — `state=opened` here is simply an empty list, with no error to notice.
        params = {"state": state if state in ("open", "closed", "all") else "open"}
        raw = self._paged(f"{self._repo_path(repo)}/pulls", params, limit=limit)
        return {"pulls": [self._norm_pr(p) for p in raw], "noun": "PR"}

    def get_pr(self, repo: str, number: int) -> dict:
        return self._norm_pr(self._req("GET", f"{self._repo_path(repo)}/pulls/{number}"))

    def create_pr(self, repo: str, title: str, head: str, base: str, body: str = "",
                  draft: bool = False) -> dict:
        """Open a pull request.

        There is NO `draft` field on this API's create payload — a draft is a TITLE PREFIX (the same
        convention the web UI uses), so a draft request is reported as `approximated`: a caller who
        then looks for a real draft flag will not find one.
        """
        payload = {"title": title, "head": head, "base": base, "body": body or ""}
        out = self._norm_pr(self._req("POST", f"{self._repo_path(repo)}/pulls", json=payload))
        out["applied"] = "native"
        if draft:
            low = title.strip().lower()
            if not (low.startswith("draft:") or low.startswith("wip:")):
                out["note"] = ("ל-Forgejo אין שדה draft ביצירת PR — הטיוטא מסומנת בקידומת "
                               "Draft: בשם; ה-PR נוצר ללא הקידומת.")
            else:
                out["note"] = "הטיוטא מסומנת בקידומת בשם ה-PR (אין שדה draft ב-API)."
            out["applied"] = "approximated"
        return out

    def merge_pr(self, repo: str, number: int, method: str = "merge", commit_title: str = "",
                 commit_message: str = "", message: str = "") -> dict:
        """Merge a pull request.

        The success answer is an EMPTY 200 — the status code IS the confirmation, and a refusal is a
        405/409 with a body (what `describe` renders). So `merged: True` follows from the call
        returning at all; reading a `merged` field off the response would report every successful
        merge as a failure.

        `message` is the canonical op's name for the merge message; `commit_title`/`commit_message`
        are the positional pair the office's dispatcher passes (the same order gitlab.py takes).
        """
        do = _MERGE_DO.get(method, "merge")
        payload: dict = {"Do": do}
        title = commit_title or ""
        text = message or commit_message or ""
        if title:
            payload["MergeTitleField"] = title
        if text:
            payload["MergeMessageField"] = text
        rp = self._repo_path(repo)
        raw = self._req("POST", f"{rp}/pulls/{number}/merge", json=payload)
        out: dict = {"merged": True, "applied": "native", "method_applied": do,
                     "sha": (raw or {}).get("sha") if isinstance(raw, dict) else None,
                     "message": (raw or {}).get("message") if isinstance(raw, dict) else None}
        if method not in _MERGE_DO:
            out["applied"] = "approximated"
            out["method_applied"] = "merge"
            out["note"] = (f"שיטת המיזוג {method!r} אינה מוכרת ל-Forgejo — בוצע מיזוג merge "
                           "רגיל. האפשרויות: merge, squash, rebase.")
        return out

    def comment_pr(self, repo: str, number: int, body: str) -> dict:
        """Comment on a pull request.

        On this API a PR comment IS an issue comment — the pull request shares the issue index
        space, and there is no `/pulls/{index}/comments` endpoint at all. The comment therefore
        lands on the same thread the issue view shows, which is also where a human will look for it.
        """
        raw = self._req("POST", f"{self._repo_path(repo)}/issues/{number}/comments",
                        json={"body": body})
        return {"id": raw.get("id"), "body": raw.get("body"),
                "author": (raw.get("user") or {}).get("login"), "url": raw.get("html_url"),
                "kind": "issue-comment", "provider": "forgejo"}

    def submit_review(self, repo: str, number: int, verdict: str, body: str = "") -> dict:
        """Submit a real review.

        `approve` / `request_changes` / `comment` are NATIVE review states here — the provider has
        an actual review object with an APPROVE that blocks a merge, which is the opposite of GitLab
        (approvals are a Premium feature there, so gitlab.py had to approximate). A review with no
        body is what this API rejects with a 422: the sentence goes in `body`.
        """
        event = {"approve": "APPROVE", "request_changes": "REQUEST_CHANGES",
                 "comment": "COMMENT"}.get(verdict)
        if not event:
            raise GitError("verdict חייב להיות approve | request_changes | comment.",
                           status=400, kind="input")
        raw = self._req("POST", f"{self._repo_path(repo)}/pulls/{number}/reviews",
                        json={"event": event, "body": body or ""})
        raw = raw if isinstance(raw, dict) else {}
        return {"review_id": raw.get("id"),
                "state": (raw.get("state") or event).lower(),
                "author": (raw.get("user") or {}).get("login"),
                "applied": "native", "blocks_merge": event == "REQUEST_CHANGES",
                "provider": "forgejo"}

    # ── releases ────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _norm_release(r: dict) -> dict:
        return {"id": r.get("id"), "tag": r.get("tag_name"), "name": r.get("name"),
                "body": r.get("body") or "", "draft": bool(r.get("draft")),
                "prerelease": bool(r.get("prerelease")),
                "created_at": r.get("created_at"), "published_at": r.get("published_at"),
                "author": (r.get("author") or {}).get("login"), "url": r.get("html_url"),
                "tarball_url": r.get("tarball_url"), "provider": "forgejo"}

    def list_releases(self, repo: str, limit: int = 20) -> dict:
        raw = self._paged(f"{self._repo_path(repo)}/releases", None, limit=limit)
        return {"releases": [self._norm_release(r) for r in raw]}

    def create_release(self, repo: str, tag: str, *, name: str = "", body: str = "",
                       draft: bool | None = None, prerelease: bool = False, target: str = "",
                       publish: bool = True) -> dict:
        """Publish a release.

        `target_commitish`, `draft` and `prerelease` are all real fields here, so this is `native` —
        the opposite of GitLab, where a release has neither a draft nor a prerelease state.

        `draft` is the canonical op's argument; `publish` is the dispatcher's spelling and is only
        consulted when `draft` is left unset (`publish=False` ⇒ a draft), so neither caller can get
        an accidental published release.
        """
        is_draft = (not publish) if draft is None else bool(draft)
        payload: dict = {"tag_name": tag, "name": name or tag, "body": body or "",
                         "draft": is_draft, "prerelease": bool(prerelease)}
        if target:
            payload["target_commitish"] = target
        out = self._norm_release(self._req("POST", f"{self._repo_path(repo)}/releases",
                                           json=payload))
        out["applied"] = "native"
        return out

    def delete_release(self, repo: str, tag: str) -> dict:
        """Delete a release — and NOT its git tag.

        The release is looked up by tag first because the id is what the delete route takes here;
        the tag that the release pointed at stays in the repository, exactly as on GitHub and GitLab,
        so a caller who meant "remove the version" has one more call to make.
        """
        rp = self._repo_path(repo)
        rel = self._req("GET", f"{rp}/releases/tags/{quote(tag, safe='')}")
        rid = (rel or {}).get("id")
        if rid is None:
            raise GitError(f"לא נמצא release לתג {tag}.", status=404, kind="input")
        self._req("DELETE", f"{rp}/releases/{rid}", allow=(200, 202, 204))
        return {"deleted": tag, "id": rid, "tag_deleted": False,
                "note": "התג נשאר במאגר — מחיקת release אינה מוחקת את התג."}
