#!/bin/sh
# connections injector — the runtime piece that makes a consumer run off the credential plane.
#
# At container boot: prove who we are to the broker, receive ONLY the connections this app declares
# in its own app.json, export them, then exec the real command. The service reads its secrets from
# connections, never from raw .env — which is what lets its compose entry blank them entirely.
#
#   entrypoint: sh /inject.sh <real command...>
#   env: CONN_URL (default http://connections:8990), CONN_SERVICE (this app's compose service name)
#
# IDENTITY — the second factor. We read our OWN container id out of /proc/self/mountinfo (docker
# bind-mounts /var/lib/docker/containers/<64-hex>/hostname into every container, so it is always
# legible from inside) and present it as X-Conn-Container. The broker checks that this id belongs to
# a running container whose addresses include the address our packet came from. An attacker then
# needs BOTH the network position and a 256-bit value it has no way to read out of another
# container. See platform-base/connections/identity.py for what this does and does not prove.
#
# The secret file is written to /tmp, sourced, and UNLINKED before exec — a container that is later
# `docker exec`-ed into does not find a plaintext dotenv sitting on its disk.
set -e
: "${CONN_URL:=http://connections:8990}"
: "${CONN_SERVICE:?set CONN_SERVICE to this service's compose service name}"
: "${CONN_ENV_FILE:=/tmp/conn.env}"

python3 - "$CONN_URL" "$CONN_SERVICE" "$CONN_ENV_FILE" <<'PY'
import json, os, sys, urllib.error, urllib.request

url, service, out_path = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]


def self_container_id():
    """Our own container id — the proof-of-container factor. mountinfo first (works on cgroup v1
    and v2), cgroup as the fallback."""
    for path, marker in (("/proc/self/mountinfo", "/containers/"), ("/proc/self/cgroup", "/docker/")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    i = line.find(marker)
                    while i != -1:
                        cand = line[i + len(marker):i + len(marker) + 64]
                        if len(cand) == 64 and all(c in "0123456789abcdef" for c in cand):
                            return cand
                        i = line.find(marker, i + 1)
        except OSError:
            continue
    return ""


headers = {"Content-Type": "application/json"}
cid = self_container_id()
if cid:
    headers["X-Conn-Container"] = cid

body = json.dumps({"service": service}).encode()
req = urllib.request.Request(url + "/api/broker/lease", data=body, headers=headers, method="POST")
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode())
    env, granted, refused = payload.get("env") or {}, payload.get("granted") or [], payload.get("refused") or []
    ident = (payload.get("identity") or {}).get("method", "?")
    note = f"lease {payload.get('lease')} · identity={ident} · granted {len(granted)}"
except urllib.error.HTTPError as e:
    detail = e.read().decode(errors="replace")[:300]
    if e.code == 404:
        # An older connections image without the broker. Fall back to the legacy export route so a
        # partially-rolled-out estate still boots; the broker logs the call either way.
        with urllib.request.urlopen(f"{url}/api/export/{service}?format=env", timeout=20) as r:
            open(out_path, "w").write(r.read().decode())
        print(f"[connections-inject] {service}: legacy /api/export (broker not present)")
        raise SystemExit(0)
    # A REFUSAL is fatal on purpose: booting anyway means booting without the secrets, which shows
    # up later as an unexplained auth error deep in the app instead of here, with the reason.
    raise SystemExit(f"[connections-inject] {service}: broker refused ({e.code}): {detail}")

if refused:
    print(f"[connections-inject] {service}: REFUSED {[r.get('id') for r in refused]}")

# POSIX single-quoting, because this file is `.`-sourced by /bin/sh. A password containing a space,
# `$`, backtick or quote written bare would be word-split or EXPANDED by the shell — the app then
# starts with a silently truncated credential and fails somewhere far away with an auth error.
with open(out_path, "w", encoding="utf-8") as f:
    for k, v in sorted(env.items()):
        f.write("%s='%s'\n" % (k, str(v).replace("'", "'\\''")))
os.chmod(out_path, 0o600)
print(f"[connections-inject] {service}: {note} · {len(env)} env key(s) from {url}")
PY

set -a
. "${CONN_ENV_FILE}"
set +a
rm -f "${CONN_ENV_FILE}"
exec "$@"
