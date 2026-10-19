#!/usr/bin/env python3
"""DGO-5/DGO-23 · phase 1 — tunnel and link: the gate of ai/context/dgo-extend-plan.md §12.

Run with `bbox dgo test 1`. What it checks, and why each one is the gate rather than a symptom:

  · the office HAS an identity, and it is stable (DGO-16) — a fingerprint that changes between two
    reads is a key that was re-minted, and every peer would have to be re-paired;
  · the identity is declared for BACKUP (DGO-22) — a volume outside `data.volumes` is a key that a
    rebuilt office loses, which is the same as a new office;
  · a tunnel exists between the declared offices and BOTH sides can reach the other's address
    (DGO-17/18/23) — measured by pinging through it, not by "the container is up";
  · a forged source drops (DGO-21) — the link authorizes a direction, and a packet pretending to come
    from the other side without the tunnel must not pass;
  · revoke takes the peer down on BOTH sides in one converge (DGO-18/20).

Until phase 1 is built, every tunnel check fails with the work item that owes it. That is the point
of a gate: it is red while the thing is missing, and the measurement says which thing.
"""
from __future__ import annotations

import json
import importlib.util
import time
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase0  # noqa: E402 — `inside()` records WHY it could not look on the module
from phase0 import api, check, inside, offices, run  # noqa: E402  (the frame is shared)

ROOT = Path(__file__).resolve().parents[3]


@check("DGO-16 · this office has an identity, and it is stable")
def c_identity():
    a = api("/api/identity") or {}
    first = (a.get("identity") or {}).get("fingerprint")
    if not first:
        # The app reads /identity (the volume). If it cannot see one, ask the machine directly: the
        # hook is what mints, and a gate that only asks the app cannot tell "not minted" from "not
        # mounted".
        code, out = run(["./bbox", "dgo", "identity", "fingerprint"], 180)
        return (False, f"the app has no identity in its volume ({out.strip()[:80]})") if code else \
               (False, f"minted on the machine ({out.strip()}) but not visible to the app — is "
                       f"dgo_identity mounted?")
    b = api("/api/identity") or {}
    second = (b.get("identity") or {}).get("fingerprint")
    ok = first == second and len(first.split("-")) == 4
    return ok, f"fingerprint {first} (stable across two reads: {first == second})"


@check("DGO-22 · the identity volume is carried by `bbox export`, and a restore returns the SAME identity")
def c_backup():
    """The identity is the one thing an office cannot re-mint and keep its name: a lost `dgo_identity`
    volume is a new office to every peer, and every link has to be re-paired. So it is not enough that
    the volume is DECLARED — the archive has to carry it, and a restore has to give back the same key.

    Declared: `data.volumes` (what the archiver derives its inventory from; gate G26 keeps it honest).
    Carried:  the archiver's own `_tar_volume`/`_untar_volume`, imported from
              `scripts/deployment-archive.py` — the same two functions `bbox export`/`import` call, so
              this measures the product's path rather than a second implementation of it.
    Same key: the fingerprint of the restored volume equals the live one's.

    The restore runs with `COMPOSE_PROJECT_NAME` pointed at a scratch project, so it writes a
    throwaway volume and cannot touch the live one. What this does NOT do: a whole `bbox import`,
    which this host refuses by design (a second compose project on `traefik-network` collides on
    docker aliases) — the check says so instead of pretending to have run it.
    """
    manifest = json.loads((ROOT / "apps/dgo-extend/app.json").read_text(encoding="utf-8"))
    vols = manifest.get("data", {}).get("volumes") or []
    named = [v if isinstance(v, str) else (v or {}).get("name") for v in vols]
    compose = (ROOT / "apps/dgo-extend/docker-compose.yml").read_text(encoding="utf-8")
    if "dgo_identity" not in named or "dgo_identity:" not in compose:
        return False, f"data.volumes={named} · compose declares it: {'dgo_identity:' in compose}"

    sys.path.insert(0, str(ROOT / "apps" / "dgo-extend"))
    # `deployment-archive.py` is not an importable name (a hyphen), and it is the ONLY implementation
    # of the archive — so it is loaded by path rather than copied here.
    spec = importlib.util.spec_from_file_location(
        "deployment_archive", ROOT / "scripts" / "deployment-archive.py")
    arch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(arch)
    import identity as idmod           # noqa: PLC0415

    # The LIVE document, through the app that mounts the volume (this check may run anywhere, and
    # /identity exists only inside that container).
    raw = inside("dgo-extend-", "print(open('/identity/identity.json', encoding='utf-8').read())") or ""
    live = json.loads(raw) if raw.strip().startswith("{") else {}
    if not live:
        return False, f"the identity volume could not be read through the app ({raw[:80]!r})"

    scratch = "dgo22-verify"
    tmp = Path(tempfile.mkdtemp())
    tar = tmp / "dgo_identity.tar.gz"
    # The LIVE volume is named `<compose project>_dgo_identity`, and the project name is not in the
    # environment everywhere this check runs (bbox exports it; a bare `python3 phase1.py` does not).
    # Asking the running container what it has mounted is the one answer that cannot drift.
    _, names = run(["docker", "ps", "--filter", "name=^dgo-extend-", "--format", "{{.Names}}"], 60)
    name = (names.splitlines() or [""])[0].strip()
    _, mount = run(["docker", "inspect", name, "--format",
                    '{{range .Mounts}}{{if eq .Destination "/identity"}}{{.Name}}{{end}}{{end}}'], 60)
    project = mount.strip()[:-len("_dgo_identity")] if mount.strip().endswith("_dgo_identity") else ""
    if not project:
        return False, f"the live identity volume could not be identified (mount={mount[:80]!r})"
    try:
        os.environ["COMPOSE_PROJECT_NAME"] = project
        arch._tar_volume("dgo_identity", tar)
        os.environ["COMPOSE_PROJECT_NAME"] = scratch
        arch._untar_volume("dgo_identity", tar)
        code, out = run(["docker", "run", "--rm", "-v", f"{scratch}_dgo_identity:/v", "alpine:3.20",
                         "cat", "/v/identity.json"], 120)
        restored = json.loads(out) if code == 0 and out.strip().startswith("{") else {}
    finally:
        os.environ.pop("COMPOSE_PROJECT_NAME", None)
        run(["docker", "volume", "rm", "-f", f"{scratch}_dgo_identity"], 60)
    same = bool(restored) and idmod.fingerprint(restored) == idmod.fingerprint(live)
    return same, (f"data.volumes={named} · exported and restored through the archiver's own volume "
                  f"step ({project} → {scratch}) · fingerprint live={idmod.fingerprint(live)} "
                  f"restored={idmod.fingerprint(restored) if restored else '(none)'} · "
                  f"private halves identical: {restored == live}")


