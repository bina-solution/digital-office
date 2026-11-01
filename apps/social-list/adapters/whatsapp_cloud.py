"""WhatsApp Business through the Cloud API — the business PROFILE only.

secret: {phone_number_id, access_token, app_id?}. WhatsApp has no API for Status or Channels
(research/platforms.md §7), so posts refuse here and are the office browser's (WhatsApp Web). The
profile photo
goes through Meta's Resumable Upload API, which needs the app id.
"""
from __future__ import annotations

import os

import media as media_mod
from adapters.base import SocialAdapter, clip
from adapters.http import call

VERSION = os.environ.get("SOCIAL_GRAPH_VERSION", "v23.0")
GRAPH = f"https://graph.facebook.com/{VERSION}"
FIELDS = "about,address,description,email,profile_picture_url,websites,vertical"


class WhatsAppCloudAdapter(SocialAdapter):
    kind = "api"

    @property
    def pn(self) -> str:
        return str(self.secret.get("phone_number_id") or "")

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.secret.get('access_token', '')}"}

    def get_profile(self) -> dict:
        prof = ((call("GET", f"{GRAPH}/{self.pn}/whatsapp_business_profile", "וואטסאפ",
                      headers=self._h(), params={"fields": FIELDS}) or {}).get("data") or [{}])[0]
        num = call("GET", f"{GRAPH}/{self.pn}", "וואטסאפ", headers=self._h(),
                   params={"fields": "verified_name,display_phone_number"}) or {}
        phone = (num.get("display_phone_number") or "").replace("+", "").replace(" ", "").replace("-", "")
        return {"name": num.get("verified_name"), "handle": phone, "bio": prof.get("about"),
                "links": prof.get("websites") or [], "avatar_url": prof.get("profile_picture_url"),
                "banner_url": None, "url": f"https://wa.me/{phone}" if phone else None,
                "extra": {"description": prof.get("description"), "address": prof.get("address"),
                          "email": prof.get("email"), "vertical": prof.get("vertical")}}

    def _upload_handle(self, data: bytes, mime: str) -> str:
        app_id = self.secret.get("app_id")
        if not app_id:
            raise self.refuse("profile.update.avatar",
                              why="להעלאת תמונת פרופיל דרך ה-API נדרש מזהה האפליקציה (app_id) של Meta")
        sess = call("POST", f"{GRAPH}/{app_id}/uploads", "וואטסאפ", headers=self._h(),
                    params={"file_length": len(data), "file_type": mime})
        up = call("POST", f"{GRAPH}/{sess['id']}", "וואטסאפ",
                  headers={"Authorization": f"OAuth {self.secret.get('access_token', '')}",
                           "file_offset": "0"}, data=data)
        return up.get("h")

    def update_profile(self, changes: dict) -> dict:
        for f in ("name", "banner", "handle"):
            if f in changes:
                raise self.refuse(f"profile.update.{f}")
        body: dict = {"messaging_product": "whatsapp"}
        if "bio" in changes:
            body["about"] = clip(str(changes["bio"] or ""), 139)
        if "links" in changes:
            body["websites"] = [u for u in (changes["links"] or []) if u][:2]
        if changes.get("avatar"):
            data, mime = media_mod.rendition(media_mod.Media(changes["avatar"]),
                                             (self.platform.get("profile") or {}).get("avatar"))
            body["profile_picture_handle"] = self._upload_handle(data, mime)
        before = self.get_profile()
        call("POST", f"{GRAPH}/{self.pn}/whatsapp_business_profile", "וואטסאפ", headers=self._h(), json=body)
        after = self.get_profile()
        verify = {}
        if "about" in body:
            verify["bio"] = self.verified(body["about"], after.get("bio"))
        if "websites" in body:
            verify["links"] = self.verified(",".join(body["websites"]), ",".join(after.get("links") or []))
        if "profile_picture_handle" in body:
            verify["avatar"] = {"expected": "תמונה חדשה", "read_back": after.get("avatar_url"),
                                "match": after.get("avatar_url") != before.get("avatar_url")}
        ok = all(v["match"] for v in verify.values())
        return {"state": "ok" if ok else "assert_failed", "verify": verify, "url": after.get("url")}
