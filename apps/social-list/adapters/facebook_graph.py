"""A Facebook Page through the Graph API — the fullest official coverage of any platform.

secret: {page_id, page_token}. The page token must carry pages_manage_posts, pages_read_engagement
and pages_manage_metadata (research/platforms.md §3). The Page NAME is not writable through the API
(it is a reviewed request) — that refusal comes from the catalogue.
"""
from __future__ import annotations

import os

import media as media_mod
from adapters.base import SocialAdapter, clip
from adapters.http import call

VERSION = os.environ.get("SOCIAL_GRAPH_VERSION", "v23.0")
GRAPH = f"https://graph.facebook.com/{VERSION}"
FIELDS = "id,name,username,about,description,website,link,fan_count,followers_count,picture.type(large),cover"


class FacebookGraphAdapter(SocialAdapter):
    kind = "api"

    @property
    def pid_(self) -> str:
        return str(self.secret.get("page_id") or "")

    def _p(self, extra: dict | None = None) -> dict:
        return {"access_token": self.secret.get("page_token", ""), **(extra or {})}

    def get_profile(self) -> dict:
        p = call("GET", f"{GRAPH}/{self.pid_}", "פייסבוק", params=self._p({"fields": FIELDS}))
        return {"name": p.get("name"), "handle": p.get("username") or p.get("id"),
                "bio": p.get("about"), "links": [x for x in [p.get("website")] if x],
                "avatar_url": ((p.get("picture") or {}).get("data") or {}).get("url"),
                "banner_url": (p.get("cover") or {}).get("source"), "url": p.get("link"),
                "extra": {"followers": p.get("followers_count"), "fans": p.get("fan_count"),
                          "cover_id": (p.get("cover") or {}).get("id")}}

    def update_profile(self, changes: dict) -> dict:
        spec = self.platform.get("profile") or {}
        for f in ("name", "handle"):
            if f in changes:
                raise self.refuse(f"profile.update.{f}")
        before = self.get_profile()
        body = {}
        if "bio" in changes:
            body["about"] = clip(str(changes["bio"] or ""), 101)
        if "links" in changes:
            body["website"] = (changes["links"] or [""])[0]
        if body:
            call("POST", f"{GRAPH}/{self.pid_}", "פייסבוק", params=self._p(), data=body)
        if changes.get("avatar"):
            data, mime = media_mod.rendition(media_mod.Media(changes["avatar"]), spec.get("avatar"))
            call("POST", f"{GRAPH}/{self.pid_}/picture", "פייסבוק", params=self._p(),
                 files={"source": ("avatar.jpg", data, mime)})
        if changes.get("banner"):
            data, mime = media_mod.rendition(media_mod.Media(changes["banner"]), spec.get("banner"))
            photo = call("POST", f"{GRAPH}/{self.pid_}/photos", "פייסבוק",
                         params=self._p({"published": "false"}),
                         files={"source": ("cover.jpg", data, mime)})
            call("POST", f"{GRAPH}/{self.pid_}", "פייסבוק", params=self._p(),
                 data={"cover": photo.get("id")})
        after = self.get_profile()
        verify = {}
        if "about" in body:
            verify["bio"] = self.verified(body["about"], after.get("bio"))
        if "website" in body:
            verify["links"] = self.verified(body["website"], (after.get("links") or [""])[0])
        if changes.get("avatar"):
            verify["avatar"] = {"expected": "תמונה חדשה", "read_back": after.get("avatar_url"),
                                "match": after.get("avatar_url") != before.get("avatar_url")}
        if changes.get("banner"):
            verify["banner"] = {"expected": "תמונה חדשה", "read_back": after.get("banner_url"),
                                "match": (after.get("extra") or {}).get("cover_id") != (before.get("extra") or {}).get("cover_id")}
        ok = all(v["match"] for v in verify.values())
        return {"state": "ok" if ok else "assert_failed", "verify": verify, "url": after.get("url")}

    def list_posts(self, limit: int = 10) -> list[dict]:
        out = call("GET", f"{GRAPH}/{self.pid_}/published_posts", "פייסבוק",
                   params=self._p({"fields": "id,message,created_time,permalink_url,full_picture",
                                   "limit": min(limit, 50)}))
        return [{"id": p["id"], "text": p.get("message"), "url": p.get("permalink_url"),
                 "created_at": p.get("created_time"),
                 "media": [{"kind": "image", "url": p["full_picture"]}] if p.get("full_picture") else [],
                 "counts": {}} for p in (out or {}).get("data") or []]

    def create_post(self, post: dict) -> dict:
        text = clip(post.get("text") or "", 63206)
        images = [m for m in post.get("media") or [] if (m or {}).get("kind") == "image"]
        if any((m or {}).get("kind") == "video" for m in post.get("media") or []):
            raise self.refuse("post.create.video", why="העלאת וידאו לעמוד עוד לא מומשה כאן")
        if images:
            mm = media_mod.Media(images[0])
            data, mime = media_mod.rendition(mm, None)
            res = call("POST", f"{GRAPH}/{self.pid_}/photos", "פייסבוק", params=self._p(),
                       data={"caption": text}, files={"source": ("post.jpg", data, mime)})
            pid = res.get("post_id") or res.get("id")
        else:
            body = {"message": text}
            if post.get("link"):
                body["link"] = post["link"]
            pid = call("POST", f"{GRAPH}/{self.pid_}/feed", "פייסבוק", params=self._p(), data=body)["id"]
        back = call("GET", f"{GRAPH}/{pid}", "פייסבוק",
                    params=self._p({"fields": "id,message,permalink_url"}))
        return {"state": "ok", "id": pid, "url": back.get("permalink_url"),
                "verify": {"text": self.verified(text, back.get("message"))}}

    def update_post(self, post_id: str, changes: dict) -> dict:
        text = changes.get("text") or ""
        call("POST", f"{GRAPH}/{post_id}", "פייסבוק", params=self._p(), data={"message": text})
        back = call("GET", f"{GRAPH}/{post_id}", "פייסבוק", params=self._p({"fields": "message"}))
        return {"state": "ok", "id": post_id, "verify": {"text": self.verified(text, back.get("message"))}}

    def delete_post(self, post_id: str) -> dict:
        call("DELETE", f"{GRAPH}/{post_id}", "פייסבוק", params=self._p())
        return {"state": "ok", "id": post_id}

    def list_comments(self, post_id: str, limit: int = 20) -> list[dict]:
        out = call("GET", f"{GRAPH}/{post_id}/comments", "פייסבוק",
                   params=self._p({"fields": "id,message,created_time,from", "limit": limit}))
        return [{"id": c["id"], "text": c.get("message"), "created_at": c.get("created_time"),
                 "author": (c.get("from") or {}).get("name")} for c in (out or {}).get("data") or []]

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        c = call("POST", f"{GRAPH}/{reply_to or post_id}/comments", "פייסבוק", params=self._p(),
                 data={"message": text})
        return {"state": "ok", "id": c.get("id")}

    def delete_comment(self, comment_id: str) -> dict:
        call("DELETE", f"{GRAPH}/{comment_id}", "פייסבוק", params=self._p())
        return {"state": "ok", "id": comment_id}

    def insights(self) -> dict:
        p = self.get_profile()
        return {"followers": (p.get("extra") or {}).get("followers"),
                "fans": (p.get("extra") or {}).get("fans")}
