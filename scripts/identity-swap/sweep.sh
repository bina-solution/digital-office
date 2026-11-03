#!/usr/bin/env bash
# sweep.sh — the identity swap's proof (README in window.sh): every host the edge gates (authentik@file),
# read from the RUNNING containers' labels — the values traefik itself sees, compose's interpolation done —
# then asked two ways, anonymous:
#   fa    forward-auth directly, the way traefik asks it (X-Forwarded-*), from the console's container
#   edge  the edge itself (127.0.0.1:${EDGE_PORT:-8080}, Host header): before the window authentik answers,
#         after it forward-auth. The MacBook's edge is the engine's 8080; a Linux office's is 80.
#   list  only write the host list (${OUT}/gated-hosts.txt), e.g. to sweep a public office from outside
# Usage, from the office (in the engine on a MacBook): bash scripts/identity-swap/sweep.sh fa|edge|list
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=ci-artifacts/identity-swap; mkdir -p "${OUT}"
D="$(sed -n 's/^DEPLOYMENT_NAME=//p' .env | tail -1)"; D="${D:-bina-deployment}"
# traefik's API is off (api.insecure false), so its two providers are read the way it reads them: the
# running containers' labels, and the file provider's YAML. A rule may carry the edge's port
# (`console.localhost:8080`); the host is asked without it, once.
case "${1:-}" in fa|edge|list) ;; *) echo "usage: sweep.sh fa|edge|list"; exit 2 ;; esac
# this office's containers only: a host may run a second stack, whose routers are not this edge's
P="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "traefik-${D}" 2>/dev/null)"
[ -n "${P}" ] || { echo "no traefik-${D} to read the project from"; exit 1; }
docker inspect --format '{{json .Config.Labels}}' $(docker ps -q --filter "label=com.docker.compose.project=${P}") 2>/dev/null | python3 -c '
import glob, json, re, sys, yaml
r = {}
for line in sys.stdin:
    for k, v in (json.loads(line) or {}).items():
        m = re.match(r"traefik\.http\.routers\.([^.]+)\.(rule|middlewares|entrypoints)$", k)
        if m: r.setdefault("d:" + m.group(1), {})[m.group(2)] = v
for f in glob.glob("platform-base/traefik/config/*.yaml"):
    try:
        doc = yaml.safe_load(re.sub(r"\{\{[^}]*\}\}", "", open(f, encoding="utf-8").read())) or {}
    except Exception:
        continue
    for name, x in ((doc.get("http") or {}).get("routers") or {}).items():
        mw = x.get("middlewares") or []
        r["f:" + name] = {"rule": x.get("rule", ""), "middlewares": ",".join(mw if isinstance(mw, list) else [mw])}
def gated(key, x):
    mws = [m.strip() for m in x.get("middlewares", "").split(",")]
    # a docker router names the file middleware `authentik@file`; a file router may name it bare
    return "authentik@file" in mws or (key.startswith("f:") and "authentik" in mws)
hosts = {h.split(":")[0] for k, x in r.items() if gated(k, x)
         for h in re.findall(r"Host\(`([^`]+)`\)", x.get("rule", ""))}
print("\n".join(sorted(hosts)))' > ${OUT}/gated-hosts.txt
n="$(grep -c . ${OUT}/gated-hosts.txt || true)"
echo "$(date -u +%T) gated hosts (live labels): ${n}"
[ "${n}" -gt 0 ] || { echo "no gated host found: nothing to sweep"; exit 1; }
case "${1}" in
  list) ;;
  fa)
    docker exec -i "console-${D}" python3 - "$(tr '\n' ' ' < ${OUT}/gated-hosts.txt)" <<'PY'
import sys, http.client, urllib.parse
hosts = sys.argv[1].split(); ok = 0
for h in hosts:
    c = http.client.HTTPConnection("forward-auth", 9078, timeout=10)
    c.request("GET", "/auth/traefik", headers={"X-Forwarded-Proto": "http", "X-Forwarded-Host": h + ":8080",
                                               "X-Forwarded-Uri": "/", "X-Forwarded-Method": "GET"})
    r = c.getresponse(); loc = r.getheader("Location") or ""; r.read(); c.close()
    u = urllib.parse.urlparse(loc); rd = urllib.parse.parse_qs(u.query).get("rd", [""])[0]
    good = r.status == 302 and u.path == "/login" and urllib.parse.urlparse(rd).hostname == h
    ok += good
    print(f"{'ok ' if good else 'BAD'} {r.status} {h:<48} -> {u.netloc}{u.path}")
c = http.client.HTTPConnection("forward-auth", 9078, timeout=10)
c.request("GET", "/auth/traefik", headers={"X-Forwarded-Proto": "http", "X-Forwarded-Host": "evil.example",
                                           "X-Forwarded-Uri": "/", "X-Forwarded-Method": "GET"})
r = c.getresponse(); foreign = (r.status, r.getheader("Location")); r.read(); c.close()
print(f"{'ok ' if foreign == (400, None) else 'BAD'} {foreign[0]} evil.example (a host this office does not serve)")
print(f"SWEEP(fa) {ok}/{len(hosts)} anonymous -> 302 to forward-auth's sign-in, return-to the same host")
sys.exit(0 if hosts and ok == len(hosts) and foreign == (400, None) else 1)
PY
    ;;
  edge)
    # the edge's own address and port: the MacBook's engine forward is 127.0.0.1:8080, a Linux office's 80
    EDGE_PORT="${EDGE_PORT:-8080}"; if [ "${EDGE_PORT}" = 80 ]; then hp=""; else hp=":${EDGE_PORT}"; fi
    ok=0
    while read -r h; do
      out="$(curl -s -o /dev/null -m 15 -w '%{http_code} %{redirect_url}' -H "Host: ${h}${hp}" "http://127.0.0.1:${EDGE_PORT}/")"
      code="${out%% *}"; loc="${out#* }"; where="$(printf '%s' "${loc}" | sed -E 's#^https?://##; s#\?.*##')"
      # forward-auth's sign-in is `<its host>/login` (signin.* before the window, auth.* after it);
      # authentik's would be /application/o/authorize/ or its flow
      case "${code} ${where}" in "302 "*"/login") ok=$((ok + 1)); r=ok ;; *) r="-- " ;; esac
      printf '%s %s %-48s -> %s\n' "${r}" "${code}" "${h}" "${where}"
    done < ${OUT}/gated-hosts.txt
    echo "SWEEP(edge) ${ok}/${n} gated hosts answer 302 to forward-auth's sign-in at the edge" ;;
esac
