#!/bin/bash
# DGO cloud — install one client server into the pool (DGO-1893). Served by the front at /node/install.sh and run as
# root by bootstrap.sh:   install.sh <front-url> <node-name> <boot-token>
#
#   1. hello       spend the boot token: the node's lasting secret and its LLM-router key come back (kept 0600 in
#                  /opt/dgo-cloud/node.json, never on a command line)
#   2. agent       /opt/dgo-cloud/agent.py as a systemd service: it dials OUT to the front (no inbound port is needed)
#   3. office      the public release (bina-solution/digital-office, branch main) at /opt/dgo; debian-install.sh pins
#                  Docker 28; .env declares the name, the router as every AI provider's address, and DGO_FOLLOW=main
#                  so the office takes each public release by itself
#   4. certificate ONE wildcard (*.<name>.<zone>) by DNS-01 through the front (lego httpreq), into traefik's file
#                  provider — so the office's ~20 hosts never draw on Let's Encrypt's 50-a-week for the company
#                  domain. With DGOCLOUD_ZONE=sslip.io there is no zone of ours: traefik's own HTTP-01 does it.
#   5. onboarding  `bbox onboarding`: the bring-up, the server's security app and the host baseline (keys-only SSH
#                  with Bina's ops key, no LLMNR/mDNS, only the office's doors open, Hostinger's monarx agent off) —
#                  confirmed at once: nobody logs in over SSH here, the agent is the way in
#   6. ready       the console answers on its name → the front puts the server in the pool
# Every step is reported to the front (the admin screen shows it); a step that fails says why and stops.
set -uo pipefail
FRONT="$1"; NAME="$2"; BOOT="$3"
D=/opt/dgo-cloud; OFFICE=/opt/dgo
mkdir -p "$D" && chmod 700 "$D"
exec > >(tee -a /var/log/dgo-cloud-install.log) 2>&1
echo "=== DGO cloud install ${NAME} $(date -u +%FT%TZ)"
export DEBIAN_FRONTEND=noninteractive

jget() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$D/node.json" "$1"; }
post() {  # post <path> <json>   (the node's secret in a header, read from the file — never in argv)
  python3 - "$FRONT" "$1" "$2" <<'PY'
import json, sys, urllib.request
front, path, body = sys.argv[1:4]
try:
    secret = json.load(open("/opt/dgo-cloud/node.json"))["secret"]
except Exception:
    secret = ""
req = urllib.request.Request(front + path, data=body.encode(), method="POST",
                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + secret})
try:
    print(urllib.request.urlopen(req, timeout=30).read().decode())
except Exception as e:
    print("post failed:", e, file=sys.stderr)
PY
}
step() { echo ">>> $1"; post /api/node/progress "$(python3 -c 'import json,sys; print(json.dumps({"step":sys.argv[1],"ok":sys.argv[2]=="1","detail":sys.argv[3][-400:]}))' "$1" "${2:-1}" "${3:-}")" >/dev/null; }
fail() { step "$1" 0 "$2"; echo "!!! $1: $2"; exit 1; }
set_env() {  # set_env KEY VALUE — replace the line, or add it
  local f="$OFFICE/.env"
  if grep -q "^$1=" "$f"; then
    python3 - "$f" "$1" "$2" <<'PY'
import sys
f, k, v = sys.argv[1:4]
lines = open(f).read().split("\n")
open(f, "w").write("\n".join(f"{k}={v}" if l.startswith(k + "=") else l for l in lines))
PY
  else
    printf '%s=%s\n' "$1" "$2" >> "$f"
  fi
}

# ── 1. hello ─────────────────────────────────────────────────────────────────────────────────────────────
if [ ! -s "$D/node.json" ]; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  python3 - "$FRONT" "$BOOT" "$IP" > "$D/node.json.tmp" <<'PY' || { echo "hello failed"; exit 1; }
import json, sys, urllib.request
front, boot, ip = sys.argv[1:4]
req = urllib.request.Request(front + "/api/node/hello", data=json.dumps({"boot": boot, "ip": ip}).encode(),
                             method="POST", headers={"Content-Type": "application/json"})
d = json.load(urllib.request.urlopen(req, timeout=30))
if not d.get("ok"):
    sys.exit("hello refused: " + str(d.get("error")))
print(json.dumps(d["data"]))
PY
  umask 077; mv "$D/node.json.tmp" "$D/node.json"; chmod 600 "$D/node.json"
fi
DOMAIN="$(jget domain)"; ZONE="$(jget zone)"; LLM="$(jget llm)"; ACME="$(jget acme)"
[ -n "$DOMAIN" ] || { echo "no domain from the front"; exit 1; }
step "שלום מהשרת — ${DOMAIN}"

# ── 2. the agent ─────────────────────────────────────────────────────────────────────────────────────────
python3 -c 'import sys,urllib.request; open(sys.argv[2],"wb").write(urllib.request.urlopen(sys.argv[1],timeout=60).read())' \
  "$FRONT/node/agent.py" "$D/agent.py" || fail agent "could not fetch agent.py"
