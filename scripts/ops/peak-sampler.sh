#!/usr/bin/env bash
# scripts/ops/peak-sampler.sh
#
# Record the memory high-water mark of every running container, robust to restarts.
#
# WHY: every memory limit in this repo was sized from a ~10-minute sample taken on a host that was
# restarting every few minutes (2026-08-06: 42 systemd inits in 24h). A peak measured over ten idle
# minutes is a FLOOR, not a maximum, and sizing limits down against a floor is how you turn a
# capacity plan into an OOM generator. The only honest sample is one taken across a real workload.
#
# WHY IT ACCUMULATES INSTEAD OF SNAPSHOTTING: cgroup `memory.peak` is the high-water mark SINCE THE
# CGROUP WAS CREATED. When a container is recreated — which on this host happens on every one of
# those 42 restarts — its peak resets to near zero. A single reading after a restart therefore
# reports a peak far BELOW the real one and looks like good news. This keeps a running maximum per
# container name across the whole sampling period, so a restart can never lower a recorded peak.
#
# Usage:
#   bash scripts/ops/peak-sampler.sh                       # sample until killed, 30s interval
#   INTERVAL=15 OUT=/tmp/peaks.tsv bash scripts/ops/peak-sampler.sh
#   bash scripts/ops/peak-sampler.sh --report              # print the accumulated table and exit
#
# Output TSV: container <TAB> peak_mib <TAB> limit_mib <TAB> pct_of_limit <TAB> samples

set -uo pipefail
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/bbox-docker.sock}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-$SCRIPT_DIR/.peak-sampler-state}"
mkdir -p "$STATE_DIR"
OUT="${OUT:-$STATE_DIR/peaks.tsv}"
INTERVAL="${INTERVAL:-30}"

report() {
  if [ ! -s "$OUT" ]; then echo "no samples recorded yet ($OUT is empty)"; return 1; fi
  printf '%-42s %10s %10s %8s %8s %8s\n' CONTAINER PEAK_MiB LIMIT_MiB PCT SRC SAMPLES
  sort "$OUT" | awk -F'\t' '{printf "%-42s %10d %10d %7s%% %8s %8d\n", $1, $2, $3, ($3>0)?int($2*100/$3):0, $4, $5}'
  echo "----"
  if grep -q $'\tsampled\t' "$OUT" 2>/dev/null; then
    echo "SRC=sampled: no kernel high-water counter exists on this host/cgroup combination"
    echo "  (kernel 5.15 + cgroup v2: memory.peak needs 5.19; max_usage_in_bytes is v1-only)."
    echo "  These are maxima of what THIS SCRIPT observed at its polling interval, so they are a"
    echo "  LOWER BOUND on the true peak — spikes shorter than the interval are invisible."
    echo "  Do NOT size a limit down against a 'sampled' figure."
  fi
  awk -F'\t' '{p+=$2; l+=$3} END{printf "SUM_PEAK_MiB=%d  SUM_LIMIT_MiB=%d\n", p, l}' "$OUT"
  echo "Containers at >80% of their limit (candidates to RAISE):"
  awk -F'\t' '$3>0 && $2*100/$3 >= 80 {printf "  %-42s %d / %d MiB (%d%%)\n", $1, $2, $3, $2*100/$3}' "$OUT" \
    || echo "  none"
}

if [ "${1:-}" = "--report" ]; then report; exit $?; fi

echo "peak-sampler: interval=${INTERVAL}s  out=${OUT}"
echo "peak-sampler: accumulating per-container maxima; restarts cannot lower a recorded peak."
echo "peak-sampler: stop with Ctrl-C or by killing this process; then run with --report."

declare -A PEAK LIMIT SAMPLES SRC
# Re-load any previous accumulation so a restarted sampler does not lose history either.
if [ -s "$OUT" ]; then
  while IFS=$'\t' read -r name peak lim _pct n; do
    [ -z "$name" ] && continue
    PEAK["$name"]=$peak; LIMIT["$name"]=$lim; SAMPLES["$name"]=${n:-0}
  done < "$OUT"
  echo "peak-sampler: resumed ${#PEAK[@]} container(s) from $OUT"
fi

flush() {
  : > "$OUT.tmp"
  for n in "${!PEAK[@]}"; do
    printf '%s\t%s\t%s\t%s\t%s\n' "$n" "${PEAK[$n]}" "${LIMIT[$n]:-0}" "${SRC[$n]:-?}" "${SAMPLES[$n]:-0}" >> "$OUT.tmp"
  done
  mv "$OUT.tmp" "$OUT"
}
trap 'echo; echo "peak-sampler: stopping, flushing…"; flush; report; exit 0' INT TERM

