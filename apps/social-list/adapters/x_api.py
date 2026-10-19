"""X through the X API v2 — posts, deletes and reads; the profile is the office browser's.

secret: {access_token}  — an OAuth 2.0 user-context token (tweet.read tweet.write users.read
media.write offline.access).

Facts that shape this file (research/platforms.md §5, 2026): the API is pay-per-use ($0.015 a post,
$0.20 a post that carries a URL — so every result carries `cost_hint`); profile writes exist only as
legacy v1.1 endpoints that need OAuth 1.0a and were not confirmed to work, so they refuse here and the
office browser (scripts/x.yaml) does them; likes were removed from self-serve access; a reply works only when summoned.
"""
from __future__ import annotations

import re

import media as media_mod
from adapters.base import SocialAdapter, clip
from adapters.http import call

API = "https://api.x.com/2"
URL_RE = re.compile(r"https?://", re.I)


class XApiAdapter(SocialAdapter):
    kind = "api"

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.secret.get('access_token', '')}"}

    def _me(self) -> dict:
        return (call("GET", f"{API}/users/me", "X", headers=self._h(), params={
            "user.fields": "description,profile_image_url,url,public_metrics,location"}) or {}).get("data") or {}

    def get_profile(self) -> dict:
        u = self._me()
        return {"name": u.get("name"), "handle": u.get("username"), "bio": u.get("description"),
                "links": [x for x in [u.get("url")] if x], "avatar_url": u.get("profile_image_url"),
                "banner_url": None, "url": f"https://x.com/{u.get('username')}",
                "extra": {"id": u.get("id"), "followers": (u.get("public_metrics") or {}).get("followers_count")}}

    def update_profile(self, changes: dict) -> dict:
        field = next(iter(changes or {"name": 0}))
        raise self.refuse(f"profile.update.{field}",
                          why="עדכון פרופיל ב-X קיים רק בנקודות v1.1 ישנות (OAuth 1.0a) שלא אומתו — "
                              "הלשכה מכינה את השינוי ללחיצה שלכם (חיבור „הכנה”).")

    def list_posts(self, limit: int = 10) -> list[dict]:
        uid = self._me().get("id")
        out = call("GET", f"{API}/users/{uid}/tweets", "X", headers=self._h(), params={
            "max_results": max(5, min(limit, 100)), "tweet.fields": "created_at,public_metrics"}) or {}
        return [{"id": t["id"], "text": t.get("text"), "url": f"https://x.com/i/status/{t['id']}",
                 "created_at": t.get("created_at"), "media": [],
                 "counts": {"likes": (t.get("public_metrics") or {}).get("like_count"),
                            "comments": (t.get("public_metrics") or {}).get("reply_count")}}
                for t in out.get("data") or []][:limit]

    def _upload(self, m: dict) -> str:
        data, mime = media_mod.rendition(media_mod.Media(m), {"w": 1200, "h": 675} if m.get("aspect") == "16:9" else None)
        out = call("POST", f"{API}/media/upload", "X", headers=self._h(),
                   files={"media": ("image.jpg" if mime == "image/jpeg" else "image.png", data, mime)},
                   data={"media_category": "tweet_image"})
        mid = ((out or {}).get("data") or {}).get("id") or (out or {}).get("media_id_string")
        if not mid:
            raise self.refuse("post.create.image", why="X לא החזיר מזהה מדיה להעלאה")
        return str(mid)

    def create_post(self, post: dict, reply_to: str | None = None) -> dict:
        text = clip(post.get("text") or "", 280)
        body: dict = {"text": text}
        images = [m for m in post.get("media") or [] if (m or {}).get("kind") == "image"][:4]
        if images:
            body["media"] = {"media_ids": [self._upload(m) for m in images]}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        out = (call("POST", f"{API}/tweets", "X", headers=self._h(), json=body) or {}).get("data") or {}
        tid = out.get("id")
        back = (call("GET", f"{API}/tweets/{tid}", "X", headers=self._h()) or {}).get("data") or {}
        return {"state": "ok", "id": tid, "url": f"https://x.com/i/status/{tid}",
                "verify": {"text": self.verified(text, back.get("text"), compare="contains")},
                "cost_hint": "$0.20" if URL_RE.search(text) else "$0.015"}

    def delete_post(self, post_id: str) -> dict:
        out = (call("DELETE", f"{API}/tweets/{post_id}", "X", headers=self._h()) or {}).get("data") or {}
        return {"state": "ok" if out.get("deleted") else "assert_failed", "id": post_id}

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        return self.create_post({"text": text}, reply_to=reply_to or post_id)

    def delete_comment(self, comment_id: str) -> dict:
        return self.delete_post(comment_id)

    def insights(self) -> dict:
        return self.get_profile().get("extra") or {}
