"""git.proxy — the smart-HTTP git proxy: real `git` from inside the platform, without the token.

The problem it solves. An account's token lives in the credential plane and must STAY there
(ai/context/platform-service-contract.md §5a: credentials never cross into the orchestration layer,
only ops and readiness do). But code work is not an op — the office agent has to run `git clone`,
`git fetch` and `git push` against a real remote, and every one of those needs the credential at the
moment of the transfer. Handing the agent a token to satisfy that is exactly the crossing the
invariant forbids, and it also means the secret lands in `.git/config`, in a shell history and in
whatever the agent decided to print.

So the app becomes the remote. Git speaks "smart HTTP": the client asks
`…/info/refs?service=git-upload-pack`, then POSTs to `…/git-upload-pack` (fetch) or
`…/git-receive-pack` (push). This module forwards those four shapes upstream, injects the account's
token server-side, and streams both bodies through WITHOUT buffering — which is why it is httpx and
not requests: a push of a large pack must not sit whole in this container's 192M.

The URL the agent uses never contains a secret, because there is none to contain:

    http://git:8978/git/gh/<account-id>/<owner>/<repo>.git
    http://git:8978/git/gl/<account-id>/<group>/<subgroup>/<repo>.git

The account is IN the URL on purpose: a remote that silently follows "the active account" would push
to whichever account was last selected in a browser tab, which is the kind of bug that is discovered
by a force-push to the wrong repository.
"""
from __future__ import annotations

import base64
import logging
import os
import re

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

import accounts
from credentials import CredentialError, credential_for

log = logging.getLogger("git.proxy")

router = APIRouter()

# The provider's short code in the URL. Short, because this part of the path is typed by hand (and
# by agents) into remotes. `lc` is the LOCAL forge — the same door as any other provider on purpose:
# a mirror is cloned from one account and pushed to another THROUGH this proxy, which is what keeps
# every third-party token out of Forgejo's own database.
CODES = {"gh": "github", "gl": "gitlab", "any": "generic", "lc": "forgejo"}
CODE_OF = {v: k for k, v in CODES.items()}
UPSTREAM = {"github": "https://github.com", "gitlab": "https://gitlab.com",
            # In-network address of the office's forge. A provider with no host in its secret falls
            # back here; a forge somewhere else sets `base_url` (see _upstream_base).
            "forgejo": os.environ.get("FORGE_URL", "http://forge:3000").rstrip("/")}
REPO_RE = re.compile(r"^[A-Za-z0-9._~%/-]+$")


class GitProxyError(Exception):
    """A credential problem in the middle of a transfer — reported as a git-visible HTTP status."""

    def __init__(self, he_message: str, status: int = 401):
        super().__init__(he_message)
        self.he_message = he_message
        self.status = status
ADV = {"upload": "application/x-git-upload-pack-advertisement",
       "receive": "application/x-git-receive-pack-advertisement"}
RESULT = {"upload": "application/x-git-upload-pack-result",
          "receive": "application/x-git-receive-pack-result"}

# Hop-by-hop and negotiation headers that must NOT be forwarded verbatim: forwarding
# `Accept-Encoding` lets the upstream gzip the advertisement while we hand back a body we did not
# decode (or decode it and leave the header), and git reports "invalid response" — the classic
# silent failure of a hand-rolled proxy. We ask for identity and pass bytes through untouched.
DROP_REQ_HEADERS = {"host", "authorization", "accept-encoding", "connection", "content-length",
                    "expect", "cookie", "proxy-authorization"}
PASS_RESP_HEADERS = {"content-type", "cache-control", "expires", "pragma"}


