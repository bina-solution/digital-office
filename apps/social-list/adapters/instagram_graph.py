"""Instagram (Business/Creator) through the Graph API — posts, comments and numbers; NO profile writes.

secret: {ig_user_id, access_token, base?}   base = https://graph.facebook.com/<v> (Facebook Login,
the default) or https://graph.instagram.com/<v> (Instagram Login).

Two facts shape this file (research/platforms.md §4): the API has no endpoint for name, bio, avatar
or links (profile edits are the office browser's), and publishing takes an `image_url`
Instagram downloads itself — so a post needs a PUBLIC copy of the image (media.publish_public).
"""
from __future__ import annotations

import os
import time

import media as media_mod
from adapters.base import SocialAdapter, clip
from adapters.http import call

VERSION = os.environ.get("SOCIAL_GRAPH_VERSION", "v23.0")


class InstagramGraphAdapter(SocialAdapter):
    kind = "api"

    @property
    def base(self) -> str:
        return (self.secret.get("base") or f"https://graph.facebook.com/{VERSION}").rstrip("/")

    @property
    def ig(self) -> str:
        return str(self.secret.get("ig_user_id") or "")

    def _p(self, extra: dict | None = None) -> dict:
        return {"access_token": self.secret.get("access_token", ""), **(extra or {})}

    def get_profile(self) -> dict:
        p = call("GET", f"{self.base}/{self.ig}", "אינסטגרם", params=self._p(
            {"fields": "username,name,biography,profile_picture_url,website,followers_count,media_count"}))
        return {"name": p.get("name"), "handle": p.get("username"), "bio": p.get("biography"),
                "links": [x for x in [p.get("website")] if x], "avatar_url": p.get("profile_picture_url"),
                "banner_url": None, "url": f"https://www.instagram.com/{p.get('username')}/",
                "extra": {"followers": p.get("followers_count"), "posts": p.get("media_count")}}

    def list_posts(self, limit: int = 10) -> list[dict]:
        out = call("GET", f"{self.base}/{self.ig}/media", "אינסטגרם", params=self._p(
            {"fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count",
             "limit": min(limit, 50)}))
        return [{"id": m["id"], "text": m.get("caption"), "url": m.get("permalink"),
                 "created_at": m.get("timestamp"),
                 "media": [{"kind": "video" if m.get("media_type") == "VIDEO" else "image",
                            "url": m.get("media_url")}],
                 "counts": {"likes": m.get("like_count"), "comments": m.get("comments_count")}}
                for m in (out or {}).get("data") or []]

    def create_post(self, post: dict) -> dict:
        images = [m for m in post.get("media") or [] if (m or {}).get("kind") == "image"]
        if not images:
            raise self.refuse("post.create.text")
        text = clip(post.get("text") or "", 2200)
        urls = []
        for m in images[:10]:
            data, mime = media_mod.rendition(media_mod.Media(m), {"w": 1080, "h": 1350, "aspect": "4:5"}
                                             if m.get("aspect") == "4:5" else {"w": 1080, "h": 1080})
            u = media_mod.publish_public(data, mime)
            if not u:
                raise self.refuse("post.create.image",
                                  why="אינסטגרם מוריד את התמונה בעצמו מכתובת ציבורית, ולפריסה הזו "
                                      "לא הוגדרה כתובת כזו (SOCIAL_LIST_PUBLIC_URL). אפשר לפרסם "
                                      "דרך „הכנה ולחיצה”.")
            urls.append(u)
        if len(urls) == 1:
            c = call("POST", f"{self.base}/{self.ig}/media", "אינסטגרם", params=self._p(),
                     data={"image_url": urls[0], "caption": text})
        else:
            children = [call("POST", f"{self.base}/{self.ig}/media", "אינסטגרם", params=self._p(),
                             data={"image_url": u, "is_carousel_item": "true"})["id"] for u in urls]
            c = call("POST", f"{self.base}/{self.ig}/media", "אינסטגרם", params=self._p(),
                     data={"media_type": "CAROUSEL", "children": ",".join(children), "caption": text})
        creation = c["id"]
        for _ in range(10):                                   # the container must finish processing
            st = call("GET", f"{self.base}/{creation}", "אינסטגרם",
                      params=self._p({"fields": "status_code"}))
            if st.get("status_code") in ("FINISHED", None):
                break
            if st.get("status_code") == "ERROR":
                raise self.refuse("post.create.image", why="אינסטגרם לא הצליח לעבד את התמונה")
            time.sleep(2)
        pub = call("POST", f"{self.base}/{self.ig}/media_publish", "אינסטגרם", params=self._p(),
                   data={"creation_id": creation})
        back = call("GET", f"{self.base}/{pub['id']}", "אינסטגרם",
                    params=self._p({"fields": "caption,permalink"}))
        return {"state": "ok", "id": pub["id"], "url": back.get("permalink"),
                "verify": {"text": self.verified(text, back.get("caption"))}}

    def delete_post(self, post_id: str) -> dict:
        call("DELETE", f"{self.base}/{post_id}", "אינסטגרם", params=self._p())
        return {"state": "ok", "id": post_id}

    def list_comments(self, post_id: str, limit: int = 20) -> list[dict]:
        out = call("GET", f"{self.base}/{post_id}/comments", "אינסטגרם",
                   params=self._p({"fields": "id,text,timestamp,username", "limit": limit}))
        return [{"id": c["id"], "text": c.get("text"), "created_at": c.get("timestamp"),
                 "author": c.get("username")} for c in (out or {}).get("data") or []]

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        if reply_to:
            c = call("POST", f"{self.base}/{reply_to}/replies", "אינסטגרם", params=self._p(),
                     data={"message": text})
        else:
            c = call("POST", f"{self.base}/{post_id}/comments", "אינסטגרם", params=self._p(),
                     data={"message": text})
        return {"state": "ok", "id": c.get("id")}

    def delete_comment(self, comment_id: str) -> dict:
        call("DELETE", f"{self.base}/{comment_id}", "אינסטגרם", params=self._p())
        return {"state": "ok", "id": comment_id}

    def insights(self) -> dict:
        p = self.get_profile()
        return p.get("extra") or {}