def _not_built(item: str, what: str):
    return False, f"NOT BUILT ({item}) — {what}"


@check("DGO-17 · the tunnel plan renders, and refuses what it must")
def c_render():
    code, out = run(["python3", "apps/dgo-extend/net.py"], 120)
    if code != 0:
        return False, f"net.py selftest failed: {out[-200:]}"
    # The sidecar has to exist in the compiled compose, or the plan has nothing to apply it.
    code2, cfg = run(["./scripts/dc", "config", "--services"], 240)
    has = "dgo-net" in cfg.split()
    return has, f"net.py selftest PASS · dgo-net in the compiled stack: {has}"


@check("DGO-19 · the link plane is validated, in Hebrew")
def c_schema():
    """`validate()` is a pure function of the body, so this is measured without a machine."""
    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import declaration
    base = {"id": "probe", "machine": "computer_ssh-x", "domain": "probe.example.co.il",
            "path": "/opt/probe", "source": {"repo": "https://x/y.git", "commit": "a" * 40}}
    cases = [
        ({"tunnel": {"slot": 0}}, "slot"),
        ({"tunnel": {"slot": 300}}, "slot"),
        ({"tunnel": {"slot": 3, "dial": "sideways"}}, "dial"),
        ({"links": [{"office": "BAD ID", "direction": "use"}]}, "office"),
        # `both` was the refused example here until a link could be bidirectional; it is a direction now
        ({"links": [{"office": "vps1", "direction": "sideways"}]}, "direction"),
        ({"links": [{"office": "vps1"}, {"office": "vps1"}]}, "פעמיים"),
        ({"serve": {"drive": {}}}, "port"),
        ({"identity": {"wg": "short"}}, "identity"),
    ]
    bad = []
    for body, needle in cases:
        _, err = declaration.apply_link_plane(body, dict(base))
        if not err or needle not in err:
            bad.append(f"{list(body)[0]}: expected a refusal mentioning {needle!r}, got {err!r}")
    _, ok_err = declaration.apply_link_plane(
        {"tunnel": {"slot": 3, "dial": "home"}, "links": [{"office": "vps1", "direction": "serve"}],
         "serve": {"drive": {"port": 8975}}}, dict(base))
    if ok_err:
        bad.append(f"a valid link plane was refused: {ok_err}")
    return not bad, (f"{len(cases) + 1} cases · " + ("all as declared" if not bad else "; ".join(bad[:2])))


