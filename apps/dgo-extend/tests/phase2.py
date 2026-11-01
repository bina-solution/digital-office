#!/usr/bin/env python3
"""DGO-35 · phase 2 — THE PORTABLE OFFICE: the machine on the LAN becomes a linked office.

Run with `bbox dgo test 2`. Owner's model (2026-10-01 16:20, ai/context/dgo-remote-apps.md): *apps run
where they run* — there is no placement. The home laptop becomes an office of its own, linked to the
Mac; the heavy apps are INSTALLED AND RUN THERE and appear at the Mac as remote apps. This gate is the
acceptance of that whole sentence, one check per clause:

  · the machine is in the fleet and answers the office key (DGO-35) — with its own numbers;
  · Docker there is **28.x** — on 29 traefik v3.3 discovers ZERO routers while reporting healthy, so
    every host 404s and it looks like a hundred unrelated failures (CLAUDE.md);
  · the office is declared with a commit the machine can actually FETCH (a local commit cannot be
    deployed: the remote clones from the repository);
  · the last converge is green: containers healthy and `console.<domain>` answering;
  · the link is up: a peer with a recent handshake, and the peer's tunnel address answers;
  · an app enabled THERE appears HERE as a remote app — the registry entry, the `<alias>.<office>`
    alias inside the engine, and the link plane reporting the office `up`;
  · the destination has the room the next heavy app needs, in numbers (not a feeling).

Written to fail with the MEASUREMENT, never with a verdict: every check prints what it saw, and a
check that could not look says so instead of passing. Two lessons from this gate's first runs are
built in: the declarations are fetched ONCE (two independent reads of a slow API gave two different
answers, and the second passed vacuously), and a container replaced mid-run by another lane's deploy
is looked at again rather than reported as a failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase0  # noqa: E402 — `inside()` records WHY it could not look on the module
from phase0 import api, check, inside, run  # noqa: E402  (the frame is shared)

APP_PREFIX = "dgo-extend-"
TUNNEL_PREFIX = "dgo-net-"
COMPUTERS_PREFIX = "computers-"


def _guard(fn):
    """A check never raises: an exception IS a failure, with its own name in the measurement."""
    def wrapped():
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"
    wrapped._check_name = fn._check_name
    return wrapped


def _why() -> str:
    return phase0.LAST_INSIDE_ERR


def _py(code: str, timeout: int = 90, tries: int = 2):
    """Run python3 inside the app container — where the office's modules and DNS live."""
    import time
    out = None
    for attempt in range(tries):
        out = inside(APP_PREFIX, code, timeout)
        if out is not None:
            break
        if attempt + 1 < tries:
            time.sleep(5)
    if out is None:
        return None
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"raw": out[-400:]}


#: One linked office's own answer to "would this app fit there now", asked through this office's
#: console door. Prints one JSON line: the answer, or `{"error": …}`.
_ROOM_OF = (
    "import json,os,urllib.request,urllib.error\n"
    "u=os.environ.get('CONSOLE_INTERNAL_URL','http://console:8000').rstrip('/')+'/a/app-management.%s/api/apps/%s/room'\n"
    "try:\n"
    "    print(urllib.request.urlopen(u,timeout=30).read().decode())\n"
    "except urllib.error.HTTPError as e:\n"
    "    print(json.dumps({'error': 'HTTP %%d' %% e.code}))\n"
    "except Exception as e:\n"
    "    print(json.dumps({'error': type(e).__name__}))\n"
)

#: Declarations, fetched ONCE (see the module docstring).
_OFFICES: dict = {}


def _offices() -> tuple[list[dict], str]:
    if not _OFFICES:
        d = api("/api/office", 60)
        if not isinstance(d, dict) or "items" not in d:
            _OFFICES["error"] = f"dgo-extend did not answer `/api/office`: {d!r}"
            _OFFICES["items"] = []
        else:
            _OFFICES["items"] = d.get("items") or []
            _OFFICES["error"] = ""
    return _OFFICES["items"], _OFFICES["error"]


def _declared(offs: list[dict]) -> list[dict]:
    """The offices this one DECLARED on a machine and converges over SSH — what DGO-35 is about."""
    return [o for o in offs if (o.get("kind") or "") != "paired"]


