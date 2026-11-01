"""The adapter contract — what every implementation of `social.v1` must answer, in one shape.

An adapter is (platform × kind): `facebook` through the office `browser`, `github` through its `api`,
the test network through either. The caller never learns which one it is talking to; that is the
whole abstraction, and it is the same rule the domains, drive and mail apps follow.

Shapes (every adapter returns these and nothing else):

    profile = {name, handle, bio, links[], avatar_url, banner_url, url, extra{}}
    post    = {id, text, url, created_at, media[], counts{likes, comments}}
    write   = {state: "ok", verify{field: {expected, read_back, match}}, id?, url?, evidence?}

A write is proved by READING IT BACK. An adapter that cannot read back what it wrote says so
(`verify: {<field>: {match: null, why}}`) instead of reporting success it did not observe.
"""
from __future__ import annotations

import platforms

#: the fields a profile update may carry, and the op that authorises each
PROFILE_FIELDS = {
    "name": "profile.update.name",
    "bio": "profile.update.bio",
    "avatar": "profile.update.avatar",
    "banner": "profile.update.banner",
    "links": "profile.update.links",
    "handle": "profile.update.handle",
}


class SocialError(Exception):
    """One failure, in the two languages a caller needs: what to do, and what the platform said.

    `state` reuses the browser-session vocabulary (`needs_human_login`, `selector_missing`, …) so a
    browser refusal and an API refusal reach the screen the same way.
    """

    def __init__(self, he_message: str, status: int = 502, *, kind: str = "provider",
                 detail: str | None = None, title: str | None = None, why: str | None = None,
                 how: str | None = None, url: str | None = None, state: str | None = None,
                 provider_error=None):
        super().__init__(he_message)
        self.he_message = he_message
        self.status = status
        self.kind = kind
        self.detail = detail
        self.title = title
        self.why = why
        self.how = how
        self.url = url
        self.state = state
        self.provider_error = provider_error

    def body(self) -> dict:
        out = {"error": self.he_message, "kind": self.kind, "status": self.status}
        for k in ("title", "why", "how", "url", "state", "detail"):
            v = getattr(self, k)
            if v:
                out[k] = v
        if self.provider_error is not None:
            out["provider_error"] = self.provider_error
        return out


class SocialAdapter:
    """Base: every op refuses, with the catalogue's own reason. A subclass overrides what it can do."""

    kind = "api"

    def __init__(self, platform: dict, secret: dict, account: dict | None = None):
        self.platform = platform
        self.pid = platform.get("id", "")
        self.secret = secret or {}
        self.account = account or {}

    # ── the contract ────────────────────────────────────────────────────────────────────────────
    def whoami(self) -> dict:
        prof = self.get_profile()
        return {"handle": prof.get("handle"), "name": prof.get("name"), "url": prof.get("url")}

    def get_profile(self) -> dict:
        raise self.refuse("profile.get")

    def update_profile(self, changes: dict) -> dict:
        raise self.refuse(PROFILE_FIELDS.get(next(iter(changes or {"name": 0})), "profile.update.name"))

    def list_posts(self, limit: int = 10) -> list[dict]:
        raise self.refuse("post.list")

    def create_post(self, post: dict) -> dict:
        raise self.refuse(post_op(post))

    def update_post(self, post_id: str, changes: dict) -> dict:
        raise self.refuse("post.update")

    def delete_post(self, post_id: str) -> dict:
        raise self.refuse("post.delete")

    def list_comments(self, post_id: str, limit: int = 20) -> list[dict]:
        raise self.refuse("comment.list")

    def create_comment(self, post_id: str, text: str, reply_to: str | None = None) -> dict:
        raise self.refuse("comment.create")

    def delete_comment(self, comment_id: str) -> dict:
        raise self.refuse("comment.delete")

    def react(self, target_id: str, reaction: str = "like") -> dict:
        raise self.refuse("reaction.create")

    def insights(self) -> dict:
        raise self.refuse("insights.get")

    # ── helpers every adapter shares ────────────────────────────────────────────────────────────
    def refuse(self, op: str, why: str | None = None) -> SocialError:
        """A refusal that names the platform, the op, why, and where a human does it instead."""
        sup = platforms.support(self.pid, op, self.kind)
        label = (platforms.ops_vocabulary().get(op) or {}).get("he", op)
        name = (self.platform.get("name") or {}).get("he", self.pid)
        reason = why or sup.get("why") or {
            "no": "הפעולה הזו עוד לא קיימת בדרך החיבור הזו",
            "limited": "הפעולה נתמכת רק בחלקה ועדיין לא מומשה כאן",
        }.get(sup.get("answer"), "הפעולה עדיין לא מומשה בחיבור הזה")
        urls = self.platform.get("urls") or {}
        where = urls.get("profile_edit") if op.startswith("profile.") else urls.get("compose")
        return SocialError(f"{name}: {label} — {reason}", status=409, kind="unsupported",
                           title=f"{label} אינו זמין ב{name}", why=reason,
                           how="פעולה שעוד אין לה תסריט בדפדפן הלשכה נכתבת ב-scripts/<platform>.yaml.",
                           url=platforms.expand(where or "", self.platform, self.values()) or None,
                           state="unsupported")

    def values(self) -> dict:
        """What URL templates may use: the account's handle and the ids its secret carries."""
        s = self.secret or {}
        return {"handle": s.get("handle") or self.account.get("account_hint") or "",
                "guild_id": s.get("guild_id"), "channel_id": s.get("channel_id"),
                "phone": s.get("phone"), "page_id": s.get("page_id")}

    @staticmethod
    def verified(expected, read_back, compare: str = "equals") -> dict:
        e = "" if expected is None else str(expected).strip()
        r = "" if read_back is None else str(read_back).strip()
        match = (e == r) if compare == "equals" else (e in r)
        return {"expected": expected, "read_back": read_back, "match": match}


def post_op(post: dict) -> str:
    """Which op a post is, by what it carries — a post with a video is `post.create.video`."""
    kinds = {(m or {}).get("kind") for m in (post or {}).get("media") or []}
    if "video" in kinds:
        return "post.create.video"
    if "image" in kinds:
        return "post.create.image"
    return "post.create.text"


def clip(text: str, limit: int | None) -> str:
    """Trim to a platform limit on a word boundary, with an ellipsis — never mid-word, never silently
    longer than the platform accepts (it would refuse the whole write)."""
    t = (text or "").strip()
    if not limit or len(t) <= limit:
        return t
    cut = t[: max(1, limit - 1)]
    if " " in cut[int(limit * 0.6):]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"
