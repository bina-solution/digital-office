"""YouTube through the Data API v3 — the channel description and banner, the uploads, the comments.

secret: {access_token, channel_id, refresh_token?, client_id?, client_secret?}. With a refresh token
and the OAuth client, an expired access token is renewed here and WRITTEN BACK to the vault
(platform-service-contract.md §1, "token write-back"), so the vault stays the one copy.

What the API cannot do (research/platforms.md §1): change the channel NAME or the AVATAR, or post in
the Posts/Community tab — those refuse here and are the office browser's (scripts/youtube.yaml).
Uploads through an unaudited project stay private, so video uploads are not offered from here yet.
"""
from __future__ import annotations

import logging
import os

import requests

import media as media_mod
from adapters.base import SocialAdapter, SocialError, clip
from adapters.http import call

log = logging.getLogger("social-list.youtube")
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")


class YouTubeApiAdapter(SocialAdapter):
    kind = "api"

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.secret.get('access_token', '')}"}

    def _refresh(self) -> bool:
        s = self.secret
        if not (s.get("refresh_token") and s.get("client_id") and s.get("client_secret")):
            return False
        r = requests.post(TOKEN_URL, data={"grant_type": "refresh_token",
                                           "refresh_token": s["refresh_token"],
                                           "client_id": s["client_id"],
                                           "client_secret": s["client_secret"]}, timeout=20)
        if r.status_code != 200:
            return False
        self.secret["access_token"] = r.json().get("access_token", "")
        cid = (self.account or {}).get("id")
        if cid:                                  # best effort: a failed write-back never fails the op
            try:
                requests.put(f"{CONNECTIONS_URL}/api/instances/{cid}/secret",
                             json={"secret": {"access_token": self.secret["access_token"]}}, timeout=10)
            except requests.RequestException as e:
                log.warning("token write-back failed: %s", type(e).__name__)
        return True

    def _call(self, method: str, url: str, headers: dict | None = None, **kw):
        """A call that survives one expired access token (refresh, write back, retry once)."""
        try:
            return call(method, url, "יוטיוב", headers={**self._h(), **(headers or {})}, **kw)
        except SocialError as e:
            if e.kind == "unauthorized" and self._refresh():
                return call(method, url, "יוטיוב", headers={**self._h(), **(headers or {})}, **kw)
            raise

    def _channel(self, parts: str = "snippet,brandingSettings,statistics,contentDetails") -> dict:
        params = {"part": parts}
        if self.secret.get("channel_id"):
            params["id"] = self.secret["channel_id"]
        else:
            params["mine"] = "true"
        items = (self._call("GET", f"{API}/channels", params=params) or {}).get("items") or []
        if not items:
            raise SocialError("יוטיוב: הערוץ לא נמצא לטוקן הזה", status=404, kind="not_found")
        return items[0]

    def get_profile(self) -> dict:
        c = self._channel()
        sn, br = c.get("snippet") or {}, (c.get("brandingSettings") or {})
        return {"name": sn.get("title"), "handle": (sn.get("customUrl") or "").lstrip("@"),
                "bio": sn.get("description"), "links": [],
                "avatar_url": ((sn.get("thumbnails") or {}).get("high") or {}).get("url"),
                "banner_url": (br.get("image") or {}).get("bannerExternalUrl"),
                "url": f"https://www.youtube.com/channel/{c['id']}",
                "extra": {"id": c["id"], "subscribers": (c.get("statistics") or {}).get("subscriberCount"),
                          "uploads": ((c.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")}}

    def update_profile(self, changes: dict) -> dict:
        for f in ("name", "avatar", "links", "handle"):
            if f in changes:
                raise self.refuse(f"profile.update.{f}")
        c = self._channel("brandingSettings")
        branding = c.get("brandingSettings") or {}
        channel = dict(branding.get("channel") or {})
        verify = {}
        if "bio" in changes:
            channel["description"] = clip(str(changes["bio"] or ""), 1000)
        body = {"id": c["id"], "brandingSettings": {"channel": channel}}
        if changes.get("banner"):
            data, mime = media_mod.rendition(media_mod.Media(changes["banner"]),
                                             (self.platform.get("profile") or {}).get("banner"))
            # two steps (research §1, unverified end to end): upload → a URL → set it on the channel
            up = self._call("POST", f"{UPLOAD}/channelBanners/insert", headers={"Content-Type": mime},
                            params={"uploadType": "media"}, data=data)
            body["brandingSettings"]["image"] = {"bannerExternalUrl": (up or {}).get("url")}
        self._call("PUT", f"{API}/channels", params={"part": "brandingSettings"}, json=body)
        after = self.get_profile()
        if "bio" in changes:
            verify["bio"] = self.verified(channel["description"], after.get("bio"))
        if changes.get("banner"):
            want = body["brandingSettings"]["image"]["bannerExternalUrl"]
            verify["banner"] = {"expected": "תמונה חדשה", "read_back": after.get("banner_url"),
                                "match": bool(want) and after.get("banner_url") == want}
        ok = all(v["match"] for v in verify.values())
        return {"state": "ok" if ok else "assert_failed", "verify": verify, "url": after.get("url")}

    def list_posts(self, limit: int = 10) -> list[dict]:
        uploads = (self.get_profile().get("extra") or {}).get("uploads")
        if not uploads:
            return []
        items = (self._call("GET", f"{API}/playlistItems", params={
            "part": "snippet,contentDetails", "playlistId": uploads, "maxResults": min(limit, 50)}) or {}).get("items") or []
        return [{"id": (i.get("contentDetails") or {}).get("videoId"),
                 "text": (i.get("snippet") or {}).get("title"),
                 "url": f"https://www.youtube.com/watch?v={(i.get('contentDetails') or {}).get('videoId')}",
                 "created_at": (i.get("contentDetails") or {}).get("videoPublishedAt"), "media": [],
                 "counts": {}} for i in items]

    def update_post(self, post_id: str, changes: dict) -> dict:
        v = ((self._call("GET", f"{API}/videos", params={"part": "snippet", "id": post_id}) or {}).get("items") or [{}])[0]
        sn = dict(v.get("snippet") or {})
        if not sn:
            raise SocialError("יוטיוב: הסרטון לא נמצא", status=404, kind="not_found")
        sn["description"] = clip(changes.get("text") or "", 5000)
        self._call("PUT", f"{API}/videos", params={"part": "snippet"},
                   json={"id": post_id, "snippet": {k: sn[k] for k in ("title", "description", "categoryId") if k in sn}})
        return {"state": "ok", "id": post_id}

    def delete_post(self, post_id: str) -> dict:
        self._call("DELETE", f"{API}/videos", params={"id": post_id})
        return {"state": "ok", "id": post_id}

    def list_comments(self, post_id: str, limit: int = 20) -> list[dict]:
        items = (self._call("GET", f"{API}/commentThreads", params={
            "part": "snippet", "videoId": post_id, "maxResults": min(limit, 100)}) or {}).get("items") or []
        out = []
        for t in items:
            top = ((t.get("snippet") or {}).get("topLevelComment") or {})
            s = top.get("snippet") or {}
            out.append({"id": top.get("id"), "text": s.get("textOriginal"),
                        "created_at": s.get("publishedAt"), "author": s.get("authorDisplayName")})
        return out

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        if reply_to:
            c = self._call("POST", f"{API}/comments", params={"part": "snippet"},
                           json={"snippet": {"parentId": reply_to, "textOriginal": text}})
        else:
            c = self._call("POST", f"{API}/commentThreads", params={"part": "snippet"},
                           json={"snippet": {"videoId": post_id,
                                             "topLevelComment": {"snippet": {"textOriginal": text}}}})
        return {"state": "ok", "id": (c or {}).get("id")}

    def delete_comment(self, comment_id: str) -> dict:
        self._call("DELETE", f"{API}/comments", params={"id": comment_id})
        return {"state": "ok", "id": comment_id}

    def react(self, target_id: str, reaction: str = "like") -> dict:
        self._call("POST", f"{API}/videos/rate", params={"id": target_id, "rating": "like"})
        return {"state": "ok", "id": target_id}

    def insights(self) -> dict:
        return self.get_profile().get("extra") or {}