def _paired_only(offs: list[dict]) -> str:
    """The sentence for a DGO-35 check on an office that has nothing declared: its linked offices
    are PAIRED — installed on their own machines, paired from their own screens, converged by
    themselves. There is no machine record, no declared commit and no convergence HERE to check, and
    calling that a failure made this gate red on every office that only pairs (hp-laptop,
    2026-10-05: four reds and a `KeyError: 'machine'`). "" when the question does apply."""
    paired = [o.get("id") for o in offs if (o.get("kind") or "") == "paired"]
    if _declared(offs) or not paired:
        return ""
    return (f"nothing is DECLARED on a machine here — {len(paired)} paired office(s) "
            f"({', '.join(sorted(map(str, paired)))}) run on their own machines and answer for "
            f"themselves; the link to them is phase 3's")


def _exec_on(machine: str, command: str, timeout: int = 60) -> dict:
    """One command ON a machine — through `computers`, the office's only door to a machine.

    Run from INSIDE the computers container (its own API on 127.0.0.1): the service name does not
    resolve on the host where this gate runs, and reaching a machine any other way is exactly what
    that app exists to prevent.
    """
    code = ("import json,urllib.request\n"
            "body=json.dumps({'command':%s,'timeout':%d}).encode()\n"
            "req=urllib.request.Request('http://127.0.0.1:8977/api/computers/%s/exec',data=body,\n"
            "  headers={'content-type':'application/json'})\n"
            "print(urllib.request.urlopen(req,timeout=%d).read().decode())\n"
            % (json.dumps(command), min(timeout, 300), machine, timeout + 20))
    got = inside(COMPUTERS_PREFIX, code, timeout + 40)
    if got is None:
        return {"error": f"computers could not be reached: {_why()}"}
    try:
        return json.loads(got.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": f"unexpected answer: {got[:200]}"}


def _machine_of(office: dict) -> dict | None:
    ctx = api("/api/context", 90)
    if not isinstance(ctx, dict):
        return None
    return next((m for m in (ctx.get("machines") or []) if m.get("id") == office.get("machine")), None)


# ── the checks ───────────────────────────────────────────────────────────────────
@check("DGO-35 · an office is declared on a machine that answers the office key")
def c_machine():
    offs, err = _offices()
    if err:
        return False, f"could not read the declarations: {err}"
    if not offs:
        return False, ("no office is declared yet — the portable machine is registered in `computers` "
                       "as computer_ssh-2a63fd64, but nothing declares it as an office")
    if _paired_only(offs):
        return True, _paired_only(offs)
    lines, ok = [], True
    for o in _declared(offs):
        m = _machine_of(o)
        if not m:
            ok = False
            lines.append(f"{o.get('id')}: machine {o.get('machine')} is not in the fleet")
        elif not m.get("ok"):
            ok = False
            lines.append(f"{o.get('id')}: {m.get('state')} — {m.get('reason') or m.get('stderr')}")
        else:
            mem = (m.get("memory") or {}).get("available") or 0
            disk = (m.get("disk") or {}).get("available") or 0
            lines.append(f"{o.get('id')}: {m.get('hostname')} {m.get('os')} · {m.get('ncpu')}c · "
                         f"{mem / 1024 ** 3:.1f}GB free RAM · {disk / 1024 ** 3:.0f}GB free disk")
    return ok, " · ".join(lines)


@check("DGO-35 · Docker on the destination is 28.x (29 routes NOTHING, silently)")
def c_docker():
    offs, err = _offices()
    if err:
        return False, f"could not read the declarations: {err}"
    if not offs:
        return False, "no declared office — nothing to check Docker on (DGO-35)"
    if _paired_only(offs):
        return True, _paired_only(offs)
    offs = _declared(offs)
    bad = []
    for o in offs:
        r = _exec_on(o["machine"], "docker version --format '{{.Server.Version}}' 2>/dev/null || echo none")
        if r.get("error") or r.get("code") not in (0, None):
            bad.append(f"{o['id']}: {r.get('error') or r.get('stderr') or r.get('stdout')}")
            continue
        v = (r.get("stdout") or "").strip().splitlines()[-1:] or [""]
        v = v[0].strip()
        if not v.startswith("28."):
            bad.append(f"{o['id']}: Docker {v or 'unknown'} — traefik v3.3 needs 28.x "
                       f"(set engine.replace_docker: true, the `engine` step pins 28.5.2)")
    return (not bad), ("; ".join(bad) if bad else f"{len(offs)} office(s) on Docker 28.x")


@check("DGO-35 · the declared commit is one the machine can FETCH")
def c_pushed():
    offs, err = _offices()
    if err:
        return False, f"could not read the declarations: {err}"
    if not offs:
        return False, "no declared office — nothing to deploy (DGO-35)"
    if _paired_only(offs):
        return True, _paired_only(offs)
    bad = [f"{o.get('id')}: no source.commit" for o in _declared(offs)
           if not ((o.get("source") or {}).get("commit") or "")]
    return (not bad), ("; ".join(bad) if bad else
                       "a pushed commit is the deployable unit: the remote clones from the repository, "
                       "so an unpushed local commit cannot be converged")


@check("DGO-28 · an app enabled on the linked office appears HERE as a remote app")
def c_remote_app():
    offs, err = _offices()
    if err:
        return False, f"could not read the declarations: {err}"
    if not offs:
        return False, "no declared office yet (DGO-35)"
    link = api("/api/link", 60)
    if not isinstance(link, dict):
        return False, f"`/api/link` did not answer: {link!r}"
    items = link.get("items") or link.get("links") or []
    if not items:
        return False, "the link plane lists nothing — no peer has been pulled yet (converge + link up)"
    lines, ok = [], True
    for it in items:
        apps = it.get("apps") or []
        state = it.get("state") or "unknown"
        lines.append(f"{it.get('office')}: {state}, {len(apps)} app(s)"
                     + (f" ({', '.join(str(a.get('alias')) for a in apps[:6])})" if apps else ""))
        if state != "up" or not apps:
            ok = False
    return ok, " · ".join(lines)


@check("DGO-28 · the compiler rendered the remote alias, and it resolves inside the engine")
def c_alias():
    code, out = run(["python3", "platform/manager/reconcile.py", "serve-plan"], 120)
    if code != 0:
        return False, f"`reconcile.py serve-plan` exited {code}: {out[:300]}"
    try:
        plan = json.loads(out)
    except ValueError:
        return False, f"serve-plan did not print JSON: {out[:200]}"
    aliases = plan.get("aliases") or []
    dotted = [a for a in aliases if "." in str(a)]
    if not dotted:
        return False, (f"{len(aliases)} alias(es) rendered, none of them `<alias>.<office>` — no "
                       f"remote app is compiled yet (projection writes `remote:` in platform.state.yaml)")
    name = str(dotted[0])
    got = _py("import json,socket\n"
              "try: print(json.dumps({'ip': socket.gethostbyname(%r)}))\n"
              "except OSError as e: print(json.dumps({'error': str(e)}))\n" % name)
    if not got or "raw" in got:
        return False, f"could not resolve {name} in the app container: {got or _why()}"
    return (("ip" in got), f"{name} → {got.get('ip') or got.get('error')}")


@check("DGO-17/18 · the link is up: a peer with a recent handshake, and its address answers")
def c_tunnel():
    out = inside(TUNNEL_PREFIX, "import subprocess;print(subprocess.run(['wg','show'],"
                                "capture_output=True,text=True).stdout)")
    if out is None:
        return False, f"the tunnel container could not be read: {_why()}"
    peers = out.count("peer:")
    if not peers:
        return False, f"no WireGuard peer on this office: {out.strip()[:200] or '(empty)'}"
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("peer:")]
    return True, f"{peers} peer(s): " + "; ".join(lines[:3])