@check("DGO-20 · the link token protocol exists, and its names are derived")
def c_link_token():
    import yaml
    cat = yaml.safe_load((ROOT / "platform-base/connections/providers/40-apps.yaml")
                         .read_text(encoding="utf-8")) or []
    listed = any(p.get("id") == "dgo-link" for p in cat)
    code, out = run(["python3", "apps/dgo-extend/links.py"], 60)
    return listed and code == 0, (f"catalogue lists dgo-link: {listed} · "
                                  f"name derivation selftest: {'PASS' if code == 0 else out[-120:]}")


def _link_doc() -> dict:
    """`GET /api/link` — this office's record plus every declared peer's link (empty when the app is
    not reachable from where the gate runs, which the checks say rather than pretending)."""
    return api("/api/link") or {}


def _link_item(doc: dict) -> dict | None:
    """The link these checks measure: an office this one INSTALLS when there is one (the model the
    converge-driven checks were written for), else the first paired office."""
    items = [i for i in (doc.get("items") or []) if i.get("declared")]
    return next((i for i in items if i.get("kind") != "paired"), None) or (items[0] if items else None)


def _paired(item: dict | None) -> bool:
    return bool(item) and item.get("kind") == "paired"


def _computers_exec(machine: str, command: str, timeout: int = 90) -> tuple[int, str]:
    """Run a command on a machine through `computers` — the same door every step uses, so a check that
    passes here is a check of the same path the product takes."""
    import urllib.request as u
    body = json.dumps({"command": command, "timeout": timeout}).encode()
    req = u.Request(f"http://computers:8977/api/computers/{machine}/exec", data=body, method="POST",
                    headers={"content-type": "application/json"})
    try:
        with u.urlopen(req, timeout=timeout + 30) as r:
            d = json.loads(r.read() or b"{}")
    except u.HTTPError as e:                     # `computers` answered — what it said is the answer
        return 255, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:                       # noqa: BLE001 — a neighbour being down is an answer
        return 255, f"{type(e).__name__}: {e}"
    return int(d.get("code") or 0), (d.get("stdout") or "") + (d.get("stderr") or "")


@check("DGO-17/18 · `bbox dgo link` reports the link, and the tunnel is rendered")
def c_tunnel():
    rows = offices()
    if not rows:
        return False, "no office is declared — nothing to link"
    code, out = run(["./bbox", "dgo", "link", "status"], 120)
    if code != 0:
        return False, f"`bbox dgo link status` exited {code}: {out.strip()[:140]}"
    doc = _link_doc()
    home = doc.get("home") or {}
    item = _link_item(doc)
    if not item:
        return False, f"no declared link ({len(rows)} office(s) declared) — `bbox dgo link up <office>`"
    files = sorted(k for k, v in ((doc.get("tunnel") or {}).get("tunnel") or {}).items()
                   if v.get("present"))
    # `both` is a direction since a link can be bidirectional; this read `in ("use", "serve")` and
    # failed every paired link, which is `both` by default.
    ok = bool(home.get("slot")) and "wg0.conf" in files and "nftables.rules" in files \
        and item.get("direction") in ("use", "serve", "both") and bool(item.get("peer_fingerprint"))
    return ok, (f"home slot={home.get('slot')} {home.get('fingerprint')} · {item['office']} "
                f"{item.get('direction')} slot={item.get('peer_slot')} "
                f"{item.get('peer_fingerprint')} · rendered {files}")


@check("DGO-155 · the link's verdict is one answer: the API's, the file the console is handed, and every tile of that office")
def c_verdict():
    """`remote.ok` was read by the console and written by nothing. Three places must now say the same
    thing about one office, measured within the last two minutes — read-only, on the live link."""
    item = _link_item(_link_doc())
    if not item:
        return None, "no declared link — nothing to judge"
    v = item.get("verdict") or {}
    # `pair` joined the vocabulary on 2026-10-12 (lnk-032): a pair written the wrong way round is a
    # cause class of its own — not a hop that fell, and not "the office is not answering".
    hops = {True: ("",), False: ("tunnel", "office", "door", "pair"), None: ("",)}
    if v.get("ok") not in hops or v.get("hop") not in hops[v.get("ok")]:
        return False, f"/api/link says {v!r} about {item['office']} — not a verdict"
    seen = inside("console", "import json,time,urllib.request as u\n"
                  "d=json.load(open('/app/peers.d/link.json'))\n"
                  "t=json.load(u.urlopen('http://127.0.0.1:8000/api/modules',timeout=20))['modules']\n"
                  "print(json.dumps({'age':int(time.time()-d['at']),'offices':d['offices'],"
                  "'tiles':[m['remote'] for m in t if isinstance(m.get('remote'),dict)]}))")
    if not seen:
        return False, f"the console could not be asked: {phase0.LAST_INSIDE_ERR}"
    seen = json.loads(seen)
    mine = [r for r in seen["tiles"] if r.get("office") == item["office"]]
    handed = (seen["offices"].get(item["office"]) or {})
    ok = (seen["age"] < 120 and handed.get("ok") == v.get("ok") and handed.get("hop") == v.get("hop")
          and all(r.get("ok") == v.get("ok") for r in mine)
          and all(bool(r.get("why")) == (v.get("ok") is False) for r in mine))
    return ok, (f"{item['office']}: api {v} · file {handed} ({seen['age']}s old) · "
                f"{len(mine)} tile(s) ok={sorted({str(r.get('ok')) for r in mine})}")


