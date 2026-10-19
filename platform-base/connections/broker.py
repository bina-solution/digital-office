"""broker — the credential plane stops being a file server and becomes a broker.

Before this module, `connections` answered `GET /api/export/<service>` and `GET /api/export-all` to
anybody who could open a socket to it: zero app-layer auth in a thousand lines (security-plan-2026
B1, proven live). Six apps additionally carried standing plaintext grants in their environment, so
`docker exec` into any one of them yielded every credential it held, permanently and silently.

Three independent systems solved this the same way — Flatpak portals, macOS Powerbox, and
Vault+SPIFFE — and the shape they agree on is what is implemented here:

  * **out of process** — the thing that holds the secret is not the thing that wants it, so
    compromising the app does not yield the vault (`identity.py` names the caller from OUTSIDE the
    request, over the docker socket; nothing the caller sends decides who it is).
  * **narrow** — a caller receives only the connections its own `app.json` declares. The manifest is
    the capability list; anything not in it is refused, in every mode, including to callers the
    broker cannot even identify.
  * **short-lived and revocable** — `POST /api/broker/token` mints a single-use capability that
    expires in seconds, so a leased value need not be a standing one.
  * **every grant logged** — an append-only, fsync'd JSONL beside the vault, readable at
    `GET /api/broker/audit`. This is the `flatpak permissions` equivalent: a platform where you
    cannot enumerate who was given what is not auditable, whatever else it does.

MODES (`CONN_BROKER_MODE`) — the 3-phase rollout the security plan asks for, because every consumer
boots by calling this service and flipping straight to enforce would strand the estate:

    warn    (default) an UNIDENTIFIED caller is still served, and logged as such. An IDENTIFIED
            caller is held to the full policy — so cross-app theft is already impossible here.
    enforce an unidentified caller is refused. Everything else identical.
    off     legacy behaviour, policy skipped, still fully logged. Escape hatch, not a destination.

The rules below are enforced in warn as well as enforce; only the treatment of "I cannot tell who
you are" differs between the two. That is deliberate: a broker whose warn mode grants indox the
right to ask for drive's secrets would be theatre.
"""
import json
import os
import secrets
import threading
import time

from flask import jsonify, request

import identity

MODE = (os.environ.get("CONN_BROKER_MODE") or "warn").strip().lower()
if MODE not in ("warn", "enforce", "off"):
    MODE = "warn"

DATA_DIR = os.environ.get("CONN_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data")
GRANT_LOG = os.path.join(DATA_DIR, "grants.jsonl")
GRANT_LOG_MAX = int(os.environ.get("CONN_AUDIT_MAX_BYTES", str(8 * 1024 * 1024)))
TOKEN_TTL = int(os.environ.get("CONN_BROKER_TOKEN_TTL", "90"))
LEASE_TTL = int(os.environ.get("CONN_BROKER_LEASE_TTL", "3600"))

# The container id a caller presents as its second factor (see identity.py).
ID_HEADER = "X-Conn-Container"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


# ── audit: append-only, fsync'd, OUTSIDE the vault ────────────────────────────
# The pre-existing `_audit()` in app.py appends to a list inside the encrypted vault, caps it at 500
# and rewrites the whole file per event — so a busy grant path both loses history and multiplies the
# chance of clobbering the vault itself. Grants go to their own file: one line per event, opened in
# append mode (atomic for writes under PIPE_BUF on POSIX), flushed and fsync'd, so a `docker kill`
# cannot lose the record of a secret that was already handed out. It lives on the connections_vault
# volume, so it survives container replacement.
_audit_lock = threading.Lock()


def _rotate_if_needed():
    try:
        if os.path.getsize(GRANT_LOG) < GRANT_LOG_MAX:
            return
        os.replace(GRANT_LOG, GRANT_LOG + ".1")
    except OSError:
        pass