@check("DGO-35 · the office converged: its own console answers and its containers are healthy")
def c_converged():
    offs, err = _offices()
    if err:
        return False, f"could not read the declarations: {err}"
    if not offs:
        return False, "no declared office (DGO-35)"
    if _paired_only(offs):
        return True, _paired_only(offs)
    lines, ok = [], True
    for o in _declared(offs):
        run_info = o.get("run") or {}
        if not run_info:
            ok = False
            lines.append(f"{o['id']}: never converged")
            continue
        health = run_info.get("health") or {}
        went = f"{run_info.get('status')} @ {run_info.get('commit') or '—'}"
        if run_info.get("status") != "ok":
            ok = False
        lines.append(f"{o['id']}: {went}, health={json.dumps(health, ensure_ascii=False)[:160]}")
    return ok, " · ".join(lines)


@check("every destination answers whether it has room for the next heavy app — in numbers")
def c_room():
    """`admission.py`'s arithmetic, run here as a MEASUREMENT (the owner dropped placement as a
    mechanism, but installing a 1.5 GB app onto a machine with 300 MB free is still the failure this
    measures). The apps' own declared budgets are the ask; the machine's live record is the answer.

    WHAT FAILS THIS CHECK, and what does not. The arithmetic being wrong fails it, and so does an
    office that cannot answer the question. A destination that answers "no room" does not: that is
    what the machine IS at this minute, the apps screen says it with these same numbers at the
    moment somebody places an app there (and asks before going on), and this line was red on both
    offices of a pair every time either laptop was busy — `hp-laptop needs 4.3GB, has 3.5GB` from the
    MacBook, the mirror of it from here (2026-10-06). A gate that is red whenever a machine is in
    use is a gate nobody reads. The measurement is printed either way."""
    import importlib.util

    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # TWO modules, and they are different files: the arithmetic and its unit tests. Both live with
    # the control plane now (the office that RECEIVES an app answers for its own room — see the
    # module), and this gate keeps measuring with them. The first run of this gate loaded the tests
    # file for BOTH and got "module has no attribute check_machine", which reads as a missing
    # function rather than as the wrong file.
    plane = Path(__file__).resolve().parents[3] / "platform-base" / "app-management"
    adm = _load("dgo_admission", plane / "admission.py")
    tests = _load("dgo_admission_tests", plane / "test_admission.py")

    bad = []
    for fn in tests.CHECKS:
        try:
            ok, measured = fn()
        except Exception as e:  # noqa: BLE001
            ok, measured = False, f"{type(e).__name__}: {e}"
        if not ok:
            bad.append(f"{fn._check_name} — {measured}")
    if bad:
        return False, "; ".join(bad[:3])

    offs, err = _offices()
    if err:
        return False, f"could not read the declarations: {err}"
    if not offs:
        return True, f"{len(tests.CHECKS)} admission checks pass; no destination to measure yet"
    lines = []
    for o in offs:
        m = _machine_of(o)
        apps = [{"id": a, "resources": {"memory": "1792M", "cpus": "6"}} for a in ("browser42",)]
        if m:
            v = adm.check_machine(m, apps)
        else:
            # A PAIRED office has no machine record here: nobody holds a door to its machine. It
            # answers the question about itself (its control plane's `/room`, the same rule), and the
            # way to it is this office's console door — the way the apps screen asks.
            v = _py(_ROOM_OF % (o["id"], "browser42"), 60) or {}
            if not isinstance(v.get("ok"), bool):
                lines.append(f"{o['id']}: NOT MEASURED — the office does not answer the room question "
                             f"(it predates it, or does not give its app-management): "
                             f"{str(v.get('error') or v)[:70]}")
                continue
        lines.append(f"{o['id']}: {'room for browser42' if v['ok'] else 'NO ROOM now — ' + v['summary']} "
                     f"({v['have']['memory_available_mb']:.0f}MB free RAM)")
    return not any("NOT MEASURED" in ln for ln in lines), " · ".join(lines)