@check("DGO-23 · both ends answer a ping through the tunnel")
def c_ping():
    doc = _link_doc()
    item = _link_item(doc)
    if not item:
        return False, "no declared link to measure"
    oid = item["office"]
    home = doc.get("home") or {}
    if _paired(item):
        # A PAIR has no converge to read and no machine to run a ping on. What it has is measured
        # where the interface lives (the tunnel container, every 15 s) and by the pull that just
        # crossed it: a handshake inside the last three minutes, her catalog here, our door answering.
        tun = item.get("tunnel")
        if not tun:
            return False, (f"the tunnel to {oid} is not measured here — its container writes nothing "
                           "(an image from before it did, or it has stopped)")
        door = ((item.get("delivery") or {}).get("door") or {}).get("listening")
        age = tun.get("handshake_age_s")
        ok = bool(tun.get("alive")) and item.get("state") == "up" and bool(door)
        return ok, (f"{oid} (paired): handshake {'never' if age is None else str(age) + 's ago'} · "
                    f"she answers: {item.get('state')} · the pair's door here: {'listening' if door else 'SILENT'}")
    # What the converge MEASURED is the step's own result: step_link refuses unless the far end
    # answered the ping, so a green step is evidence, and it is read from the run, not assumed.
    run_doc = api(f"/api/office/{oid}/run") or {}
    step = ((run_doc.get("run") or {}).get("steps") or {}).get("link") or {}
    measured = ((step.get("result") or {}).get("links") or [{}])[0]
    if not measured:
        return False, f"the last converge of {oid} has no `link` result — run `bbox dgo link up {oid}`"
    # And a LIVE round trip both ways, through the same door: wg on both ends, and a ping from the
    # far machine to THIS office's tunnel address (the direction the link authorizes).
    my_addr = measured.get("self")
    local_wg = inside("dgo-net-", "import subprocess;print(subprocess.run(['wg','show','wg0'],"
                                  "capture_output=True,text=True).stdout or 'no wg0')") or ""
    code, remote = _computers_exec(item["machine"],
                                   f"wg show wg0 2>/dev/null | head -2; ping -c1 -W3 {my_addr} "
                                   f">/dev/null 2>&1 && echo PONG || echo SILENT")
    up_both = "interface:" in local_wg and "interface:" in remote
    pong = "PONG" in remote
    ok = up_both and pong
    if not ok and "255" == str(code):
        return False, f"computers is not reachable from where this gate runs: {remote[:120]}"
    return ok, (f"{my_addr} ↔ {measured.get('peer')} · wg up on both ends: {up_both} · "
                f"ping from {oid}: {'PONG' if pong else 'SILENT'}")


