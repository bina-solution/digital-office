#!/usr/bin/env bash
# dgo55-score.sh — ONE command: the beauty score of bina-ds and mail, at desktop AND at 390.
#
# The owner's ask (DGO-55) is comparative: "i want beauty score on both of thees windows (bina-ds
# and mail) all compared". That is two apps × two profiles, and doing it by hand is four `bbox
# ui-map` runs, four score runs and one person reading four files. This is the one command.
#
# WHAT IT DOES, per profile:
#   UI_MAP_APPS="bina mailview" UI_MAP_SHARDS=1 ./bbox ui-map --profile <p>   capture (2 apps only)
#   python3 scripts/ui-coverage/score.py --data <profile data> --profile <p>  the seven dimensions
# and then prints ONE table: every scored view of both apps at both sizes, worst first.
#
# WHY SHARDS=1 AND ONE PROFILE AT A TIME: measured twice on this engine — four Chromium shards of
# the full map took the host to load 223 and left orphan containers behind. Two apps are cheap; a
# quiet window is still required, and `bbox ui-map` takes the heavy-job slot itself.
#
# Refuses to start on a full disk (<6 GiB free) or a busy engine (load1 > 20) instead of half-running.
#
#   bash scripts/ui-coverage/dgo55-score.sh                 # desktop + mobile, bina + mailview
#   UI55_APPS="bina" UI55_PROFILES=mobile bash scripts/ui-coverage/dgo55-score.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
cd "${ROOT}"

APPS="${UI55_APPS:-bina mailview}"
PROFILES="${UI55_PROFILES:-desktop mobile}"
SKIP_SEED="${UI_MAP_SKIP_SEED:-0}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# ── the two refusals, before anything is started ────────────────────────────────────────────────
free_mb=$(df -Pm / | awk 'NR==2{print $4}')
if [ "${free_mb:-0}" -lt 6144 ]; then
  echo "REFUSING: ${free_mb} MiB free on / — a capture needs headroom (>= 6144 MiB)." >&2
  echo "  free some space (docker image prune / old artifacts) and run again." >&2
  exit 3
fi
load1=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)
if awk "BEGIN{exit !(${load1} > 20)}"; then
  echo "REFUSING: load1=${load1} — the engine is busy. Wait for a quiet window; a capture that" >&2
  echo "  races another heavy job is how the last one left four orphan browsers behind." >&2
  exit 4
fi
echo "free ${free_mb} MiB · load1 ${load1} · apps: ${APPS} · profiles: ${PROFILES}"

# ── capture + score, one profile at a time ──────────────────────────────────────────────────────
for p in ${PROFILES}; do
  say "capture — ${p} (${APPS})"
  UI_MAP_APPS="${APPS}" UI_MAP_SHARDS=1 UI_MAP_SKIP_SEED="${SKIP_SEED}" \
    ./bbox ui-map --profile "${p}" || { echo "capture failed for ${p}" >&2; continue; }

  if [ "${p}" = desktop ]; then data="data/ui-map"; else data="data/ui-map/${p}"; fi
  say "score — ${p}"
  # scored into its OWN directory: ci-artifacts/ui-score.json holds the whole-platform desktop
  # score, and a two-app comparison must never overwrite the office's baseline with it.
  python3 scripts/ui-coverage/score.py --data "${data}" --profile "${p}" \
    --out "ci-artifacts/dgo55/${p}" || { echo "score failed for ${p}" >&2; continue; }
done

# ── ONE table: both apps, both sizes, worst first ───────────────────────────────────────────────
say "the comparison"
python3 - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "scripts/ui-coverage")
try:
    from score import DIMENSIONS, MAX          # one source for the dimension names and their maxima
except Exception:
    DIMENSIONS, MAX = [], {}

def weakest(s):
    """The dimension that lost the most OF ITS OWN total — 8/10 hurts more than 18/25."""
    if not DIMENSIONS:
        return ""
    lost = sorted(((MAX[k] - s.get(k, 0)) / MAX[k], k) for k in DIMENSIONS)
    return f"{lost[-1][1]} ({s.get(lost[-1][1], 0)}/{MAX[lost[-1][1]]})" if lost[-1][0] > 0 else "—"

rows = []
for p, f in (("desktop", "ci-artifacts/dgo55/desktop/ui-score.json"),
             ("390", "ci-artifacts/dgo55/mobile/ui-score.json")):
    f = pathlib.Path(f)
    if not f.exists():
        print(f"  (no {p} score — {f} missing; that profile did not finish)")
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    for v in d.get("views", []):
        rows.append((p, v.get("app"), v.get("title") or v.get("id"), v.get("score"), weakest(v)))
if not rows:
    raise SystemExit("nothing scored")
rows.sort(key=lambda r: (r[3] if isinstance(r[3], (int, float)) else 0))
print(f"{'profile':<9}{'app':<11}{'view':<42}{'score':>6}  weakest dimension")
for p, app, title, s, worst in rows:
    print(f"{p:<9}{(app or ''):<11}{str(title)[:40]:<42}{s if s is not None else '—':>6}  {worst}")
apps = {}
for p, app, _, s, _ in rows:
    if isinstance(s, (int, float)):
        apps.setdefault((p, app), []).append(s)
print()
for (p, app), ss in sorted(apps.items()):
    ss.sort()
    med = ss[len(ss)//2] if len(ss) % 2 else (ss[len(ss)//2-1]+ss[len(ss)//2])/2
    print(f"  {p:<9}{(app or ''):<11} median {med:>5}  worst {ss[0]:>5}  ({len(ss)} views)")
PY
