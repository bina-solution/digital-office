"""git.adapters — `adapter_for(provider, secret)` is the ONLY way an adapter is built.

A provider that does not exist is a programming error, not a user error: it can only come from a
protocol in the vault that this app does not implement, so it raises with the provider named.
"""
from __future__ import annotations

from .base import GitError, describe, split_repo  # noqa: F401  (re-exported for callers)
from .forge import ForgejoAdapter
from .github import GitHubAdapter
from .gitlab import GitLabAdapter

# `forgejo` is the office's OWN forge. It sits in the same registry as the remote providers on
# purpose: the local repository list, the mirrors' target projects and every issue/PR/release the
# office raises on them go through the same op surface, so "where do I see it" is a UI question and
# never a different code path.
ADAPTERS = {"github": GitHubAdapter, "gitlab": GitLabAdapter, "forgejo": ForgejoAdapter}


def adapter_for(provider: str, secret: dict, cid: str | None = None):
    """The ONE way an adapter is built.

    `cid` is the vault instance id, passed on so an expiring credential (a GitHub App's hourly token,
    a refreshed OAuth access token) can be minted — and written back — for the account it belongs to.
    A provider that does not exist is a programming error, not a user error; it raises with the name.
    """
    cls = ADAPTERS.get(provider or "")
    if not cls:
        raise GitError(f"אין תמיכה בספק {provider!r}.", status=400, kind="account")
    return cls(secret or {}, cid)