cat > /etc/systemd/system/dgo-cloud-agent.service <<UNIT
[Unit]
Description=DGO cloud agent (dials out to ${FRONT})
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/usr/bin/python3 ${D}/agent.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable --now dgo-cloud-agent.service || fail agent "systemd refused the agent"

# ── 3. the office ────────────────────────────────────────────────────────────────────────────────────────
step "מתקין חבילות"
apt-get update -q && apt-get install -y -q git python3-yaml curl ca-certificates openssl \
  || fail packages "apt-get failed"
# an 8 GB server builds better with room to swap (a first build peaks above the RAM of a small machine)
if ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile \
    && echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
# Bina's operations key: the host baseline makes SSH keys-only and refuses to apply without a root key
OPS_KEY="$(jget ops_key)"
if [ -n "$OPS_KEY" ]; then
  mkdir -p /root/.ssh && chmod 700 /root/.ssh
  grep -qF "$OPS_KEY" /root/.ssh/authorized_keys 2>/dev/null || echo "$OPS_KEY" >> /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
fi
step "מוריד את הלשכה הדיגיטלית"
if [ ! -d "$OFFICE/.git" ]; then
  git clone --depth 50 -b "$(jget branch)" "$(jget release)" "$OFFICE" || fail release "git clone failed"
fi
cd "$OFFICE" || fail release "no checkout"
step "מתקין Docker"
bash debian-install.sh || fail docker "debian-install.sh failed"
[ -f .env ] || cp .env.ex .env
chmod 600 .env
set_env BUSINESS_NAME "\"DGO Cloud\""
set_env DEPLOYMENT_NAME dgo
set_env DEPLOYMENT_DOMAIN "$DOMAIN"
set_env TRAEFIK_ACME_EMAIL "$(jget acme_email)"
set_env AUTHENTIK_BOOTSTRAP_EMAIL "admin@${DOMAIN}"
set_env DGO_BRANCH main
set_env DGO_FOLLOW main
set_env HOST_SSH_PASSWORD_FROM ""
# every AI provider's address is the router; one key, the node's, spends its owner's wallet (DGO-1893)
KEY="$(jget key)"
set_env DEEPSEEK_API_KEY "$KEY"
set_env DEEPSEEK_BASE_URL "$LLM"
set_env OPENAI_API_KEY "$KEY"
set_env OPENAI_BASE_URL "${LLM}/v1"
set_env ANTHROPIC_API_KEY "$KEY"
set_env ANTHROPIC_BASE_URL "$LLM"

# ── 4. one certificate ───────────────────────────────────────────────────────────────────────────────────
if [ "$ZONE" != "sslip.io" ]; then
  step "מנפיק תעודת אבטחה ל-*.${DOMAIN}"
  systemctl is-active --quiet docker || systemctl start docker
  mkdir -p "$D/lego"
  # lego's httpreq posts {fqdn, value} to <endpoint>/present|cleanup with basic auth: the node's name and secret
  HTTPREQ_PASSWORD="$(jget secret)" docker run --rm -v "$D/lego:/lego" \
    -e HTTPREQ_ENDPOINT="$ACME" -e HTTPREQ_USERNAME="$(jget name)" -e HTTPREQ_PASSWORD \
    "$(jget lego_image)" --accept-tos --email "$(jget acme_email)" --dns httpreq \
    -d "$DOMAIN" -d "*.${DOMAIN}" --path /lego run \
    || fail certificate "lego could not get *.${DOMAIN} (is ${ZONE} delegated to the front?)"
  python3 "$D/agent.py" --install-cert || fail certificate "could not place the certificate"
fi

# ── 5. onboarding ────────────────────────────────────────────────────────────────────────────────────────
step "מקים את הלשכה (10–15 דקות בפעם הראשונה)"
BBOX_WAIT_TIMEOUT=1200 bash ./bbox onboarding || step onboarding 0 "bbox onboarding reported issues — continuing to the health check"
# confirmed at once: the revert timer exists to protect a person who could lock themself out of SSH; here nobody
# logs in — the agent dials out, and Bina's key is in place
bash scripts/ops/host-baseline.sh confirm 2>/dev/null || true

# ── 6. ready ─────────────────────────────────────────────────────────────────────────────────────────────
step "בודק שהקונסול עונה"
for i in $(seq 1 60); do
  code="$(curl -sk -o /dev/null -w '%{http_code}' -m 10 --resolve "console.${DOMAIN}:443:127.0.0.1" "https://console.${DOMAIN}/")"
  case "$code" in 200|302|303) break ;; esac
  sleep 10
done
case "$code" in 200|302|303) ;; *) fail health "console.${DOMAIN} answered ${code} after 10 minutes" ;; esac
step ready
echo "=== ready $(date -u +%FT%TZ)"
