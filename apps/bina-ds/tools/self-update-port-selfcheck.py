#!/usr/bin/env python3
"""Is the self-update port pre-flight still able to tell "taken by someone else" from "mine"?

WHY THIS EXISTS. `busy_ports` in apps/bina-ds/self-update.sh refuses a swap while a host port the NEW
definition publishes is held by somebody else — written after 2026-09-30, when 127.0.0.1:3081 was held
by a host forwarder and bina-ds sat down for 41 minutes (compose stops the old container, the new one
cannot bind, and the rollback fails the same way).

On 2026-10-13 12:04 that guard refused a REAL swap and named the holder as `bina-ds-staging` — the very
container being replaced. A port held by the container about to be replaced is freed by the replace, so
refusing on it is always wrong; the swap then waited for a hand on the host. Two causes, both fixed in
the script: `current_container` read a `dc ps -a` list (a `Created` leftover has EMPTY port bindings, so
the replaced container's own port looked foreign), and the exclusion compared `ip:port` strings (so a
definition that only changed the bind address, 0.0.0.0:3081 vs 127.0.0.1:3081, missed it).

What this test pins — A/B are the fix, C/D are the guard it must keep:

  A  a port the replaced container publishes, asked as it publishes it          -> no refusal
  B  the same port on the other host-ip form                                    -> no refusal
  B2 the same question with a FOREIGN container as the replaced one             -> refusal (so B's
                                                                                  silence is the rule,
                                                                                  not a free port)
  C  a port held by a different container/process                               -> refusal, named
  D  the port of A, with a foreign container as the replaced one                -> refusal

It is a SHELL function, so it is extracted from the script verbatim (the body the office runs) and
called with a stub `dc` returning the ports we ask about.

TWO MODES, and it says which one it used:
  LIVE  a docker engine is reachable: the scenario is built on the real running bina-ds.
  STUB  no engine (a gate container runs with `--network none`): a fake `docker` on PATH answers
        inspect/ps/run, and the same five cases run deterministically. The gate therefore tests the
        RULE; an office run tests the rule against the real engine.

The proof that it catches the defect: `BINA_DS_SELF_UPDATE_SCRIPT=<git show HEAD:apps/bina-ds/self-update.sh>`
run here → B fails. Run against the fixed script → 5/5.

Run: python3 apps/bina-ds/tools/self-update-port-selfcheck.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
# BINA_DS_SELF_UPDATE_SCRIPT points the check at another copy of the script — the proof above.
SCRIPT = pathlib.Path(
    os.environ.get("BINA_DS_SELF_UPDATE_SCRIPT") or (REPO / "apps" / "bina-ds" / "self-update.sh"))
SERVICE = "bina-ds"
HOLDER = "bina-ds-port-holder-selfcheck"


def run(cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def docker_ok() -> bool:
    return run("docker info --format '{{.ServerVersion}}'", timeout=60).returncode == 0


def extract_busy_ports(into: pathlib.Path) -> None:
    """The function exactly as the script writes it, plus a stub `dc` and its call."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("busy_ports() {"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    into.write_text(
        "set -uo pipefail\n"
        f'SERVICE="{SERVICE}"\n'
        "dc() { printf '%s' \"${FAKE_DC_JSON}\"; }\n"
        + "\n".join(lines[start:end + 1]) + "\n"
        'busy_ports "${SOCK:-/var/run/docker.sock}" "${CID}" "${IMG}"\n',
        encoding="utf-8",
    )


def ask(harness: pathlib.Path, cid: str, image: str, wanted: list[str],
        path_prefix: str = "") -> str:
    """What busy_ports says for a definition publishing `wanted` — empty means 'no refusal'."""
    ports = [{"published": w.rsplit(":", 1)[1], "host_ip": w.rsplit(":", 1)[0]} for w in wanted]
    # This process's environment plus the harness's own keys, never PATH alone: busy_ports runs `python3`
    # from PATH, and a python that needs its own LD_LIBRARY_PATH (actions/setup-python's, on a self-hosted
    # runner) cannot start without it — every case then read "no refusal" (the Dell's gates, 2026-11-01).
    env = dict(os.environ, FAKE_DC_JSON=json.dumps({"services": {SERVICE: {"ports": ports}}}),
               CID=cid, IMG=image,
               PATH=(f"{path_prefix}:" if path_prefix else "") + os.environ.get("PATH", "/usr/bin:/bin"))
    r = subprocess.run(["bash", str(harness)], capture_output=True, text=True, env=env, timeout=300)
    out = (r.stdout + "\n" + r.stderr).strip()
    if "busy_ports.sh: line" in out:      # the harness itself fell over — not a verdict about ports
        print(f"SELFCHECK FAIL — the extracted guard did not run: {out[:300]}")
        sys.exit(1)
    return out


def case_table(own: str, other_form: str, foreign_port: str):
    """The five cases: (name, whose container is replaced, the ports asked about, expect silence)."""
    ip = other_form.rsplit(":", 1)[0]
    return [
        ("A own port, as published → no refusal", "CID", [own], True),
        (f"B own port on {ip} → no refusal", "CID", [other_form], True),
        (f"B2 own port on {ip}, foreign replaced container → refusal", "FOREIGN", [other_form], False),
        (f"C foreign holder on {foreign_port} → refusal", "CID", [foreign_port], False),
        ("D own port with a foreign container as the replaced one → refusal", "FOREIGN", [own], False),
    ]


