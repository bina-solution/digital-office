#!/usr/bin/env python3
"""mail-connection-lint — gate G62: every AUTOMATION call into apps/mail's canonical ops names its
connection explicitly.

    python3 scripts/refactor/mail-connection-lint.py [--self-test]

WHY THIS GATE EXISTS

`apps/mail/mailapi` resolves a missing `connection_id` to whatever this deployment's console happens
to be bound to: `adapters.resolve_active` is

    cid = connection_id or cc.active() or cc.default_id()

where `cc.active()` reads `/data/active.json` — a single shared file holding one id, flipped by a
human clicking the account bar (`POST /connections/select`) and by any test run that needs a
different mailbox. It is the SAME ambient-binding defect `apps/drive` closed on 2026-08-06 with
`_explicit_connection_required` (gate G46), and it is live on the mail side today:

  1. `data/registry/sync_registry.json`'s `mail-private` row declares
     `connection_id: "mail_imap_local-local"` — an id that has not existed since the synthetic local
     instance was removed. `adapters.py` silently REMAPS that exact string to
     `cc.active() or cc.default_id()`, so the pipe named *private* has been reading whatever the
     pointer names. Measured 2026-08-07: 26 REAL client documents (777 אקססוריס, מבנה דרום חדש,
     קיסנר, פלסאון, סופר מנחם, אם טי אי — real invoices, real COMPANY_IDs) were ingested under
     `SYNC_NAME='mail-private'` from the CLIENT's Gmail, alongside 6 rows genuinely from the private
     mailbox. Both id shapes appear in the same pipe because the pointer moved underneath it.
  2. `SyncSource000001`'s `Resolve` node builds an explicit `identity` for `source==='drive'` and
     emits NOTHING for `source==='gmail'` — so the mailbox the registry actually declares is dropped
     at that node.
  3. `mailapi`'s access log shows the signature of the fallback directly:
     `GET /thread/<id>?connection_id=` and `GET /message/0?...&connection_id=` with the value EMPTY,
     from `gmailApiImap01`'s `|| ''` defaults.

Nothing errors on any of these. A mail op against the wrong mailbox answers just as promptly as the
right one — it returns other people's mail, or nothing, and an unattended pipeline treats that as
ground truth. That is why reads are linted exactly like writes.

SCOPE — EVERY CALLER, UI INCLUDED. (REWRITTEN 2026-08-09; the previous text is kept below because
being wrong in a specific way is the finding.)

This docstring used to say:

    "SCOPE — THE AUTOMATION PLANE ONLY. The UI plane is deliberately NOT linted, for the reason
     drive's `_explicit_connection_required` states: a browser behind SSO has no other identity to
     declare, so the binding IS its identity. `apps/mail/mailapi/static/app.js` and
     `apps/mail/mailview/**` are that plane and are out of scope here."

That is DRIVE's scope, copied onto MAIL, and mail's contract is deliberately wider. `apps/drive/app.py`
does exempt its `/api/*` UI plane; `apps/mail/mailapi/service.py` explicitly does NOT — the owner
considered that exemption and overruled it on 2026-08-07: "no fallbacks or so-called selected
connection at mail app level. we might have a selected connection but even then it's two separate
calls — one to get the selected connection, one to act — never act blindly." So the mail service
REFUSES a UI-triggered canonical op with no id, exactly like an n8n one.

The cost of the copied sentence was an outage. `apps/mail/mailview` (a SEPARATE compose service that
reaches mailapi over HTTP — not the service, a client of it) had twelve canonical-op call sites
carrying no id. The guard landed, every one of them started 400ing, and the client's whole mail page
went to 500. This gate was watching for exactly that and saw none of it, for three independent
reasons, each of which is now a fixed hole:

  1. GLOB. The Python scan roots were `apps/*/app/**/*.py` + `scripts/**/*.py`. `apps/*/app/**`
     matches `apps/indox/app/…` and NOTHING ELSE in this repo — 47 of the 209 first-party app
     `.py` files, one app out of fourteen. `apps/mail/mailview/app.py` is not under a directory
     named `app`, so it was never opened. A gate reporting zero because it is looking at an empty
     set reads identically to a gate reporting zero because the tree is clean.
  2. SERVICE EXCLUSION TOO WIDE. `scan_python` skipped `apps/mail/` wholesale as "the service".
     The service is `apps/mail/mailapi/`. `mailview` and `mailboxd` are their own containers and
     are CALLERS; excluding the app directory excluded them with it.
  3. HELPER-BLINDNESS. The scan only recognised a literal `requests.get|post("<canonical path>")`.
     `mailview` reaches mailapi through one `gi()` proxy helper, so there is no literal
     `requests.post(".../labels/add")` anywhere in the file — twelve real call sites in a shape the
     regex could not represent.

WHAT COUNTS AS A VIOLATION
  * an n8n `executeWorkflow` node whose `workflowId` names a mail op router/client
    (`gmailApiImap01`, `gmailApiImap01` — see MAIL_OP_WORKFLOWS) and whose workflowInputs
    expression does not mention `connection_id` anywhere;
  * an n8n `httpRequest` node calling a mailapi canonical-op path directly on a mail host whose URL
    or body does not mention `connection_id` — INCLUDING one that mentions it but can only ever send
    an empty value (`connection_id={{ ... || '' }}` with no other source), which is the fallback
    spelled out rather than avoided;
  * a first-party Python `requests`/`httpx` call to one of those paths on a mail host that does not
    mention `connection_id` within the same statement;
  * a first-party Python MAIL PROXY HELPER (a function that issues `requests`/`httpx` at a mailapi
    base URL) that does not itself attach a `connection_id` — reported ONCE on the helper plus once
    per canonical-op call site it serves, because that is where the fix goes;
  * (sibling check, see `_opaque_proxy_reason`) a mail proxy helper that ends in a bare
    `raise_for_status()` outside any `try`. This one is not about the mailbox — it is about why the
    mailbox bug was INVISIBLE: `raise_for_status()` raises an `HTTPError` whose message carries the
    status and NOT the body, so mailapi's actionable 400 ("this operation requires an explicit
    connection_id — none was passed. Available connections: …") became an opaque Flask 500 with
    nothing in the proxy's own log. The diagnosis existed and was thrown away one hop from the
    person reading the log.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

#: apps/mail/mailapi/adapters.py CANONICAL_OPS + the connection-scoped settings loader. These are the
#: paths an automated caller reaches; `/connections*`, `/engine/profiles*`, `/mailboxes*`, `/ui/*`
#: and `/providers` are console surfaces and are NOT linted.
#:
#: `/organizer/settings` WAS on this list and was REMOVED 2026-08-09. It is not a canonical op: the
#: route never calls `_backend`, never opens an IMAP connection and never touches a message — with
#: no id it serves the mail-scoped DEFAULTS singleton (`options.get_defaults()`), a document in its
#: own right and not the active connection's options. `service.py`'s own docstring says so and names
#: the consequence of getting this wrong: "Requiring an id there would only break
#: `mailLabelEngine01`'s three `Load Settings` nodes for no safety gain." This gate was demanding an
#: id the SERVICE deliberately does not want, on three nodes that are correct as written. That is
#: the false-positive face of the same defect as the glob hole — the gate's model of the contract
#: drifting from the contract — and three permanent false findings are how a gate stops being read.
CANONICAL_PATHS = ("/search", "/message", "/thread", "/labels/add", "/labels/remove",
                   "/labels/create", "/labels/delete", "/labels", "/append", "/send")

#: The n8n sub-workflows that ARE the mail op surface. A call into one of these is a mail op call.
#: (`gmailApiRouter01`, the 3-node passthrough, was retired 2026-09-02 — nothing called it.)
MAIL_OP_WORKFLOWS = {"gmailApiImap01"}

#: Their own definition files forward the CALLER's `params` object blindly
#: (`jsonBody: "={{ $json.params }}"`), exactly like driveApi01.json does for drive. The id, if any,
#: lives in the caller's params and is checked there — flagging these would be a false positive on
#: the plumbing rather than on a caller that forgot something.
MAIL_OP_DEFINITIONS = {
    "apps/mail/blueprint/n8n/gmailApiImap01.workflow.ts",
}

_ID_MENTION = re.compile(r"\bconnection_id\b")

#: `connection_id={{ <anything> || '' }}` / `connection_id: $x.connection_id || ""` with no other
#: mention — the field is present but its ONLY possible value when the caller omits it is the empty
#: string, which mailapi treats as absent and resolves through the ambient pointer. This is the
#: exact shape in gmailApiImap01's `http:get` / `http:listLabels` / `http:getThread` URLs and it is
#: what produces the empty `connection_id=` in the access log. Reported as its own kind so the fix
#: is obvious: the caller must supply one, not the callee default it away.
#: Lazy, same-line, bounded: from a `connection_id=` / `connection_id:` to the first `|| ''` that
#: follows it. It must be able to cross a nested `{}` — the real shape is
#: `connection_id={{ ($json.params || {}).connection_id || '' }}`, where an expression that stops at
#: the first `}` never reaches the default it is looking for (the bug this comment exists to record).
_EMPTY_ONLY = re.compile(r"""connection_id[=:][^\n]{0,90}?\|\|\s*(['"])\1""")

#: `...(<cond> ? { connection_id: <x> } : {})` — a CONDITIONAL SPREAD. The field is named, so a
#: plain "does it mention connection_id" test passes it, but when the condition is falsy the key is
#: OMITTED ENTIRELY and mailapi resolves through /data/active.json. Behaviourally identical to the
#: `|| ''` default above, and identical to not passing one at all.
#:
#: THIS WAS THE GATE'S OWN FALSE CLEAN (found 2026-08-09). `_EMPTY_ONLY` was only ever applied to
#: httpRequest nodes; the executeWorkflow branch returned on a bare `_ID_MENTION` hit. So
#: syncV3Deliver0001's `Get Message`/`Get Link Msg` and the three Gmail downloaders — every one of
#: them a conditional spread — were reported as compliant, while mailapi's access log showed them
#: emitting `connection_id=` EMPTY and 404ing on messages that resolve fine with an explicit id.
#: The gate certified as correct the exact shape the owner's rule forbids ("never act blindly, no
#: fallbacks"). Same defect class as G41's false clean: the scan matched a NAME, not a BEHAVIOUR.
#:
#: Bounded and non-greedy so it cannot leap across unrelated ternaries; the false arm must be an
#: EMPTY object literal, which is what makes the key vanish rather than take another value.
_OPTIONAL_SPREAD = re.compile(r"""\?\s*\{[^{}]{0,140}?connection_id[^{}]{0,200}?\}\s*:\s*\{\s*\}""")


def _id_is_optional(text: str) -> str | None:
    """Return a reason when connection_id is NAMED but can still reach mailapi absent/empty."""
    if _OPTIONAL_SPREAD.search(text):
        return ("connection_id is spread in CONDITIONALLY (`cond ? {connection_id: x} : {}`) — when "
                "the source value is falsy the key is omitted entirely and the mailbox falls back "
                "to /data/active.json")
    if _EMPTY_ONLY.search(text):
        return ("connection_id is present but defaults to '' — an empty value is resolved through "
                "the ambient pointer exactly like an absent one")
    return None

#: Not first-party source. NOTE what is deliberately NOT here: `tests/`. A test that drives a mail
#: op with no connection is not a lesser finding than a production one — it is G64's incident
#: verbatim (148 fixture messages delivered into the client's real Gmail between 2026-08-05 and
#: 2026-08-09, because the ops resolved through the ambient pointer). Excluding tests to keep the
#: report tidy would re-open the same class of hole this rewrite exists to close, one directory
#: over. Vendored/generated trees below are excluded because they are not ours to fix.
SKIP = ("/node_modules/", "/_archive/", "/attic/", "/legacy/", "/.git/", "/ci-artifacts/",
        "/issues/", "/.refactor/", "/context-collection/", "/__pycache__/",
        "/.venv/", "/venv/", "/site-packages/", "/dist-packages/", "/.tox/", "/.mypy_cache/",
        "/vendor/", "/third_party/", "/.pytest_cache/", "/egg-info/")


# ─────────────────────────────────────────────────────────────────────────────
# n8n scanner
# ─────────────────────────────────────────────────────────────────────────────
def _rl_value(v):
    """An n8n resourceLocator field is either a bare string or {"__rl":true,"value":...}."""
    if isinstance(v, dict):
        return v.get("value")
    return v


def _workflow_inputs_text(params: dict) -> str:
    """Every string this node's workflowInputs carries, joined."""
    wi = (params or {}).get("workflowInputs") or {}
    bits: list[str] = []

    def _walk(o):
        if isinstance(o, str):
            bits.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(wi.get("value"))
    return "\n".join(bits)


def _http_text(params: dict) -> str:
    """Every string an httpRequest node's URL + body carries. The URL matters here in a way it does
    not for drive: mail's GET ops (`/message`, `/thread`, `/labels`) carry `connection_id` as a
    QUERY PARAM, not in a body."""
    bits = [str((params or {}).get("url") or "")]
    jb = (params or {}).get("jsonBody")
    if isinstance(jb, str):
        bits.append(jb)
    for p in (((params or {}).get("bodyParameters") or {}).get("parameters") or []):
        if isinstance(p, dict):
            bits.append(str(p.get("name") or ""))
            bits.append(str(p.get("value") or ""))
    for p in (((params or {}).get("queryParameters") or {}).get("parameters") or []):
        if isinstance(p, dict):
            bits.append(str(p.get("name") or ""))
            bits.append(str(p.get("value") or ""))
    return "\n".join(bits)


def _is_mail_host(url: str) -> bool:
    u = url.lower()
    return "mailapi" in u or "mail.localhost" in u or ":8970" in u


def _hits_canonical_path(url: str) -> bool:
    """Does this URL name a mailapi canonical op? Matched on the path segment after the host, so an
    expression-built URL (`.../message/{{ ... }}?...`) still resolves."""
    u = url.split("?", 1)[0].rstrip("/").lower()
    return any(("/" + p.strip("/")) in u for p in CANONICAL_PATHS)


#: Workflows a run could not compile — counted out of what the summary line says was scanned.
UNREADABLE: list[str] = []


def scan_workflow_file(path: pathlib.Path, is_definition: bool = False) -> list[tuple[str, str, str]]:
    """[(node_name, kind, detail)] for every violation in one workflow file."""
    try:
        doc = load_blueprint(str(path))
    except (OSError, ValueError, CompileError) as e:
        print(f"  ! {path.name}: {e}")
        UNREADABLE.append(path.name)
        return []
    return scan_workflow_doc(doc, is_definition=is_definition)


def _upstream_text(doc: dict, node_name: str, hops: int = 4) -> str:
    """Every parameter string of the nodes feeding `node_name`, up to `hops` back.

    Why this exists: an `executeWorkflow` node with NO `workflowInputs` uses n8n's implicit
    item-passthrough — it forwards whatever the previous node emitted as `{op, params}`. The
    connection therefore CANNOT be on the exec node; it is built in the upstream Code node
    (`Gmail Search Req` → `Gmail Search`, `Label Req` → `Call Label`, …). Checking only the exec
    node would make every passthrough call permanently unfixable: threading the id correctly would
    not clear the gate, which is how a gate stops being read. Resolved through the workflow's own
    `connections` graph rather than "does the file mention connection_id anywhere", because that
    weaker test would clear `syncV3Deliver0001`'s four unthreaded label calls on the strength of
    `Get Message` — the sibling node that IS threaded — and hide four real violations.
    """
    rev: dict[str, list[str]] = {}
    for src, spec in (doc.get("connections") or {}).items():
        for branch in (spec.get("main") or []):
            for t in (branch or []):
                if isinstance(t, dict) and t.get("node"):
                    rev.setdefault(t["node"], []).append(src)
    by_name = {n.get("name"): n for n in (doc.get("nodes") or [])}
    seen, frontier, bits = set(), [node_name], []
    for _ in range(hops):
        nxt = []
        for cur in frontier:
            for src in rev.get(cur, []):
                if src in seen:
                    continue
                seen.add(src)
                nxt.append(src)
                n = by_name.get(src)
                if n:
                    bits.append(json.dumps(n.get("parameters") or {}, ensure_ascii=False))
        frontier = nxt
    return "\n".join(bits)


def scan_workflow_doc(doc: dict, is_definition: bool = False) -> list[tuple[str, str, str]]:
    out = []
    for node in doc.get("nodes", []) or []:
        ntype = str(node.get("type") or "")
        params = node.get("parameters") or {}
        name = str(node.get("name") or "?")

        if ntype.endswith("executeWorkflow") and not ntype.endswith("executeWorkflowTrigger"):
            if is_definition:
                # the router's OWN forwarding node (gmailApiImap01's "Call IMAP" -> gmailApiImap01):
                # blind passthrough of {op, params}, exactly like driveApi01's own d:list node. The id,
                # if any, lives in the ORIGINAL caller's params and is checked there; flagging the
                # router's plumbing against itself would be a false positive on the fix's own target.
                continue
            target = _rl_value(params.get("workflowId"))
            if target not in MAIL_OP_WORKFLOWS:
                continue
            text = _workflow_inputs_text(params)
            if _ID_MENTION.search(text):
                # NAMED is not the same as SUPPLIED — see _OPTIONAL_SPREAD. A conditional spread or
                # a `|| ''` default still reaches mailapi with nothing and binds ambiently.
                why = _id_is_optional(text)
                if why:
                    out.append((name, f"{target} call", f"{why}: {text[:160]!r}"))
                continue
            wi_map = (params.get("workflowInputs") or {}).get("value") or {}
            # Two passthrough shapes carry the id upstream instead of on this node, and BOTH must
            # be traced through rather than flagged directly:
            #   (a) no workflowInputs at all (old-style implicit item-passthrough, typeVersion 1.1)
            #   (b) workflowInputs EXPLICITLY set to forward the caller's own {op, params} verbatim
            #       (`op: "={{ $json.op }}"`, `params: "={{ $json.params }}"` — mailOrgTest00001's
            #       and ztestGmailApi01's own router-forwarding shape). Checking only (a) made every
            #       call site using shape (b) permanently unfixable: threading connection_id into the
            #       UPSTREAM builder (the only place shape (b) ever could carry it) would never clear
            #       the gate, which is how a gate stops being trusted. Matched on the LITERAL
            #       untransformed expression, not just "params key exists", so a node that actually
            #       transforms params (e.g. `={{ ({...$json.params, extra:1}) }}`) still falls through
            #       to the direct per-node check below rather than being waved through unread.
            is_pure_passthrough = (not text) or (
                wi_map.get("op") == "={{ $json.op }}" and wi_map.get("params") == "={{ $json.params }}")
            if is_pure_passthrough:
                if _ID_MENTION.search(_upstream_text(doc, name)):
                    continue
                out.append((name, f"{target} call",
                            "workflowInputs only forwards the caller's {op, params} verbatim (or "
                            "has none at all), and no upstream node within 4 hops builds a "
                            "connection_id — so the mailbox is whichever one /data/active.json "
                            "happens to name."))
                continue
            out.append((name, f"{target} call",
                        f"op input carries no connection_id: {text[:160]!r}"))
            continue

        if is_definition:
            continue  # the router/client's own forwarding nodes — see MAIL_OP_DEFINITIONS

        if ntype.endswith("httpRequest"):
            url = str(params.get("url") or "")
            if not _is_mail_host(url) or not _hits_canonical_path(url):
                continue
            text = _http_text(params)
            if not _ID_MENTION.search(text):
                out.append((name, f"direct HTTP call to {url[:90]}",
                            f"no connection_id in url/body: {text[:160]!r}"))
            elif _OPTIONAL_SPREAD.search(text) or (
                    _EMPTY_ONLY.search(text) and len(_ID_MENTION.findall(text)) <= 2):
                out.append((name, f"direct HTTP call to {url[:90]}",
                            _id_is_optional(text) or
                            "connection_id is present but defaults to '' — an empty value is "
                            "resolved through the ambient pointer exactly like an absent one"))
    return out


# The n8n half read NOTHING from 2026-08-16 to 2026-10-07: these named `*.json`, the directories
# hold `.workflow.ts`, and the summary line said "+ 0 n8n workflow(s)" on every run. (The third
# pattern, apps/*/tests/*.json, went with the mail consolidation.)
N8N_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)


def _n8n_scope():
    seen = set()
    for pattern in N8N_GLOBS:
        for wf in sorted(REPO.glob(pattern)):
            rel = str(wf.relative_to(REPO)).replace("\\", "/")
            if rel in seen or any(s in f"/{rel}" for s in SKIP):
                continue
            seen.add(rel)
            yield rel


def scan_n8n() -> list[tuple[str, str, str, str]]:
    findings = []
    for rel in _n8n_scope():
        wf = REPO / rel
        for name, kind, detail in scan_workflow_file(wf, is_definition=(rel in MAIL_OP_DEFINITIONS)):
            findings.append((rel, name, kind, detail))
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Python scanner
# ─────────────────────────────────────────────────────────────────────────────
_PY_CALL = re.compile(
    r"""(?:requests|httpx)\.(get|post|put|patch|delete|request)\s*\(\s*[^,()]*?"""
    r"""(/search|/message|/thread|/labels/add|/labels/remove|/labels/create|/labels/delete"""
    r"""|/labels|/append|/send)["'f]"""
)

_LOOKAHEAD_LINES = 6

#: A module constant that holds a mailapi BASE URL. This is what makes a helper a MAIL helper rather
#: than some other service's — `GI = os.environ.get("GMAIL_IMAP_URL", "http://mailapi:8970")` in
#: mailview, `MAIL_URL = os.getenv("MAIL_API_URL", ...)` elsewhere. Matched on the assignment line so
#: the constant's NAME can then be looked for inside candidate helper bodies.
_MAIL_BASE_ASSIGN = re.compile(
    r"""^\s*([A-Z_][A-Z_0-9]*)\s*=\s*[^\n]*?"""
    r"""(?:mailapi|mail\.localhost|:8970|GMAIL_IMAP_URL|MAIL_API_URL|MAILAPI_URL|MAIL_URL|MAIL_BASE)""",
    re.M)

#: `connection_id` present but only ever able to arrive empty — the Python spelling of the
#: `|| ''` shape `_EMPTY_ONLY` catches in n8n expressions.
#: Both spellings the key takes on the left of an assignment must be reachable: `"connection_id":`
#: (a dict literal / kwarg) and `d["connection_id"] =` (a subscript store). The first version had no
#: `\]?` and therefore matched only the former — it passed its own self-test on the dict shape and
#: silently allowed `body["connection_id"] = _requested_cid() or ""`, which is the shape a Flask
#: proxy actually writes.
_PY_EMPTY_ONLY = re.compile(r"""connection_id["']?\]?\s*[:=,][^\n]{0,90}?\bor\s+(['"])\1""")

#: `**({"connection_id": x} if x else {})` / `**(x and {"connection_id": x})` — the Python spelling
#: of `_OPTIONAL_SPREAD`. The key is NAMED and still vanishes when the source is falsy, which is what
#: makes a plain "does it mention connection_id" test useless here too.
_PY_COND_SPREAD = re.compile(
    r"""\*\*\s*\(\s*\{[^{}]{0,140}?connection_id[^{}]{0,160}?\}\s*(?:if\b|\)\s*if\b)"""
    r"""|\*\*\s*\(\s*\w[\w.]*\s+and\s+\{[^{}]{0,160}?connection_id""")

#: `if <something>:` and, within the next two lines, an assignment that INSTALLS connection_id. The
#: guarded-assignment form: falsy source, key never written, op travels bare. Line-scanned rather
#: than regexed in one piece because it spans lines by construction; deliberately does NOT match a
#: `raise`/`return` guard (`if cid is None: cid = _selected()` leaves the key unconditionally
#: written further down and is the shape a fix is supposed to reach).
_PY_GUARDED_SET = re.compile(r"""\[\s*["']connection_id["']\s*\]\s*=|setdefault\(\s*["']connection_id["']""")


_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def _py_guarded_assignment(src: str) -> bool:
    """`if cid: body["connection_id"] = cid` — the guard tests THE ID ITSELF, so a falsy id means the
    key is never written and the op travels bare.

    THE NARROWING IS PAID FOR. The first version flagged any `if` with a `["connection_id"] =` within
    two lines of it, and its first real run reported `apps/mail/mailview/app.py`'s FIXED `gi()` —
    where the guard is `if body is not None or method != "GET":`, a guard on the HTTP SHAPE choosing
    between putting the id in the body and putting it in the query string, with both branches
    installing it. Flagging the shape a correct fix takes is how a gate becomes unfixable and then
    unread (this gate's own `_upstream_text` comment records the same lesson). So the condition must
    name an identifier that is also the VALUE being installed — which is what makes the assignment
    conditional ON the id rather than merely near one.
    """
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not (s.startswith("if ") and s.endswith(":")):
            continue
        if "connection_id" in s:
            continue  # `if "connection_id=" not in path:` — a guard ABOUT the id, not a guard on it
        cond_names = set(_IDENT.findall(s[3:-1]))
        indent = len(ln) - len(ln.lstrip())
        for j in range(i + 1, min(i + 3, len(lines))):
            nxt = lines[j]
            if not nxt.strip():
                continue
            if (len(nxt) - len(nxt.lstrip())) <= indent:
                break  # left the if-body
            m = _PY_GUARDED_SET.search(nxt)
            if not m:
                continue
            value = nxt[m.end():]
            if cond_names & set(_IDENT.findall(value)):
                return True
    return False


def _py_id_is_optional(src: str) -> str | None:
    """Return a reason when connection_id is NAMED in this Python source but can still travel absent
    or empty. The exact counterpart of `_id_is_optional` for the n8n side — same three shapes."""
    if _PY_COND_SPREAD.search(src):
        return ("connection_id is spread in CONDITIONALLY (`**({'connection_id': x} if x else {})`) "
                "— when the source value is falsy the key is omitted entirely and the mailbox falls "
                "back to /data/active.json")
    if _PY_EMPTY_ONLY.search(src):
        return ("connection_id is present but defaults to '' — an empty value is resolved through "
                "the ambient pointer exactly like an absent one")
    if _py_guarded_assignment(src):
        return ("connection_id is installed inside an `if` guard — on the falsy branch the key is "
                "never written and the op travels with no connection at all")
    return None


# ── mail proxy helpers ───────────────────────────────────────────────────────────────────────────
# WHY THIS EXISTS. The 2026-08-09 outage's twelve call sites are all `gi("/labels/add", "POST", …)`.
# There is no literal `requests.post(".../labels/add")` anywhere in `apps/mail/mailview/app.py`, so
# `_PY_CALL` — which can only see a canonical path inside a `requests`/`httpx` call — matched none of
# them. A service reached through one proxy helper is the NORMAL shape for a Flask front end in this
# repo; a scanner that can only read the un-abstracted shape can only ever check the callers that
# happen not to have factored their HTTP out.
#
# The fix mirrors the n8n scanner's `_upstream_text`: do not flag the call site for something that
# belongs one hop away. There, the id may legitimately be built in an upstream Code node; here, it
# may legitimately be attached inside the helper (and in mailview's fix it IS — `gi()` resolves the
# selected connection and threads it onto every canonical path). So:
#
#   * helper attaches an id unconditionally  -> its call sites are CLEAN, and threading it correctly
#     actually clears the gate. A gate that stays red after the right fix is a gate nobody reads.
#   * helper attaches nothing, or attaches it in a shape that can vanish -> the helper is reported
#     ONCE (that is where the fix goes) and every canonical-op call site through it is listed with
#     it, so the blast radius is the number in the report rather than a footnote.
#
# STATED LIMIT, not an oversight: "attaches it unconditionally" is judged from the helper's own text
# by the same three vanish-shapes used everywhere else in this gate, not by proving the value is
# non-empty on every path. Proving that needs a dataflow analysis this repo does not have, and the
# n8n side already accepts the identical weaker standard for upstream builders (`_ID_MENTION` over
# `_upstream_text`). A helper that mentions the id and dodges all three shapes passes here.
_HTTP_CLIENT = re.compile(r"\b(?:requests|httpx)\s*\.\s*(?:get|post|put|patch|delete|request|Session)\b")


def _mail_base_names(text: str) -> set[str]:
    return {m.group(1) for m in _MAIL_BASE_ASSIGN.finditer(text)}


def _find_mail_helpers(tree, src_lines, bases: set[str]) -> dict[str, tuple[int, int, str]]:
    """name -> (lineno, end_lineno, source) for every function that issues HTTP at a mail base URL."""
    import ast as _ast
    helpers: dict[str, tuple[int, int, str]] = {}
    for node in _ast.walk(tree):
        if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            continue
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        body = "\n".join(src_lines[start - 1:end])
        if not _HTTP_CLIENT.search(body):
            continue
        used = {n.id for n in _ast.walk(node) if isinstance(n, _ast.Name)}
        if not (used & bases):
            continue
        helpers[node.name] = (start, end, body)
    return helpers


def _literal_path(node) -> str | None:
    """The leading literal text of a call's first argument — a plain string, or the constant head of
    an f-string (`f"/message/0?id={mid}"` -> `/message/0?id=`). Enough to name the op."""
    import ast as _ast
    if isinstance(node, _ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, _ast.JoinedStr):
        bits = []
        for v in node.values:
            if isinstance(v, _ast.Constant) and isinstance(v.value, str):
                bits.append(v.value)
            else:
                bits.append("\x00")
        return "".join(bits)
    if isinstance(node, _ast.BinOp) and isinstance(node.op, _ast.Add):
        left = _literal_path(node.left)
        return left if left else None
    return None


#: A canonical-op path spelled literally inside a helper's own body — the case where the helper
#: builds the path itself instead of taking it from its caller.
_BODY_CANONICAL = re.compile(
    "|".join(re.escape(p) + r"""(?=["'/?])""" for p in sorted(CANONICAL_PATHS, key=len, reverse=True)))


def _names_canonical_op(path: str) -> bool:
    head = (path or "").split("?", 1)[0].rstrip("/").lower()
    return any(head.startswith(p) or head.startswith(p + "/") for p in CANONICAL_PATHS)


#: A helper that ends in a bare `raise_for_status()` OUTSIDE any `try` throws the upstream BODY away
#: and keeps only the status: `requests.HTTPError`'s message is "400 Client Error: BAD REQUEST for
#: url: …", and mailapi's actual sentence — "this operation requires an explicit `connection_id` —
#: none was passed. Available connections: …" — is discarded one hop from the log that would have
#: named the outage in its first minute. Inside a `try` it is not flagged: that is the shape where
#: the handler re-raises something carrying the diagnosis, which is exactly the fix.
_RFS = re.compile(r"\braise_for_status\s*\(\s*\)")
_PRESERVES = re.compile(r"\bstatus_code\b|\.text\b|\bresp(?:onse)?\.json\(")


def _opaque_proxy_reason(node, src_lines) -> str | None:
    import ast as _ast
    try_spans = [(t.lineno, getattr(t, "end_lineno", t.lineno))
                 for t in _ast.walk(node) if isinstance(t, _ast.Try)]
    bare = []
    for sub in _ast.walk(node):
        if not (isinstance(sub, _ast.Call) and isinstance(sub.func, _ast.Attribute)
                and sub.func.attr == "raise_for_status"):
            continue
        ln = sub.lineno
        if any(a <= ln <= b for a, b in try_spans):
            continue
        bare.append(ln)
    if not bare:
        return None
    body = "\n".join(src_lines[node.lineno - 1:getattr(node, "end_lineno", node.lineno)])
    if _PRESERVES.search(body):
        return None
    return (f"bare raise_for_status() at line {bare[0]} outside any try/except, and this helper "
            f"never reads status_code or the response text — an upstream 4xx becomes an HTTPError "
            f"carrying the STATUS and not the BODY, so mailapi's actionable message (e.g. "
            f"\"requires an explicit `connection_id`\") is discarded here and the caller sees a "
            f"generic 500. Carry the upstream status and body instead of raising on them.")


def scan_python_text(rel: str, text: str) -> list[tuple[str, str, str]]:
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = _PY_CALL.search(line)
        if not m:
            continue
        # only flag calls that plausibly name the MAIL service, not another service sharing an
        # op-name-shaped path segment (drive also has a /search, INDOX has a /send)
        if not any(h in line.lower() for h in ("mail", ":8970")):
            window_has_mail = any(
                any(h in lines[j].lower() for h in ("mailapi", "mail_url", "mail_base", ":8970"))
                for j in range(max(0, i - 3), i))
            if not window_has_mail:
                continue
        window = "\n".join(lines[i:i + _LOOKAHEAD_LINES])
        if not _ID_MENTION.search(window):
            out.append((rel, f"line {i + 1}", line.strip()))
        else:
            why = _py_id_is_optional(window)
            if why:
                out.append((rel, f"line {i + 1}", f"{line.strip()}   <- {why}"))
    out += scan_python_helpers(rel, text)
    return out


def scan_python_helpers(rel: str, text: str) -> list[tuple[str, str, str]]:
    """Call sites that reach mailapi through a per-service proxy helper, plus the helper itself."""
    import ast as _ast
    bases = _mail_base_names(text)
    if not bases:
        return []
    try:
        tree = _ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    helpers = _find_mail_helpers(tree, lines, bases)
    if not helpers:
        return []

    out: list[tuple[str, str, str]] = []
    by_name = {n.name: n for n in _ast.walk(tree)
               if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}

    # 1. every canonical-op call site, per helper — collected FIRST, because a helper that serves no
    #    canonical op is not this gate's business at all. `mailview`'s `organizer_defaults_put()`
    #    proxies `/organizer/defaults`, a settings document with no mailbox behind it; reporting it
    #    for "never names a connection_id" would be a permanent false finding of exactly the kind
    #    `/organizer/settings` already was on the n8n side.
    sites: dict[str, list[tuple[int, str, str]]] = {}
    for call in _ast.walk(tree):
        if not (isinstance(call, _ast.Call) and isinstance(call.func, _ast.Name)
                and call.func.id in helpers and call.args):
            continue
        path = _literal_path(call.args[0])
        if not path or not _names_canonical_op(path):
            continue
        seg = lines[call.lineno - 1].strip() if call.lineno - 1 < len(lines) else ""
        sites.setdefault(call.func.id, []).append(
            (call.lineno, seg, path.split("?")[0].replace("\x00", "…")))

    # 2. the helper's own contract. A helper that attaches the id unconditionally makes its call
    #    sites correct and nothing here is reported — see the block comment above.
    for name, (start, _end, body) in sorted(helpers.items(), key=lambda kv: kv[1][0]):
        serves_canonical = bool(sites.get(name)) or bool(_BODY_CANONICAL.search(body))
        if not serves_canonical:
            continue
        if not _ID_MENTION.search(body):
            why = ("this helper proxies mail ops and never names a connection_id, so every "
                   "canonical-op path routed through it reaches mailapi bare")
        else:
            why = _py_id_is_optional(body)
        opaque = _opaque_proxy_reason(by_name[name], lines)
        if opaque:
            out.append((rel, f"line {start}  [proxy helper `{name}()` — opaque upstream error]",
                        opaque))
        if not why:
            continue
        out.append((rel, f"line {start}  [proxy helper `{name}()`]", why))
        for lineno, seg, op in sorted(sites.get(name, [])):
            out.append((rel, f"line {lineno}",
                        f"{seg[:150]}   <- `{name}()` op {op!r} with no connection_id "
                        f"(see the helper finding above)"))
    return out


#: EVERY first-party Python tree that can hold a mailapi caller.
#:
#: WAS `("apps/*/app/**/*.py", "scripts/**/*.py")` until 2026-08-09. In THIS repo `apps/*/app/**`
#: resolves to `apps/indox/app/**` and nothing else — 47 of 209 first-party app `.py` files, one app
#: out of fourteen — because it requires a directory literally named `app`, and only indox has one.
#: `apps/mail/mailview/app.py`, `apps/drive/app.py`, `apps/browser42/*.py`,
#: `platform-base/connections/*.py` were all outside it. The gate was not lenient; it was looking at
#: an empty room and reporting that the room was clean, which is indistinguishable from a pass in
#: every report it has ever printed.
#:
#: `apps/**/*.py` is deliberately un-narrowed beyond SKIP: the shape of the last hole was a caller
#: living somewhere the author of the glob did not think of, and every narrowing here is another
#: chance to make that mistake. The host-mention filter in `scan_python_text` and the mail-base
#: filter in `scan_python_helpers` are what keep the report quiet, not the glob.
PY_GLOBS = ("apps/**/*.py", "scripts/**/*.py", "platform-base/**/*.py")

#: The SERVICE is `apps/mail/mailapi/`, not `apps/mail/`. `mailview` and `mailboxd` are their own
#: compose services that reach mailapi over HTTP (see apps/mail/docker-compose.yml) — they are
#: CALLERS, and excluding the whole app directory excluded them along with the service. That single
#: prefix is hole #2 of the three that made the 2026-08-09 outage invisible to this gate.
MAIL_SERVICE_PREFIXES = ("apps/mail/mailapi/",)


def python_scan_set() -> list[str]:
    """Exactly the files `scan_python` will open, as repo-relative paths.

    Split out from the scan so the SET can be asserted on rather than inferred from a finding count.
    "Zero findings" and "zero files" print the same line otherwise, and telling them apart after the
    fact is not possible — which is the whole of what went wrong here."""
    seen: list[str] = []
    known: set[str] = set()
    for pattern in PY_GLOBS:
        for py in sorted(REPO.glob(pattern)):
            rel = str(py.relative_to(REPO)).replace("\\", "/")
            if rel in known:
                continue
            known.add(rel)
            if rel.startswith(MAIL_SERVICE_PREFIXES):
                continue  # the service itself, not a caller
            if rel.startswith("scripts/refactor/"):
                continue  # the gates themselves (this file quotes call shapes in its own docstring)
            if any(s in f"/{rel}" for s in SKIP):
                continue
            seen.append(rel)
    return seen


def scan_python() -> list[tuple[str, str, str]]:
    out = []
    for rel in python_scan_set():
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out += scan_python_text(rel, text)
    return out


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST_N8N = [
    ("gmailApiImap01 call, no connection_id anywhere", True, {
        "nodes": [{"name": "Add Done Tag", "type": "n8n-nodes-base.executeWorkflow",
                   "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                  "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                      "op": "addLabels",
                                      "params": "={{ ({ id: $json.id, labelIds: ['x'] }) }}"}}}}]}),
    ("gmailApiImap01 call WITH connection_id — must allow", False, {
        "nodes": [{"name": "Apply Gmail Label", "type": "n8n-nodes-base.executeWorkflow",
                   "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                  "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                      "op": "addLabels",
                                      "params": "={{ ({ id: $json.id, connection_id: $json.CONNECTION }) }}"}}}}]}),
    ("gmailApiImap01 call, no connection_id — must catch (the router is being retired, "
     "so calls land here next)", True, {
         "nodes": [{"name": "Call Search", "type": "n8n-nodes-base.executeWorkflow",
                    "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                   "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                       "op": "search", "params": "={{ ({ query: 'x' }) }}"}}}}]}),
    ("executeWorkflow to the router with NO workflowInputs (implicit passthrough) — must catch",
     True, {
         "nodes": [{"name": "Gmail Search", "type": "n8n-nodes-base.executeWorkflow",
                    "typeVersion": 1.1,
                    "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01",
                                                   "mode": "id"}, "options": {}}}]}),
    ("passthrough exec node whose UPSTREAM builder sets connection_id — must allow "
     "(SyncScanUnit0001's Gmail Search Req -> Gmail Search after the 2026-08-07 fix)", False, {
         "nodes": [
             {"name": "Gmail Search Req", "type": "n8n-nodes-base.code",
              "parameters": {"jsCode": "const _conn = u.connection ? { connection_id: u.connection } : {};\n"
                                        "return [{ json: { op:'search', params: { query, ..._conn } } }];"}},
             {"name": "Gmail Search", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.1,
              "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                             "options": {}}}],
         "connections": {"Gmail Search Req": {"main": [[{"node": "Gmail Search", "type": "main",
                                                          "index": 0}]]}}}),
    ("passthrough exec node whose upstream builder does NOT set connection_id — must catch, "
     "even though a SIBLING node elsewhere in the file does", True, {
         "nodes": [
             {"name": "Label Req", "type": "n8n-nodes-base.code",
              "parameters": {"jsCode": "return [{json:{op:'addLabels',params:{ids:[j.platform_id]}}}];"}},
             {"name": "Call Label", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.1,
              "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                             "options": {}}},
             {"name": "Get Message", "type": "n8n-nodes-base.executeWorkflow",
              "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                             "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                 "op": "get",
                                 "params": "={{ ({ connection_id: $json.list_ctx.connection_id }) }}"}}}}],
         "connections": {"Label Req": {"main": [[{"node": "Call Label", "type": "main",
                                                   "index": 0}]]}}}),
    ("passthrough exec node whose builder is 4 hops upstream (syncV3Deliver0001's real shape: "
     "Apply Synced Labels <- Emit Label Ops <- Any Label Ops? <- Synced Label Ops) — must allow",
     False, {
         "nodes": [
             {"name": "Synced Label Ops", "type": "n8n-nodes-base.code",
              "parameters": {"jsCode": "const _conn=(j.list_ctx||{}).connection_id?{connection_id:j.list_ctx.connection_id}:{};\n"
                                        "return [{json:{ops:[{op:'addLabels',params:{ids:[j.platform_id],..._conn}}]}}];"}},
             {"name": "Any Label Ops?", "type": "n8n-nodes-base.if", "parameters": {}},
             {"name": "Emit Label Ops", "type": "n8n-nodes-base.code",
              "parameters": {"jsCode": "return ($input.first().json.ops||[]).map(o=>({json:o}));"}},
             {"name": "Apply Synced Labels", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.1,
              "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                             "options": {}, "mode": "each"}}],
         "connections": {
             "Synced Label Ops": {"main": [[{"node": "Any Label Ops?", "type": "main", "index": 0}]]},
             "Any Label Ops?": {"main": [[{"node": "Emit Label Ops", "type": "main", "index": 0}]]},
             "Emit Label Ops": {"main": [[{"node": "Apply Synced Labels", "type": "main", "index": 0}]]}}}),
    ("passthrough exec node whose builder is 6 hops upstream — must STILL CATCH (the bound is "
     "real, not effectively unlimited)", True, {
         "nodes": [
             {"name": "Far Builder", "type": "n8n-nodes-base.code",
              "parameters": {"jsCode": "return [{json:{op:'addLabels',params:{connection_id:'x'}}}];"}},
             {"name": "Hop2", "type": "n8n-nodes-base.noOp", "parameters": {}},
             {"name": "Hop3", "type": "n8n-nodes-base.noOp", "parameters": {}},
             {"name": "Hop4", "type": "n8n-nodes-base.noOp", "parameters": {}},
             {"name": "Hop5", "type": "n8n-nodes-base.noOp", "parameters": {}},
             {"name": "Apply Far Labels", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.1,
              "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                             "options": {}}}],
         "connections": {
             "Far Builder": {"main": [[{"node": "Hop2", "type": "main", "index": 0}]]},
             "Hop2": {"main": [[{"node": "Hop3", "type": "main", "index": 0}]]},
             "Hop3": {"main": [[{"node": "Hop4", "type": "main", "index": 0}]]},
             "Hop4": {"main": [[{"node": "Hop5", "type": "main", "index": 0}]]},
             "Hop5": {"main": [[{"node": "Apply Far Labels", "type": "main", "index": 0}]]}}}),
    ("EXPLICIT passthrough shape (op/params forward $json.op/$json.params verbatim — "
     "mailOrgTest00001's own 'LE Pre' shape), upstream builder DOES set connection_id — must "
     "allow (this is the exact gap 2026-08-07 found: LE Seed Req was fixed but LE Seed stayed "
     "flagged because only the fully-empty passthrough shape was traced upstream)", False, {
         "nodes": [
             {"name": "LE Pre Req", "type": "n8n-nodes-base.code",
              "parameters": {"jsCode": "const cfg=$('Config').first().json; const tok=cfg.tok;\n"
                                        "return [{json:{op:'search', params:{query:'x', limit:5, "
                                        "...(cfg.connection_id?{connection_id:cfg.connection_id}:{})}}}];"}},
             {"name": "LE Pre", "type": "n8n-nodes-base.executeWorkflow",
              "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                             "options": {}, "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                 "op": "={{ $json.op }}", "params": "={{ $json.params }}"}}}}],
         "connections": {"LE Pre Req": {"main": [[{"node": "LE Pre", "type": "main", "index": 0}]]}}}),
    ("EXPLICIT passthrough shape, upstream builder does NOT set connection_id — must catch "
     "(the bound stays real for this shape too)", True, {
         "nodes": [
             {"name": "CallRouter Req", "type": "n8n-nodes-base.code",
              "parameters": {"jsCode": "return [{json:{op:'listLabels',params:{}}}];"}},
             {"name": "CallRouter", "type": "n8n-nodes-base.executeWorkflow",
              "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                             "options": {}, "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                 "op": "={{ $json.op }}", "params": "={{ $json.params }}"}}}}],
         "connections": {"CallRouter Req": {"main": [[{"node": "CallRouter", "type": "main",
                                                        "index": 0}]]}}}),
    ("workflowInputs.op/params look ALMOST like the pure-passthrough shape but params is "
     "actually TRANSFORMED (not the literal '={{ $json.params }}') — must catch on the DIRECT "
     "text check, not be waved through as passthrough", True, {
         "nodes": [{"name": "Transformed Call", "type": "n8n-nodes-base.executeWorkflow",
                    "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                   "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                       "op": "={{ $json.op }}",
                                       "params": "={{ ({...$json.params, extra:1}) }}"}}}}]}),
    ("executeWorkflow to a NON-mail workflow — must not be flagged", False, {
        "nodes": [{"name": "Upload Doc", "type": "n8n-nodes-base.executeWorkflow",
                   "parameters": {"workflowId": {"__rl": True, "value": "driveApi01", "mode": "id"},
                                  "workflowInputs": {"mappingMode": "defineBelow",
                                                      "value": {"op": "upload"}}}}]}),
    ("executeWorkflowTrigger (the router's OWN trigger) — must not be flagged", False, {
        "nodes": [{"name": "When Called", "type": "n8n-nodes-base.executeWorkflowTrigger",
                   "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01",
                                                  "mode": "id"}}}]}),
    ("direct HTTP to mailapi /organizer/settings with no connection_id — must ALLOW as of "
     "2026-08-09 (was 'must catch'). That route never calls _backend, never opens IMAP and never "
     "touches a message: with no id it serves the mail-scoped DEFAULTS singleton, not the active "
     "connection's options, so there is no wrong-mailbox failure mode to close. service.py says so "
     "in its own words and names these exact three mailLabelEngine01 `Load Settings` nodes as what "
     "requiring an id there would break 'for no safety gain'", False, {
         "nodes": [{"name": "Load Settings (sched)", "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "http://mailapi:8970/organizer/settings",
                                   "options": {"timeout": 15000}}}]}),
    ("direct HTTP to mailapi /organizer/settings WITH connection_id — must allow", False, {
        "nodes": [{"name": "Load Settings", "type": "n8n-nodes-base.httpRequest",
                   "parameters": {"url": "=http://mailapi:8970/organizer/settings?connection_id={{ $json.cid }}"}}]}),
    ("direct HTTP to mailapi /labels/add with connection_id in jsonBody — must allow", False, {
        "nodes": [{"name": "http:addLabels", "type": "n8n-nodes-base.httpRequest",
                   "parameters": {"url": "http://mailapi:8970/labels/add", "sendBody": True,
                                  "jsonBody": "={{ ({ ids: $json.ids, connection_id: $json.cid }) }}"}}]}),
    ("direct HTTP to mailapi /thread with connection_id that can ONLY be empty — must catch", True, {
        "nodes": [{"name": "http:getThread", "type": "n8n-nodes-base.httpRequest",
                   "parameters": {"url": "=http://mailapi:8970/thread/{{ $json.params.id }}"
                                          "?connection_id={{ ($json.params || {}).connection_id || '' }}"}}]}),
    ("HTTP call to a DIFFERENT service's own /search — must not be flagged", False, {
        "nodes": [{"name": "Drive Search", "type": "n8n-nodes-base.httpRequest",
                   "parameters": {"url": "http://drive:8975/search", "sendBody": True,
                                  "jsonBody": "={{ {} }}"}}]}),
    ("gmailApiImap01's OWN http:search forwarding node — must not be flagged as the definition",
     False, {
         "nodes": [{"name": "http:search", "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "http://mailapi:8970/search", "sendBody": True,
                                   "jsonBody": "={{ $json.params }}"}}]},
     True),
    ("gmailApiImap01's OWN 'Call IMAP' node forwarding {op,params} into gmailApiImap01 — must "
     "not be flagged when scanned as the definition (blind passthrough plumbing, not a caller "
     "that forgot something — the id, if any, lives in whoever called the router)", False, {
         "nodes": [{"name": "Call IMAP", "type": "n8n-nodes-base.executeWorkflow",
                    "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                   "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                       "op": "={{ $json.op }}", "params": "={{ $json.params }}"}}}}]},
     True),

    # ── The gate's own false clean, 2026-08-09. Both shapes NAME connection_id, so the old
    # `_ID_MENTION` check waved them through; both can still reach mailapi with nothing.
    # Measured live: syncV3Deliver0001's `Get Message` (shape A) produced
    # `GET /message/0?...&connection_id=` EMPTY and 404ed on ids that resolve fine with an
    # explicit one. Without these two cases the fix is unproven and re-regressible.
    ("executeWorkflow whose connection_id is spread in CONDITIONALLY (`cond ? {connection_id: x} "
     ": {}`) — must catch: when the source is falsy the key vanishes and the mailbox is ambient "
     "(syncV3Deliver0001 'Get Message', indoxGmailBSDownloader01 'Get Message')", True, {
         "nodes": [{"name": "Get Message", "type": "n8n-nodes-base.executeWorkflow",
                    "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                   "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                       "op": "get",
                                       "params": "={{ ({ id: $json.platform_id, attachments: true, "
                                                 "...(($json.list_ctx||{}).connection_id ? "
                                                 "{ connection_id: $json.list_ctx.connection_id } : {}) }) }}"}}}}]}),
    ("executeWorkflow whose connection_id defaults to '' — must catch (mailLabelEngine01 "
     "'Get Mail Thread' / 'Sub Search'); an empty value binds ambiently exactly like an absent one",
     True, {
         "nodes": [{"name": "Sub Search", "type": "n8n-nodes-base.executeWorkflow",
                    "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                   "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                       "op": "search",
                                       "params": "={{ ({ query: $json.query, "
                                                 "connection_id: $json.connection_id || '' }) }}"}}}}]}),
    ("executeWorkflow passing an UNCONDITIONAL connection_id — must allow (this is the shape the "
     "two cases above must be fixed INTO, so it has to stay green)", False, {
         "nodes": [{"name": "Get Message", "type": "n8n-nodes-base.executeWorkflow",
                    "parameters": {"workflowId": {"__rl": True, "value": "gmailApiImap01", "mode": "id"},
                                   "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                       "op": "get",
                                       "params": "={{ ({ id: $json.platform_id, "
                                                 "connection_id: $json.list_ctx.connection_id }) }}"}}}}]}),
]

