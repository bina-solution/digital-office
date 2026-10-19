"""Discord through a bot — the only door Discord allows (self-bots are banned; research §6).

secret: {bot_token, guild_id, channel_id}. The server is the "profile" (name, description, icon,
banner) and the channel is the "feed". The bot needs Manage Server (profile) and Send Messages /
Manage Messages (posts) in that server.
"""
from __future__ import annotations

import json
from urllib.parse import quote

import media as media_mod
from adapters.base import SocialAdapter, clip
from adapters.http import call, data_uri

API = "https://discord.com/api/v10"
CDN = "https://cdn.discordapp.com"


class DiscordBotAdapter(SocialAdapter):
    kind = "api"

    def _h(self, reason: str = "") -> dict:
        h = {"Authorization": f"Bot {self.secret.get('bot_token', '')}",
             "User-Agent": "DigitalOffice-social-list (https://digital-office.co.il, 1)"}
        if reason:
            h["X-Audit-Log-Reason"] = quote(reason)
        return h

    @property
    def gid(self) -> str:
        return str(self.secret.get("guild_id") or "")

    @property
    def cid(self) -> str:
        return str(self.secret.get("channel_id") or "")

    def whoami(self) -> dict:
        g = call("GET", f"{API}/guilds/{self.gid}", "Discord", headers=self._h())
        return {"handle": g.get("id"), "name": g.get("name"),
                "url": f"https://discord.com/channels/{self.gid}"}

    def get_profile(self) -> dict:
        g = call("GET", f"{API}/guilds/{self.gid}", "Discord", headers=self._h(),
                 params={"with_counts": "true"})
        icon = f"{CDN}/icons/{g['id']}/{g['icon']}.png?size=512" if g.get("icon") else None
        banner = f"{CDN}/banners/{g['id']}/{g['banner']}.png?size=1024" if g.get("banner") else None
        return {"name": g.get("name"), "handle": g.get("vanity_url_code") or g.get("id"),
                "bio": g.get("description"), "links": [], "avatar_url": icon, "banner_url": banner,
                "url": f"https://discord.com/channels/{self.gid}",
                "extra": {"members": g.get("approximate_member_count"), "icon_hash": g.get("icon"),
                          "banner_hash": g.get("banner")}}

    def update_profile(self, changes: dict) -> dict:
        spec = self.platform.get("profile") or {}
        body = {}
        if "name" in changes:
            body["name"] = clip(str(changes["name"] or ""), 100)
        if "bio" in changes:
            body["description"] = clip(str(changes["bio"] or ""), 120)
        for f, key in (("avatar", "icon"), ("banner", "banner")):
            if changes.get(f):
                data, mime = media_mod.rendition(media_mod.Media(changes[f]), spec.get(f),
                                                 prefer_png=True)
                body[key] = data_uri(data, mime)
        for f in ("links", "handle"):
            if f in changes:
                raise self.refuse(f"profile.update.{f}")
        before = self.get_profile()
        call("PATCH", f"{API}/guilds/{self.gid}", "Discord", headers=self._h("digital-assets"),
             json=body)
        after = self.get_profile()
        verify = {}
        if "name" in body:
            verify["name"] = self.verified(body["name"], after.get("name"))
        if "description" in body:
            verify["bio"] = self.verified(body["description"], after.get("bio"))
        for f, h in (("avatar", "icon_hash"), ("banner", "banner_hash")):
            if changes.get(f):
                changed = (after["extra"].get(h) != before["extra"].get(h)) and bool(after["extra"].get(h))
                verify[f] = {"expected": "תמונה חדשה", "read_back": after.get(f"{f}_url"),
                             "match": changed}
        ok = all(v["match"] for v in verify.values())
        return {"state": "ok" if ok else "assert_failed", "verify": verify, "url": after["url"]}

    def list_posts(self, limit: int = 10) -> list[dict]:
        msgs = call("GET", f"{API}/channels/{self.cid}/messages", "Discord", headers=self._h(),
                    params={"limit": min(limit, 100)}) or []
        return [{"id": m["id"], "text": m.get("content"),
                 "url": f"https://discord.com/channels/{self.gid}/{self.cid}/{m['id']}",
                 "created_at": m.get("timestamp"),
                 "media": [{"kind": "image", "url": a.get("url")} for a in m.get("attachments") or []],
                 "counts": {"likes": sum(r.get("count", 0) for r in m.get("reactions") or []),
                            "comments": None}} for m in msgs]

    def create_post(self, post: dict, reply_to: str | None = None) -> dict:
        text = clip(post.get("text") or "", 2000)
        payload = {"content": text}
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}
        files = {}
        atts = []
        for i, m in enumerate((post.get("media") or [])[:10]):
            mm = media_mod.Media(m)
            data, mime = media_mod.rendition(mm, None)
            name = mm.filename("png" if mime == "image/png" else "jpg" if mime == "image/jpeg" else None)
            files[f"files[{i}]"] = (name, data, mime)
            atts.append({"id": i, "filename": name})
        if files:
            payload["attachments"] = atts
            msg = call("POST", f"{API}/channels/{self.cid}/messages", "Discord", headers=self._h(),
                       data={"payload_json": json.dumps(payload, ensure_ascii=False)}, files=files)
        else:
            msg = call("POST", f"{API}/channels/{self.cid}/messages", "Discord", headers=self._h(),
                       json=payload)
        back = call("GET", f"{API}/channels/{self.cid}/messages/{msg['id']}", "Discord", headers=self._h())
        return {"state": "ok", "id": msg["id"],
                "url": f"https://discord.com/channels/{self.gid}/{self.cid}/{msg['id']}",
                "verify": {"text": self.verified(text, back.get("content"))}}

    def update_post(self, post_id: str, changes: dict) -> dict:
        text = clip(changes.get("text") or "", 2000)
        m = call("PATCH", f"{API}/channels/{self.cid}/messages/{post_id}", "Discord",
                 headers=self._h(), json={"content": text})
        return {"state": "ok", "id": post_id, "verify": {"text": self.verified(text, m.get("content"))}}

    def delete_post(self, post_id: str) -> dict:
        call("DELETE", f"{API}/channels/{self.cid}/messages/{post_id}", "Discord", headers=self._h())
        return {"state": "ok", "id": post_id}

    def list_comments(self, post_id: str, limit: int = 20) -> list[dict]:
        msgs = call("GET", f"{API}/channels/{self.cid}/messages", "Discord", headers=self._h(),
                    params={"limit": 100}) or []
        replies = [m for m in msgs if (m.get("message_reference") or {}).get("message_id") == post_id]
        return [{"id": m["id"], "text": m.get("content"), "created_at": m.get("timestamp"),
                 "author": (m.get("author") or {}).get("username")} for m in replies[:limit]]

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        return self.create_post({"text": text}, reply_to=reply_to or post_id)

    def delete_comment(self, comment_id: str) -> dict:
        return self.delete_post(comment_id)

    def react(self, target_id: str, reaction: str = "like") -> dict:
        emoji = quote("👍" if reaction == "like" else reaction)
        call("PUT", f"{API}/channels/{self.cid}/messages/{target_id}/reactions/{emoji}/@me",
             "Discord", headers=self._h())
        return {"state": "ok", "id": target_id}