def report(results, mode: str) -> int:
    bad = [n for n, ok, _ in results if not ok]
    for name, ok, detail in results:
        print(f"  {'ok  ' if ok else 'FAIL'} {name} — {detail[:150] or '(no refusal)'}")
    if bad:
        print(f"SELFCHECK FAIL — {len(bad)} of {len(results)} in {mode} mode: " + "; ".join(bad))
        return 1
    print(f"SELFCHECK PASS ({mode}) — silent on a port the container being replaced holds, "
          f"refuses it for anyone else")
    return 0


# ── STUB: no engine here (a gate container runs with --network none) ────────────────────────────────
STUB_OWN = "127.0.0.1:3081"
STUB_OTHER = "0.0.0.0:3081"
STUB_FOREIGN = "127.0.0.1:39999"
STUB_CID = "stubbina-ds01"
STUB_IMAGE = "stub-image"


def stub_docker(bindir: pathlib.Path) -> None:
    """A `docker` that answers only the questions busy_ports asks."""
    shim = bindir / "docker"
    shim.write_text(f'''#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
PORTS = {{"OWN": {{"3081/tcp": [{{"HostIp": "127.0.0.1", "HostPort": "3081"}}]}}, "FOREIGN": {{}}}}
NAMES = {{"OWN": "/{SERVICE}-staging", "FOREIGN": "/{HOLDER}"}}
who = "FOREIGN" if "{HOLDER}" in " ".join(a) else "OWN"
if a[:1] == ["inspect"]:
    fmt = a[2] if len(a) > 2 and a[1] == "-f" else " ".join(a[1:])
    if "PortBindings" in fmt:
        # two callers, two shapes: `{{json …}}` (the checker) and the shell template `{{range …}}`
        # that busy_ports renders into "ip:port " pairs.
        print(json.dumps(PORTS[who]) if "json" in fmt else
              " ".join("%s:%s" % (e["HostIp"], e["HostPort"])
                       for entries in PORTS[who].values() for e in entries))
    else:
        print(NAMES[who])
elif a[:1] == ["ps"]:
    print("{SERVICE}-staging {STUB_OWN}->3081/tcp")
    print("{HOLDER} ")
elif a[:1] == ["run"]:
    port = a[-1].rsplit(":", 1)[1]
    print("pid 4242 (/usr/bin/docker-proxy -proto tcp -host-ip 127.0.0.1 -host-port %s -container-ip 172.18.0.10)" % port)
''', encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)


def stub_mode(harness: pathlib.Path) -> int:
    bindir = harness.parent / "bin"
    bindir.mkdir(exist_ok=True)
    stub_docker(bindir)
    results = []
    for name, who, wanted, silent in case_table(STUB_OWN, STUB_OTHER, STUB_FOREIGN):
        cid = STUB_CID if who == "CID" else HOLDER
        said = ask(harness, cid, STUB_IMAGE, wanted, path_prefix=str(bindir))
        results.append((name, (said == "") == silent, said))
    return report(results, "stub")


# ── LIVE: a real engine, a real running bina-ds ─────────────────────────────────────────────────────
def bina_ds_container():
    out = run("docker ps --filter label=com.docker.compose.service=bina-ds "
              "--format '{{.ID}} {{.Image}}'").stdout.split()
    return (out[0], out[1]) if len(out) >= 2 else None


def published_port(cid: str):
    raw = run(f"docker inspect -f '{{{{json .HostConfig.PortBindings}}}}' {cid}").stdout.strip()
    try:
        binds = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    for entries in binds.values():
        for e in entries or []:
            hp = str(e.get("HostPort") or "")
            if hp.isdigit():
                return (e.get("HostIp") or "0.0.0.0", hp)
    return None


def free_port() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = str(s.getsockname()[1])
    s.close()
    return port


def live_mode(harness: pathlib.Path) -> int:
    found = bina_ds_container()
    if not found:
        print(f"SELFCHECK SKIP — no running {SERVICE} container to compare against")
        return 0
    cid, image = found
    own = published_port(cid)
    if not own:
        print(f"SELFCHECK SKIP — the running {SERVICE} publishes no host port for the guard to judge")
        return 0
    own_ip, own_port = own
    other_form = f"{'0.0.0.0' if own_ip == '127.0.0.1' else '127.0.0.1'}:{own_port}"
    foreign_port = f"127.0.0.1:{free_port()}"
    cid_name = run(f"docker inspect -f '{{{{.Name}}}}' {cid}").stdout.strip().lstrip("/")
    print(f"container under test: {cid_name} ({cid[:12]}) publishes {own_ip}:{own_port}")

    hip, hport = foreign_port.rsplit(":", 1)
    started = run(f"docker run -d --rm --name {HOLDER} --network host --entrypoint python3 {image} -c "
                  f"'import socket,time; s=socket.socket(); s.bind((\"{hip}\",{hport})); time.sleep(300)'")
    if started.returncode != 0:
        print(f"SELFCHECK SKIP — could not start a foreign holder: {started.stderr.strip()[:140]}")
        return 0
    results = []
    try:
        for name, who, wanted, silent in case_table(f"{own_ip}:{own_port}", other_form, foreign_port):
            said = ask(harness, cid if who == "CID" else HOLDER, image, wanted)
            results.append((name, (said == "") == silent, said))
    finally:
        run(f"docker rm -f {HOLDER}")
    return report(results, "live")


def main() -> int:
    if not SCRIPT.exists():
        print(f"SELFCHECK FAIL — no script to read at {SCRIPT}")
        return 1
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="bina-ds-port-selfcheck-"))
    try:
        harness = tmp / "busy_ports.sh"
        extract_busy_ports(harness)
        return live_mode(harness) if docker_ok() else stub_mode(harness)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