SELF_TEST_PY = [
    ("requests.post to mailapi /search, no connection_id", "apps/indox/app/x.py",
     'requests.post(f"{MAIL_URL}/search", json={"query": q, "limit": 10}, timeout=30)\n',
     True),
    ("requests.post to mailapi /search WITH connection_id", "apps/indox/app/x.py",
     'requests.post(f"{MAIL_URL}/search", json={"query": q, "connection_id": conn}, timeout=30)\n',
     False),
    ("requests.get to mailapi /labels, connection_id on the next line", "apps/indox/app/x.py",
     'requests.get(f"{MAIL_URL}/labels",\n    params={"connection_id": conn},\n    timeout=30)\n',
     False),
    ("requests.post to an unrelated host's own /send — must not be flagged", "apps/indox/app/x.py",
     'requests.post(f"{WHATSAPP_URL}/send", json={"to": to}, timeout=30)\n',
     False),

    # ── The 2026-08-09 outage's shape: a service reached through ONE proxy helper. None of these
    # contain a literal `requests.post(".../labels/add")`, which is the only thing the pre-rewrite
    # scanner could see — it reported this file clean while every op in it travelled bare.
    ("proxy helper that never names a connection_id + a canonical-op call site through it — must "
     "catch (apps/mail/mailview/app.py's pre-fix `gi()`)", "apps/mail/mailview/app.py",
     'GI = os.environ.get("GMAIL_IMAP_URL", "http://mailapi:8970")\n'
     'def gi(path, method="GET", body=None, timeout=60):\n'
     '    r = requests.request(method, GI + path, json=body, timeout=timeout)\n'
     '    r.raise_for_status()\n'
     '    return r.json()\n'
     'def tag():\n'
     '    gi("/labels/add", "POST", {"id": mid, "labels": add})\n',
     True),
    ("the SAME file after the helper threads an explicit id — must allow. This is the case that "
     "decides whether the gate is fixable: if a correctly-threaded helper still reported its call "
     "sites, the only way to green would be to delete the abstraction",
     "apps/mail/mailview/app.py",
     'GI = os.environ.get("GMAIL_IMAP_URL", "http://mailapi:8970")\n'
     'def gi(path, method="GET", body=None, timeout=60):\n'
     '    if any(path.startswith(p) for p in _OPS) and "connection_id=" not in path:\n'
     '        cid = _requested_cid()\n'
     '        if cid is None:\n'
     '            cid = _selected()\n'
     '        if body is not None or method != "GET":\n'
     '            body = dict(body or {})\n'
     '            body.setdefault("connection_id", cid)\n'
     '        else:\n'
     '            path += ("&" if "?" in path else "?") + "connection_id=" + cid\n'
     '    r = requests.request(method, GI + path, json=body, timeout=timeout)\n'
     '    if r.status_code >= 400:\n'
     '        raise Upstream(r.status_code, (r.text or "")[:800], path=path)\n'
     '    return r.json()\n'
     'def tag():\n'
     '    gi("/labels/add", "POST", {"id": mid, "labels": add})\n',
     False),
    ("proxy helper that NAMES connection_id but installs it under an `if` guard ON THE ID — must "
     "catch: falsy id, key never written, op travels bare (the Python spelling of _OPTIONAL_SPREAD)",
     "apps/mail/mailview/app.py",
     'GI = "http://mailapi:8970"\n'
     'def gi(path, method="GET", body=None):\n'
     '    cid = _requested_cid()\n'
     '    if cid:\n'
     '        body["connection_id"] = cid\n'
     '    return requests.request(method, GI + path, json=body).json()\n'
     'def tag():\n'
     '    gi("/send", "POST", {"to": to})\n',
     True),
    ("proxy helper whose connection_id defaults to '' — must catch (`or \"\"` reaches mailapi as "
     "absent)", "apps/mail/mailview/app.py",
     'GI = "http://mailapi:8970"\n'
     'def gi(path, method="GET", body=None):\n'
     '    body["connection_id"] = _requested_cid() or ""\n'
     '    return requests.request(method, GI + path, json=body).json()\n'
     'def tag():\n'
     '    gi("/search", "POST", {})\n',
     True),
    ("proxy helper serving a NON-canonical path only (/organizer/defaults) — must allow; that "
     "route has no mailbox behind it and a permanent finding there is how a gate stops being read",
     "apps/mail/mailview/app.py",
     'GI = "http://mailapi:8970"\n'
     'def organizer_defaults_put(body):\n'
     '    r = requests.put(GI + "/organizer/defaults", json=body, timeout=60)\n'
     '    return r.json(), r.status_code\n',
     False),
    ("a helper at a DIFFERENT service's base URL — must not be flagged, whatever paths it names",
     "apps/indox/app/x.py",
     'DRIVE_URL = "http://drive:8975"\n'
     'def dv(path, body=None):\n'
     '    r = requests.post(DRIVE_URL + path, json=body)\n'
     '    r.raise_for_status()\n'
     '    return r.json()\n'
     'def go():\n'
     '    dv("/search", {})\n',
     False),
]