def _tileless() -> set[str]:
    """Apps with no TILE at all: no `module` in any of their `routing[]` entries.

    A catalog is a projection of the compiled registry, and an app with no module has no row in it on
    ANY office — so its absence from a peer's catalog is not "it stopped existing": there was never
    anything to show. The answer has to come from the MANIFESTS and not from this office's registry:
    that registry only carries the apps ENABLED here, so reading it classified every app this office
    has switched off (`n8n`, `glitchtip`) as tileless — the first version of this helper did exactly
    that, and it is the difference between "nothing to publish" and "we did not look".

    Measured 2026-10-05: `apitools` declares one routing entry and no module → tileless. `n8n` and
    `glitchtip` each declare a module → they stay on the leak list, which is the point.
    """
    root = Path(__file__).resolve().parents[3]
    out: set[str] = set()
    for base in ("apps", "platform-base"):
        for man in (root / base).glob("*/app.json"):
            try:
                m = json.loads(man.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not any((r.get("module") for r in (m.get("routing") or []) if isinstance(r, dict))):
                out.add(man.parent.name)
    return out


@check("DGO-28 · nothing falls between the two offices (off here AND unpublished there)")
def c_nothing_lost():
    """The one failure this migration can produce that nothing else would catch.

    The owner's plan is explicit about the ORDER — an app is disabled at the Mac only after the copy
    on hp serves it — and that rule is exactly what a gate has to hold: an app that is switched off
    here and absent from the peer's published catalog is an app that has silently STOPPED EXISTING
    (its containers stopped, its volumes still on the Mac's disk, and no tile anywhere). Every other
    check in this file can be green while that is true.

    `enabled-apps` is the compiler's own answer to "what runs here" (one source, no second list), and
    the catalog is the peer's own answer to "what do I publish" — the two facts this compares.
    """
    offs, err = _offices()
    if err:
        return False, f"could not read the declarations: {err}"
    if not offs:
        return False, "no declared office yet (DGO-35)"

    code, out = run(["python3", "platform/manager/reconcile.py", "enabled-apps"], 120)
    if code != 0:
        return False, f"`reconcile.py enabled-apps` exited {code}: {out[:200]}"
    # The verb prints one line per app as `<layer> <id>` — `platform-base` for the substrate and
    # `apps` for the products. Reading only the `apps` lines (the first version of this check did)
    # reports a three-app office and then calls every substrate app "missing".
    local = {ln.split()[1] for ln in out.splitlines()
             if len(ln.split()) > 1 and ln.split()[0] in ("apps", "platform-base")}

    # `/api/link/remote` is where the catalogs this office holds are reported. They used to ride on
    # `/api/link`; when they moved this check kept reading the old field, found none, and said "no
    # catalog pulled yet" for every peer — red for a reason that had stopped being true.
    link = api("/api/link/remote", 90)
    if not isinstance(link, dict) or "catalogs" not in link:
        return False, (f"`/api/link/remote` did not answer with the catalogs ({str(link)[:120]}) — "
                       f"without them there is no way to tell an app that MOVED from an app that is GONE")
    catalogs = link.get("catalogs") or {}
    pulled = set(catalogs)
    published = {oid: {str(a.get("app") or a.get("alias")) for a in (doc.get("apps") or [])}
                 for oid, doc in catalogs.items()}

    unreachable, both, moved, nothing = [], [], [], []
    tileless = _tileless()         # nothing to publish is not "it stopped existing" — see the helper
    for o in offs:
        oid = o.get("id") or ""
        remote_ids = {a for a, disp in (o.get("apps") or {}).items() if disp == "enabled"}
        no_catalog = oid not in pulled
        for app in sorted(remote_ids):
            if app in local:
                both.append(app)
            elif app in published.get(oid, set()):
                moved.append(app)
            elif app in tileless:
                nothing.append(f"{app} ({oid})")
            else:
                unreachable.append(f"{app} ({oid}{', no catalog pulled yet' if no_catalog else ''})")
    text = (f"here: {len(local)} app(s) · declared enabled on a peer: "
            f"{len(both) + len(moved) + len(unreachable) + len(nothing)}"
            f" · enabled in BOTH: {len(both)} · published by the peer and off here: {len(moved)}"
            f" · no tile on any office: {len(nothing)}"
            f" · catalogs pulled: {sorted(pulled) or 'none'}")
    if nothing:
        text += f" — nothing to publish for {', '.join(nothing)}"
    if unreachable:
        return False, (f"{text} — declared by a peer, NOT enabled here and NOT published by it, so "
                       f"nothing in this office can reach them: {', '.join(unreachable[:12])}"
                       + (" …" if len(unreachable) > 12 else ""))
    return True, text


PHASE2 = [_guard(f) for f in
          (c_machine, c_docker, c_pushed, c_converged, c_tunnel, c_remote_app, c_alias, c_room,
           c_nothing_lost)]
