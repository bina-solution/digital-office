#!/usr/bin/env bash
# scripts/ops/edge-bypass-probe.sh — does any known way around the sign-in reach an app? (DGO-1656, sec2-005)
#
#   scripts/ops/edge-bypass-probe.sh <office-ipv4> <host>[:<public-prefix>] …
#   e.g. (from vps1, at Exampleu)
#     scripts/ops/edge-bypass-probe.sh 93.184.216.10 console.exampleu.digital-office.co.il \
#       computers.exampleu.digital-office.co.il:/share/ drive.exampleu.digital-office.co.il:/file/d/ \
#       n8n.exampleu.digital-office.co.il:/webhook/ meet.exampleu.digital-office.co.il
#
# RUN IT FROM ANOTHER MACHINE. On the office itself a request to its own address arrives from the docker bridge,
# a private source, and every «private only» rule would answer as if the probe were the office.
#
# GET only, over HTTP/1.1 (the shapes below do not exist in h2). The probe writes nothing itself; but if a bypass
# DID work, an app that makes users from proxy headers could make the user «probe» — look for it after a LOOK.
#
# Each host is asked for / first: its baseline. A gated host answers with a redirect to the sign-in; a public one
# with its own page. Then the shapes of the 2025–2026 advisories against forward-auth edges, traefik's above all
# (CVE-2026-88009 rootless and opaque request-targets, CVE-2026-39858 Forwarded, CVE-2026-35051
# X-Forwarded-Prefix, CVE-2026-29054 Connection stripping, CVE-2025-66490 path normalisation; spoofed
# X-Forwarded-Uri into authentik's outpost path; identity headers sent by the client), and dot segments in every
# encoding that climb from a public prefix all the way to /. A line reads
#   held           the same answer as the baseline: the same sign-in redirect (with the same rd= return target, for
#                  a request for / itself), a refusal (4xx), on a public host the same page (title and size), or —
#                  for a climb — the very answer the prefix's app gives any path (its own 404, or n8n's own 500);
#   LOOK           a 2xx that is not the baseline's own page: a gated host answered, or a public host answered
#                  something else, or an answer under a public prefix changed when the client sent identity headers;
#   look-redirect  a redirect that is not the baseline's (a spoofed header reached rd=, or an app's own login);
#   look-5xx       a 5xx: traefik may have routed past the challenge to a backend that failed;
#   no-answer      nothing came back: the run proves nothing for that line.
# Exit 0 every line held · 1 any LOOK/look-* · 3 no LOOK but some no-answer (or a host with no baseline) · 2 usage.
#
#   scripts/ops/edge-bypass-probe.sh --targets <office-domain> < docker-inspect.json
#     prints the probe's arguments for that office, one per line: every HTTPS host it routes, and each public
#     prefix (a router without the sign-in that names a Path or PathPrefix) as <host>:<prefix>. Run on the office
#     itself (`bbox security probe --targets`), then hand the list to another machine. It reads docker labels
#     only: routers from traefik's own files (config/*.yaml) and HostRegexp/PathRegexp rules are not listed — add
#     those by hand; «gated» means a middleware whose name says authentik (the sign-in's name on every office).
set -u
usage() { sed -n '2,8p' "$0" >&2; exit 2; }
if [ "${1:-}" = --targets ]; then
  [ -n "${2:-}" ] || usage
  exec python3 -c '
import json, re, sys
domain = sys.argv[1]
out = set()
for c in json.load(sys.stdin):
    labels = c.get("Config", {}).get("Labels") or {}
    routers = {}
    for k, v in labels.items():
        m = re.match(r"traefik\.http\.routers\.([^.]+)\.(rule|middlewares|entrypoints)$", k)
        if m:
            routers.setdefault(m.group(1), {})[m.group(2)] = v
    for r in routers.values():
        if "websecure" not in r.get("entrypoints", "websecure"):
            continue
        rule = r.get("rule", "")
        hosts = [h for h in re.findall(r"Host\(`([^`]+)`\)", rule) if h.endswith("." + domain)]
        paths = re.findall(r"Path(?:Prefix)?\(`([^`]+)`\)", rule)
        gated = "authentik" in r.get("middlewares", "")
        for h in hosts:
            out.add(h)
            if paths and not gated:
                out.update(h + ":" + p for p in paths if p.startswith("/"))