def _auth_header(user: str, password: str) -> str:
    """Git over HTTPS takes BASIC auth, and the username is NOT cosmetic: GitHub wants
    `x-access-token` (or any non-empty name) with the token as the password, GitLab wants `oauth2`,
    and a GitLab deploy token wants its own username with the token as the password. A bearer header
    is not honoured by these git endpoints — which is why credentials.py resolves the PAIR and this
    function only encodes it.
    """
    raw = f"{user}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _resolve(code: str, account_id: str) -> tuple[dict, dict, dict | None]:
    """(instance, secret, error-response) for one proxy call. Never falls back to the active account."""
    provider = CODES.get(code)
    if not provider:
        return {}, {}, JSONResponse({"error": f"ספק לא מוכר בכתובת: {code!r}"}, status_code=404)
    inst, sec, err = accounts.resolve(account_id)
    if err:
        return {}, {}, JSONResponse({"error": err}, status_code=409)
    actual, _kind = accounts.provider_kind(inst.get("protocol") or "")
    if actual != provider:
        return {}, {}, JSONResponse(
            {"error": f"החשבון {account_id} אינו חשבון {provider}."}, status_code=409)
    return inst, sec or {}, None


def _upstream_base(provider: str, secret: dict) -> str:
    """The host a repository lives on. Absent host = the provider's public one; a generic account has
    no default at all — its host IS the account. `base_url` is the same idea spelled for an account
    that lives INSIDE the platform (the local forge), where "host" would be an in-network URL."""
    host = (secret.get("host") or secret.get("base_url") or "").strip().strip("/")
    if not host:
        return UPSTREAM.get(provider, "")
    if host.lower().startswith("http"):
        return host.rstrip("/")
    return f"https://{host}"


def _headers_for(provider: str, secret: dict, request: Request, cid: str | None = None) -> dict:
    """Build the upstream headers. The credential is resolved HERE — per request — so an expiring
    credential (a GitHub App's hour, a refreshed OAuth token) is re-minted when it needs to be
    rather than at container start."""
    try:
        cred = credential_for(provider, secret, cid)
    except CredentialError as e:
        raise GitProxyError(e.he_message, status=e.status)
    h = {
        "Authorization": _auth_header(cred.git_user, cred.git_password),
        "User-Agent": "git/bina-office-proxy",
        # The client's own Accept, not `*/*`: it is how a git client declares which of the two
        # result types it expects, and the provider echoes it back in the negotiation.
        "Accept": request.headers.get("accept") or "*/*",
        "Accept-Encoding": "identity",
    }
    # THE BODY IS FORWARDED VERBATIM, so the headers that DESCRIBE it have to come with it. Measured
    # 2026-09-29, and it is a size-triggered bug that hides on every small repository:
    #
    #   git gzips the upload-pack request once it grows past a few hundred bytes and sends
    #   `Content-Encoding: gzip` with `Content-Type: application/x-git-upload-pack-request`. A proxy
    #   that rebuilds the header set from scratch drops both, so GitHub receives gzip bytes it has no
    #   reason to decompress, and answers `HTTP 400` with an EMPTY BODY — "expected 'packfile'" in the
    #   client, and nothing at all in the log. Small repos clone perfectly; large ones cannot be
    #   cloned at all, which is exactly the shape of failure that looks like a provider problem.
    for hdr in ("content-type", "content-encoding"):
        v = request.headers.get(hdr)
        if v:
            h[hdr.title()] = v
    # Protocol v2 is negotiated with this header; the client's own value is forwarded so the
    # negotiation we proxy is the one the client asked for.
    proto = request.headers.get("git-protocol")
    if proto:
        h["Git-Protocol"] = proto
    return h


def _repo_path(repo_path: str) -> str | None:
    path = (repo_path or "").strip("/")
    if not path or ".." in path or not REPO_RE.match(path):
        return None
    return path


