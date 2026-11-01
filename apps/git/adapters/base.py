"""git.adapters — one canonical op set, two providers.

Every op is provider-agnostic and returns a NORMALIZED shape, because the two providers disagree
about almost every name: `body` vs `description`, `number` vs `iid`, `state` vs `state_event`,
labels as objects vs strings, `user` vs `author`, a review vs an approval. A caller in this office
(the console, another app, the office agent) must not have to know which provider is behind an
account — so the disagreement is resolved HERE, once, and never leaks upward.

What cannot be resolved is reported instead of hidden: an op that one provider performs natively and
the other only approximates says so in its answer (`applied: "native"|"approximated"` plus a note),
and an op that is impossible for the connected token (`createRepo` on a GitLab project access token)
refuses with an explanation rather than failing opaquely later.

Errors are Hebrew and actionable: the provider's own message is preserved verbatim in `provider_error`
for the operator who needs it, while the sentence shown in the UI says what to DO.
"""
from __future__ import annotations

import base64
import re


class GitError(Exception):
    """One failure, in the two languages the caller needs: what to do, and what the provider said."""

    def __init__(self, he_message: str, status: int = 502, *, detail: str | None = None,
                 provider_error=None, kind: str = "provider"):
        super().__init__(he_message)
        self.he_message = he_message
        self.status = status
        self.detail = detail
        self.provider_error = provider_error
        self.kind = kind

    def body(self) -> dict:
        out = {"error": self.he_message, "kind": self.kind, "status": self.status}
        if self.detail:
            out["detail"] = self.detail
        if self.provider_error is not None:
            out["provider_error"] = self.provider_error
        return out


# ── the polymorphic error renderer ───────────────────────────────────────────────────────────────
#
# GitLab's `message` is a string, an array OR an object of field → [messages]; GitHub hides
# validation detail inside `errors[]` next to a generic `message`; a scope problem arrives as a bare
# 403 with a sentence meant for a developer. One renderer walks all of those, because three
# hand-written per-call handlers is how one of them ends up rendering "[object Object]".
_STATUS_HE = {
    400: "הבקשה נדחתה על ידי הספק",
    401: "הטוקן של החשבון אינו תקף או שפג תוקפו",
    403: "לטוקן אין הרשאה לפעולה הזו",
    404: "לא נמצא — ייתכן שהמאגר או הפריט לא קיים, או שלטוקן אין גישה אליו",
    405: "הפעולה חסומה כרגע על ידי הספק (למשל מיזוג שאינו אפשרי במצב הנוכחי)",
    409: "הנתונים השתנו מאז הקריאה — יש לרענן ולנסות שוב",
    410: "התכונה מבוטלת במאגר הזה (למשל issues כבויים)",
    422: "הנתונים לא עברו ולידציה אצל הספק",
    429: "חריגה ממכסת הקריאות של הספק — יש להמתין ולנסות שוב",
}


def _flatten_message(msg) -> str:
    """string | [string] | {field: [string]} → one sentence. Never returns a Python repr."""
    if msg is None:
        return ""
    if isinstance(msg, str):
        return msg
    if isinstance(msg, list):
        return " · ".join(_flatten_message(m) for m in msg if m)
    if isinstance(msg, dict):
        return " · ".join(f"{k}: {_flatten_message(v)}" for k, v in msg.items() if v)
    return str(msg)


def _flatten_errors(errors) -> str:
    if not errors:
        return ""
    if isinstance(errors, dict):
        return _flatten_message(errors)
    parts = []
    for e in errors if isinstance(errors, list) else [errors]:
        if isinstance(e, dict):
            bits = [e.get("message") or e.get("code") or "", e.get("field") or ""]
            parts.append(" ".join(b for b in bits if b))
        else:
            parts.append(str(e))
    return " · ".join(p for p in parts if p)


def describe(status: int, payload, headers=None) -> GitError:
    """One HTTP failure → a GitError with a Hebrew sentence and the provider's own words attached."""
    msg = ""
    extra = ""
    if isinstance(payload, dict):
        msg = _flatten_message(payload.get("message") or payload.get("error_description")
                               or payload.get("error"))
        extra = _flatten_errors(payload.get("errors"))
    elif isinstance(payload, str):
        msg = payload.strip()[:400]

    he = _STATUS_HE.get(status, f"הספק החזיר שגיאה (HTTP {status})")
    if status == 401:
        he = "הטוקן נדחה על ידי הספק — יש לחדש את הטוקן ולעדכן את החשבון במסך „גיט”."
    elif status == 403:
        he = ("לטוקן אין הרשאה לפעולה הזו. בדוק את ה-scopes: GitHub צריך repo (ו-delete_repo "
              "למחיקה, Administration ליצירת מאגר ב-fine-grained); GitLab צריך api.")
    elif status == 404:
        he = "לא נמצא: ייתכן שהמאגר או הפריט אינו קיים, או שהטוקן אינו מורשה אליו."
    elif status == 429:
        he = "הספק הגביל את קצב הקריאות (rate limit) — יש להמתין מעט ולנסות שוב."
    if extra:
        he = f"{he} ({extra})"
    detail = msg or extra or None
    return GitError(he, status=status if status in _STATUS_HE else 502,
                    detail=detail, provider_error=payload)


# ── small shared helpers ─────────────────────────────────────────────────────────────────────────
def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unb64(data: str) -> str:
    """Base64 → text, tolerating the newlines GitHub inserts every 60 chars and a missing padding."""
    if not data:
        return ""
    clean = re.sub(r"\s+", "", data)
    clean += "=" * (-len(clean) % 4)
    try:
        return base64.b64decode(clean).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def split_repo(repo: str) -> tuple[str, str]:
    """'owner/name' → ('owner', 'name').

    The OWNER half is opaque and may itself contain slashes (GitLab nests groups: `a/b/c/proj`), so
    only the LAST segment is the repository name and everything before it is the namespace. Splitting
    on the first slash — the obvious implementation — silently mangles every nested GitLab project.
    """
    repo = (repo or "").strip().strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if "/" not in repo:
        raise GitError("צורת המאגר צריכה להיות owner/repo (או group/subgroup/repo ב-GitLab).",
                       status=400, kind="input")
    owner, _, name = repo.rpartition("/")
    return owner, name


def norm_repo(raw: dict, provider: str, host: str) -> dict:
    """Provider repo payload → the one repo shape this office speaks."""
    if provider == "github":
        return {
            "id": raw.get("id"), "name": raw.get("name"),
            "full_name": raw.get("full_name"), "owner": (raw.get("owner") or {}).get("login"),
            "description": raw.get("description") or "",
            "private": bool(raw.get("private")),
            "visibility": raw.get("visibility") or ("private" if raw.get("private") else "public"),
            "default_branch": raw.get("default_branch"),
            "clone_url": raw.get("clone_url"), "web_url": raw.get("html_url"),
            "archived": bool(raw.get("archived")), "provider": provider, "host": host,
        }
    return {
        "id": raw.get("id"), "name": raw.get("path") or raw.get("name"),
        "full_name": raw.get("path_with_namespace"),
        "owner": (raw.get("namespace") or {}).get("full_path"),
        "description": raw.get("description") or "",
        "private": (raw.get("visibility") or "private") != "public",
        "visibility": raw.get("visibility") or "private",
        "default_branch": raw.get("default_branch"),
        "clone_url": raw.get("http_url_to_repo"), "web_url": raw.get("web_url"),
        "archived": bool(raw.get("archived")), "provider": provider, "host": host,
    }
