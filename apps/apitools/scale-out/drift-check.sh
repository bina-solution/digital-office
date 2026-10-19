#!/bin/bash
# Surface CONFIG DRIFT between the two apitools instances.
#
# WHY: the two instances are interchangeable only while they agree. Drift here does not
# crash anything -- it silently changes ANSWERS, so the same document yields different
# extraction depending on which instance happened to serve it, and nothing alerts.
# Two real incidents motivated this file:
#   * a duplicate apitools-gate container ran a stale OCR_ENGINE=local at ~231% CPU,
#     leaving 878 tesseract rows in a table that should be all google/pdf_textlayer;
#   * dev_signer.p12 existed on the host and NOT on the portable, with SIGN_CERT_P12
#     empty on both -- so the first signed /docGen served by the portable would have
#     minted a SECOND, different self-signed certificate and documents would carry one
#     of two signers depending on routing.
#
# Exit 0 = no drift. Exit 1 = drift found. Safe to run any time; read-only.
#
#   ./drift-check.sh          human-readable report
#   ./drift-check.sh --quiet  only print drift
set -uo pipefail

export DOCKER_HOST=${DOCKER_HOST:-unix:///run/bbox-docker.sock}
KEY=${PORTABLE_KEY:-/home/shlomo/.ssh/portable_key}
HOST=${PORTABLE_HOST:-shlomy@192.168.16.103}
SSHO="-i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
LOCAL_C=${LOCAL_CONTAINER:-apitools}
REMOTE_C=${REMOTE_CONTAINER:-apitools-remote}
QUIET=${1:-}
DRIFT=0
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

say() { [ "$QUIET" = "--quiet" ] || echo "$@"; }
bad() { echo "DRIFT: $*"; DRIFT=1; }

# Variables that MUST be identical: they change extraction RESULTS or shared identity.
# A difference here means the two instances disagree about what a document says.
MUST_MATCH='^(OCR_ENGINE|GOOGLE_VISION_API_KEY|SUPABASE_DB_NAME|SUPABASE_DB_USER|SUPABASE_DB_PASSWORD|DOC_DB_NAME|DOC_DB_USER|DOC_DB_PASSWORD|APITOOLS_VISION_MAX_PX|APITOOLS_MAX_MP_PER_PAGE|APITOOLS_MIN_EFFECTIVE_DPI|APITOOLS_BORN_DIGITAL|PDF_OCR_DPI|OCR_CACHE_BACKEND|OCR_CACHE_STRICT|OCR_CACHE_READINESS|SIGN_CERT_P12|SIGN_CERT_PEM|SIGN_CERT_CERTIFIED)='

# Variables that MUST differ (correct per-instance sizing / addressing). Listed so they
# are EXCLUDED from the "unclassified difference" sweep rather than silently ignored.
MAY_DIFFER='^(GUNICORN_WORKERS|GUNICORN_HEALTH_PORT|APITOOLS_MAX_CONCURRENT_OCR|APITOOLS_MAX_CONCURRENT_PDF|APITOOLS_MAX_CONCURRENT_JSON_QUERY|SUPABASE_DB_HOST|DOC_DB_HOST|DOC_DB_PORT|SUPABASE_DB_PORT|SENTRY_ENVIRONMENT|SENTRY_RELEASE|HOSTNAME|HOME|PATH|LANG|GPG_KEY|PYTHON_[A-Z_]*|PIP_[A-Z_]*|N8N_[A-Z_]*)='

env_of_local()  { docker inspect "$LOCAL_C"  --format '{{range .Config.Env}}{{println .}}{{end}}'; }
env_of_remote() { ssh $SSHO "$HOST" "docker inspect $REMOTE_C --format '{{range .Config.Env}}{{println .}}{{end}}'"; }

env_of_local  | grep -v '^$' | sort > "$TMP/local.env"  2>/dev/null
env_of_remote | grep -v '^$' | sort > "$TMP/remote.env" 2>/dev/null
if [ ! -s "$TMP/local.env" ] || [ ! -s "$TMP/remote.env" ]; then
  echo "DRIFT: could not read env from both instances (local=$(wc -l < "$TMP/local.env") remote=$(wc -l < "$TMP/remote.env"))"
  exit 1
fi

say "== 1. variables that MUST be identical =="
for k in $(grep -oE "$MUST_MATCH" "$TMP/local.env" "$TMP/remote.env" 2>/dev/null | sed 's/.*://; s/=$//' | sort -u); do
  L=$(grep -E "^$k=" "$TMP/local.env"  | head -1 | cut -d= -f2-)
  R=$(grep -E "^$k=" "$TMP/remote.env" | head -1 | cut -d= -f2-)
  if [ "$L" = "$R" ]; then
    say "  ok    $k"
  else
    # Never print secrets; fingerprint them instead.
    case "$k" in *PASSWORD*|*KEY*) L="sha:$(printf %s "$L" | sha256sum | cut -c1-12)"
                                   R="sha:$(printf %s "$R" | sha256sum | cut -c1-12)";; esac
    bad "$k  local='$L'  remote='$R'"
  fi
