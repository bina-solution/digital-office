"""Adapters: (platform × kind) → the object that speaks `social.v1` for one account.

The choice is made HERE and only here, from the account's protocol (accounts.resolve), which is what
"automatically transforms to the connection type's implementation" means in practice: connect a
Facebook page token and the Graph adapter answers; connect the office browser to the same page and
the browser adapter answers; the caller sends the same `createPost` either way. The office browser is
the default door for every network (scripts/<platform>.yaml); an API is the alternative.
"""
from __future__ import annotations

from adapters.base import SocialAdapter, SocialError


def _api_class(pid: str):
    # imported lazily: an adapter module that fails to import must cost its own platform, not all
    if pid == "fixture":
        from adapters.fixture_api import FixtureApiAdapter
        return FixtureApiAdapter
    if pid == "github":
        from adapters.github import GitHubAdapter
        return GitHubAdapter
    if pid == "facebook":
        from adapters.facebook_graph import FacebookGraphAdapter
        return FacebookGraphAdapter
    if pid == "instagram":
        from adapters.instagram_graph import InstagramGraphAdapter
        return InstagramGraphAdapter
    if pid == "x":
        from adapters.x_api import XApiAdapter
        return XApiAdapter
    if pid == "youtube":
        from adapters.youtube_api import YouTubeApiAdapter
        return YouTubeApiAdapter
    if pid == "discord":
        from adapters.discord_bot import DiscordBotAdapter
        return DiscordBotAdapter
    if pid == "whatsapp":
        from adapters.whatsapp_cloud import WhatsAppCloudAdapter
        return WhatsAppCloudAdapter
    return SocialAdapter


def adapter_for(platform: dict, kind: str, secret: dict, account: dict | None = None,
                **kw) -> SocialAdapter:
    if not platform:
        raise SocialError("הפרוטוקול של החשבון אינו מוכר לאפליקציה", status=400, kind="unknown")
    pid = platform.get("id") or ""
    if kind == "browser":
        from adapters.browser import BrowserAdapter
        a = BrowserAdapter(platform, secret, account, session=kw.get("session"))
        a.watch = bool(kw.get("watch"))
        return a
    try:
        cls = _api_class(pid)
    except ImportError:
        cls = SocialAdapter
    return cls(platform, secret, account)
