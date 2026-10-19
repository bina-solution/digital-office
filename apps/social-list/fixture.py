"""social-list.fixture — the office's own tiny social network, for proving the chain end to end.

Why it exists: the chain this app is part of — digital-assets makes a logo active → social-list
updates every connected profile → the write is READ BACK — has to be proven before it touches the
owner's real Facebook. The domains app solved the same problem with a fixture DNS panel it serves
itself; this is the social version: one profile, a composer, a feed and comments, with

  * an HTTP API (`/fixture/api/...`)  — what the `social_fixture_api` adapter calls, and
  * two HTML pages (`/fixture/`, `/fixture/settings`) — what the office browser drives for the
    `social_fixture_browser` adapter, labelled the way real platforms are (Hebrew + English
    accessible names, a contenteditable composer, a hidden file input behind a button).

State is one JSON file in the app's volume. Nothing here is reachable from outside the network in a
real deployment except through the app's own authenticated route.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from pathlib import Path

STATE_DIR = Path(os.environ.get("APP_STATE_DIR", "/data"))
PATH = STATE_DIR / "fixture.json"
_lock = threading.Lock()

DEFAULT = {
    "profile": {"name": "העסק לדוגמה", "handle": "example.biz", "bio": "עסק לדוגמה ברשת הבדיקה",
                "links": ["https://example.com"], "avatar": None, "banner": None},
    "posts": [],
    "files": {},
}


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT))


def _save(d: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PATH)


def reset() -> dict:
    with _lock:
        d = json.loads(json.dumps(DEFAULT))
        _save(d)
        return d


def profile(base: str = "") -> dict:
    d = _load()
    p = dict(d["profile"])
    p["avatar_url"] = f"{base}/fixture/files/{p['avatar']}" if p.get("avatar") else None
    p["banner_url"] = f"{base}/fixture/files/{p['banner']}" if p.get("banner") else None
    p["url"] = f"{base}/fixture/"
    return p


def update_profile(changes: dict) -> dict:
    with _lock:
        d = _load()
        for k in ("name", "handle", "bio"):
            if k in changes and changes[k] is not None:
                d["profile"][k] = str(changes[k])
        if "links" in changes and changes["links"] is not None:
            d["profile"]["links"] = [str(x) for x in changes["links"]][:3]
        for k in ("avatar", "banner"):
            blob = changes.get(k)
            if blob:
                fid = _store_file(d, blob)
                d["profile"][k] = fid
        _save(d)
        return d["profile"]


def _store_file(d: dict, blob: dict) -> str:
    """blob = {data_base64, mime} → a file id kept inside the fixture's own state."""
    fid = uuid.uuid4().hex[:10]
    d["files"][fid] = {"mime": blob.get("mime") or "image/png",
                       "data_base64": blob.get("data_base64") or ""}
    # keep the fixture small: the last 12 files are enough for any test
    if len(d["files"]) > 12:
        for old in list(d["files"].keys())[:-12]:
            d["files"].pop(old, None)
    return fid


def file(fid: str) -> tuple[bytes, str] | None:
    f = (_load().get("files") or {}).get(fid)
    if not f:
        return None
    return base64.b64decode(f["data_base64"] or ""), f["mime"]


def posts(base: str = "", limit: int = 20) -> list[dict]:
    out = []
    for p in reversed(_load()["posts"][-limit:]):
        out.append({**p, "url": f"{base}/fixture/#post-{p['id']}",
                    "media": [{"kind": "image", "url": f"{base}/fixture/files/{m}"}
                              for m in p.get("media_ids") or []]})
    return out


def create_post(text: str, media: list[dict] | None = None) -> dict:
    with _lock:
        d = _load()
        ids = [_store_file(d, m) for m in (media or []) if m.get("data_base64")]
        post = {"id": uuid.uuid4().hex[:8], "text": text or "", "media_ids": ids,
                "created_at": int(time.time()), "likes": 0, "comments": []}
        d["posts"].append(post)
        d["posts"] = d["posts"][-50:]
        _save(d)
        return post


def update_post(pid: str, text: str) -> dict | None:
    with _lock:
        d = _load()
        for p in d["posts"]:
            if p["id"] == pid:
                p["text"] = text
                p["edited_at"] = int(time.time())
                _save(d)
                return p
    return None


def delete_post(pid: str) -> bool:
    with _lock:
        d = _load()
        n = len(d["posts"])
        d["posts"] = [p for p in d["posts"] if p["id"] != pid]
        _save(d)
        return len(d["posts"]) < n


def comments(pid: str) -> list[dict] | None:
    for p in _load()["posts"]:
        if p["id"] == pid:
            return p.get("comments") or []
    return None


def add_comment(pid: str, text: str, reply_to: str | None = None) -> dict | None:
    with _lock:
        d = _load()
        for p in d["posts"]:
            if p["id"] == pid:
                c = {"id": uuid.uuid4().hex[:8], "text": text, "reply_to": reply_to,
                     "created_at": int(time.time())}
                p.setdefault("comments", []).append(c)
                _save(d)
                return c
    return None


def delete_comment(cid: str) -> bool:
    with _lock:
        d = _load()
        for p in d["posts"]:
            before = len(p.get("comments") or [])
            p["comments"] = [c for c in p.get("comments") or [] if c["id"] != cid]
            if len(p["comments"]) < before:
                _save(d)
                return True
    return False


def like(pid: str) -> dict | None:
    with _lock:
        d = _load()
        for p in d["posts"]:
            if p["id"] == pid:
                p["likes"] = int(p.get("likes") or 0) + 1
                _save(d)
                return p
    return None


def insights() -> dict:
    d = _load()
    return {"posts": len(d["posts"]),
            "likes": sum(int(p.get("likes") or 0) for p in d["posts"]),
            "comments": sum(len(p.get("comments") or []) for p in d["posts"])}