async def _proxy(request: Request, code: str, account_id: str, repo_path: str,
                 kind: str) -> Response:
    """One proxied exchange. `kind` is upload (fetch/clone) or receive (push)."""
    inst, sec, bad = _resolve(code, account_id)
    if bad is not None:
        return bad
    path = _repo_path(repo_path)
    if not path:
        return JSONResponse({"error": "נתיב מאגר לא תקין."}, status_code=400)
    provider = CODES[code]

    if kind == "receive" and sec.get("readonly"):
        # Refuse BEFORE contacting the provider, so a read-only account cannot be pushed to even by
        # a client that ignored the advertisement.
        return Response("החשבון מוגדר לקריאה בלבד — דחיפה נדחתה.", status_code=403,
                        media_type="text/plain; charset=utf-8")

    base = _upstream_base(provider, sec)
    # The tail is the git verb, and the query (for `info/refs`) carries the service. Both are
    # forwarded untouched: a proxy that "normalizes" `?service=` breaks the handshake silently.
    tail = "info/refs" if request.url.path.endswith("/info/refs") \
        else request.url.path.rsplit("/", 1)[-1]
    url = f"{base}/{path}/{tail}"
    if request.url.query:
        url += f"?{request.url.query}"
    try:
        headers = _headers_for(provider, sec, request, inst.get("id"))
    except GitProxyError as e:
        return Response(e.he_message, status_code=e.status,
                        media_type="text/plain; charset=utf-8")

    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0),
                               follow_redirects=False)
    try:
        if request.method == "GET":
            up = client.build_request("GET", url, headers=headers)
        else:
            up = client.build_request("POST", url, headers=headers,
                                      content=request.stream())
        resp = await client.send(up, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("upstream %s failed: %s", url, type(e).__name__)
        return JSONResponse({"error": "לא ניתן להגיע לספק."}, status_code=502)

    if resp.status_code in (401, 403):
        await resp.aclose()
        await client.aclose()
        # No WWW-Authenticate on purpose: with one, git stops and PROMPTS for a username, and a
        # prompt inside a container is a hang, not a question. Fail loudly instead.
        return Response(f"הספק דחה את האימות (HTTP {resp.status_code}) עבור {path}.",
                        status_code=403, media_type="text/plain; charset=utf-8")
    if resp.status_code >= 400:
        body = await resp.aread()
        await resp.aclose()
        await client.aclose()
        # LOG the provider's own words on the way past. A git client prints "HTTP 400" and nothing
        # else, so without this line the cause of a failed clone exists only inside a response body
        # nobody can see — the exact "opaque failure" this app is not allowed to produce. Truncated:
        # this is a diagnostic, not a copy of the response.
        log.warning("upstream %s → HTTP %s: %s", url, resp.status_code,
                    body[:500].decode("utf-8", errors="replace").replace("\n", " "))
        return Response(body, status_code=resp.status_code,
                        media_type=resp.headers.get("content-type", "text/plain"))

    out = {k: v for k, v in resp.headers.items() if k.lower() in PASS_RESP_HEADERS}
    out.setdefault("Content-Type", ADV[kind] if request.url.path.endswith("/info/refs")
                   else RESULT[kind])
    out["Cache-Control"] = "no-cache"

    async def body():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(body(), status_code=resp.status_code, headers=out)


@router.get("/{code}/{account_id}/{repo_path:path}/info/refs")
async def info_refs(request: Request, code: str, account_id: str, repo_path: str):
    service = request.query_params.get("service") or ""
    kind = "receive" if service.endswith("git-receive-pack") else "upload"
    return await _proxy(request, code, account_id, repo_path, kind)


@router.post("/{code}/{account_id}/{repo_path:path}/git-upload-pack")
async def upload_pack(request: Request, code: str, account_id: str, repo_path: str):
    return await _proxy(request, code, account_id, repo_path, "upload")


@router.post("/{code}/{account_id}/{repo_path:path}/git-receive-pack")
async def receive_pack(request: Request, code: str, account_id: str, repo_path: str):
    return await _proxy(request, code, account_id, repo_path, "receive")


def remote_url(account_id: str, provider: str, repo: str) -> str:
    """The remote to hand to a git client — in-network address, no credential in it."""
    code = CODE_OF.get(provider)
    if not code:
        raise GitProxyError(f"אין תמיכה בספק {provider!r} בפרוקסי.", status=400)
    return f"http://git:8978/git/{code}/{account_id}/{repo.strip('/')}.git"