print("\n".join(sorted(out)))
' "$2"
fi
[ $# -ge 2 ] || usage
IP="$1"; shift
command -v curl >/dev/null || { echo "edge-bypass-probe: needs curl" >&2; exit 2; }
BODY="$(mktemp)"; trap 'rm -f "${BODY}"' EXIT
FOUND=0; MISSED=0

ask() {   # ask <host> <curl args…> — prints «code size redirect»; ${BODY} holds this answer's body, empty if none
  local host="$1" out; shift
  : > "${BODY}"
  out="$(curl -sk --http1.1 -m 10 -o "${BODY}" -w '%{http_code} %{size_download} %{redirect_url}' \
         --resolve "${host}:443:${IP}" "$@" 2>/dev/null)"
  echo "${out:-000 0 }"
}
field() { awk -v n="$2" '{ print $n }' <<<"$1"; }
title() {   # the page's <title>, even across lines; empty when it has none
  tr -d '\r\n' < "${BODY}" | grep -o -i '<title[^>]*>[^<]*' | head -1 | sed -E 's/^<[Tt][Ii][Tt][Ll][Ee][^>]*>//'
}
near() { local a="$1" b="$2" d; d=$(( a > b ? a - b : b - a )); [ "${d}" -le $(( b / 50 + 64 )) ]; }   # within 2 % + 64 B
# A redirect's identity: where it sends the browser and the return target it carries (rd=). forward-auth adds a
# fresh state (st=) to every challenge, so the whole Location never repeats; what must repeat is rd=, the place
# the edge says the visitor asked for — a spoofed X-Forwarded-Host/Uri that reached it would show here.
loc_key() { local l="$1"; printf '%s|%s' "${l%%\?*}" "$(sed -n 's/.*[?&]rd=\([^&]*\).*/\1/p' <<<"${l}")"; }

say() {   # say <verdict> <code> <size> <label> <note>
  case "$1" in LOOK|look-*) FOUND=1 ;; no-answer) MISSED=1 ;; esac
  printf '  %-13s %s %7s  %-58.58s %.70s\n' "$1" "$2" "$3" "$4" "$5"
}

judge() {   # judge <label> <answer> [exact] — against this host's baseline; exact: a request for / itself
  local label="$1" ans="$2" exact="${3:-}" code size loc t verdict=held
  code="$(field "${ans}" 1)"; size="$(field "${ans}" 2)"; loc="$(field "${ans}" 3)"; t="$(title)"
  case "${code}" in
    000) verdict=no-answer ;;
    2??) if [ "${B_PUBLIC}" = 1 ] && [ -n "${B_TITLE}" ] && [ "${t}" = "${B_TITLE}" ] && near "${size}" "${B_SIZE}"; then
           verdict=held
         else
           verdict=LOOK
         fi ;;
    30?) if [ -n "${exact}" ]; then [ -n "${B_LOC}" ] && [ "$(loc_key "${loc}")" = "$(loc_key "${B_LOC}")" ] || verdict=look-redirect
         else [ -n "${B_LOC}" ] && [ "${loc%%\?*}" = "${B_LOC%%\?*}" ] || verdict=look-redirect; fi ;;
    5??) verdict=look-5xx ;;
  esac
  say "${verdict}" "${code}" "${size}" "${label}" "${t:-${loc}}"
}

judge_climb() {   # judge_climb <label> <answer> — held when it is the prefix's own answer (${plain}), else as judge
  local code size
  code="$(field "$2" 1)"; size="$(field "$2" 2)"
  case "${code}" in 000|2??|30?) ;; *)   # a 2xx or a redirect is never «the prefix's own answer»: judge decides it
    if [ "${code}" = "$(field "${plain}" 1)" ] && near "${size}" "$(field "${plain}" 2)"; then
      say held "${code}" "${size}" "$1" "the prefix's own answer to any path"; return
    fi ;;
  esac
  judge "$1" "$2"
}

same() {   # same <label> <answer-plain> <answer-with-headers> — an answer under a public prefix must not change
  local a="$2" b="$3" verdict=held
  if [ "$(field "${a}" 1)" = 000 ] || [ "$(field "${b}" 1)" = 000 ]; then verdict=no-answer
  elif [ "$(field "${a}" 1)" != "$(field "${b}" 1)" ] || ! near "$(field "${b}" 2)" "$(field "${a}" 2)"; then verdict=LOOK; fi
  say "${verdict}" "$(field "${b}" 1)" "$(field "${b}" 2)" "$1" "plain: $(field "${a}" 1) $(field "${a}" 2) B"
}

IDENTITY=(-H "X-authentik-username: probe" -H "X-authentik-groups: authentik Admins" -H "X-authentik-uid: probe"
          -H "X_authentik_username: probe" -H "Remote-User: probe" -H "X-Forwarded-User: probe")

