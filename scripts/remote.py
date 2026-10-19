#!/usr/bin/env python3
"""bbox remote — the apps of a LINKED office, and one authenticated call through the link.

The contract is `ai/context/dgo-remote-apps.md` §6–7. An app of another office is never copied here:
it runs there, and this office gives it THREE faces, all of them derived from the same `remote:`
block the compiler renders:

    a tile      `<alias>.<office>`                        (the apps rail, the app manager)
    an edge     the same name nested under this office's own host
    an address  `http://<alias>.<office>:<port>`          (a network alias on the link proxy)

This CLI is the fourth face — the terminal and the agent:

    bbox remote                       the linked offices and the apps they publish
    bbox remote <office>              one office
    bbox remote <office> <alias>      one app: its two doors, its edge host, its auth declaration
    bbox remote <office> <alias> <p>  one authenticated request through the link

`<p>` is a PATH, never a URL. The host is derived from the office, the alias and the port the
SERVING office published — a caller that can name the host can name any host, and the whole point of
the alias is that there is exactly one door per remote app. A token never appears in a URL and never
on a command line: it is read from this office's vault by NAME, through the engine — the same trust
`bbox agent` already uses — and the name comes from what the serving office published about its own
app (`api.auth: bearer:vault:<instance>`).

TWO KINDS OF "INSIDE", and the CLI picks by asking rather than by assuming:

  · this process may already be inside the office network (an agent in a container, a shell in the
    engine) — then the request is made here;
  · on the office's own host it is not, and `<alias>.<office>` does not resolve there at all,
    because it is a DOCKER NETWORK ALIAS: it means something to a process attached to the office
    network and to nobody else. So the request is handed to a container that IS attached
    (`_delegate`), which re-runs this same file with the resolution already made.

Rebuilding the whole presentation on the far side, rather than a bespoke "inner mode", is what keeps
one implementation of what a linked office looks like.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
# The engine hand-off (`darwin` → the Lima guest) and the vault reader are bbox_agent's, and they
# exist once. A second copy of "how to reach docker from this host" is how the Mac path rots.
from bbox_agent import client as agentcli  # noqa: E402

#: The office network — the shared external network every app is attached to (root `compose.yml`).
#: It is not an app's; it is the platform's, and the network alias this CLI depends on lives on it.
NETWORK = "traefik-network"
#: Set on the delegated run. Its presence means "you are already where the alias resolves".
ENV_IN_NETWORK = "BBOX_REMOTE_IN_NETWORK"
#: The resolution the outer run made and the delegated run must not redo (it has no checkout).
ENV_RESOLVED = "BBOX_REMOTE_RESOLVED"
#: Where the link plane answers. Read from that app's own manifest (see `link_endpoint`).
ENV_LINK_URL = "BBOX_REMOTE_LINK_URL"
DEFAULT_TIMEOUT = 30.0
#: Exit codes, so a script can tell a refusal from an outage. 3 is bbox_agent's "could not reach or
#: could not authenticate" on purpose — the same class of failure reads the same way in both verbs.
EXIT_HTTP = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3

#: WHERE the two planes this verb speaks to live, addressed the one way layer 0 may name an app: by
#: its own DIRECTORY — the same delegation `bbox` performs when it dispatches into
#: `apps/<id>/hooks/<verb>`. Nothing about either app is copied here: the endpoint is read out of the
#: manifest this path points at, so moving a port or a container name is a manifest edit and not a
#: CLI bug, and there is no second list of which app plays which role.
#:   · the link plane publishes the catalog and the link state this verb reads (contract §6);
#:   · the credential plane holds the token an app's API door is opened with (§7).
LINK_MANIFEST = "apps/dgo-extend/app.json"
VAULT_MANIFEST = "platform-base/connections/app.json"


class RemoteError(Exception):
    """A failed command, carrying the exit code the CLI should end with."""

    def __init__(self, message: str, code: int = EXIT_UNREACHABLE):
        super().__init__(message)
        self.message, self.code = message, code


#: The program that runs in the delegated container: unpack the payload, put the module it ships on
#: `sys.path`, and run THIS file with the same arguments. Kept as source rather than as a one-liner
#: because it is the one place the two halves of a delegated run have to agree.
INNER_SCRIPT = '''
import base64, json, os, pathlib, sys, tempfile
p = json.loads(base64.b64decode("%(payload)s").decode("utf-8"))
d = pathlib.Path(tempfile.mkdtemp())
for name, text in p["modules"].items():
    f = d / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
sys.path.insert(0, str(d))
os.environ.update(p["env"])
sys.argv = ["bbox remote"] + p["argv"]
exec(compile(p["src"], "remote.py", "exec"),
     {"__name__": "__main__", "__file__": p["file"]})
'''


def _module_sources() -> dict:
    """The source of the one module this file imports — so a delegated run needs no checkout.

    `bbox_agent.client` owns "how to reach the engine from this host" and "how to read the vault",
    and neither is re-implemented here. Shipping its SOURCE is what lets the far side keep using the
    one copy: a container is not promised this repo, and a delegated run that silently depended on
    the mount would work on the box it was written on and nowhere else.
    """
    out = {}
    base = Path(__file__).resolve().parent / "bbox_agent"
    for name in ("__init__.py", "client.py"):
        try:
            out[f"bbox_agent/{name}"] = (base / name).read_text(encoding="utf-8")
        except OSError:
            pass
    return out


def _require_repo() -> None:
    """Refuse a checkout-dependent read with a sentence, instead of answering "nothing there"."""
    if not (REPO / "apps").is_dir():
        raise RemoteError(f"this run has no checkout at {REPO} — a delegated run uses the "
                          f"resolution it was handed, and only a run on the office's own host "
                          f"can read `platform.state.yaml` or `.generated/`")


# ── the engine ──────────────────────────────────────────────────────────────────
def _docker(args: list, timeout: float = 60.0, input_text: str = None) -> subprocess.CompletedProcess:
    return subprocess.run(agentcli._engine_cmd(["docker", *args]), capture_output=True, text=True,
                          timeout=timeout, input=input_text)


def _runner() -> str:
    """A running container on the office network that can run python3.

    Which container is NOT a fact worth declaring: any of them answers, because the alias resolves
    for every process attached to that network. So the CLI asks Docker which containers are attached
    and uses the first one that actually runs python3 — an image without an interpreter is skipped by
    measurement, not by a list of names that goes stale.
    """
    try:
        p = _docker(["ps", "--filter", f"network={NETWORK}", "--format", "{{.Names}}"], timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RemoteError(f"the office engine is not answering ({type(e).__name__}: {e})")
    names = [n.strip() for n in p.stdout.split() if n.strip()]
    if not names:
        raise RemoteError(f"no running container is attached to {NETWORK} — cannot reach the link "
                          f"from this host")
    problems = []
    for name in sorted(names):
        try:
            t = _docker(["exec", name, "python3", "-c", "pass"], timeout=45)
        except (OSError, subprocess.TimeoutExpired) as e:
            problems.append(f"{name}: {type(e).__name__}")
            continue
        if t.returncode == 0:
            return name
        problems.append(f"{name}: {t.stderr.strip()[:60]}")
    raise RemoteError("no container on the office network can run python3 — tried "
                      + "; ".join(problems))


def _delegate(argv: list, resolved: dict, timeout: float) -> int:
    """Run THIS file inside a container on the office network, and give back its output.

    The source and the arguments travel as one base64 JSON payload on the runner's STDIN rather
    than as arguments: the path from a Mac host to the engine re-parses the command line twice
    (Lima's shell, then sudo), so anything quoted is a coin toss, and a line has a size limit a
    stream does not. The vault instance NAMES travel in it too (they are not secrets); the token
    itself is read on the far side, inside the network, and never exists in an argv anywhere.

    What the far side cannot re-derive comes with it, because the container is not promised a
    checkout: where the link plane and the vault answer, and what was already resolved (a call's
    URL, an app's registry record). The
    one small module this file imports (`bbox_agent.client`, for the vault reader) is shipped as
    SOURCE for the same reason — a delegated run that depends on the repo being mounted somewhere
    inside a container would work on the box it was written on and nowhere else.
    """
    runner = _runner()
    env = {ENV_IN_NETWORK: "1", ENV_RESOLVED: json.dumps(resolved)}
    # BOTH planes' endpoints, not only the link's: the runner is whichever container answers first,
    # and it is promised neither a checkout nor `CONNECTIONS_URL` in its environment. Measured
    # 2026-10-06 on hp-laptop (the runner that answered first had neither): every call died on "no
    # credential … this run has no checkout", because the vault's address was looked up over there.
    for name, where in ((ENV_LINK_URL, link_endpoint), ("CONNECTIONS_URL", vault_url)):
        try:
            env[name] = where()
        except RemoteError:
            pass
    payload = {"src": Path(__file__).read_text(encoding="utf-8"), "argv": argv, "env": env,
               "file": str(Path(__file__).resolve()), "modules": _module_sources()}
    blob = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    inner = INNER_SCRIPT % {"payload": blob}
    # THE PAYLOAD TRAVELS ON STDIN. It used to be the command line — one base64 argument, because
    # nothing in such an argument can be re-parsed by the shells between here and the container
    # (Lima's shell, sudo, ssh). But ONE argument has a size the kernel enforces (128 KiB), and this
    # file plus the module it ships are 67 KB — base64'd twice, 119 KB: a few more comments and every
    # delegated run died on "Argument list too long" (measured 2026-10-06, hp-laptop). What stays on
    # the line is a constant with no spaces and no `$`, and it turns an empty stdin into a loud
    # ZeroDivisionError rather than a silent success.
    code = "exec(__import__('sys').stdin.read()or'1/0')"
    try:
        p = _docker(["exec", "-i", runner, "python3", "-c", code], timeout=timeout, input_text=inner)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RemoteError(f"could not run inside {runner} ({type(e).__name__}: {e})")
    if p.stdout:
        sys.stdout.write(p.stdout)
    if p.stderr:
        sys.stderr.write(p.stderr)
    return p.returncode


# ── where things are ────────────────────────────────────────────────────────────
def _in_network() -> bool:
    return os.environ.get(ENV_IN_NETWORK) == "1"


def _endpoint_from_manifest(rel: str) -> str:
    """The in-network endpoint an app declares about itself, from the manifest at this path.

    The service capability first (`type: service`, e.g. `instances.v1`), then any capability with an
    endpoint — an app that declares itself as a protocol only is still reachable at the one address it
    publishes, and asking the manifest is what keeps one number in one place.
    """
    _require_repo()
    try:
        doc = json.loads((REPO / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RemoteError(f"cannot read {rel} in this checkout ({type(e).__name__}: {e})")
    caps = [c for c in (doc.get("capabilities") or []) if c.get("endpoint")]
    caps.sort(key=lambda c: 0 if c.get("type") == "service" else 1)
    if not caps:
        raise RemoteError(f"{rel} declares no capability with an endpoint")
    return str(caps[0]["endpoint"]).rstrip("/")


def link_endpoint() -> str:
    """Where the link plane answers, INSIDE the office network. Never a public URL."""
    url = os.environ.get(ENV_LINK_URL, "").strip().rstrip("/")
    return url or _endpoint_from_manifest(LINK_MANIFEST)


def vault_url() -> str:
    """Where the credential plane answers, inside the office network.

    The environment wins (`CONNECTIONS_URL`, which is what every app's compose passes), and on the
    office's own host — where no compose environment exists — the app's own manifest answers.
    """
    return (os.environ.get("CONNECTIONS_URL") or _endpoint_from_manifest(VAULT_MANIFEST)).rstrip("/")


def registry_record(office: str, alias: str) -> dict:
    """The compiler's own record of one remote app: `.generated/registry/remote.<office>.<alias>.json`.

    Read here for the same reason the app manager reads it: it is the per-app artifact layer 0
    renders from the very `remote:` entry that produced the route, so "the CLI thinks this app is at
    port X" and "the edge routes it at port X" cannot drift. Absent = this office does not show that
    app right now (no link, an exclusion, or a render that has not run).

    A delegated run is HANDED the record (`link_state`): the file is on the office's own host.
    """
    handed = (json.loads(os.environ.get(ENV_RESOLVED) or "{}") or {}).get("registry")
    if handed is not None:
        return handed
    _require_repo()
    path = REPO / ".generated/registry" / f"remote.{office}.{alias}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def state_remote_app(office: str, alias: str) -> dict:
    """The `remote:` entry of `platform.state.yaml` for one app — the fallback when the registry has
    not been rendered yet (a checkout that has never run `bbox reconcile`). It carries the doors but
    not the catalog's auth declaration, which is exactly the difference the two readers report."""
    _require_repo()
    for entry in agentcli._remote_blocks():
        if str(entry.get("office") or "").strip().lower() != office:
            continue
        for app in (entry.get("apps") or []):
            if not isinstance(app, dict):
                continue
            if str(app.get("alias") or app.get("app") or "").strip().lower() == alias:
                api = app.get("api") if isinstance(app.get("api"), dict) else {}
                return {"port": int(entry.get("link_port") or app.get("port") or 0),
                        "api_port": int(app.get("agent_api_port") or api.get("port") or 0),
                        "auth": str(api.get("auth") or ""), "app": str(app.get("app") or ""),
                        "source": "platform.state.yaml"}
    return {}


# ── one HTTP request ────────────────────────────────────────────────────────────
def http(method: str, url: str, data: bytes = None, headers: dict = None,
         timeout: float = DEFAULT_TIMEOUT) -> tuple:
    """(status, headers, body-bytes) — or RemoteError. Never follows a redirect with credentials."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise RemoteError(f"{method} {url}: {type(e).__name__}: {e}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A remote app must not be able to move this request — and its Authorization header — elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def vault_token(instances: list, office: str, timeout: float = DEFAULT_TIMEOUT) -> tuple:
    """(token, the instance it came from) — one credential from THIS office's vault, by name, from
    inside the network. The NAME goes back with it so that a refusal can say whose token was refused.

    Candidate names, tried in order, because more than one convention is live: the instance the
    serving office's own catalog named (`api.auth`), the per-app instance its converge writes
    (`dgo_link-serve-<office>-<app>-agent`, DGO-32) and the per-office link token. A miss names every
    name it tried — "no token" without the list is a sentence nobody can act on.
    """
    from bbox_agent.client import INSTANCE_RE
    names = [str(i).strip() for i in instances if i and INSTANCE_RE.match(str(i).strip())]
    if not names:
        raise RemoteError("the catalog names no vault instance for this app's API")
    tried = []
    for name in names:
        try:
            status, _h, body = http("GET", f"{vault_url()}/api/instances/{name}/secret",
                                    timeout=timeout)
        except RemoteError as e:
            tried.append(f"{name}: {e.message}")
            continue
        if status != 200:
            tried.append(f"{name}: HTTP {status}")
            continue
        try:
            secret = (json.loads(body) or {}).get("secret") or {}
        except ValueError:
            secret = {}
        token = _pick_token(secret)
        if token:
            return token, name
        tried.append(f"{name}: no token in the secret ({', '.join(sorted(secret)) or 'empty'})")
    raise RemoteError(f"no credential for `{office}` in this office's vault — tried "
                      + "; ".join(tried))


def _pick_token(secret: dict) -> str:
    """The token field of a vault secret, by preference. Protocols differ in what they call it, and
    the CLI's question is the same for all of them: which of these strings is the bearer?"""
    if not isinstance(secret, dict):
        return ""
    for key in ("token", "api_token", "access_token", "secret", "key", "password"):
        v = secret.get(key)
        if isinstance(v, str) and v:
            return v
    strings = [v for v in secret.values() if isinstance(v, str) and v]
    return strings[0] if len(strings) == 1 else ""


# ── the link plane's own view ───────────────────────────────────────────────────
def link_state(args) -> dict:
    """`GET /api/link` on the link plane: this office's record, and every linked office.

    Which office is linked, whether it answers, and which apps it publishes are ITS facts — this is
    the only reader that has them (the compiled registry can only name the apps this office already
    routes), so the list is ASKED for rather than reconstructed.

    THE REACH DECISION IS HERE, once for every command that needs the link plane: if this process is
    not where the endpoint resolves, the whole command is handed to a container that is — including
    the presentation, so the far side runs one code path and not a special "remote mode".
    """
    url = link_endpoint()
    if not _in_network() and not _resolves(_host_of(url)):
        one = getattr(args, "office", None) and getattr(args, "alias", None)
        handed = {"registry": registry_record(args.office, args.alias)} if one else {}
        raise _Delegated(_delegate(_ARGV, handed, args.timeout + 60))
    return _fetch_link(url, args.timeout)


def _fetch_link(url: str, timeout: float) -> dict:
    """The link plane's answer, with NO reach decision — for a caller that is already where it has to
    be, and for the one place that must not delegate a second time (a running call)."""
    status, _h, body = http("GET", f"{url}/api/link", timeout=timeout)
    if status != 200:
        raise RemoteError(f"{url}/api/link answered HTTP {status}")
    try:
        return json.loads(body)
    except ValueError:
        raise RemoteError(f"{url}/api/link did not answer JSON")


class _Delegated(Exception):
    """The work was done by the delegated run, whose stdout/stderr and exit code are already out."""

    def __init__(self, rc: int):
        super().__init__(f"delegated (exit {rc})")
        self.rc = rc


#: The invocation being run, so the delegated copy is the SAME command and not an approximation.
_ARGV: list = []


def _host_of(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].split(":")[0]


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def offices(data: dict) -> list:
    return list(data.get("items") or [])


def find_office(data: dict, office: str) -> dict:
    for item in offices(data):
        if str(item.get("office") or "").lower() == office:
            return item
    known = ", ".join(sorted(str(i.get("office")) for i in offices(data))) or "(none)"
    raise RemoteError(f"no linked office named {office!r} — linked: {known}", EXIT_USAGE)


def find_app(item: dict, alias: str) -> dict:
    for app in (item.get("apps") or []):
        if str(app.get("alias") or "").lower() == alias:
            return app
    known = ", ".join(sorted(str(a.get("alias")) for a in (item.get("apps") or []))) or "(none)"
    raise RemoteError(f"{item.get('office')} publishes no app with the alias {alias!r} — "
                      f"published: {known}", EXIT_USAGE)


# ── resolving one call ──────────────────────────────────────────────────────────
def resolve(office: str, alias: str, use_api: bool) -> dict:
    """Everything a call needs, from the compiler's own record or the state block.

    The registry record wins (it carries the catalog's `api.auth`, which is what decides whether
    there is a token to fetch); the state block is the fallback for a checkout that has not rendered.
    Both name the app by its office and alias, and the URL is built from the alias and the port that
    the SERVING office published — never from the tunnel address, which is this office's private view
    of the peer and means nothing to anyone else.
    """
    rec = registry_record(office, alias)
    if rec:
        doors = {"port": int(rec.get("link_port") or rec.get("port") or 0),
                 "api_port": int(rec.get("agent_api_port") or 0),
                 "auth": str((rec.get("api") or {}).get("auth") or ""),
                 "app": str(rec.get("app") or ""), "source": "registry"}
    else:
        doors = state_remote_app(office, alias)
    if not doors:
        raise RemoteError(
            f"{alias}.{office} is not declared in this office — it is not in the compiled registry "
            f"(no link, an exclusion, or no render yet). Ask the link plane what it DOES hold: "
            f"`bbox remote`", EXIT_USAGE)
    port = doors["api_port"] if use_api else doors["port"]
    if not port:
        raise RemoteError(f"{alias}.{office} has no {'API' if use_api else 'UI'} door published"
                          f"{' — the app declares no second port' if use_api else ''}", EXIT_USAGE)
    auth = doors["auth"]
    instances = []
    if auth:
        instances = _auth_instances(auth, office, doors.get("app") or alias)
    return {"office": office, "alias": alias, "app": doors.get("app") or "",
            "url": f"http://{alias}.{office}:{port}", "port": port, "api": bool(use_api),
            "auth": auth, "instances": instances, "source": doors["source"]}


def _auth_instances(auth: str, office: str, app: str) -> list:
    """The vault instances to try for one app's API, in order.

    The two derived names are the conventions a converge writes HERE for the other office's agent,
    and they are listed so that a name that has moved is a sentence naming both, not a silent 401.
    `bearer:vault:<name>` is the shape the catalog publishes (`catalog.py`).
    """
    # THE NAMES THAT SAY WHICH OFFICE come first, and the catalog's own name is used only when it is
    # one of them. What the serving office publishes (`bearer:vault:bina-ds`) is a name in ITS vault;
    # read here it is THIS office's instance of the same name — every office has a `bina-ds` — so the
    # call presented this office's own agent token to the other office and was answered 401
    # (measured 2026-10-06, hp-laptop → macbook). One office's token is never offered to another.
    out = [f"dgo_link-serve-{office}-{app}-agent", f"dgo_link-{office}"]
    named = auth.split("bearer:vault:", 1)[1].strip() if auth.startswith("bearer:vault:") else ""
    if named.startswith("dgo_link-"):
        out.insert(0, named)
    seen, uniq = set(), []
    for name in out:
        if name and name not in seen:
            seen.add(name)
            uniq.append(name)
    return uniq


# ── the commands ────────────────────────────────────────────────────────────────
def cmd_offices(args) -> int:
    data = link_state(args)
    home = data.get("home") or {}
    items = offices(data)
    if args.json:
        print(json.dumps({"home": home, "offices": items}, ensure_ascii=False, indent=2))
        return 0
    print(f"this office: {home.get('id')}  domain={home.get('domain')}  "
          f"slot={home.get('slot')}  {home.get('fingerprint') or ''}")
    if not items:
        print("no linked offices — a link is DECLARED, never discovered: `./bbox help` lists the link "
              "verbs, and the office UI has a connected-offices screen")
        return 0
    for item in items:
        print_office(item)
    return 0


def print_office(item: dict) -> None:
    print(f"\n{item.get('office')}  {item.get('label') or ''}")
    print(f"  link {item.get('direction') or '—':<5} slot={item.get('peer_slot') or '—'} "
          f"state={item.get('state') or 'unknown'}"
          + (f"  ({item.get('state_at') or ''})" if item.get('state_at') else "")
          + (f"  error: {item.get('state_error')}" if item.get('state_error') else ""))
    print(f"  commit {(item.get('commit') or '—')[:12]}")
    apps = item.get("apps") or []
    if not apps:
        print("  apps: none published (or the catalog was never pulled)")
        return
    print(f"  apps ({len(apps)}):")
    for app in apps:
        api = app.get("api") or {}
        title = (app.get("title") or {}).get("he") or ""
        mark = "  (not on this rail)" if app.get("hidden") else ""
        print(f"    {str(app.get('alias') or ''):<16} {title:<20}"
              f"ui {str(app.get('port') or '—'):<6} api {str(api.get('port') or '—'):<6}{mark}")


def cmd_office(args) -> int:
    data = link_state(args)
    item = find_office(data, args.office)
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0
    print_office(item)
    return 0


def cmd_app(args) -> int:
    data = link_state(args)
    item = find_office(data, args.office)
    app = find_app(item, args.alias)
    rec = registry_record(args.office, args.alias)
    api = app.get("api") or {}
    doors = {"ui": app.get("port"), "api": api.get("port"),
             "auth": api.get("auth") or (rec.get("api") or {}).get("auth") or ""}
    if args.json:
        print(json.dumps({"office": args.office, "label": item.get("label"), "app": app,
                          "registry": rec}, ensure_ascii=False, indent=2))
        return 0
    print(f"{args.alias}.{args.office}  —  {app.get('title', {}).get('he') or app.get('app') or ''}"
          f"  [{app.get('app') or rec.get('app') or '?'}]")
    print(f"  office      {item.get('office')} · {item.get('label') or ''} · "
          f"state={item.get('state') or 'unknown'}  commit={(item.get('commit') or '—')[:12]}")
    print(f"  tile id     {args.alias}.{args.office}")
    print(f"  in-network  ui http://{args.alias}.{args.office}:{doors['ui'] or '—'}"
          f"   api http://{args.alias}.{args.office}:{doors['api'] or '—'}")
    print(f"  rendered    {'yes — .generated/registry/remote.%s.%s.json' % (args.office, args.alias) if rec else 'no — this office does not route it (excluded, or no render yet)'}")
    if doors["auth"]:
        print(f"  api auth    {doors['auth']}  (the token is read from the vault by name, never "
              f"passed on a command line)")
    if app.get("hidden"):
        print("  note        hidden on this rail (POST /api/link/exclude) — the app keeps running "
              "there; the tile, the router and the alias are gone here")
    if app.get("ok") is False:
        print("  note        the office did not answer on the last pull")
    print(f"\n  call it:    bbox remote {args.office} {args.alias} <path>")
    return 0


def cmd_call(args) -> int:
    path = args.path
    if "://" in path or path.startswith("//") or not path.startswith("/"):
        raise RemoteError("the third argument is a PATH on the remote app (it must start with `/` "
                          "and contain no host) — the host is derived from the office, the alias "
                          "and the port the serving office published", EXIT_USAGE)
    resolved = json.loads(os.environ.get(ENV_RESOLVED) or "{}") or None
    if not resolved:
        resolved = resolve(args.office, args.alias, args.api)
    url = resolved["url"] + path
    if not _in_network() and not _resolves(_host_of(resolved["url"])):
        # The alias is a docker network alias: on the office's own machine it means nothing, and the
        # request has to be made from a container that is attached to the office network.
        return _delegate(_argv_for(args), resolved, args.timeout + 60)
    headers = {}
    data = None
    if args.data is not None:
        data = args.data.encode("utf-8")
    for raw in (args.header or []):
        if ":" in raw:
            k, v = raw.split(":", 1)
            headers[k.strip()] = v.strip()
    if resolved.get("api"):
        # The API door is a BEARER door. Which credential opens it is the serving office's own
        # declaration — the `api.auth` it published in its catalog — so it is asked for, and only
        # when it names a vault instance is a token fetched. A miss does not stop the call: an app
        # whose API is open answers, and one that refuses answers 401 with its own sentence.
        instances = resolved.get("instances") or []
        if not instances:
            instances = _catalog_instances(resolved, args.timeout)
        if instances:
            token, held_as = vault_token(instances, resolved["office"], args.timeout)
            headers.setdefault("Authorization", f"Bearer {token}")
    method = (args.method or ("POST" if data is not None else "GET")).upper()
    status, hdrs, body = http(method, url, data=data, headers=headers, timeout=args.timeout)
    text = body.decode("utf-8", "replace")
    if status == 401 and resolved.get("api") and instances:
        # WHOSE token was refused is the only fact that makes a 401 actionable, and a name is not a
        # secret: the credential this office holds for that agent is older than the agent's own.
        print(f"  the token offered is `{held_as}` in this office's vault — {resolved['office']} does "
              f"not accept it; the handoff is that office's (its link converge writes it here)",
              file=sys.stderr)
    if args.json:
        print(json.dumps({"url": url, "method": method, "status": status,
                          "content_type": hdrs.get("Content-Type", ""), "body": text},
                         ensure_ascii=False, indent=2))
    else:
        print(f"HTTP {status}  {method} {url}")
        if args.include:
            for k, v in sorted(hdrs.items()):
                print(f"  {k}: {v}")
        print(text if text.endswith("\n") else text + "\n", end="")
    return 0 if status < 400 else EXIT_HTTP


def _catalog_instances(resolved: dict, timeout: float) -> list:
    """The vault instances the SERVING office's catalog names for this app's API.

    `catalog.build` publishes `api.auth` as `bearer:vault:<instance>` — the instance the office that
    runs the app says opens it. The link plane holds that catalog here, so this is where the CLI
    reads it; a link plane that does not answer is not fatal (the call goes out unauthenticated and
    the app's own 401 is the answer), which is why this returns an empty list rather than raising.
    """
    try:
        data = _fetch_link(link_endpoint(), timeout)
    except RemoteError:
        return []
    for item in offices(data):
        if str(item.get("office") or "").lower() != resolved["office"]:
            continue
        for app in (item.get("apps") or []):
            if str(app.get("alias") or "").lower() != resolved["alias"]:
                continue
            auth = str((app.get("api") or {}).get("auth") or "")
            if auth:
                return _auth_instances(auth, resolved["office"],
                                       str(app.get("app") or resolved.get("app") or
                                           resolved["alias"]))
    return []


def _argv_for(args) -> list:
    """The same invocation, for the delegated run — so the far side uses ONE code path."""
    out = [args.office, args.alias, args.path]
    if args.method:
        out += ["-X", args.method]
    if args.data is not None:
        out += ["-d", args.data]
    if args.api:
        out += ["--api"]
    for h in (args.header or []):
        out += ["-H", h]
    out += ["--timeout", str(args.timeout)]
    if args.json:
        out += ["--json"]
    if args.include:
        out += ["-i"]
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bbox remote", add_help=True,
                                 description="the apps of a linked office, and one call through "
                                             "the link (ai/context/dgo-remote-apps.md §6–7)")
    ap.add_argument("office", nargs="?", help="a linked office id (see `bbox remote`)")
    ap.add_argument("alias", nargs="?", help="the app's alias there — one office may publish two "
                                             "apps, and a local app may share the alias")
    ap.add_argument("path", nargs="?", help="a PATH on that app, e.g. /v1/sessions or /healthz")
    ap.add_argument("-X", "--method", help="HTTP method (default GET, or POST with -d)")
    ap.add_argument("-d", "--data", help="request body (implies POST unless -X says otherwise)")
    ap.add_argument("-H", "--header", action="append", metavar="K: V", help="extra header (repeatable)")
    ap.add_argument("--api", action="store_true",
                    help="call the app's API door (agent_api_port) instead of its UI door")
    ap.add_argument("-i", "--include", action="store_true", help="print response headers")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SEC")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    return ap


def main(argv: list = None) -> int:
    global _ARGV
    argv = list(sys.argv[1:] if argv is None else argv)
    _ARGV = argv
    args = build_parser().parse_args(argv)
    args.office = (args.office or "").strip().lower()
    args.alias = (args.alias or "").strip().lower()
    try:
        if not args.office:
            return cmd_offices(args)
        if not args.alias:
            return cmd_office(args)
        if not args.path:
            return cmd_app(args)
        return cmd_call(args)
    except _Delegated as d:
        return d.rc
    except RemoteError as e:
        print(f"  ERROR {e.message}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