while true; do
  # Plain counter, not ${#PEAK[@]}: under `set -u` an EMPTY associative array is an unbound
  # variable in bash < 4.4, so the length test itself crashed the sampler on its first pass.
  found=0
  while read -r id name; do
    [ -z "$name" ] && continue
    # BOTH cgroup versions must be probed, and not as a portability nicety — this host ALTERNATES
    # between them across distro restarts. Measured 2026-08-06: at 03:38 the hierarchy was cgroup v2
    # unified (/sys/fs/cgroup/docker/<id>/memory.peak); by 04:35, after a distro re-init, it was v1
    # hybrid (/sys/fs/cgroup/memory/docker/<id>/memory.max_usage_in_bytes) with controllers split
    # into per-controller mounts. packaging/windows/build-rootfs.sh documents the cause: systemd is
    # what gives WSL a unified v2 hierarchy, and "without it /sys/fs/cgroup is a tmpfs with no
    # controllers and dockerd runs on cgroup v1 hybrid".
    #
    # This matters well beyond this script: memory accounting and limit ENFORCEMENT differ between
    # the two, so the same compose file does not constrain the stack identically across restarts.
    cg=""
    for cand in "/sys/fs/cgroup/docker/$id" \
                "/sys/fs/cgroup/system.slice/docker-$id.scope" \
                "/sys/fs/cgroup/memory/docker/$id"; do
      [ -d "$cand" ] && { cg="$cand"; break; }
    done
    [ -z "$cg" ] && continue
    # THREE sources, in order of fidelity, because on this host NONE of them is always present:
    #   memory.peak                 cgroup v2 kernel high-water — added in kernel 5.19
    #   memory.max_usage_in_bytes   cgroup v1 kernel high-water
    #   memory.current              INSTANTANEOUS. Not a high-water at all.
    #
    # This host runs kernel 5.15 and FLIPS between cgroup v1-hybrid and v2-unified across distro
    # restarts (observed three times on 2026-08-06). In v1 it has max_usage_in_bytes; in v2 on 5.15
    # it has NEITHER kernel high-water counter, because memory.peak postdates the kernel. So in v2
    # mode the only thing available is the instantaneous value, and the best obtainable "peak" is
    # the maximum of what WE sampled — coarser, and it will miss spikes shorter than the interval.
    #
    # That distinction must never be silently lost: a sampled max reported as a kernel high-water
    # would understate real peaks and invite cutting limits below what services actually use. The
    # source is recorded per container and printed in --report.
    cur=""; src=""
    if [ -r "$cg/memory.peak" ]; then
      cur=$(cat "$cg/memory.peak" 2>/dev/null); src=kernel
    elif [ -r "$cg/memory.max_usage_in_bytes" ]; then
      cur=$(cat "$cg/memory.max_usage_in_bytes" 2>/dev/null); src=kernel
    elif [ -r "$cg/memory.current" ]; then
      cur=$(cat "$cg/memory.current" 2>/dev/null); src=sampled
    elif [ -r "$cg/memory.usage_in_bytes" ]; then
      cur=$(cat "$cg/memory.usage_in_bytes" 2>/dev/null); src=sampled
    fi
    # A container that yields no readable number is SKIPPED, not recorded as a peak of zero. The
    # first version recorded the zeros and printed SUM_PEAK_MiB=0 as though that were a finding.
    case "${cur:-}" in ''|*[!0-9]*) continue ;; esac
    [ "$cur" -eq 0 ] && continue
    SRC[$name]="$src"
    mib=$(( cur / 1048576 ))
    prev=${PEAK[$name]:-0}
    # STRICTLY the running maximum. A recreated container reports a small fresh peak; never let
    # that overwrite a larger value already observed for the same service.
    [ "$mib" -gt "$prev" ] && PEAK[$name]=$mib || PEAK[$name]=$prev
    SAMPLES[$name]=$(( ${SAMPLES[$name]:-0} + 1 ))
    found=$(( found + 1 ))
    if [ -z "${LIMIT[$name]:-}" ] || [ "${LIMIT[$name]:-0}" -eq 0 ]; then
      l=$(docker inspect -f '{{.HostConfig.Memory}}' "$name" 2>/dev/null || echo 0)
      LIMIT[$name]=$(( ${l:-0} / 1048576 ))
    fi
    # --no-trunc is LOAD-BEARING. `docker ps --format '{{.ID}}'` returns the 12-char short id, but
    # the cgroup directory is named with the FULL 64-char id. Without it every path probe misses,
    # every container is skipped, and this script cheerfully writes an empty file and reports
    # success — which is exactly what it did on its first run.
  done < <(docker ps --no-trunc --format '{{.ID}} {{.Names}}' 2>/dev/null)
  if [ "$found" -eq 0 ]; then
    echo "peak-sampler: WARNING — zero containers resolved to a cgroup this pass. Not writing an" >&2
    echo "peak-sampler: empty result over good data. Check /sys/fs/cgroup layout and DOCKER_HOST." >&2
  else
    flush
  fi
  sleep "$INTERVAL"
done
