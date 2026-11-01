"""GitHub through its API — a personal or organization profile, and posts as Discussions / Releases.

secret: {token, org?, repo?}   (`org` set → the organization's profile; `repo` = "owner/name" is where
posts go: an Announcements discussion by default, or a Release when the post names a `tag`).

What the API cannot do, said once: the avatar and a repository's social-preview image have no
endpoint (research/platforms.md §2) — those two are the browser kind's, and the refusal says so.
"""
from __future__ import annotations

import time

from adapters.base import SocialAdapter, clip
from adapters.http import call

API = "https://api.github.com"
GQL = "https://api.github.com/graphql"


class GitHubAdapter(SocialAdapter):
    kind = "api"

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.secret.get('token', '')}",
                "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    def _get(self, path: str, **kw):
        return call("GET", API + path, "GitHub", headers=self._h(), **kw)

    def _gql(self, query: str, variables: dict) -> dict:
        out = call("POST", GQL, "GitHub", headers=self._h(), json={"query": query, "variables": variables})
        if (out or {}).get("errors"):
            from adapters.base import SocialError
            raise SocialError(f"GitHub: {out['errors'][0].get('message', 'שגיאת GraphQL')}",
                              status=400, kind="rejected")
        return (out or {}).get("data") or {}

    def _repo(self) -> tuple[str, str]:
        repo = (self.secret.get("repo") or "").strip()
        if "/" not in repo:
            raise self.refuse("post.create.text", why="לא הוגדר מאגר לפרסום (repo = owner/name)")
        o, n = repo.split("/", 1)
        return o, n

    # ── profile ─────────────────────────────────────────────────────────────────────────────────
    def get_profile(self) -> dict:
        org = self.secret.get("org")
        p = self._get(f"/orgs/{org}") if org else self._get("/user")
        return {"name": p.get("name"), "handle": p.get("login"),
                "bio": p.get("description") if org else p.get("bio"),
                "links": [x for x in [p.get("blog")] if x], "avatar_url": p.get("avatar_url"),
                "banner_url": None, "url": p.get("html_url"),
                "extra": {"followers": p.get("followers"), "public_repos": p.get("public_repos")}}

    def update_profile(self, changes: dict) -> dict:
        org = self.secret.get("org")
        for f in ("avatar", "banner", "handle"):
            if f in changes:
                raise self.refuse(f"profile.update.{f}")
        body = {}
        if "name" in changes:
            body["name"] = str(changes["name"] or "")
        if "bio" in changes:
            body["description" if org else "bio"] = clip(str(changes["bio"] or ""), 160)
        if "links" in changes:
            body["blog"] = (changes["links"] or [""])[0]
        call("PATCH", API + (f"/orgs/{org}" if org else "/user"), "GitHub", headers=self._h(), json=body)
        after = self.get_profile()
        verify = {}
        if "name" in body:
            verify["name"] = self.verified(body["name"], after.get("name"))
        if "bio" in changes:
            verify["bio"] = self.verified(body.get("description", body.get("bio")), after.get("bio"))
        if "blog" in body:
            verify["links"] = self.verified(body["blog"], (after.get("links") or [""])[0])
        ok = all(v["match"] for v in verify.values())
        return {"state": "ok" if ok else "assert_failed", "verify": verify, "url": after.get("url")}

    # ── posts: discussions (default) and releases ────────────────────────────────────────────────
    def list_posts(self, limit: int = 10) -> list[dict]:
        o, n = self._repo()
        data = self._gql("""query($o:String!,$n:String!,$k:Int!){repository(owner:$o,name:$n){
            discussions(first:$k, orderBy:{field:CREATED_AT, direction:DESC}){nodes{
              id title body url createdAt comments{totalCount} reactions{totalCount}}}}}""",
                         {"o": o, "n": n, "k": min(limit, 50)})
        nodes = (((data.get("repository") or {}).get("discussions") or {}).get("nodes")) or []
        return [{"id": f"discussion:{d['id']}", "text": f"{d['title']}\n\n{d['body']}".strip(),
                 "url": d["url"], "created_at": d["createdAt"], "media": [],
                 "counts": {"likes": d["reactions"]["totalCount"],
                            "comments": d["comments"]["totalCount"]}} for d in nodes]

    def create_post(self, post: dict) -> dict:
        o, n = self._repo()
        text = (post.get("text") or "").strip()
        title = (post.get("title") or text.split("\n", 1)[0])[:120] or "עדכון"
        if post.get("tag"):                                   # a release, when a tag is named
            rel = call("POST", f"{API}/repos/{o}/{n}/releases", "GitHub", headers=self._h(),
                       json={"tag_name": post["tag"], "name": title, "body": text})
            return {"state": "ok", "id": f"release:{rel['id']}", "url": rel.get("html_url"),
                    "verify": {"text": self.verified(title, rel.get("name"))}}
        repo = self._gql("""query($o:String!,$n:String!){repository(owner:$o,name:$n){id
            discussionCategories(first:25){nodes{id slug name}}}}""", {"o": o, "n": n})["repository"]
        cats = (repo.get("discussionCategories") or {}).get("nodes") or []
        if not cats:
            raise self.refuse("post.create.text", why="Discussions כבויים במאגר — הפעילו אותם בהגדרות")
        want = post.get("category") or "announcements"
        cat = next((c for c in cats if c["slug"] == want), cats[0])
        d = self._gql("""mutation($r:ID!,$c:ID!,$t:String!,$b:String!){createDiscussion(input:
            {repositoryId:$r,categoryId:$c,title:$t,body:$b}){discussion{id url title}}}""",
                      {"r": repo["id"], "c": cat["id"], "t": title, "b": text or title})
        disc = d["createDiscussion"]["discussion"]
        return {"state": "ok", "id": f"discussion:{disc['id']}", "url": disc["url"],
                "verify": {"text": self.verified(title, disc["title"])}}

    def update_post(self, post_id: str, changes: dict) -> dict:
        kind, _, pid = post_id.partition(":")
        text = changes.get("text") or ""
        if kind == "release":
            o, n = self._repo()
            rel = call("PATCH", f"{API}/repos/{o}/{n}/releases/{pid}", "GitHub", headers=self._h(),
                       json={"body": text})
            return {"state": "ok", "id": post_id, "url": rel.get("html_url")}
        d = self._gql("""mutation($i:ID!,$b:String!){updateDiscussion(input:{discussionId:$i,body:$b})
            {discussion{url body}}}""", {"i": pid, "b": text})["updateDiscussion"]["discussion"]
        return {"state": "ok", "id": post_id, "url": d["url"],
                "verify": {"text": self.verified(text, d["body"])}}

    def delete_post(self, post_id: str) -> dict:
        kind, _, pid = post_id.partition(":")
        if kind == "release":
            o, n = self._repo()
            call("DELETE", f"{API}/repos/{o}/{n}/releases/{pid}", "GitHub", headers=self._h())
        else:
            self._gql("mutation($i:ID!){deleteDiscussion(input:{id:$i}){discussion{id}}}", {"i": pid})
        return {"state": "ok", "id": post_id}

    def list_comments(self, post_id: str, limit: int = 20) -> list[dict]:
        _, _, pid = post_id.partition(":")
        d = self._gql("""query($i:ID!,$k:Int!){node(id:$i){... on Discussion{comments(first:$k){nodes{
            id body url createdAt author{login}}}}}}""", {"i": pid, "k": min(limit, 50)})
        nodes = (((d.get("node") or {}).get("comments") or {}).get("nodes")) or []
        return [{"id": c["id"], "text": c["body"], "url": c["url"], "created_at": c["createdAt"],
                 "author": (c.get("author") or {}).get("login")} for c in nodes]

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        _, _, pid = post_id.partition(":")
        c = self._gql("""mutation($i:ID!,$b:String!){addDiscussionComment(input:{discussionId:$i,body:$b})
            {comment{id url}}}""", {"i": pid, "b": text})["addDiscussionComment"]["comment"]
        return {"state": "ok", "id": c["id"], "url": c["url"]}

    def delete_comment(self, comment_id: str) -> dict:
        self._gql("mutation($i:ID!){deleteDiscussionComment(input:{id:$i}){comment{id}}}",
                  {"i": comment_id})
        return {"state": "ok", "id": comment_id}

    def react(self, target_id: str, reaction: str = "like") -> dict:
        _, _, pid = target_id.partition(":")
        self._gql("mutation($i:ID!){addReaction(input:{subjectId:$i,content:THUMBS_UP}){reaction{content}}}",
                  {"i": pid or target_id})
        return {"state": "ok", "id": target_id}

    def insights(self) -> dict:
        p = self.get_profile()
        return {"followers": (p.get("extra") or {}).get("followers"),
                "public_repos": (p.get("extra") or {}).get("public_repos"), "at": int(time.time())}