#: The `raise_for_status()` swallow — a SIBLING check, not the connection rule. It is why the
#: connection rule's own violation was invisible: mailapi answered with an actionable 400 naming the
#: fix, and the proxy threw the sentence away and re-raised a status.
SELF_TEST_OPAQUE = [
    ("bare raise_for_status() in a mail proxy helper, no status/body read — must catch "
     "(mailview's pre-fix `gi()`, the reason the outage produced an opaque 500 and an empty log)",
     'GI = "http://mailapi:8970"\n'
     'def gi(path, method="GET", body=None):\n'
     '    r = requests.request(method, GI + path, json=body, connection_id=1)\n'
     '    r.raise_for_status()\n'
     '    return r.json()\n'
     'def t():\n'
     '    gi("/labels")\n',
     True),
    ("helper that carries the upstream status AND body — must allow (the fix's shape)",
     'GI = "http://mailapi:8970"\n'
     'def gi(path, method="GET", body=None, connection_id=None):\n'
     '    r = requests.request(method, GI + path, json=body)\n'
     '    if r.status_code >= 400:\n'
     '        raise Upstream(r.status_code, (r.text or "")[:800])\n'
     '    return r.json()\n'
     'def t():\n'
     '    gi("/labels")\n',
     False),
    ("raise_for_status() INSIDE a try whose handler re-raises something carrying the diagnosis — "
     "must allow (mailview's `_selected()`; the status is not discarded, it is translated)",
     'GI = "http://mailapi:8970"\n'
     'def gi(path, connection_id=None):\n'
     '    try:\n'
     '        r = requests.get(GI + path)\n'
     '        r.raise_for_status()\n'
     '    except Exception as exc:\n'
     '        raise Upstream(503, f"could not reach {path}: {exc}")\n'
     '    return r.json()\n'
     'def t():\n'
     '    gi("/labels")\n',
     False),
]