@check("DGO-24 · a served port is DELIVERED, not merely allowed")
def c_delivery():
    """`firewall.py` renders the PERMISSION; this is the half that makes it a delivery.

    The distinction is not academic: measured from vps1 on 2026-10-01, `10.79.2.1:3081` and `:8983`
    did not answer — `timeout 8` expired (rc=124), i.e. the SYN was DROPPED, not refused. The tunnel
    was up, the firewall had already `accept`ed the port, and nothing delivered it. So the check is:

      1. the renderer's own decisions (`linkproxy.py` selftest) — pure, so it holds before a second
         office exists;
      2. the plan on disk matches the office's OWN `serve:` list — a port declared and not delivered
         is a door the owner believes is open;
      3. a connection to that port ANSWERS inside the tunnel's namespace (the listener exists);
      4. and it answers FROM THE FAR MACHINE, through the tunnel — which is the acceptance, and the
         only one of the four that a permission alone cannot pass.
    """
    code, out = run(["python3", "apps/dgo-extend/linkproxy.py"], 120)
    if code != 0:
        return False, f"linkproxy.py selftest failed: {out[-200:]}"
    doc = _link_doc()
    served = doc.get("serve") or {}
    rules = ((doc.get("proxy") or {}).get("rules")) or []
    if not served:
        return False, ("NOT BUILT (DGO-24) — this office declares no `serve:` list, so there is nothing "
                       "it offers a peer: `POST /api/link/serve {\"serve\":{\"bina-ds\":{\"port\":3081}}}`")
    # `*` is "everything this office runs" (the pairing screen's default): the rules are then one per
    # app it runs, so there is no count to hold them to — only "at least one".
    if "*" not in served and len(rules) != len(served):
        return False, (f"{len(served)} app(s) declared in `serve:` but {len(rules)} delivery rule(s) "
                       f"rendered — declared: {sorted(served)}")
    if not rules:
        return False, f"`serve:` is declared ({sorted(served)}) and no delivery rule is rendered"
    item = _link_item(doc)
    if not item:
        return False, "no declared link, so no peer's address to deliver from (`bbox dgo link up <office>`)"

    # 3 · the listener, in the namespace where the tunnel address exists at all.
    snippet = (
        "import json,socket\n"
        "p=json.load(open('/tunnel/link-proxy.json'))\n"
        "out=[]\n"
        "for r in p['rules']:\n"
        "    b='127.0.0.1' if r['bind']=='0.0.0.0' else r['bind']\n"
        "    try:\n"
        "        s=socket.create_connection((b,int(r['port'])),timeout=4); s.close()\n"
        "        out.append('OPEN '+r['bind']+':'+str(r['port']))\n"
        "    except OSError as e:\n"
        "        out.append('FAIL '+r['bind']+':'+str(r['port'])+' '+(e.strerror or str(e)))\n"
        "print('; '.join(out))")
    # RETRIED, not asked once: a converge re-renders the plan and the tunnel applier re-applies it,
    # so a single probe measures the applier's own timer rather than the delivery (measured
    # 2026-10-01: a gate run that asked once read `10.79.2.1` as unreachable for the few seconds the
    # tunnel was being rebuilt, and called a link that works a link that does not).
    listened, waited = None, 0
    while waited < 90:
        listened = inside("dgo-link-", snippet, 90)
        if listened and "FAIL" not in listened and "OPEN" in listened:
            break
        time.sleep(10)
        waited += 10
    if listened is None:
        return False, ("the link proxy does not answer here (no `dgo-link-*` container, or it "
                       f"could not be asked): {phase0.LAST_INSIDE_ERR}")
    if "FAIL" in listened or "OPEN" not in listened:
        return False, f"the plan is rendered but nothing listens: {listened}"

    # 4 · and from the far machine, through the tunnel — the acceptance itself. A paired office's
    # machine is not ours to run a command on; its own gate measures this half from its side. What
    # can be said from here is the half that crosses the same tunnel the other way.
    if _paired(item):
        tun = item.get("tunnel") or {}
        ok = item.get("state") == "up" and bool(tun.get("alive"))
        return ok, (f"{len(rules)} rule(s) from `serve:` {sorted(served)} · listener present ({listened}) · "
                    f"{item['office']} (paired): her catalog arrived through the tunnel: {item.get('state')}; "
                    "the reach from her machine is her own gate's to measure")
    my_addr = rules[0]["bind"]
    ports = sorted(int(r["port"]) for r in rules)
    measured, missing = [], []
    for port in ports:
        _rc, out_r = _computers_exec(
            item["machine"],
            f"for i in $(seq 1 8); do timeout 3 bash -c 'echo > /dev/tcp/{my_addr}/{port}' "
            f"2>/dev/null && {{ echo OPEN; break; }}; sleep 4; done; echo END", 120)
        ok = "OPEN" in out_r
        measured.append(f":{port}={'OPEN' if ok else 'SILENT'}")
        if not ok:
            missing.append(port)
    if missing:
        return False, (f"rendered and listening here, but {item['machine']} cannot reach "
                       f"{my_addr} on {missing} — the permission is not a delivery "
                       f"({', '.join(measured)})")
    return True, (f"{len(rules)} rule(s) from `serve:` {sorted(served)} · listener present "
                  f"({listened}) · from {item['office']}: {', '.join(measured)}")