done

say "== 2. unclassified differences (neither must-match nor known-per-instance) =="
comm -3 <(grep -vE "$MAY_DIFFER" "$TMP/local.env"  | grep -vE "$MUST_MATCH" | sort) \
        <(grep -vE "$MAY_DIFFER" "$TMP/remote.env" | grep -vE "$MUST_MATCH" | sort) \
  | sed 's/^\t/  remote-only: /; s/^\([^ ]\)/  local-only:  \1/' \
  | sed -E 's/(PASSWORD|KEY|SECRET|TOKEN)=.*/\1=<redacted>/' > "$TMP/unclassified"
if [ -s "$TMP/unclassified" ]; then
  cat "$TMP/unclassified"
  bad "$(grep -c . "$TMP/unclassified") unclassified env difference(s) — classify them above or fix them"
else
  say "  ok    none"
fi

say "== 3. signing certificate (per-instance state that changes DOCUMENT identity) =="
LP=$(docker exec "$LOCAL_C" sh -c 'sha256sum /app/.storage/dev_signer.p12 2>/dev/null | cut -c1-16' </dev/null)
RP=$(ssh $SSHO "$HOST" "docker exec $REMOTE_C sh -c 'sha256sum /app/.storage/dev_signer.p12 2>/dev/null | cut -c1-16'" </dev/null)
SIGN_ENV=$(grep -E '^SIGN_CERT_P12=.+' "$TMP/local.env" | wc -l)
if [ "$SIGN_ENV" -gt 0 ]; then
  say "  ok    SIGN_CERT_P12 is set — the dev self-signed path is not in use"
elif [ -n "$LP" ] && [ "$LP" = "$RP" ]; then
  say "  ok    dev_signer.p12 identical on both ($LP)"
else
  bad "dev_signer.p12 local='${LP:-ABSENT}' remote='${RP:-ABSENT}' — a signed /docGen served by"
  echo "       the instance without it MINTS A SECOND, DIFFERENT signer. Fix:"
  echo "         ./up.sh signer      (copies the local cert to the portable)"
fi

say "== 4. deployed code fingerprint (catches a stale image, e.g. the OCR_ENGINE=local gate) =="
FP='find /app/src -name "*.py" -type f | sort | xargs sha256sum | sha256sum | cut -c1-16'
LF=$(docker exec "$LOCAL_C" sh -c "$FP" </dev/null)
RF=$(ssh $SSHO "$HOST" "docker exec $REMOTE_C sh -c '$FP'" </dev/null)
if [ "$LF" = "$RF" ]; then say "  ok    src identical on both ($LF)"
else bad "src differs — local=$LF remote=$RF. Rebuild the remote: ./up.sh remote"; fi

say "== 5. shared-cache readiness on both instances =="
# python, NOT wget/curl: the apitools image is python:slim and ships NEITHER. Using wget
# here made this check report "old image without the endpoint" against two instances that
# both had it — a false DRIFT, which is worse than no check at all.
#
# The probe is written to a file and `docker cp`'d rather than passed as a -c one-liner:
# the remote leg goes through ssh -> sh -> docker exec -> sh -> python, which is five
# levels of quoting, and getting it wrong produces the SAME empty output as a genuinely
# missing endpoint. A file has no quoting at all.
cat > "$TMP/readyz.py" <<'PYEOF'
import sys, urllib.request
try:
    r = urllib.request.urlopen("http://127.0.0.1:8080/readyz", timeout=15)
    print(r.read().decode())
except urllib.error.HTTPError as e:
    print(e.read().decode())
except Exception as e:
    print("PROBE_FAILED %s: %s" % (type(e).__name__, e)); sys.exit(1)
PYEOF

docker cp "$TMP/readyz.py" "$LOCAL_C":/tmp/readyz.py >/dev/null 2>&1
out_local=$(docker exec "$LOCAL_C" python /tmp/readyz.py </dev/null 2>/dev/null)
scp $SSHO -q "$TMP/readyz.py" "$HOST":/tmp/readyz.py >/dev/null 2>&1
ssh $SSHO "$HOST" 'docker cp /tmp/readyz.py '"$REMOTE_C"':/tmp/readyz.py' >/dev/null 2>&1
out_remote=$(ssh $SSHO "$HOST" 'docker exec '"$REMOTE_C"' python /tmp/readyz.py' </dev/null 2>/dev/null)

for pair in "local|$out_local" "remote|$out_remote"; do
  n=${pair%%|*}; out=${pair#*|}
  case "$out" in
    *'"ready"'*)     say "  ok    $n ready — $out" ;;
    '')              bad "$n /readyz gave no output (old image without the endpoint, or instance down)" ;;
    *PROBE_FAILED*)  bad "$n /readyz probe failed — $out" ;;
    *)               bad "$n NOT ready — $out" ;;
  esac
done

echo
if [ "$DRIFT" = 0 ]; then echo "RESULT: no drift"; else echo "RESULT: DRIFT FOUND (see above)"; fi
exit $DRIFT