def self_test() -> int:
    bad = 0
    print("n8n scanner:")
    for entry in SELF_TEST_N8N:
        label, should, doc = entry[0], entry[1], entry[2]
        is_definition = entry[3] if len(entry) > 3 else False
        got = bool(scan_workflow_doc(doc, is_definition=is_definition))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    print("python scanner:")
    for label, rel, text, should in SELF_TEST_PY:
        got = bool(scan_python_text(rel, text))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    print("opaque-upstream-error sibling check:")
    for label, text, should in SELF_TEST_OPAQUE:
        got = any("opaque upstream error" in w
                  for _r, w, _d in scan_python_helpers("apps/mail/mailview/app.py", text))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")

    # THE SCAN ROOTS ARE THEMSELVES A SELF-TEST CASE. Every scanner assertion above is about
    # verdicts on text; none of them can fail if the file never reaches the scanner, and that is
    # precisely how this gate read green through the 2026-08-09 outage. So the globs are asserted
    # to actually contain the callers they exist to watch.
    print("scan coverage (the hole that caused the outage — a glob that matched nothing):")
    scanned = python_scan_set()
    must_cover = ["apps/mail/mailview/app.py", "apps/indox/app/main.py",
                  "platform-base/connections/app.py"]
    for rel in must_cover:
        present = rel in scanned
        exists = (REPO / rel).exists()
        ok = present or not exists
        bad += 0 if ok else 1
        note = "" if exists else "  (file absent from this checkout — vacuous)"
        print(f"  [{'ok ' if ok else 'FAIL'}] {'in scope' if present else 'NOT SCANNED':<11}: "
              f"{rel}{note}")
    ok = len(scanned) >= 100
    bad += 0 if ok else 1
    print(f"  [{'ok ' if ok else 'FAIL'}] python scan set = {len(scanned)} file(s) "
          f"(the pre-2026-08-09 globs reached 47, all in one app)")

    total = (len(SELF_TEST_N8N) + len(SELF_TEST_PY) + len(SELF_TEST_OPAQUE)
             + len(must_cover) + 1)
    print(f"\nG62 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    n8n_findings = scan_n8n()
    py_scope = python_scan_set()
    py_findings = scan_python()

    # WHAT WAS SCANNED IS PART OF THE RESULT. Printed on PASS and on FAIL, because for two days this
    # gate printed "G62 PASS" while its Python glob (`apps/*/app/**/*.py`) matched exactly one app
    # and never opened the file that was breaking production. A clean report and an empty scan set
    # are the same sentence unless the sentence says how much it looked at.
    n8n_scope = [rel for rel in _n8n_scope() if rel.rsplit("/", 1)[-1] not in UNREADABLE]
    coverage = (f"scanned: {len(py_scope)} first-party Python file(s) across {len(PY_GLOBS)} root(s) "
                f"+ {len(n8n_scope)} n8n workflow(s)")
    if not n8n_scope:
        print("G62 FAIL — scanned ZERO n8n workflows, so no automation call site was checked.\n"
              "  globs: " + ", ".join(N8N_GLOBS))
        return 1

    if not n8n_findings and not py_findings:
        print("G62 PASS — every automation call into apps/mail's canonical ops names an explicit "
              "connection_id.")
        print(f"  {coverage}")
        return 0

    if n8n_findings:
        by_file: dict[str, list] = {}
        for path, node, kind, detail in n8n_findings:
            by_file.setdefault(path, []).append((node, kind, detail))
        print(f"n8n call sites with no explicit connection ({len(n8n_findings)} "
              f"across {len(by_file)} workflow(s)):\n")
        for path in sorted(by_file):
            print(f"  {path}")
            for node, kind, detail in by_file[path]:
                print(f"      :: {node}  [{kind}]")
                print(f"         {detail}")
        print()
    if py_findings:
        print(f"Python call sites with no explicit connection ({len(py_findings)}):\n")
        for path, where, line in py_findings:
            print(f"  {path}  {where}")
            print(f"      {line}")
        print()

    total = len(n8n_findings) + len(py_findings)
    print(f"G62 FAIL — {total} automation call site(s) into apps/mail's canonical ops carry no "
          f"explicit connection_id.")
    print(f"  {coverage}")
    print(
        "\n  These resolve through /data/active.json — one shared pointer, flipped by a human\n"
        "  clicking the account bar and by any test run that needs another mailbox. A mail op\n"
        "  against the wrong mailbox does not error; it returns someone else's mail, or nothing.\n"
        "  Add `connection_id` (a vault instance id — `GET /connections` lists them) to this\n"
        "  call's params/body/query. For a pipe, it belongs in the registry entry and must travel\n"
        "  with the work item, exactly as `drive_connection_id` already does."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