@check("DGO-21 · the allow-list is rendered from the declaration, and a port it never named is closed")
def c_forged():
    """Direction is enforced where the packet ARRIVES (decision 9), so the measurement is of the
    RULES — and of the kernel taking them.

    Three questions, in the order that makes a wrong answer visible:

      1. does the renderer decide what it claims (`firewall.py` selftest: `use` opens nothing,
         `serve` opens exactly its ports, an undescribable peer is refused)?
      2. does the rule set for a two-office example leave a forged port OUT — a packet to 9999, or to
         an app port nobody declared, has no `accept` to match?
      3. does the kernel accept the rendered ruleset AND read it back unchanged (`nft -c` in the very
         container that applies it, then `nft -f` in a throwaway network namespace)?

    What this check does NOT yet measure: an actual packet from another office, because a forged
    packet needs a live tunnel and a second machine — the acceptance of DGO-21 says the rules are the
    measurement until then. When a link IS live, the same rule set is what the peer's FORGERY meets.
    """
    code, out = run(["python3", "apps/dgo-extend/firewall.py"], 120)
    if code != 0:
        return False, f"firewall.py selftest failed: {out[-200:]}"

    sys.path.insert(0, str(ROOT / "apps/dgo-extend"))
    import firewall  # noqa: PLC0415 — the module under test, from the checkout being tested

    # 8975 is served; 9999/8976/5432/22 are not, and 22 is in the list on purpose: the tunnel must
    # not become a way into the machine just because the office runs sshd on it.
    peers = [{"office": "peer", "address": "10.79.9.2", "direction": "serve",
              "ports": {"drive": 8975}},
             {"office": "other", "address": "10.79.8.2", "direction": "use"}]
    doc = firewall.nft_document(peers)
    forged = [p for p in (22, 8976, 9999, 5432) if f"tcp dport {p} accept" in doc]
    if forged:
        return False, f"the rendered rules accept forged ports {forged} — a link is not a port list"
    if "10.79.8.2" not in doc or "10.79.8.2 tcp dport" in doc:
        return False, "a `use` link must be present in the firewall as a drop, and open no port"

    parsed, parsed_why = firewall.nft_check(doc)
    if parsed is not True:
        return False, f"nft refused the rendered ruleset: {parsed_why}"
    applied, applied_why = firewall.nft_apply_check(doc)
    if applied is not True:
        return False, f"the kernel did not take the ruleset: {applied_why}"
    return True, (f"2 peers · served drive:8975 · forged 22/5432/8976/9999 absent · {parsed_why} · "
                  f"{applied_why}")


def _wait_run(oid: str, timeout: int = 240) -> dict:
    """Block until an office's converge finishes, and return the step's result. The gate is the only
    caller that waits on purpose: a revocation is not proven by the request being accepted."""
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        run_doc = api(f"/api/office/{oid}/run", timeout=30) or {}
        run = run_doc.get("run") or run_doc
        if run.get("status") in ("ok", "failed", "error"):
            return run
        _t.sleep(7)
    return {}


@check("DGO-18/20 · revoke removes the peer on BOTH sides in one converge")
def c_revoke():
    """`bbox dgo link down <office>` IS the revoke: one converge that takes the far end's tunnel down,
    removes this end's rendered plan, drops the link entry and revokes the vault's link tokens.
    Measured on both ends, then the link is put back — a gate that left the estate without a tunnel
    would be a gate that breaks what it measures."""
    doc = _link_doc()
    item = _link_item(doc)
    if not item:
        return False, "no declared link to revoke"
    # NEVER A PAIR. This check takes a link DOWN and puts it back, which is a converge on a machine
    # this office installs. A paired office is taken apart by its owner from the pairing screen and
    # by nothing else — on 2026-10-06 this line ran `bbox dgo link down macbook` against a live pair
    # (the app refused it; the gate must not have asked).
    if _paired(item):
        return None, (f"{item['office']} is a paired office: a pair is unpaired by its owner from the "
                      "pairing screen, and this gate does not press that")
    oid, machine = item["office"], item["machine"]
    code, out = run(["./bbox", "dgo", "link", "down", oid], 120)
    if code != 0:
        return False, f"`bbox dgo link down {oid}` exited {code}: {out.strip()[:120]}"
    run_res = _wait_run(oid)
    step = ((run_res.get("steps") or {}).get("unlink")) or {}
    if step.get("status") != "ok":
        return False, f"unlink step: {step.get('status')} {str(step.get('result'))[:120]}"
    files = sorted(k for k, v in ((_link_doc().get("tunnel") or {}).get("tunnel") or {}).items()
                   if v.get("present"))
    _rc, remote = _computers_exec(machine, "wg show wg0 2>/dev/null | head -1 || echo NO-WG")
    gone_here = "wg0.conf" not in files
    gone_there = "NO-WG" in remote or not remote.strip()
    still_linked = any(i.get("declared") for i in (_link_doc().get("items") or []))
    # put it back: the acceptance is "one converge cleans both sides", not "the link is gone forever"
    run(["./bbox", "dgo", "link", "up", oid], 120)
    back = _wait_run(oid)
    up_again = ((back.get("steps") or {}).get("link") or {}).get("status") == "ok"
    ok = gone_here and gone_there and not still_linked and up_again
    return ok, (f"this end: rendered={files or 'none'} · {oid}: {remote.strip()[:40] or 'no wg0'} · "
                f"link entry removed: {not still_linked} · re-created after: {up_again}")


