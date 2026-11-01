"""The test network through its HTTP API — the reference `api` adapter.

It is deliberately a REAL network client (requests against `/fixture/api/...`, even though the
server is this same app): the point is to exercise exactly the path a Graph-API adapter takes —
serialise, send, parse, read back — not a function call that could never fail the way a platform
does.
"""
from __future__ import annotations

import base64
import os

import requests

import media as media_mod
from adapters.base import SocialAdapter, SocialError, clip

TIMEOUT = 20


class FixtureApiAdapter(SocialAdapter):
    kind = "api"

    def __init__(self, platform: dict, secret: dict, account: dict | None = None):
        super().__init__(platform, secret, account)
        base = (os.environ.get("SOCIAL_FIXTURE_URL") or "").rstrip("/")
        self.base = base or (os.environ.get("SOCIAL_LIST_URL", "http://social-list:8986").rstrip("/")
                             + "/fixture")

    def _call(self, method: str, path: str, **kw):
        try:
            r = requests.request(method, f"{self.base}/api/{path}", timeout=TIMEOUT, **kw)
        except requests.RequestException as e:
            raise SocialError("רשת הבדיקה אינה זמינה", status=502,
                              detail=str(e)[:300]) from e
        if r.status_code >= 400:
            raise SocialError(f"רשת הבדיקה החזירה {r.status_code}", status=502,
                              detail=r.text[:300])
        return r.json() if r.content else {}

    def get_profile(self) -> dict:
        p = self._call("GET", "profile")
        return {"name": p.get("name"), "handle": p.get("handle"), "bio": p.get("bio"),
                "links": p.get("links") or [], "avatar_url": p.get("avatar_url"),
                "banner_url": p.get("banner_url"), "url": p.get("url"), "extra": {}}

    def update_profile(self, changes: dict) -> dict:
        spec = (self.platform.get("profile") or {})
        limits = spec.get("fields") or {}
        body, verify = {}, {}
        for k in ("name", "bio", "handle"):
            if k in changes:
                body[k] = clip(changes[k], (limits.get(k) or {}).get("max_len"))
        if "links" in changes:
            body["links"] = list(changes["links"] or [])
        for k in ("avatar", "banner"):
            if changes.get(k):
                data, mime = media_mod.rendition(media_mod.Media(changes[k]), spec.get(k),
                                                 prefer_png=(k == "avatar"))
                body[k] = {"data_base64": base64.b64encode(data).decode(), "mime": mime}
        before = self.get_profile()
        self._call("PATCH", "profile", json=body)
        after = self.get_profile()
        for k in ("name", "bio", "handle"):
            if k in body:
                verify[k] = self.verified(body[k], after.get(k))
        if "links" in body:
            verify["links"] = self.verified(",".join(body["links"]), ",".join(after.get("links") or []))
        for k in ("avatar", "banner"):
            if k in body:
                changed = bool(after.get(f"{k}_url")) and after.get(f"{k}_url") != before.get(f"{k}_url")
                verify[k] = {"expected": "תמונה חדשה", "read_back": after.get(f"{k}_url"),
                             "match": changed}
        ok = all(v.get("match") for v in verify.values())
        return {"state": "ok" if ok else "assert_failed", "verify": verify, "url": after.get("url"),
                "before": {k: before.get(k) for k in ("name", "bio", "handle")},
                "after": {k: after.get(k) for k in ("name", "bio", "handle")}}

    def list_posts(self, limit: int = 10) -> list[dict]:
        out = []
        for p in (self._call("GET", "posts", params={"limit": limit}).get("posts") or [])[:limit]:
            out.append({"id": p["id"], "text": p.get("text"), "url": p.get("url"),
                        "created_at": p.get("created_at"), "media": p.get("media") or [],
                        "counts": {"likes": p.get("likes", 0),
                                   "comments": len(p.get("comments") or [])}})
        return out

    def create_post(self, post: dict) -> dict:
        limit = next((t.get("text_max") for t in self.platform.get("posts") or []
                      if t.get("id") == "text"), None)
        text = clip(post.get("text") or "", limit)
        media = []
        for m in post.get("media") or []:
            mm = media_mod.Media(m)
            if mm.kind != "image":
                raise self.refuse("post.create.video")
            data, mime = media_mod.rendition(mm, {"w": 1200, "h": 1200})
            media.append({"data_base64": base64.b64encode(data).decode(), "mime": mime})
        created = self._call("POST", "posts", json={"text": text, "media": media})
        pid = created.get("id")
        back = next((p for p in self.list_posts(20) if p["id"] == pid), None)
        return {"state": "ok" if back else "assert_failed", "id": pid,
                "url": (back or {}).get("url"),
                "verify": {"text": self.verified(text, (back or {}).get("text"))}}

    def update_post(self, post_id: str, changes: dict) -> dict:
        text = changes.get("text") or ""
        self._call("PATCH", f"posts/{post_id}", json={"text": text})
        back = next((p for p in self.list_posts(50) if p["id"] == post_id), None)
        return {"state": "ok" if back and back.get("text") == text else "assert_failed",
                "id": post_id, "verify": {"text": self.verified(text, (back or {}).get("text"))}}

    def delete_post(self, post_id: str) -> dict:
        self._call("DELETE", f"posts/{post_id}")
        gone = not any(p["id"] == post_id for p in self.list_posts(50))
        return {"state": "ok" if gone else "assert_failed", "id": post_id,
                "verify": {"gone": {"expected": True, "read_back": gone, "match": gone}}}

    def list_comments(self, post_id: str, limit: int = 20) -> list[dict]:
        return (self._call("GET", f"posts/{post_id}/comments").get("comments") or [])[:limit]

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        c = self._call("POST", f"posts/{post_id}/comments", json={"text": text, "reply_to": reply_to})
        return {"state": "ok", "id": c.get("id")}

    def delete_comment(self, comment_id: str) -> dict:
        self._call("DELETE", f"comments/{comment_id}")
        return {"state": "ok", "id": comment_id}

    def react(self, target_id: str, reaction: str = "like") -> dict:
        p = self._call("POST", f"posts/{target_id}/like")
        return {"state": "ok", "id": target_id, "counts": {"likes": p.get("likes")}}

    def insights(self) -> dict:
        return self._call("GET", "insights")