def audit(event, decision, ident, **extra):
    """Record one brokered decision. Never raises — a failing log must not fail the request, but it
    IS reported through /api/broker/policy so a silently unlogged broker is visible."""
    rec = {
        "t": round(time.time(), 3),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "decision": decision,
        "mode": MODE,
        "service": (ident or {}).get("service") or "",
        "method": (ident or {}).get("method") or "none",
        "container": (ident or {}).get("container_name") or "",
        "container_id": ((ident or {}).get("container_id") or "")[:12],
        "ip": (ident or {}).get("ip") or "",
        **extra,
    }
    try:
        with _audit_lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            _rotate_if_needed()
            with open(GRANT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        _stats["written"] += 1
    except OSError as e:
        _stats["failed"] += 1
        _stats["last_error"] = f"{type(e).__name__}: {e}"
    return rec


_stats = {"written": 0, "failed": 0, "last_error": None}


def read_audit(limit=200, service=None, decision=None):
    """Newest-first slice of the grant log. Reads the rotated file too when the live one is short,
    so `bbox`/the UI never silently shows an empty history right after a rotation."""
    lines = []
    for path in (GRANT_LOG, GRANT_LOG + ".1"):
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines() + lines
        except OSError:
            continue
    out = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if service and rec.get("service") != service:
            continue
        if decision and rec.get("decision") != decision:
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


# ── identity ──────────────────────────────────────────────────────────────────
def caller():
    """Identify the current request's caller. Loopback is treated as the operator (the CLI runs via
    `docker exec` INSIDE this container, so it arrives on 127.0.0.1 and no docker lookup can name
    it) — it is the one caller that is already inside the trust boundary by construction."""
    addr = request.remote_addr or ""
    if addr in LOOPBACK:
        return {"ok": True, "method": "loopback", "service": "connections", "app": "connections",
                "container_id": "", "container_name": "connections(local)", "ip": addr,
                "reason": "request originated inside the connections container"}
    return identity.identify(addr, request.headers.get(ID_HEADER))


# ── policy ────────────────────────────────────────────────────────────────────
class Refusal(Exception):
    """A brokered request that must not be served. Carries the audited reason verbatim."""

    def __init__(self, reason, status=403):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def authorize(ident, want_service, declared_for):
    """Decide which service's capability list this call runs under.

    `declared_for(service) -> [{"id":…,"required":…}, …]` is the compiled manifest lookup (each
    app's own `connections[]`). Returns (service, declared_ids).

    Refusals that hold in EVERY mode:
      · a claimed container id that does not own the source address (spoof-suspected)
      · asking for a service other than the one you are
      · asking for a service that declares nothing
    """
    if ident.get("method") == "spoof-suspected":
        raise Refusal("container-id/address mismatch: " + ident.get("reason", ""))

    if ident.get("ok") and ident.get("method") != "loopback":
        svc = ident.get("service") or ""
        if want_service and want_service != svc:
            raise Refusal(
                f"caller is compose service '{svc}' but requested secrets for '{want_service}' — "
                f"an app may only request its own declared connections")
        want_service = want_service or svc
    elif not ident.get("ok"):
        if MODE == "enforce":
            raise Refusal("caller could not be identified: " + (ident.get("reason") or "unknown"))
        if not want_service:
            raise Refusal("caller could not be identified and named no service", status=400)

    if not want_service:
        raise Refusal("no service to resolve", status=400)
    declared = declared_for(want_service)
    if not declared:
        raise Refusal(f"'{want_service}' declares no connections[] in its app.json — nothing to grant")
    return want_service, [d["id"] for d in declared]


def narrow(requested, declared_ids, service):
    """Intersect what was asked for with what the manifest declares. Undeclared ids are REFUSED
    individually (and named), never silently dropped — 'you asked for something you never declared'
    is the single most useful line in an audit log."""
    if not requested:
        return list(declared_ids), []
    allowed, refused = [], []
    for cid in requested:
        (allowed if cid in declared_ids else refused).append(cid)
    return allowed, [{"id": cid,
                      "reason": f"'{cid}' is not in {service}'s declared connections[]"}
                     for cid in refused]


# ── short-lived capabilities ──────────────────────────────────────────────────
# A minted token is a NARROW, SINGLE-USE, EXPIRING capability for one connection of one service —
# the "result is narrow and revocable" half of the portal design. In-memory on purpose: connections
# runs one process, and a capability that does not survive a broker restart is a feature (restart =
# mass revocation). If this ever runs multi-worker, this dict moves to the vault.
_tokens = {}
_tokens_lock = threading.Lock()


def mint_token(service, cid, ident):
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with _tokens_lock:
        for t, rec in list(_tokens.items()):          # opportunistic sweep
            if rec["exp"] < now:
                del _tokens[t]
        _tokens[tok] = {"service": service, "cid": cid, "exp": now + TOKEN_TTL,
                        "container_id": ident.get("container_id", "")}
    return tok, TOKEN_TTL


def redeem_token(tok, ident):
    """Single use. A token is consumed whether or not the redeemer turns out to be entitled to it,
    so a leaked token cannot be replayed while the attacker searches for a usable caller."""
    with _tokens_lock:
        rec = _tokens.pop(tok, None)
    if not rec:
        raise Refusal("unknown or already-redeemed capability token", status=404)
    if rec["exp"] < time.time():
        raise Refusal("capability token expired")
    if ident.get("ok") and ident.get("method") != "loopback" and ident.get("service") != rec["service"]:
        raise Refusal(f"token was minted for '{rec['service']}', redeemed by '{ident.get('service')}'")
    return rec


def revoke_all():
    with _tokens_lock:
        n = len(_tokens)
        _tokens.clear()
    return n


# ── HTTP surface ──────────────────────────────────────────────────────────────
def register(app, *, declared_for, export_env, instance_protocol=None):
    """Attach the broker routes to the connections Flask app.

    Dependencies are injected rather than imported so this module never reaches back into app.py
    (which owns the vault, the catalog and the resolve chain) — the import graph stays one-way and
    this file stays testable on its own.

        declared_for(service)       -> [{"id":…, "required":…}, …]   the compiled manifest
        export_env(service, only)   -> {ENV_KEY: value, …}           the resolve chain
    """

    def _refuse(e, event, ident, **extra):
        rec = audit(event, "refuse", ident, reason=e.reason, **extra)
        return jsonify(error=e.reason, decision="refuse", mode=MODE,
                       identity={k: rec[k] for k in ("service", "method", "container", "ip")}), e.status

    @app.get("/api/broker/whoami")
    def broker_whoami():
        """What the broker thinks you are. No secrets — the endpoint you use to PROVE identity
        resolution works before trusting anything built on it."""
        ident = caller()
        declared = declared_for(ident.get("service") or "") if ident.get("ok") else []
        audit("whoami", "allow" if ident.get("ok") else "unidentified", ident)
        return jsonify(mode=MODE, docker=identity.docker_available(), identity=ident,
                       declares=[d["id"] for d in declared])

    @app.get("/api/broker/policy")
    def broker_policy():
        """Broker configuration + audit-writer health, so 'is anything actually being logged?' is a
        question with an answer."""
        size = None
        try:
            size = os.path.getsize(GRANT_LOG)
        except OSError:
            pass
        return jsonify(mode=MODE, docker=identity.docker_available(),
                       token_ttl_seconds=TOKEN_TTL, lease_ttl_seconds=LEASE_TTL,
                       id_header=ID_HEADER, grant_log=GRANT_LOG, grant_log_bytes=size,
                       audit_written=_stats["written"], audit_failed=_stats["failed"],
                       audit_last_error=_stats["last_error"],
                       live_tokens=len(_tokens))

    @app.get("/api/broker/audit")
    def broker_audit():
        """The `flatpak permissions` equivalent: who was granted what, when, allowed or refused."""
        try:
            limit = min(int(request.args.get("limit", 200)), 2000)
        except ValueError:
            limit = 200
        return jsonify(mode=MODE, grants=read_audit(limit, request.args.get("service"),
                                                    request.args.get("decision")))

    @app.post("/api/broker/lease")
    def broker_lease():
        """The injector's entry point. Body: {"service": optional, "connections": optional [ids]}.

        Identity decides the service; `service` in the body is only ever a cross-check, and a
        mismatch is a refusal rather than an override."""
        body = request.get_json(silent=True) or {}
        ident = caller()
        want = (body.get("service") or "").strip() or None
        try:
            svc, declared = authorize(ident, want, declared_for)
        except Refusal as e:
            return _refuse(e, "lease", ident, requested_service=want)
        allowed, refused = narrow(body.get("connections"), declared, svc)
        for r in refused:
            audit("lease", "refuse", ident, service_requested=svc, connection=r["id"],
                  reason=r["reason"])
        env = export_env(svc, only=allowed)
        lease = secrets.token_urlsafe(12)
        for cid in allowed:
            audit("lease", "allow", ident, service_requested=svc, connection=cid, lease=lease,
                  unidentified=not ident.get("ok"))
        return jsonify(lease=lease, service=svc, mode=MODE, granted=sorted(allowed),
                       refused=refused, expires_at=int(time.time()) + LEASE_TTL,
                       identity={k: ident.get(k) for k in ("method", "service", "container_name")},
                       env=env)

    @app.post("/api/broker/token")
    def broker_token():
        """Mint a single-use, seconds-lived capability for ONE connection. For callers that can
        fetch on demand instead of holding a value for the process lifetime."""
        body = request.get_json(silent=True) or {}
        cid = (body.get("connection") or "").strip()
        ident = caller()
        try:
            svc, declared = authorize(ident, (body.get("service") or "").strip() or None, declared_for)
            if not cid:
                raise Refusal("body must name one {connection: id}", status=400)
            if cid not in declared:
                raise Refusal(f"'{cid}' is not in {svc}'s declared connections[]")
        except Refusal as e:
            return _refuse(e, "token", ident, connection=cid)
        tok, ttl = mint_token(svc, cid, ident)
        audit("token", "allow", ident, service_requested=svc, connection=cid, ttl=ttl)
        return jsonify(token=tok, connection=cid, service=svc, expires_in=ttl,
                       redeem=f"/api/broker/redeem/{tok}")

    @app.get("/api/broker/redeem/<tok>")
    def broker_redeem(tok):
        ident = caller()
        try:
            rec = redeem_token(tok, ident)
        except Refusal as e:
            return _refuse(e, "redeem", ident)
        env = export_env(rec["service"], only=[rec["cid"]])
        audit("redeem", "allow", ident, service_requested=rec["service"], connection=rec["cid"])
        return jsonify(connection=rec["cid"], service=rec["service"], env=env)

    @app.post("/api/broker/revoke")
    def broker_revoke():
        """Revoke every live capability token (the panic button). Loopback/operator only."""
        ident = caller()
        if ident.get("method") != "loopback":
            return _refuse(Refusal("revoke is an operator action (loopback only)"), "revoke", ident)
        n = revoke_all()
        audit("revoke", "allow", ident, revoked=n)
        return jsonify(revoked=n)

    return app


# ── policy for the two legacy routes ──────────────────────────────────────────
def guard_export(service, declared_for):
    """Policy for the pre-existing `GET /api/export/<service>`, so migrating an app does not mean
    losing the old route's protection. Returns (ident, service) or raises Refusal."""
    ident = caller()
    svc, _declared = authorize(ident, service, declared_for)
    return ident, svc


def guard_export_all():
    """`/api/export-all` returns EVERY secret in the estate. It is the exact endpoint the documented
    kill chain uses (email -> SSRF -> export-all -> AUTHENTIK_SECRET_KEY -> forged admin session),
    and nothing in the repo calls it over the network — only `cli.py`, from inside this container.

    So it is not policy-checked, it is CLOSED: loopback only, in every mode except `off`. There is no
    per-service narrowing that makes 'here is everything' safe to hand across the network."""
    ident = caller()
    if MODE != "off" and ident.get("method") != "loopback":
        raise Refusal("export-all is loopback-only — use POST /api/broker/lease for a service's "
                      "own declared connections")
    return ident