@check("DGO-155 · the link's door answers for itself: a card to a page request, a bare status to anything else, and says it was the door")
def c_door_says():
    """An empty `404`/`502` or a closed connection was what the door said, and on a real domain that
    empty answer IS the frame a person sees. Pure: the door's own function over a socket pair."""
    import socket
    spec = importlib.util.spec_from_file_location("dgo_link_proxy", ROOT / "apps" / "dgo-extend" / "link-proxy.py")
    lp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lp)

    def ask(reason: str, accept: str) -> tuple[bytes, bytes]:
        a, b = socket.socketpair()
        lp._say(a, reason, b"GET / HTTP/1.1\r\nHost: x\r\nAccept: " + accept.encode() + b"\r\n\r\n")
        got = b""
        b.settimeout(5)
        while True:
            chunk = b.recv(65536)
            if not chunk:
                break
            got += chunk
        b.close()
        head, _, body = got.partition(b"\r\n\r\n")
        return head, body

    bad = []
    for reason, status in (("no-app", b"404"), ("app-down", b"502"), ("unreachable", b"502")):
        head, body = ask(reason, "text/html,application/xhtml+xml")
        text = body.decode("utf-8", "replace")
        if not (head.startswith(b"HTTP/1.1 " + status) and b"X-Dgo-Door: " + reason.encode() in head
                and b"Content-Length: " + str(len(body)).encode() in head
                and 'dir="rtl"' in text and 'http-equiv="refresh"' in text and len(text) > 300):
            bad.append(f"{reason}: a page request got {head[:60]!r} + {len(body)} bytes")
        head, body = ask(reason, "application/json")
        if body or b"X-Dgo-Door: " + reason.encode() not in head or b"Content-Length: 0" not in head:
            bad.append(f"{reason}: an API call got a body of {len(body)} bytes")
    return not bad, ("three reasons × (page, call): the page is a Hebrew card that asks again, the call a bare status, "
                     "both name the door" if not bad else "; ".join(bad))


@check("DGO-181 · the old move door hands a paired office to the office's own mover, and never crashes on it")
def c_paired_move():
    """`POST /api/office/<paired>/move` died on `office["machine"]`. It is asked here ONLY with
    requests that are refused before anything can happen — a core app (which never moves), a request
    marked as arriving over a link, and "the whole office" — so this check moves nothing, on any
    office. What it proves is who answers: the control plane's mover, in its own words."""
    item = _link_item(_link_doc())
    if not _paired(item):
        return None, "no paired office here — the SSH-era mover is the one that answers, and it is phase 3's"
    seen = inside("dgo-extend", "import json,urllib.request as u,urllib.error\n"
                  "def post(path,body,h=None):\n"
                  "    q=u.Request('http://127.0.0.1:8983'+path,data=json.dumps(body).encode(),method='POST',"
                  "headers={'content-type':'application/json',**(h or {})})\n"
                  "    try:\n        r=u.urlopen(q,timeout=150); return [r.status,r.read().decode()[:200]]\n"
                  "    except urllib.error.HTTPError as e:\n        return [e.code,e.read().decode()[:200]]\n"
                  "o=%r\n"
                  "print(json.dumps({'core':post('/api/office/'+o+'/move',{'app':'console'}),"
                  "'link':post('/api/office/'+o+'/move',{'app':'console'},{'X-DGO-Office':o}),"
                  "'whole':post('/api/office/'+o+'/move-office',{})}))" % item["office"], 200)
    if not seen:
        return False, f"the app could not be asked: {phase0.LAST_INSIDE_ERR}"
    got = json.loads(seen)
    ok = (got["core"][0] == 403 and "core platform app" in got["core"][1]
          and got["link"][0] == 403 and "core platform app" not in got["link"][1]
          and got["whole"][0] == 409)
    return ok, (f"{item['office']}: a core app -> {got['core'][0]} from the control plane's mover · "
                f"asked over a link -> {got['link'][0]} here · the whole office -> {got['whole'][0]}")


