"""git.repoindex — ONE list of repositories, out of every account the office holds.

The app's screen is a repository browser, and the first thing it shows is "every repository the
office can act on": GitHub's own, GitLab's, and the ones that live in the office's forge. That list
does not exist inside any provider — it has to be assembled, and this module is the assembly.

Three rules it keeps, each learned from the alternative:

  * **Partial failure is the normal case.** One dead token, one rate-limited provider, one account that
    is code-only and has no API at all: none of those may empty the screen. Every account reports its
    own repos OR its own error, side by side, and the caller renders both.
  * **The providers are expensive and they count.** A GitHub PAT allows 5000 calls an hour and a
    repository list is one call per account — but the screen refreshes, the same account is listed
    again, and rate limits do not recover on their own. So the answer is CACHED per account with a
    short TTL, and `refresh=1` is how a caller says "I know, ask again anyway".
  * **A mirror is not a repository of its own.** Repos are returned with the mirror that copies them
    (if any), keyed by (source account, repo), so the browser can mark "there is a local copy" without
    a second round trip and without inventing a row that no provider would return.
"""
from __future__ import annotations

import logging
import threading
import time

import accounts
import mirrors

log = logging.getLogger("git.repoindex")

TTL = float(__import__("os").environ.get("GIT_REPOS_TTL", "45"))
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict]] = {}


def _account_rows(insts: list[dict]) -> list[dict]:
    out = []
    for i in insts:
        provider, kind = accounts.provider_kind(i.get("protocol") or "")
        out.append({"id": i.get("id"), "label": i.get("label"), "provider": provider,
                    "kind": kind, "account_hint": i.get("account_hint") or "",
                    "code_only": kind in ("deploy_token", "generic_token")})
    return out


def _one_account(inst: dict, limit: int, refresh: bool) -> tuple[list[dict], str | None]:
    """(repos, error) for ONE account — never both. Cached per account id."""
    cid = inst.get("id") or ""
    now = time.time()
    if not refresh:
        with _LOCK:
            hit = _CACHE.get(cid)
        if hit and now - hit[0] < TTL:
            return hit[1]["repos"], hit[1]["error"]
    provider, kind = accounts.provider_kind(inst.get("protocol") or "")
    if kind in ("deploy_token", "generic_token"):
        # A code-only credential is a legitimate account with no API to list: saying so is the
        # difference between "this account has no repositories" and "this account cannot be asked".
        return [], "קוד בלבד (clone/push) — אין API לרשימת מאגרים"
    try:
        ad = accounts.adapter_for_instance(inst, accounts.vault_secret(cid) or {})
        data = ad.list_repos(limit=limit) or {}
        repos = data.get("repos") or []
        err = None
    except Exception as e:                          # noqa: BLE001 — one account must not break the list
        repos, err = [], getattr(e, "he_message", None) or f"{type(e).__name__}: {e}"
        log.info("repoindex: %s failed: %s", cid, err)
    with _LOCK:
        _CACHE[cid] = (now, {"repos": repos, "error": err})
    return repos, err


def index(account: str = "", q: str = "", limit: int = 100, refresh: bool = False) -> dict:
    """Every repository, tagged with the account it came from, plus a mirror marker where one exists.

    `account` limits the answer to one connection id (the account switcher). `q` filters on the
    full name and the description, case-insensitively — the providers' own search is honoured too,
    but a provider that ignores it would otherwise silently return everything.
    """
    insts, vault_err = accounts.vault_list()
    if vault_err:
        return {"repos": [], "accounts": [], "errors": [{"account": None, "error": vault_err}]}
    if account:
        insts = [i for i in insts if i.get("id") == account] or []
    rows = _account_rows(insts)
    by_id = {r["id"]: r for r in rows}

    mirror_of: dict[tuple[str, str], dict] = {}
    for m in mirrors.load():
        mirror_of[(m.get("source_account") or "", (m.get("source_repo") or "").lower())] = {
            "id": m.get("id"), "status": m.get("last_status"), "error": m.get("last_error"),
            "target": f"{m.get('target_owner')}/{m.get('target_repo')}",
            "browse_url": mirrors.public_base() + "/" + (m.get("target_owner") or "") + "/"
                          + (m.get("target_repo") or ""),
            "bytes": m.get("bytes"), "last_run": m.get("last_run"),
        }

    out: list[dict] = []
    errors: list[dict] = []
    needle = (q or "").strip().lower()
    for inst in insts:
        repos, err = _one_account(inst, limit, refresh)
        meta = by_id.get(inst.get("id")) or {}
        if err:
            errors.append({"account": inst.get("id"), "label": inst.get("label"),
                           "provider": meta.get("provider"), "error": err})
        for r in repos:
            full = (r.get("full_name") or "").lower()
            if needle and needle not in full and needle not in (r.get("description") or "").lower():
                continue
            row = dict(r)
            row["account"] = inst.get("id")
            row["account_label"] = inst.get("label")
            row["account_login"] = inst.get("account_hint")
            mirror = mirror_of.get((inst.get("id") or "", full))
            row["mirror"] = mirror
            row["local"] = bool(meta.get("provider") == "forgejo")
            out.append(row)
    out.sort(key=lambda r: (not r.get("local"), (r.get("full_name") or "").lower()))
    return {"repos": out, "accounts": rows, "errors": errors,
            "cached_ttl": TTL, "at": int(time.time())}


def forget(account: str = "") -> None:
    with _LOCK:
        if account:
            _CACHE.pop(account, None)
        else:
            _CACHE.clear()