for spec in "$@"; do
  host="${spec%%:*}"; prefix=""
  [ "${spec}" != "${host}" ] && prefix="${spec#*:}"
  case "${prefix}" in ""|/*) ;; *) echo "edge-bypass-probe: '${spec}': a public prefix starts with /" >&2; exit 2 ;; esac
  base="https://${host}"; short="${host%%.*}"
  b="$(ask "${host}" "${base}/")"
  B_CODE="$(field "${b}" 1)"; B_SIZE="$(field "${b}" 2)"; B_LOC="$(field "${b}" 3)"; B_TITLE="$(title)"
  B_PUBLIC=0; case "${B_CODE}" in 2??) B_PUBLIC=1 ;; esac
  if [ "${B_CODE}" = 000 ]; then
    MISSED=1; printf '== %s  (/ → no answer: nothing probed; check the address and that this machine may reach it)\n' "${host}"
    continue
  fi
  case "${B_CODE}" in
    2??) printf '== %s  (/ → %s, a public page «%s», %s B)\n' "${host}" "${B_CODE}" "${B_TITLE:-no title}" "${B_SIZE}" ;;
    30?) printf '== %s  (/ → %s to %s)\n' "${host}" "${B_CODE}" "${B_LOC%%\?*}" ;;
    *)   printf '== %s  (/ → %s: no page here, so any 2xx below is a LOOK)\n' "${host}" "${B_CODE}" ;;
  esac
  # request-targets that are not origin-form (CVE-2026-88009 and kin)
  for t in "http:http://${short}.localhost/" "http:http://console.localhost/" "http:http://n8n.localhost/rest/settings" \
           "http:http://supabase.localhost/storage/v1/version" "http:admin/secret" "http:/etc/passwd" "x" "*" \
           "http://${short}.localhost/" "http://console.localhost/" "https://${host}/"; do
    judge "request-target ${t}" "$(ask "${host}" --request-target "${t}" "${base}/")"
  done
  # forwarded-header families on / itself: the answer must be the baseline's own, rd= included
  judge "Forwarded for=127.0.0.1;host=${short}.localhost" "$(ask "${host}" -H "Forwarded: for=127.0.0.1;host=${short}.localhost;proto=https" "${base}/")" exact
  judge "X-Forwarded-For / X-Real-IP 127.0.0.1" "$(ask "${host}" -H "X-Forwarded-For: 127.0.0.1" -H "X-Real-IP: 127.0.0.1" "${base}/")" exact
  judge "X-Forwarded-Prefix/Uri/Host spoofed" "$(ask "${host}" -H "X-Forwarded-Prefix: /signin" -H "X-Forwarded-Uri: /signin/x" -H "X-Forwarded-Host: signin.localhost" "${base}/")" exact
  judge "X-Forwarded-Uri into authentik's outpost path" "$(ask "${host}" -H "X-Forwarded-Uri: /outpost.goauthentik.io/ping" "${base}/")" exact
  judge "Connection strips X-Forwarded-*" "$(ask "${host}" -H "Connection: close, X-Forwarded-For, X-Forwarded-Uri, X-Forwarded-Host, X-Forwarded-Proto" "${base}/")" exact
  judge "identity headers from the client" "$(ask "${host}" "${IDENTITY[@]}" "${base}/")" exact
  judge "X-Original-URL / X-Rewrite-URL" "$(ask "${host}" -H "X-Original-URL: /" -H "X-Rewrite-URL: /" "${base}/x-probe")"
  [ -n "${prefix}" ] || continue
  p="${prefix%/}/"; depth="$(tr '/' '\n' <<<"${p}" | grep -c .)"
  # the prefix's own answer to a path that means nothing: an app's 404 (or its own 500, as n8n's
  # /webhook-waiting/<not a number>/) — a climb that answers exactly that never left the prefix's app
  plain="$(ask "${host}" "${base}${p}dgo-probe-x")"
  # identity headers where no forward-auth overwrites them: under the public prefix, the answer must not change
  same "identity headers under ${p}" "${plain}" "$(ask "${host}" "${IDENTITY[@]}" "${base}${p}dgo-probe-x")"
  # dot segments climbing from the public prefix all the way to / (one shape per level, then one more), each
  # sent twice: plain, and with the identity headers — an app behind the climb that trusts them answers 2xx
  for d in "../" "%2e%2e/" "%2E%2E/" ".%2e/" "%2e%2e%2f" "..%2f" "..%2F" "%252e%252e/" "..;/" "..%5c" "%2e%2e%5c" "/../"; do
    climb=""; for i in $(seq 1 $(( depth + 1 ))); do climb="${climb}${d}"; done
    judge_climb "${p}${climb}" "$(ask "${host}" --path-as-is "${base}${p}${climb}")"
    judge_climb "${p}${climb} + identity" "$(ask "${host}" --path-as-is "${IDENTITY[@]}" "${base}${p}${climb}")"
  done
done
[ "${FOUND}" = 1 ] && exit 1
[ "${MISSED}" = 1 ] && exit 3
exit 0