@check("DGO-6 · a 404 is classified by WHO served it (identity / edge / app)")
def c_refusal_origin():
    """The health step counts a host dead on a 4xx, and that judgement is only worth anything if it
    tells the three sources apart: the identity layer refusing a host nobody registered (dead),
    traefik matching no router (dead), and the app answering for a path it has no page for — an API
    root like kong's, which is a LIVE host. Pure function, so it runs wherever the suite runs."""
    sys.path.insert(0, str(ROOT / "apps" / "dgo-extend"))
    import converge  # noqa: PLC0415
    cases = {
        b'<!DOCTYPE html><title>authentik</title>404 page not found': "identity",
        b'404 page not found\n': "edge",
        b'{"message":"no Route matched with those values"}': "app",
        b'': "edge",
    }
    bad = [f"{k[:24]!r} -> {converge._refusal_origin(k)} (want {v})"
           for k, v in cases.items() if converge._refusal_origin(k) != v]
    # …and a host that gave no answer at all says which errand it is: a record, a router, a machine.
    import socket  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415
    silent = {"השם לא נפתר ב-DNS": urllib.error.URLError(socket.gaierror(-2, "Name or service not known")),
              "החיבור נדחה": urllib.error.URLError(ConnectionRefusedError(111, "refused")),
              "לא ענה בזמן": TimeoutError("timed out")}
    bad += [f"{type(e).__name__} -> {converge._no_answer(e)} (want {want})"
            for want, e in silent.items() if converge._no_answer(e) != want]
    return not bad, ("ארבעת המקרים מסווגים · שלוש שתיקות נקראות בשמן" if not bad else "סיווג שגוי: " + "; ".join(bad))


@check("DGO-6 · every GET route of the app answers (a 500 must not read as 'no data')")
def c_routes():
    """`/api/office/<id>/login` — the button the owner presses to get INTO a remote office — answered
    `500 NameError: CONNECTIONS_URL` from the day it was written until DGO-6's acceptance read it,
    because nothing had ever CALLED it: a route with no test behind it is a route nobody knows the
    state of. The paths are read out of `app.py`, so a route added later is covered the moment it
    exists; the office-id ones are asked about every declared office."""
    src = (ROOT / "apps" / "dgo-extend" / "app.py").read_text(encoding="utf-8")
    paths = re.findall(r'@app\.get\("([^"]+)"\)', src)
    oid = ((offices() or [{}])[0] or {}).get("id") or "no-such-office"
    bad, checked, pages, refused = [], 0, [], []
    for p in paths:
        if p == "/":                       # the static UI, not a JSON route
            continue
        filled = p.replace("{oid}", oid)
        if "{" in filled:                  # a path parameter we cannot invent a value for
            continue
        checked += 1
        # `/api/context` runs git on the office's own machine through `computers` and takes ~90s on a
        # large checkout (measured 2026-10-01: 88.3s); a 40s timeout there is the gate lying about a
        # route that answers.
        if api(filled, timeout=150 if filled == "/api/context" else 45) is not None:
            continue
        # NOT every route answers JSON, and a route that serves a PAGE is not a broken route:
        # `/connect` (DGO-34) returns `connect.html`. What this check exists to catch is a route nobody
        # ever called answering 500 (the `/api/office/<id>/login` NameError), so for those the question
        # is the HTTP answer itself — an exception carries a 5xx, a page carries 200.
        # …and a REFUSAL is an answer too: a paired office has no login to reveal and no machine to
        # move to, and the app says so with a 4xx and its reason. Counting those as broken kept this
        # check red on every office whose first declared office is a paired one.
        status = _http_status(filled)
        if status == 200:
            pages.append(filled)
        elif status and 400 <= status < 500:
            refused.append(f"{filled} ({status})")
        else:
            bad.append(f"{filled} ({status if status else 'no answer'})")
    note = (f"{checked} נתיבים עונים" + (f" · עמוד (לא JSON): {', '.join(pages)}" if pages else "")
            + (f" · סירוב עם סיבה: {', '.join(refused)}" if refused else ""))
    return not bad, (note if not bad else "נתיבים שהחזירו שגיאה: " + ", ".join(bad))


def _http_status(path: str) -> int | None:
    """The status of one GET from wherever this gate runs — the same doors `phase0.api` uses."""
    import urllib.error
    import urllib.request
    for base in [u for u in (os.environ.get("DGO_EXTEND_URL", ""), "http://dgo-extend:8983") if u]:
        try:
            with urllib.request.urlopen(base.rstrip("/") + path, timeout=45) as r:
                return int(r.status)
        except urllib.error.HTTPError as e:
            return int(e.code)
        except Exception:                            # noqa: BLE001 — try the next door
            continue
    out = inside("dgo-extend-",
                 "import urllib.request,urllib.error\n"
                 "try:\n"
                 f"    print(urllib.request.urlopen('http://127.0.0.1:8983{path}',timeout=20).status)\n"
                 "except urllib.error.HTTPError as e:\n"
                 "    print(e.code)")
    try:
        return int(str(out).strip())
    except (TypeError, ValueError):
        return None


PHASE1 = [c_identity, c_backup, c_render, c_schema, c_link_token, c_tunnel, c_verdict, c_ping, c_delivery,
          c_forged, c_revoke, c_door_says, c_paired_move, c_refusal_origin, c_routes]
